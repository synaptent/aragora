"""
Global Work Queue: Unified Priority Queue.

This module provides a unified priority queue that merges work from
beads, convoys, and other sources with dynamic prioritization.

Key concepts:
- GlobalWorkQueue: Merges bead/convoy priorities into unified queue
- PriorityCalculator: Computes priority considering dependencies and deadlines
- DynamicReprioritization: Adjusts priorities based on real-time conditions
- WorkItem: Unified work item representation

Usage:
    from aragora.nomic.global_work_queue import GlobalWorkQueue

    queue = GlobalWorkQueue(
        bead_store=bead_store,
        convoy_manager=convoy_manager,
    )
    await queue.initialize()

    # Get next work item
    work = await queue.pop()

    # Add work with priority
    await queue.push(work_item, priority=80)

    # Reprioritize based on conditions
    await queue.reprioritize()
"""

from __future__ import annotations

import asyncio
import heapq
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

if TYPE_CHECKING:
    from aragora.nomic.beads import BeadStore
    from aragora.nomic.convoys import ConvoyManager

logger = logging.getLogger(__name__)


class WorkType(str, Enum):
    """Types of work in the queue."""

    BEAD = "bead"
    CONVOY = "convoy"
    MOLECULE = "molecule"
    ESCALATION = "escalation"
    MAINTENANCE = "maintenance"
    CUSTOM = "custom"


class WorkStatus(str, Enum):
    """Status of work items."""

    PENDING = "pending"
    READY = "ready"  # Dependencies met, can be claimed
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"  # Waiting on dependencies
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(order=True)
class PrioritizedWork:
    """
    Wrapper for priority queue ordering.

    Uses negative priority so higher priority = earlier in heap.
    """

    sort_priority: tuple[int, datetime, str] = field(compare=True)
    work_item: WorkItem = field(compare=False)


