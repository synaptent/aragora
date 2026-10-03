"""
Task Scheduler for the Aragora Control Plane.

Provides distributed task scheduling with:
- Priority-based queue ordering
- Capability-based agent matching
- Task timeout and retry handling
- Redis Streams backend for durability

The scheduler works with the AgentRegistry to assign tasks
to the most suitable available agents.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from aragora.server.prometheus_control_plane import (
    record_control_plane_task_submitted,
    record_control_plane_task_completed,
    record_control_plane_task_retry,
)
from aragora.config.distributed import is_distributed_state_required
from aragora.control_plane.leader import DistributedStateError

# Observability
from aragora.observability import (
    get_logger,
    create_span,
    add_span_attributes,
)

# Type hints for optional imports (available at type-checking time only)
if TYPE_CHECKING:
    from aragora.control_plane.policy import (
        ControlPlanePolicyManager,
    )
    from aragora.control_plane.cost_enforcement import (
        CostEnforcer,
    )

# Pre-declare optional imports with Any to avoid no-redef errors
PolicyViolationError: Any = None
EnforcementLevel: Any = None
CostLimitExceededError: Any = None

# Policy imports (optional - graceful fallback if not available)
try:
    from aragora.control_plane.policy import (  # type: ignore[no-redef]
        PolicyViolationError,
        EnforcementLevel,
    )

    HAS_POLICY = True
except ImportError:
    HAS_POLICY = False

# Cost enforcement imports (optional - graceful fallback if not available)
try:
    from aragora.control_plane.cost_enforcement import (  # type: ignore[no-redef]
        CostLimitExceededError,
    )

    HAS_COST_ENFORCEMENT = True
except ImportError:
    HAS_COST_ENFORCEMENT = False

# Resilience patterns
from aragora.resilience import get_v2_circuit_breaker as get_circuit_breaker

logger = get_logger(__name__)

# Circuit breaker for scheduler Redis operations
_scheduler_redis_cb = get_circuit_breaker(
    "scheduler_redis", failure_threshold=5, cooldown_seconds=30
)


class TaskStatus(Enum):
    """Task lifecycle status."""

    PENDING = "pending"  # Task is queued, waiting for assignment
    ASSIGNED = "assigned"  # Task assigned to an agent
    RUNNING = "running"  # Task is being executed
    COMPLETED = "completed"  # Task completed successfully
    FAILED = "failed"  # Task failed after all retries
    CANCELLED = "cancelled"  # Task was cancelled
    TIMEOUT = "timeout"  # Task timed out


class TaskPriority(Enum):
    """Task priority levels."""

    LOW = 0
    NORMAL = 50
    HIGH = 75
    URGENT = 100


class RegionRoutingMode(Enum):
    """How tasks should be routed to regions."""

    ANY = "any"  # Execute in any available region
    PREFERRED = "preferred"  # Prefer target region, fallback to others
    STRICT = "strict"  # Only execute in target region, fail if unavailable


@dataclass
class Task:
    """
    Represents a task in the scheduling system.

    Attributes:
        id: Unique task identifier
        task_type: Type of task (e.g., "debate", "code", "analysis")
        payload: Task-specific data
        required_capabilities: Capabilities required to execute
        status: Current task status
        priority: Task priority
        created_at: Creation timestamp
        assigned_at: When task was assigned
        started_at: When execution started
        completed_at: When task completed/failed
        assigned_agent: Agent assigned to this task
        timeout_seconds: Task timeout
        max_retries: Maximum retry attempts
        retries: Current retry count
        result: Task result (if completed)
        error: Error message (if failed)
        metadata: Additional task metadata
        target_region: Preferred region for task execution
        fallback_regions: Fallback regions if target unavailable
        assigned_region: Region where task was actually assigned
        region_routing_mode: How to handle regional routing
        origin_region: Region where task was submitted
    """

    task_type: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    required_capabilities: set[str] = field(default_factory=set)
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: float = field(default_factory=time.time)
    assigned_at: float | None = None
    started_at: float | None = None
    completed_at: float | None = None
    assigned_agent: str | None = None
    timeout_seconds: float = 300.0
    max_retries: int = 3
    retries: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # Regional routing fields
    target_region: str | None = None
    fallback_regions: list[str] = field(default_factory=list)
    assigned_region: str | None = None
    region_routing_mode: RegionRoutingMode = RegionRoutingMode.ANY
    origin_region: str = "default"

    def is_timed_out(self) -> bool:
        """Check if task has timed out."""
        if self.started_at is None:
            return False
        return (time.time() - self.started_at) > self.timeout_seconds

    def should_retry(self) -> bool:
        """Check if task should be retried."""
        return self.retries < self.max_retries

    def get_eligible_regions(self) -> list[str]:
        """Get list of regions eligible for task execution in priority order.

        Returns:
            List of region IDs, with target_region first if specified
        """
        regions = []
        if self.target_region:
            regions.append(self.target_region)
        regions.extend([r for r in self.fallback_regions if r not in regions])
        return regions

    def can_execute_in_region(self, region_id: str) -> bool:
        """Check if task can be executed in a specific region.

        Args:
            region_id: Region to check

        Returns:
            True if task can be executed in this region
        """
        if self.region_routing_mode == RegionRoutingMode.ANY:
            return True
        if self.region_routing_mode == RegionRoutingMode.STRICT:
            return region_id == self.target_region
        # PREFERRED mode
        if self.target_region and region_id == self.target_region:
            return True
        return region_id in self.fallback_regions or not self.target_region

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "task_type": self.task_type,
            "payload": self.payload,
            "required_capabilities": list(self.required_capabilities),
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at,
            "assigned_at": self.assigned_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "assigned_agent": self.assigned_agent,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retries": self.retries,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            # Regional fields
            "target_region": self.target_region,
            "fallback_regions": self.fallback_regions,
            "assigned_region": self.assigned_region,
            "region_routing_mode": self.region_routing_mode.value,
            "origin_region": self.origin_region,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Task:
        """Deserialize from dictionary."""
        # Parse region routing mode
        routing_mode_str = data.get("region_routing_mode", "any")
        try:
            routing_mode = RegionRoutingMode(routing_mode_str)
        except ValueError:
            routing_mode = RegionRoutingMode.ANY

        return cls(
            id=data["id"],
            task_type=data["task_type"],
            payload=data["payload"],
            required_capabilities=set(data.get("required_capabilities", [])),
            status=TaskStatus(data.get("status", "pending")),
            priority=TaskPriority(data.get("priority", 50)),
            created_at=data.get("created_at", time.time()),
            assigned_at=data.get("assigned_at"),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            assigned_agent=data.get("assigned_agent"),
            timeout_seconds=data.get("timeout_seconds", 300.0),
            max_retries=data.get("max_retries", 3),
            retries=data.get("retries", 0),
            result=data.get("result"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
            # Regional fields
            target_region=data.get("target_region"),
            fallback_regions=data.get("fallback_regions", []),
            assigned_region=data.get("assigned_region"),
            region_routing_mode=routing_mode,
            origin_region=data.get("origin_region", "default"),
        )


class TaskScheduler:
    """
    Redis-backed task scheduler for distributed task distribution.

    Uses Redis Streams for durable task queuing with:
    - Priority ordering via multiple streams
    - Consumer groups for work distribution
    - Pending entry tracking for timeout detection

    Usage:
        scheduler = TaskScheduler(redis_url="redis://localhost:6379")
        await scheduler.connect()

        # Submit a task
        task_id = await scheduler.submit(
            task_type="debate",
            payload={"question": "..."},
            required_capabilities=["debate"],
            priority=TaskPriority.HIGH,
        )

        # Claim a task (from worker)
        task = await scheduler.claim(worker_id="worker-1", capabilities=["debate"])

        # Complete a task
        await scheduler.complete(task_id, result={"conclusion": "..."})

        await scheduler.close()
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "aragora:cp:tasks:",
        stream_prefix: str = "aragora:cp:stream:",
        consumer_group: str = "aragora-workers",
        claim_timeout_ms: int = 60000,
        policy_manager: ControlPlanePolicyManager | None = None,
        cost_enforcer: CostEnforcer | None = None,
    ):
        """
        Initialize the task scheduler.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for task data keys
            stream_prefix: Prefix for stream keys
            consumer_group: Consumer group name
            claim_timeout_ms: Time before unclaimed task can be reclaimed
            policy_manager: Optional policy manager for enforcement
            cost_enforcer: Optional cost enforcer for budget-aware scheduling
        """
        self._redis_url = redis_url
        self._key_prefix = key_prefix
        self._stream_prefix = stream_prefix
        self._index_prefix = f"{key_prefix}index:"  # Secondary index prefix
        self._consumer_group = consumer_group
        self._claim_timeout_ms = claim_timeout_ms
        self._policy_manager = policy_manager
        self._cost_enforcer = cost_enforcer
        self._redis: Any | None = None
        self._local_tasks: dict[str, Task] = {}
        self._local_queue: list[Task] = []
        # Local indexes for in-memory fallback
        self._local_status_index: dict[TaskStatus, set[str]] = {
            status: set() for status in TaskStatus
        }

    async def connect(self) -> None:
        """Connect to Redis."""
        with create_span(
            "scheduler.connect",
            {"redis_url": self._redis_url},
        ) as span:
            start = time.time()

            # Check for explicit in-memory mode via special URL
            if self._redis_url.startswith("memory://"):
                add_span_attributes(span, {"backend": "memory", "explicit": True})
                logger.info(
                    "scheduler_using_memory",
                    event="scheduler_memory_mode",
                    reason="memory:// URL specified",
                )
                self._redis = None
                return

            # Check circuit breaker before attempting Redis connection
            if not _scheduler_redis_cb.can_execute():
                add_span_attributes(span, {"backend": "memory", "circuit_breaker": "open"})
                logger.warning(
                    "scheduler_circuit_breaker_open",
                    event="scheduler_fallback",
                    reason="circuit breaker open",
                )
                self._redis = None
                return

            try:
                import redis.asyncio as aioredis
                from redis.exceptions import ResponseError as RedisResponseError

                self._redis = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
                await self._redis.ping()

                # Create consumer groups for each priority stream
                for priority in TaskPriority:
                    stream_key = f"{self._stream_prefix}{priority.name.lower()}"
                    try:
                        await self._redis.xgroup_create(
                            stream_key,
                            self._consumer_group,
                            id="0",
                            mkstream=True,
                        )
                    except RedisResponseError as e:
                        # BUSYGROUP error means group already exists - this is expected
                        if "BUSYGROUP" not in str(e):
                            logger.debug(
                                "consumer_group_note",
                                stream_key=stream_key,
                                error=str(e),
                            )

                latency_ms = (time.time() - start) * 1000
                _scheduler_redis_cb.record_success()
                add_span_attributes(span, {"latency_ms": latency_ms, "backend": "redis"})
                logger.info(
                    "scheduler_connected",
                    redis_url=self._redis_url,
                    latency_ms=latency_ms,
                )

            except ImportError:
                if is_distributed_state_required():
                    raise DistributedStateError(
                        "task_scheduler",
                        "redis package not installed. Install with: pip install redis",
                    )
                add_span_attributes(span, {"backend": "memory", "fallback": True})
                logger.warning(
                    "Using in-memory scheduler fallback - NOT suitable for multi-instance deployments",
                    event="scheduler_fallback",
                    reason="redis package not installed",
                )
                self._redis = None
            except (ConnectionError, OSError, TimeoutError) as e:
                _scheduler_redis_cb.record_failure(e)
                if is_distributed_state_required():
                    raise DistributedStateError(
                        "task_scheduler",
                        f"Failed to connect to Redis: {e}",
                    ) from e
                add_span_attributes(span, {"backend": "memory", "fallback": True, "error": str(e)})
                logger.warning(
                    "Scheduler Redis error - using in-memory fallback",
                    event="scheduler_redis_error",
                    error=str(e),
                )
                self._redis = None
            except Exception as e:  # noqa: BLE001 - redis-specific exceptions are not subclasses of built-in types
                # Catch redis-specific exceptions (RedisConnectionError, RedisTimeoutError)
                # These are not subclasses of built-in exceptions
                error_name = type(e).__name__
                if "ConnectionError" in error_name or "TimeoutError" in error_name:
                    _scheduler_redis_cb.record_failure(e)
                    if is_distributed_state_required():
                        raise DistributedStateError(
                            "task_scheduler",
                            f"Failed to connect to Redis: {e}",
                        ) from e
                    add_span_attributes(
                        span, {"backend": "memory", "fallback": True, "error": str(e)}
                    )
                    logger.warning(
                        "Scheduler Redis connection failed - using in-memory fallback",
                        event="scheduler_redis_error",
                        error=str(e),
                    )
                    self._redis = None
                else:
                    raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            logger.info("TaskScheduler disconnected from Redis")

    def set_cost_enforcer(self, cost_enforcer: CostEnforcer) -> None:
        """
        Set the cost enforcer for budget-aware scheduling.

        Args:
            cost_enforcer: CostEnforcer instance for budget checks
        """
        self._cost_enforcer = cost_enforcer
        logger.info("TaskScheduler connected to CostEnforcer")

    def get_budget_status(
        self, workspace_id: str | None = None, org_id: str | None = None
    ) -> dict[str, Any]:
        """
        Get current budget status for a workspace/org.

        Args:
            workspace_id: Workspace to check
            org_id: Organization to check

        Returns:
            Budget status dictionary
        """
        if not self._cost_enforcer:
            return {"error": "No cost enforcer configured"}
        return self._cost_enforcer.get_budget_status(workspace_id=workspace_id, org_id=org_id)

    async def submit(
        self,
        task_type: str,
        payload: dict[str, Any],
        required_capabilities: list[str] | None = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout_seconds: float = 300.0,
        max_retries: int = 3,
        metadata: dict[str, Any] | None = None,
        target_region: str | None = None,
        fallback_regions: list[str] | None = None,
        region_routing_mode: RegionRoutingMode = RegionRoutingMode.ANY,
        origin_region: str = "default",
        workspace_id: str | None = None,
    ) -> str:
        """
        Submit a task for execution.

        Args:
            task_type: Type of task
            payload: Task data
            required_capabilities: Required agent capabilities
            priority: Task priority
            timeout_seconds: Task timeout
            max_retries: Maximum retries
            metadata: Additional metadata
            target_region: Preferred region for execution
            fallback_regions: Fallback regions if target unavailable
            region_routing_mode: How to handle regional routing
            origin_region: Region where task was submitted
            workspace_id: Optional workspace ID for policy scoping

        Returns:
            Task ID

        Raises:
            PolicyViolationError: If task violates HARD enforcement policy
            CostLimitExceededError: If task would exceed budget limits
        """
        # Cost constraint check before creating task (if cost enforcer configured)
        effective_priority = priority
        cost_result = None
        if self._cost_enforcer and HAS_COST_ENFORCEMENT:
            cost_result = self._cost_enforcer.check_budget_constraint(
                workspace_id=workspace_id,
                task_type=task_type,
            )

            if not cost_result.allowed:
                raise CostLimitExceededError(
                    result=cost_result,
                    task_type=task_type,
                )

            # Apply priority adjustment for throttling
            if cost_result.priority_adjustment != 0:
                # Adjust priority (lower number = lower priority)
                priority_values = list(TaskPriority)
                current_idx = priority_values.index(priority)
                new_idx = max(
                    0, min(len(priority_values) - 1, current_idx + cost_result.priority_adjustment)
                )
                effective_priority = priority_values[new_idx]

                if effective_priority != priority:
                    logger.info(
                        "cost_throttle_priority_adjusted",
                        task_type=task_type,
                        workspace_id=workspace_id,
                        original_priority=priority.name,
                        new_priority=effective_priority.name,
                        throttle_level=cost_result.throttle_level.value,
                        budget_percentage=cost_result.budget_percentage_used,
                    )

        task = Task(
            task_type=task_type,
            payload=payload,
            required_capabilities=set(required_capabilities or []),
            priority=effective_priority,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            metadata=metadata or {},
            target_region=target_region,
            fallback_regions=fallback_regions or [],
            region_routing_mode=region_routing_mode,
            origin_region=origin_region,
        )

        # Store cost constraint info in metadata for observability
        if cost_result is not None:
            task.metadata["cost_constraint"] = {
                "throttle_level": cost_result.throttle_level.value,
                "budget_percentage_used": cost_result.budget_percentage_used,
                "original_priority": priority.name,
            }

        # Store workspace_id in metadata if provided
        if workspace_id:
            task.metadata["workspace_id"] = workspace_id

        # Policy check before saving task (if policy manager configured)
        if self._policy_manager and HAS_POLICY:
            # For submit, we check region constraints but not agent (no agent yet)
            # Evaluate with a placeholder agent_id since we don't have one yet
            result = self._policy_manager.evaluate_task_dispatch(
                task_type=task_type,
                agent_id="__submission__",  # Placeholder for submission check
                region=target_region or origin_region,
                capabilities=required_capabilities,
                workspace=workspace_id,
                task_id=task.id,
            )

            if not result.allowed:
                if result.enforcement_level == EnforcementLevel.HARD:
                    raise PolicyViolationError(
                        result=result,
                        task_type=task_type,
                        region=target_region or origin_region,
                    )
                elif result.enforcement_level == EnforcementLevel.WARN:
                    logger.warning(
                        "policy_warning_on_submit",
                        task_id=task.id,
                        task_type=task_type,
                        reason=result.reason,
                        policy_id=result.policy_id,
                    )

        await self._save_task(task)
        await self._enqueue_task(task)

        # Record metrics
        record_control_plane_task_submitted(task_type, priority.name.lower())

        region_info = f", region={target_region}" if target_region else ""
        logger.info(
            "Task submitted: %s (type=%s, priority=%s%s)",
            task.id,
            task_type,
            priority.name,
            region_info,
        )

        return task.id

    async def claim(
        self,
        worker_id: str,
        capabilities: list[str],
        block_ms: int = 5000,
        worker_region: str | None = None,
        workspace_id: str | None = None,
    ) -> Task | None:
        """
        Claim a task for execution.

        Args:
            worker_id: ID of the worker claiming the task
            capabilities: Capabilities the worker provides
            block_ms: Time to block waiting for a task
            worker_region: Region where the worker is located (for policy checks)
            workspace_id: Workspace ID for policy scoping

        Returns:
            Task if claimed, None if no suitable task available
        """
        if self._redis:
            return await self._claim_from_redis(
                worker_id, capabilities, block_ms, worker_region, workspace_id
            )
        else:
            return self._claim_from_local(worker_id, capabilities, worker_region, workspace_id)

    async def claim_in_region(
        self,
        worker_id: str,
        capabilities: list[str],
        worker_region: str,
        block_ms: int = 5000,
    ) -> Task | None:
        """
        Claim a task for execution with regional affinity.

        Prefers tasks targeted at the worker's region, but will claim
        tasks from other regions if the routing mode allows.

        Args:
            worker_id: ID of the worker claiming the task
            capabilities: Capabilities the worker provides
            worker_region: Region where the worker is located
            block_ms: Time to block waiting for a task

        Returns:
            Task if claimed, None if no suitable task available
        """
        task = await self.claim(worker_id, capabilities, block_ms)
        if not task:
            return None

        # Check if task can be executed in this region
        if not task.can_execute_in_region(worker_region):
            # Release the task back for another worker
            await self._release_task(task)
            return None

        # Set the assigned region
        task.assigned_region = worker_region
        await self._save_task(task)

        return task

    async def _release_task(self, task: Task) -> None:
        """Release a claimed task back to the queue."""
        task.status = TaskStatus.PENDING
        task.assigned_agent = None
        task.assigned_at = None
        await self._save_task(task)
        await self._enqueue_task(task)
        logger.debug("Task %s released back to queue", task.id)

    async def complete(
        self,
        task_id: str,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """
        Mark a task as completed.

        Args:
            task_id: Task to complete
            result: Task result

        Returns:
            True if marked complete, False if task not found
        """
        task = await self.get(task_id)
        if not task:
            return False

        previous_status = task.status
        task.status = TaskStatus.COMPLETED
        task.completed_at = time.time()
        task.result = result

        await self._save_task(task, previous_status=previous_status)
        await self._ack_task(task)

        # Record metrics
        duration = task.completed_at - (task.started_at or task.created_at)
        record_control_plane_task_completed(task.task_type, "completed", duration)

        logger.info("Task completed: %s", task_id)
        return True

    async def fail(
        self,
        task_id: str,
        error: str,
        requeue: bool = True,
    ) -> bool:
        """
        Mark a task as failed.

        Args:
            task_id: Task that failed
            error: Error message
            requeue: Whether to requeue for retry

        Returns:
            True if processed, False if task not found
        """
        task = await self.get(task_id)
        if not task:
            return False

        previous_status = task.status
        task.error = error
        task.retries += 1

        if requeue and task.should_retry():
            task.status = TaskStatus.PENDING
            task.assigned_agent = None
            task.assigned_at = None
            task.started_at = None
            # Clear the message ID since we're requeuing (new stream entry)
            task.metadata.pop("_stream_message_id", None)
            await self._save_task(task, previous_status=previous_status)
            await self._enqueue_task(task)

            # Record retry metric
            record_control_plane_task_retry(task.task_type, "error")

            logger.warning(
                "Task %s failed (attempt %s/%s), requeued: %s",
                task_id,
                task.retries,
                task.max_retries,
                error,
            )
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = time.time()
            await self._save_task(task, previous_status=previous_status)
            await self._ack_task(task)
            # Move to dead-letter queue for later analysis
            await self._move_to_dead_letter(task, error)

            # Record failed task metrics
            duration = task.completed_at - (task.started_at or task.created_at)
            record_control_plane_task_completed(task.task_type, "failed", duration)

            logger.error("Task %s failed permanently: %s", task_id, error)

        return True

    async def cancel(self, task_id: str) -> bool:
        """
        Cancel a pending or running task.

        Args:
            task_id: Task to cancel

        Returns:
            True if cancelled, False if not found or already completed
        """
        task = await self.get(task_id)
        if not task:
            return False

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            return False

        previous_status = task.status
        task.status = TaskStatus.CANCELLED
        task.completed_at = time.time()

        await self._save_task(task, previous_status=previous_status)
        await self._ack_task(task)

        logger.info("Task cancelled: %s", task_id)
        return True

    async def get(self, task_id: str) -> Task | None:
        """
        Get task by ID.

        Args:
            task_id: Task to retrieve

        Returns:
            Task if found, None otherwise
        """
        if self._redis:
            key = f"{self._key_prefix}{task_id}"
            # Normalize AsyncMock side_effect lists to iterators (test safety).
            try:
                side_effect = getattr(self._redis.get, "side_effect", None)
                if isinstance(side_effect, list):
                    self._redis.get.side_effect = iter(side_effect)
            except (AttributeError, TypeError) as e:
                logger.debug("Mock side_effect normalization skipped: %s", e)
            data = await self._redis.get(key)
            if data:
                return Task.from_dict(json.loads(data))
            return None
        else:
            return self._local_tasks.get(task_id)

    async def list_by_status(
        self,
        status: TaskStatus,
        limit: int = 100,
    ) -> list[Task]:
        """
        List tasks by status using secondary index for O(1) lookups.

        Args:
            status: Status to filter by
            limit: Maximum tasks to return

        Returns:
            List of tasks with the given status
        """
        tasks: list[Task] = []

        if self._redis:
            # Use secondary index for O(1) lookup instead of O(n) SCAN
            index_key = f"{self._index_prefix}status:{status.value}"
            task_ids = await self._redis.smembers(index_key)

            # Fetch tasks in batches for efficiency
            for task_id in list(task_ids)[:limit]:
                task = await self.get(task_id)
                if task and task.status == status:
                    tasks.append(task)
                elif task is None:
                    # Task expired, remove from index
                    await self._redis.srem(index_key, task_id)
        else:
            # Use local index for O(1) lookup
            task_ids = list(self._local_status_index.get(status, set()))[:limit]
            for task_id in task_ids:
                task = self._local_tasks.get(task_id)
                if task and task.status == status:
                    tasks.append(task)

        return tasks

    async def get_stats(self) -> dict[str, Any]:
        """
        Get scheduler statistics.

        Returns:
            Dict with task counts by status, queue depths, etc.
        """
        status_counts = {s.value: 0 for s in TaskStatus}
        priority_counts = {p.name.lower(): 0 for p in TaskPriority}
        type_counts: dict[str, int] = {}

        if self._redis:
            pattern = f"{self._key_prefix}*"
            async for key in self._redis.scan_iter(match=pattern):
                data = await self._redis.get(key)
                if data:
                    task = Task.from_dict(json.loads(data))
                    status_counts[task.status.value] += 1
                    priority_counts[task.priority.name.lower()] += 1
                    type_counts[task.task_type] = type_counts.get(task.task_type, 0) + 1
        else:
            for task in self._local_tasks.values():
                status_counts[task.status.value] += 1
                priority_counts[task.priority.name.lower()] += 1
                type_counts[task.task_type] = type_counts.get(task.task_type, 0) + 1

        return {
            "by_status": status_counts,
            "by_priority": priority_counts,
            "by_type": type_counts,
            "total": sum(status_counts.values()),
        }

    async def claim_stale_tasks(self, idle_ms: int = 60000) -> int:
        """
        Reclaim tasks from dead workers.

        Args:
            idle_ms: Minimum idle time to consider a task stale

        Returns:
            Number of tasks reclaimed
        """
        if not self._redis:
            return 0

        reclaimed = 0

        for priority in TaskPriority:
            stream_key = f"{self._stream_prefix}{priority.name.lower()}"
            try:
                # Get pending entries
                pending = await self._redis.xpending_range(
                    stream_key,
                    self._consumer_group,
                    min="-",
                    max="+",
                    count=100,
                )

                for entry in pending:
                    if entry.get("time_since_delivered", 0) > idle_ms:
                        # Claim the entry
                        messages = await self._redis.xclaim(
                            stream_key,
                            self._consumer_group,
                            "recovery-worker",
                            min_idle_time=idle_ms,
                            message_ids=[entry["message_id"]],
                        )

                        for msg_id, msg_data in messages:
                            task_id = msg_data.get("task_id")
                            if task_id:
                                task = await self.get(task_id)
                                if task and task.status == TaskStatus.RUNNING:
                                    await self.fail(
                                        task_id,
                                        "Worker timeout - task reclaimed",
                                        requeue=True,
                                    )
                                    reclaimed += 1

            except (ConnectionError, OSError, TimeoutError) as e:
                logger.error("Connection error reclaiming stale tasks for %s: %s", priority.name, e)
            except (KeyError, TypeError, ValueError) as e:
                logger.error("Data error reclaiming stale tasks for %s: %s", priority.name, e)

        if reclaimed > 0:
            logger.info("Reclaimed %s stale tasks", reclaimed)

        return reclaimed

    async def _save_task(self, task: Task, previous_status: TaskStatus | None = None) -> None:
        """Save task to Redis or local storage with status index maintenance."""
        if self._redis:
            key = f"{self._key_prefix}{task.id}"

            # Update status index if status changed
            if previous_status and previous_status != task.status:
                await self._update_status_index(task.id, previous_status, task.status)
            elif not previous_status:
                # New task - add to status index
                await self._add_to_status_index(task.id, task.status)

            await self._redis.set(
                key,
                json.dumps(task.to_dict()),
                ex=86400,  # 24 hour expiry
            )
        else:
            # Use explicit previous_status if provided, otherwise check stored task
            if previous_status is None:
                old_task = self._local_tasks.get(task.id)
                old_status = old_task.status if old_task else None
            else:
                old_status = previous_status

            # Update local status index
            if old_status and old_status != task.status:
                self._local_status_index[old_status].discard(task.id)
                self._local_status_index[task.status].add(task.id)
            elif old_status is None:
                self._local_status_index[task.status].add(task.id)

            self._local_tasks[task.id] = task

    async def _add_to_status_index(self, task_id: str, status: TaskStatus) -> None:
        """Add task ID to status index set."""
        if self._redis:
            index_key = f"{self._index_prefix}status:{status.value}"
            await self._redis.sadd(index_key, task_id)
            # Set expiry on index key to match task expiry
            await self._redis.expire(index_key, 86400)

    async def _update_status_index(
        self, task_id: str, old_status: TaskStatus, new_status: TaskStatus
    ) -> None:
        """Move task ID from old status index to new status index."""
        if self._redis:
            old_key = f"{self._index_prefix}status:{old_status.value}"
            new_key = f"{self._index_prefix}status:{new_status.value}"
            # Use pipeline for atomic update
            async with self._redis.pipeline() as pipe:
                pipe.srem(old_key, task_id)
                pipe.sadd(new_key, task_id)
                pipe.expire(new_key, 86400)
                await pipe.execute()

    async def _enqueue_task(self, task: Task) -> None:
        """Add task to the appropriate queue."""
        if self._redis:
            stream_key = f"{self._stream_prefix}{task.priority.name.lower()}"
            await self._redis.xadd(
                stream_key,
                {"task_id": task.id, "task_type": task.task_type},
            )
        else:
            self._local_queue.append(task)
            # Sort by priority (higher first)
            self._local_queue.sort(key=lambda t: t.priority.value, reverse=True)

    async def _ack_task(self, task: Task) -> None:
        """Acknowledge task completion in the queue.

        Performs XACK to remove the message from the pending entries list (PEL),
        then XDEL to remove the message from the stream entirely.
        """
        if not self._redis:
            return

        # Get the stream key for this task's priority
        stream_key = f"{self._stream_prefix}{task.priority.name.lower()}"

        # Get the message ID stored when we claimed the task
        message_id = task.metadata.get("_stream_message_id")
        if not message_id:
            logger.warning("Task %s has no stream message ID for acknowledgment", task.id)
            return

        try:
            # XACK removes from pending entries list
            await self._redis.xack(stream_key, self._consumer_group, message_id)

            # XDEL removes the message from stream (keeps stream size bounded)
            await self._redis.xdel(stream_key, message_id)

            logger.debug("Acknowledged task %s (message_id=%s)", task.id, message_id)
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.error("Connection error acknowledging task %s: %s", task.id, e)
        except (KeyError, TypeError) as e:
            logger.error("Data error acknowledging task %s: %s", task.id, e)

    async def _move_to_dead_letter(self, task: Task, reason: str) -> None:
        """Move task to dead-letter queue after exhausting retries.

        Args:
            task: The failed task
            reason: Reason for moving to dead-letter queue
        """
        if not self._redis:
            return

        dlq_key = f"{self._stream_prefix}dead_letter"
        try:
            await self._redis.xadd(
                dlq_key,
                {
                    "task_id": task.id,
                    "task_type": task.task_type,
                    "reason": reason,
                    "failed_at": str(time.time()),
                    "retries": str(task.retries),
                    "original_priority": task.priority.name,
                },
            )
            logger.info("Task %s moved to dead-letter queue: %s", task.id, reason)
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.error("Connection error moving task %s to dead-letter queue: %s", task.id, e)
        except (KeyError, TypeError) as e:
            logger.error("Data error moving task %s to dead-letter queue: %s", task.id, e)

    async def _claim_from_redis(
        self,
        worker_id: str,
        capabilities: list[str],
        block_ms: int,
        worker_region: str | None = None,
        workspace_id: str | None = None,
    ) -> Task | None:
        """Claim task from Redis Streams."""
        cap_set = set(capabilities)

        # Try each priority level from highest to lowest
        for priority in sorted(TaskPriority, key=lambda p: p.value, reverse=True):
            stream_key = f"{self._stream_prefix}{priority.name.lower()}"

            try:
                # Read from consumer group
                messages = await self._redis.xreadgroup(  # type: ignore[union-attr]
                    groupname=self._consumer_group,
                    consumername=worker_id,
                    streams={stream_key: ">"},
                    count=1,
                    block=block_ms if priority == TaskPriority.LOW else 0,
                )

                if not messages:
                    continue

                for stream, entries in messages:
                    for msg_id, msg_data in entries:
                        task_id = msg_data.get("task_id")
                        if not task_id:
                            continue

                        task = await self.get(task_id)
                        if not task:
                            # Task deleted, ack and skip
                            await self._redis.xack(stream_key, self._consumer_group, msg_id)  # type: ignore[union-attr]
                            await self._redis.xdel(stream_key, msg_id)  # type: ignore[union-attr]
                            continue

                        # Check capabilities
                        if task.required_capabilities and not task.required_capabilities.issubset(
                            cap_set
                        ):
                            # Worker doesn't have required capabilities
                            # XACK to remove from this worker's pending list
                            await self._redis.xack(stream_key, self._consumer_group, msg_id)  # type: ignore[union-attr]

                            # Track rejection in metadata for debugging
                            if "rejection_count" not in task.metadata:
                                task.metadata["rejection_count"] = 0
                            task.metadata["rejection_count"] += 1
                            task.metadata["last_rejected_by"] = worker_id
                            task.metadata["last_rejected_reason"] = (
                                f"Missing capabilities: {task.required_capabilities - cap_set}"
                            )

                            # Requeue for another worker to claim
                            # Note: This creates a new stream entry, old one is acked
                            await self._save_task(task)
                            await self._enqueue_task(task)

                            logger.debug(
                                "Task %s rejected by %s: needs %s, has %s",
                                task_id,
                                worker_id,
                                task.required_capabilities,
                                cap_set,
                            )
                            continue

                        # Policy check (if policy manager configured)
                        if self._policy_manager and HAS_POLICY:
                            task_workspace = workspace_id or task.metadata.get("workspace_id")
                            result = self._policy_manager.evaluate_task_dispatch(
                                task_type=task.task_type,
                                agent_id=worker_id,
                                region=worker_region or task.target_region or "default",
                                capabilities=capabilities,
                                workspace=task_workspace,
                                task_id=task_id,
                            )

                            if not result.allowed:
                                # Policy violation - requeue task for another worker
                                await self._redis.xack(stream_key, self._consumer_group, msg_id)  # type: ignore[union-attr]

                                # Track policy rejection
                                if "policy_rejection_count" not in task.metadata:
                                    task.metadata["policy_rejection_count"] = 0
                                task.metadata["policy_rejection_count"] += 1
                                task.metadata["last_policy_rejected_by"] = worker_id
                                task.metadata["last_policy_rejection_reason"] = result.reason

                                # Requeue for another worker
                                await self._save_task(task)
                                await self._enqueue_task(task)

                                if result.enforcement_level == EnforcementLevel.WARN:
                                    logger.warning(
                                        "policy_warning_on_claim",
                                        task_id=task_id,
                                        worker_id=worker_id,
                                        reason=result.reason,
                                        policy_id=result.policy_id,
                                    )
                                else:
                                    logger.debug(
                                        "Task %s rejected by policy for %s: %s",
                                        task_id,
                                        worker_id,
                                        result.reason,
                                    )
                                continue

                        # Store message_id for later acknowledgment
                        task.metadata["_stream_message_id"] = msg_id

                        # Claim the task
                        previous_status = task.status
                        task.status = TaskStatus.RUNNING
                        task.assigned_agent = worker_id
                        task.assigned_at = time.time()
                        task.started_at = time.time()

                        await self._save_task(task, previous_status=previous_status)
                        logger.debug("Task %s claimed by %s", task_id, worker_id)

                        return task

            except (ConnectionError, OSError, TimeoutError) as e:
                logger.error("Connection error claiming from %s queue: %s", priority.name, e)
            except (KeyError, TypeError, ValueError) as e:
                logger.error("Data error claiming from %s queue: %s", priority.name, e)

        return None

    def _claim_from_local(
        self,
        worker_id: str,
        capabilities: list[str],
        worker_region: str | None = None,
        workspace_id: str | None = None,
    ) -> Task | None:
        """Claim task from local queue."""
        cap_set = set(capabilities)

        for i, task in enumerate(self._local_queue):
            if task.status != TaskStatus.PENDING:
                continue

            if task.required_capabilities and not task.required_capabilities.issubset(cap_set):
                continue

            # Policy check (if policy manager configured)
            if self._policy_manager and HAS_POLICY:
                task_workspace = workspace_id or task.metadata.get("workspace_id")
                result = self._policy_manager.evaluate_task_dispatch(
                    task_type=task.task_type,
                    agent_id=worker_id,
                    region=worker_region or task.target_region or "default",
                    capabilities=capabilities,
                    workspace=task_workspace,
                    task_id=task.id,
                )

                if not result.allowed:
                    # Policy violation - skip this task, try next one
                    # Track policy rejection
                    if "policy_rejection_count" not in task.metadata:
                        task.metadata["policy_rejection_count"] = 0
                    task.metadata["policy_rejection_count"] += 1
                    task.metadata["last_policy_rejected_by"] = worker_id
                    task.metadata["last_policy_rejection_reason"] = result.reason

                    if result.enforcement_level == EnforcementLevel.WARN:
                        logger.warning(
                            "policy_warning_on_claim",
                            task_id=task.id,
                            worker_id=worker_id,
                            reason=result.reason,
                            policy_id=result.policy_id,
                        )
                    else:
                        logger.debug(
                            "Task %s rejected by policy for %s: %s",
                            task.id,
                            worker_id,
                            result.reason,
                        )
                    continue

            # Claim the task - update local status index
            previous_status = task.status
            task.status = TaskStatus.RUNNING
            task.assigned_agent = worker_id
            task.assigned_at = time.time()
            task.started_at = time.time()

            # Update local status index
            self._local_status_index[previous_status].discard(task.id)
            self._local_status_index[task.status].add(task.id)

            # Update local_tasks storage so get() returns updated task
            self._local_tasks[task.id] = task

            self._local_queue.pop(i)
            return task

        return None