@dataclass
class WorkItem:
    """
    Unified work item representation.

    Can represent beads, convoys, molecules, or custom work.
    """

    id: str
    work_type: WorkType
    title: str
    description: str
    status: WorkStatus
    created_at: datetime
    updated_at: datetime
    base_priority: int  # 0-100, higher is more important
    computed_priority: int = 0  # After dynamic adjustments
    source_id: str | None = None  # ID of source bead/convoy
    assigned_to: str | None = None
    dependencies: list[str] = field(default_factory=list)  # Other work IDs
    blockers: list[str] = field(default_factory=list)  # Blocking conditions
    deadline: datetime | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize computed priority from base."""
        if self.computed_priority == 0:
            self.computed_priority = self.base_priority

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "work_type": self.work_type.value,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "base_priority": self.base_priority,
            "computed_priority": self.computed_priority,
            "source_id": self.source_id,
            "assigned_to": self.assigned_to,
            "dependencies": self.dependencies,
            "blockers": self.blockers,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkItem:
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            work_type=WorkType(data["work_type"]),
            title=data["title"],
            description=data.get("description", ""),
            status=WorkStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            base_priority=data.get("base_priority", 50),
            computed_priority=data.get("computed_priority", 0),
            source_id=data.get("source_id"),
            assigned_to=data.get("assigned_to"),
            dependencies=data.get("dependencies", []),
            blockers=data.get("blockers", []),
            deadline=(datetime.fromisoformat(data["deadline"]) if data.get("deadline") else None),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )

    def is_ready(self, completed_ids: set[str]) -> bool:
        """Check if work is ready (all dependencies met)."""
        return all(dep in completed_ids for dep in self.dependencies) and not self.blockers


@dataclass
class PriorityConfig:
    """Configuration for priority calculation."""

    # Weight factors (should sum to ~1.0)
    base_weight: float = 0.3
    deadline_weight: float = 0.3
    age_weight: float = 0.2
    dependency_weight: float = 0.1
    boost_weight: float = 0.1

    # Thresholds
    deadline_urgent_hours: int = 4
    deadline_soon_hours: int = 24
    age_boost_hours: int = 2
    max_age_boost: int = 30

    # Boosts and penalties
    critical_tag_boost: int = 20
    blocker_penalty: int = -50
    dependency_ready_boost: int = 10


class PriorityCalculator:
    """
    Calculates dynamic priority for work items.

    Considers multiple factors:
    - Base priority
    - Deadline urgency
    - Work age
    - Dependencies
    - Tags and boosts
    """

    def __init__(self, config: PriorityConfig | None = None):
        """
        Initialize the calculator.

        Args:
            config: Priority calculation configuration
        """
        self.config = config or PriorityConfig()
        self._tag_boosts: dict[str, int] = {
            "critical": 20,
            "urgent": 15,
            "high": 10,
            "normal": 0,
            "low": -10,
        }
        self._custom_boosts: dict[str, int] = {}

    def add_tag_boost(self, tag: str, boost: int) -> None:
        """Add a custom tag boost."""
        self._tag_boosts[tag] = boost

    def add_custom_boost(self, work_id: str, boost: int) -> None:
        """Add a custom boost for a specific work item."""
        self._custom_boosts[work_id] = boost

    def calculate(
        self,
        work: WorkItem,
        completed_ids: set[str] | None = None,
    ) -> int:
        """
        Calculate priority for a work item.

        Args:
            work: Work item to calculate priority for
            completed_ids: Set of completed work IDs (for dependency check)

        Returns:
            Computed priority (0-100, higher is more important)
        """
        completed_ids = completed_ids or set()
        now = datetime.now(timezone.utc)

        # Start with base priority
        priority = work.base_priority * self.config.base_weight

        # Deadline factor
        if work.deadline:
            hours_until = (work.deadline - now).total_seconds() / 3600
            if hours_until < 0:
                # Overdue - max urgency
                priority += 100 * self.config.deadline_weight
            elif hours_until < self.config.deadline_urgent_hours:
                priority += 80 * self.config.deadline_weight
            elif hours_until < self.config.deadline_soon_hours:
                priority += 50 * self.config.deadline_weight
            else:
                priority += 20 * self.config.deadline_weight

        # Age factor - older work gets priority boost
        age_hours = (now - work.created_at).total_seconds() / 3600
        if age_hours > self.config.age_boost_hours:
            age_boost = min(age_hours - self.config.age_boost_hours, self.config.max_age_boost)
            priority += age_boost * self.config.age_weight

        # Dependency factor
        if work.is_ready(completed_ids):
            priority += self.config.dependency_ready_boost * self.config.dependency_weight
        elif work.blockers:
            priority += self.config.blocker_penalty * self.config.dependency_weight

        # Tag boosts
        for tag in work.tags:
            if tag in self._tag_boosts:
                priority += self._tag_boosts[tag] * self.config.boost_weight

        # Custom boosts
        if work.id in self._custom_boosts:
            priority += self._custom_boosts[work.id] * self.config.boost_weight

        # Clamp to valid range
        return max(0, min(100, int(priority)))


class GlobalWorkQueue:
    """
    Unified priority queue for all work items.

    Merges work from beads, convoys, and other sources with
    dynamic prioritization.
    """

    def __init__(
        self,
        bead_store: BeadStore | None = None,
        convoy_manager: ConvoyManager | None = None,
        storage_dir: Path | None = None,
        calculator: PriorityCalculator | None = None,
    ):
        """
        Initialize the queue.

        Args:
            bead_store: Store for bead operations
            convoy_manager: Manager for convoy operations
            storage_dir: Directory for persistence
            calculator: Priority calculator
        """
        self.bead_store = bead_store
        self.convoy_manager = convoy_manager
        self.storage_dir = storage_dir or Path(".work_queue")
        self.calculator = calculator or PriorityCalculator()

        self._heap: list[PrioritizedWork] = []
        self._items: dict[str, WorkItem] = {}
        self._completed: set[str] = set()
        self._lock = asyncio.Lock()
        self._initialized = False
        self._callbacks: list[Callable] = []

    def register_callback(self, callback: Callable) -> None:
        """Register a callback for queue events."""
        self._callbacks.append(callback)

    async def initialize(self) -> None:
        """Initialize the queue, loading existing items."""
        if self._initialized:
            return

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        await self._load_queue()
        self._initialized = True
        logger.info("GlobalWorkQueue initialized with %s items", len(self._items))

    async def _load_queue(self) -> None:
        """Load queue from storage."""
        queue_file = self.storage_dir / "queue.jsonl"
        if not queue_file.exists():
            return

        try:
            with open(queue_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        work = WorkItem.from_dict(data)
                        self._items[work.id] = work
                        if work.status == WorkStatus.COMPLETED:
                            self._completed.add(work.id)
                        elif work.status in (WorkStatus.PENDING, WorkStatus.READY):
                            self._add_to_heap(work)
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Invalid queue data: %s", e)
        except OSError as e:
            logger.error("Failed to load queue: %s", e)

    async def _save_queue(self) -> None:
        """Save queue to storage."""
        queue_file = self.storage_dir / "queue.jsonl"
        temp_file = queue_file.with_suffix(".tmp")

        try:
            with open(temp_file, "w") as f:
                for work in self._items.values():
                    f.write(json.dumps(work.to_dict()) + "\n")
            temp_file.rename(queue_file)
        except OSError as e:
            if temp_file.exists():
                temp_file.unlink()
            logger.error("Failed to save queue: %s", e)

    def _add_to_heap(self, work: WorkItem) -> None:
        """Add work item to the priority heap."""
        # Update computed priority
        work.computed_priority = self.calculator.calculate(work, self._completed)

        # Use negative priority for max-heap behavior (higher priority first)
        sort_key = (
            -work.computed_priority,
            work.created_at,
            work.id,
        )
        heapq.heappush(self._heap, PrioritizedWork(sort_key, work))

    async def push(
        self,
        work: WorkItem,
        priority: int | None = None,
    ) -> WorkItem:
        """
        Add a work item to the queue.

        Args:
            work: Work item to add
            priority: Optional priority override

        Returns:
            The added work item
        """
        async with self._lock:
            if priority is not None:
                work.base_priority = priority

            work.status = WorkStatus.PENDING
            work.updated_at = datetime.now(timezone.utc)

            # Check if ready
            if work.is_ready(self._completed):
                work.status = WorkStatus.READY

            self._items[work.id] = work
            self._add_to_heap(work)
            await self._save_queue()

            logger.debug("Pushed work %s with priority %s", work.id, work.computed_priority)

            # Notify callbacks
            for callback in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback("push", work)
                    else:
                        callback("push", work)
                except (
                    TypeError,
                    ValueError,
                    RuntimeError,
                    AttributeError,
                    KeyError,
                    OSError,
                ) as e:
                    logger.error("Callback error: %s", e)

            return work

    async def upsert(
        self,
        work: WorkItem,
        *,
        priority: int | None = None,
        allow_reopen: bool = False,
        preserve_claimed: bool = True,
    ) -> WorkItem:
        """Create or refresh a work item without stomping active claims."""
        async with self._lock:
            existing = self._items.get(work.id)

            if (
                existing
                and preserve_claimed
                and existing.status
                in (
                    WorkStatus.CLAIMED,
                    WorkStatus.IN_PROGRESS,
                )
            ):
                return existing

            if priority is not None:
                work.base_priority = priority

            if existing:
                work.created_at = existing.created_at
                work.assigned_to = existing.assigned_to

            if existing and existing.status in (WorkStatus.COMPLETED, WorkStatus.FAILED):
                if not allow_reopen:
                    return existing
                self._completed.discard(work.id)

            work.updated_at = datetime.now(timezone.utc)
            work.status = WorkStatus.PENDING
            if work.is_ready(self._completed):
                work.status = WorkStatus.READY

            self._items[work.id] = work
            self._add_to_heap(work)
            await self._save_queue()

            logger.debug("Upserted work %s with priority %s", work.id, work.computed_priority)
            return work

    async def pop(
        self,
        work_type: WorkType | None = None,
        tags: list[str] | None = None,
    ) -> WorkItem | None:
        """
        Get the highest priority ready work item.

        Args:
            work_type: Optional filter by work type
            tags: Optional filter by tags

        Returns:
            Highest priority ready work item, or None
        """
        async with self._lock:
            while self._heap:
                prioritized = heapq.heappop(self._heap)
                work = prioritized.work_item

                # Skip if work is no longer in valid state
                current = self._items.get(work.id)
                if not current or current.status not in (WorkStatus.PENDING, WorkStatus.READY):
                    continue

                # Check filters
                if work_type and current.work_type != work_type:
                    # Put it back
                    heapq.heappush(self._heap, prioritized)
                    continue

                if tags and not any(t in current.tags for t in tags):
                    heapq.heappush(self._heap, prioritized)
                    continue

                # Check if ready
                if not current.is_ready(self._completed):
                    current.status = WorkStatus.BLOCKED
                    heapq.heappush(self._heap, prioritized)
                    continue

                # Claim the work
                current.status = WorkStatus.CLAIMED
                current.updated_at = datetime.now(timezone.utc)
                await self._save_queue()

                logger.debug(
                    "Popped work %s with priority %s", current.id, current.computed_priority
                )
                return current

            return None

    async def peek(self, count: int = 1) -> list[WorkItem]:
        """
        Peek at the top items without removing them.

        Args:
            count: Number of items to peek

        Returns:
            List of top items
        """
        async with self._lock:
            items: list[WorkItem] = []
            temp_heap = list(self._heap)

            while temp_heap and len(items) < count:
                prioritized = heapq.heappop(temp_heap)
                work = prioritized.work_item
                current = self._items.get(work.id)

                if current and current.status in (WorkStatus.PENDING, WorkStatus.READY):
                    items.append(current)

            return items

    async def complete(
        self,
        work_id: str,
        result: Any | None = None,
    ) -> WorkItem | None:
        """
        Mark work as completed.

        Args:
            work_id: ID of work to complete
            result: Optional result data

        Returns:
            Completed work item, or None if not found
        """
        async with self._lock:
            work = self._items.get(work_id)
            if not work:
                return None

            work.status = WorkStatus.COMPLETED
            work.updated_at = datetime.now(timezone.utc)
            if result:
                work.metadata["result"] = result

            self._completed.add(work_id)

            # Check for unblocked work
            await self._check_unblocked()
            await self._save_queue()

            logger.info("Completed work %s", work_id)
            return work

    async def fail(
        self,
        work_id: str,
        error: str | None = None,
    ) -> WorkItem | None:
        """
        Mark work as failed.

        Args:
            work_id: ID of work to fail
            error: Optional error message

        Returns:
            Failed work item, or None if not found
        """
        async with self._lock:
            work = self._items.get(work_id)
            if not work:
                return None

            work.status = WorkStatus.FAILED
            work.updated_at = datetime.now(timezone.utc)
            if error:
                work.metadata["error"] = error

            await self._save_queue()

            logger.warning("Failed work %s: %s", work_id, error)
            return work

    async def _check_unblocked(self) -> list[WorkItem]:
        """Check for work items that are now unblocked."""
        unblocked = []

        for work in self._items.values():
            if work.status == WorkStatus.BLOCKED:
                if work.is_ready(self._completed):
                    work.status = WorkStatus.READY
                    work.updated_at = datetime.now(timezone.utc)
                    self._add_to_heap(work)
                    unblocked.append(work)
                    logger.debug("Work %s unblocked", work.id)

        return unblocked

    async def reprioritize(self) -> int:
        """
        Recalculate priorities for all pending work.

        Returns:
            Number of items reprioritized
        """
        async with self._lock:
            count = 0

            # Rebuild heap with new priorities
            new_heap: list[PrioritizedWork] = []

            for work in self._items.values():
                if work.status in (WorkStatus.PENDING, WorkStatus.READY, WorkStatus.BLOCKED):
                    # Check if blocked status changed
                    if work.is_ready(self._completed):
                        if work.status == WorkStatus.BLOCKED:
                            work.status = WorkStatus.READY
                    elif work.status != WorkStatus.BLOCKED:
                        work.status = WorkStatus.BLOCKED

                    # Recalculate priority
                    old_priority = work.computed_priority
                    work.computed_priority = self.calculator.calculate(work, self._completed)

                    if work.computed_priority != old_priority:
                        count += 1

                    # Add to new heap
                    sort_key = (
                        -work.computed_priority,
                        work.created_at,
                        work.id,
                    )
                    heapq.heappush(new_heap, PrioritizedWork(sort_key, work))

            self._heap = new_heap
            await self._save_queue()

            logger.info("Reprioritized %s work items", count)
            return count

    async def import_from_beads(self) -> int:
        """
        Import pending beads into the queue.

        Returns:
            Number of beads imported
        """
        if not self.bead_store:
            return 0

        from aragora.nomic.beads import BeadStatus

        async with self._lock:
            count = 0
            beads = await self.bead_store.list_by_status(status=BeadStatus.PENDING)

            for bead in beads:
                if bead.id not in self._items:
                    work = WorkItem(
                        id=bead.id,
                        work_type=WorkType.BEAD,
                        title=bead.title,
                        description=bead.description,
                        status=WorkStatus.PENDING,
                        created_at=bead.created_at,
                        updated_at=bead.updated_at,
                        base_priority=bead.priority.value,
                        source_id=bead.id,
                        dependencies=bead.dependencies,
                        tags=bead.tags,
                        metadata={"bead_type": bead.bead_type.value},
                    )

                    # Check if ready
                    if work.is_ready(self._completed):
                        work.status = WorkStatus.READY

                    self._items[work.id] = work
                    self._add_to_heap(work)
                    count += 1

            if count > 0:
                await self._save_queue()
                logger.info("Imported %s beads into queue", count)

            return count

    async def import_from_convoys(self) -> int:
        """
        Import pending convoy beads into the queue.

        Returns:
            Number of work items imported
        """
        if not self.convoy_manager:
            return 0

        from aragora.nomic.convoys import ConvoyStatus

        async with self._lock:
            count = 0
            convoys = await self.convoy_manager.list_convoys(status=ConvoyStatus.PENDING)

            for convoy in convoys:
                # Create a work item for the convoy itself
                if convoy.id not in self._items:
                    work = WorkItem(
                        id=convoy.id,
                        work_type=WorkType.CONVOY,
                        title=convoy.title,
                        description=convoy.description,
                        status=WorkStatus.PENDING,
                        created_at=convoy.created_at,
                        updated_at=convoy.updated_at,
                        base_priority=convoy.priority.value,
                        source_id=convoy.id,
                        dependencies=convoy.dependencies,
                        tags=convoy.tags,
                        metadata={"bead_count": len(convoy.bead_ids)},
                    )

                    if work.is_ready(self._completed):
                        work.status = WorkStatus.READY

                    self._items[work.id] = work
                    self._add_to_heap(work)
                    count += 1

            if count > 0:
                await self._save_queue()
                logger.info("Imported %s convoys into queue", count)

            return count

    async def get(self, work_id: str) -> WorkItem | None:
        """Get a work item by ID."""
        return self._items.get(work_id)

    async def list_items(
        self,
        status: WorkStatus | None = None,
        work_type: WorkType | None = None,
        limit: int = 100,
    ) -> list[WorkItem]:
        """
        List work items with optional filters.

        Args:
            status: Optional status filter
            work_type: Optional type filter
            limit: Maximum items to return

        Returns:
            List of matching work items
        """
        items = list(self._items.values())

        if status:
            items = [i for i in items if i.status == status]

        if work_type:
            items = [i for i in items if i.work_type == work_type]

        # Sort by priority
        items.sort(key=lambda i: -i.computed_priority)

        return items[:limit]

    async def get_statistics(self) -> dict[str, Any]:
        """Get queue statistics."""
        items = list(self._items.values())

        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for item in items:
            status_key = item.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            type_key = item.work_type.value
            by_type[type_key] = by_type.get(type_key, 0) + 1

        pending = [i for i in items if i.status in (WorkStatus.PENDING, WorkStatus.READY)]
        avg_priority = sum(i.computed_priority for i in pending) / len(pending) if pending else 0

        return {
            "total_items": len(items),
            "pending_items": len(pending),
            "completed_items": len(self._completed),
            "by_status": by_status,
            "by_type": by_type,
            "avg_pending_priority": avg_priority,
            "heap_size": len(self._heap),
        }


# Singleton instance
_default_queue: GlobalWorkQueue | None = None


async def get_global_work_queue(
    bead_store: BeadStore | None = None,
    convoy_manager: ConvoyManager | None = None,
) -> GlobalWorkQueue:
    """Get the default global work queue instance."""
    global _default_queue
    if _default_queue is None:
        _default_queue = GlobalWorkQueue(
            bead_store=bead_store,
            convoy_manager=convoy_manager,
        )
        await _default_queue.initialize()
    return _default_queue


def reset_global_work_queue() -> None:
    """Reset the default queue (for testing)."""
    global _default_queue
    _default_queue = None
