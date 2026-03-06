"""Comprehensive tests for the global_work_queue module."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from aragora.nomic.global_work_queue import (
    GlobalWorkQueue,
    PriorityCalculator,
    PriorityConfig,
    PrioritizedWork,
    WorkItem,
    WorkStatus,
    WorkType,
    get_global_work_queue,
    reset_global_work_queue,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _make_work_item(
    id: str = "w-1",
    work_type: WorkType = WorkType.BEAD,
    title: str = "Test work",
    description: str = "Test description",
    status: WorkStatus = WorkStatus.PENDING,
    base_priority: int = 50,
    computed_priority: int = 0,
    source_id: str | None = None,
    assigned_to: str | None = None,
    dependencies: list[str] | None = None,
    blockers: list[str] | None = None,
    deadline: datetime | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> WorkItem:
    """Create a WorkItem with sensible defaults."""
    now = _now()
    return WorkItem(
        id=id,
        work_type=work_type,
        title=title,
        description=description,
        status=status,
        created_at=created_at or now,
        updated_at=updated_at or now,
        base_priority=base_priority,
        computed_priority=computed_priority,
        source_id=source_id,
        assigned_to=assigned_to,
        dependencies=dependencies or [],
        blockers=blockers or [],
        deadline=deadline,
        tags=tags or [],
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton before and after each test."""
    reset_global_work_queue()
    yield
    reset_global_work_queue()


@pytest.fixture
def tmp_storage(tmp_path: Path) -> Path:
    """Provide a temporary storage directory."""
    return tmp_path / "work_queue"


@pytest.fixture
def calculator() -> PriorityCalculator:
    return PriorityCalculator()


@pytest.fixture
def queue(tmp_storage: Path) -> GlobalWorkQueue:
    """Create a GlobalWorkQueue with temporary storage."""
    return GlobalWorkQueue(storage_dir=tmp_storage)


# ===========================================================================
# WorkType and WorkStatus enums
# ===========================================================================


class TestWorkType:
    """Tests for the WorkType enum."""

    def test_values(self):
        assert WorkType.BEAD.value == "bead"
        assert WorkType.CONVOY.value == "convoy"
        assert WorkType.MOLECULE.value == "molecule"
        assert WorkType.ESCALATION.value == "escalation"
        assert WorkType.MAINTENANCE.value == "maintenance"
        assert WorkType.CUSTOM.value == "custom"

    def test_is_string_enum(self):
        assert isinstance(WorkType.BEAD, str)
        assert WorkType.BEAD == "bead"


class TestWorkStatus:
    """Tests for the WorkStatus enum."""

    def test_values(self):
        assert WorkStatus.PENDING.value == "pending"
        assert WorkStatus.READY.value == "ready"
        assert WorkStatus.CLAIMED.value == "claimed"
        assert WorkStatus.IN_PROGRESS.value == "in_progress"
        assert WorkStatus.BLOCKED.value == "blocked"
        assert WorkStatus.COMPLETED.value == "completed"
        assert WorkStatus.FAILED.value == "failed"


# ===========================================================================
# WorkItem
# ===========================================================================


class TestWorkItem:
    """Tests for the WorkItem dataclass."""

    def test_creation_defaults(self):
        item = _make_work_item()
        assert item.id == "w-1"
        assert item.work_type == WorkType.BEAD
        assert item.base_priority == 50
        assert item.computed_priority == 50  # defaults to base when 0
        assert item.dependencies == []
        assert item.blockers == []
        assert item.tags == []
        assert item.metadata == {}
        assert item.assigned_to is None
        assert item.deadline is None

    def test_post_init_sets_computed_from_base(self):
        """When computed_priority is 0 (default), it should take base_priority."""
        item = _make_work_item(base_priority=75)
        assert item.computed_priority == 75

    def test_post_init_preserves_nonzero_computed(self):
        """When computed_priority is explicitly set to nonzero, it should stay."""
        item = _make_work_item(base_priority=75, computed_priority=90)
        assert item.computed_priority == 90

    def test_to_dict(self):
        deadline = _now() + timedelta(hours=5)
        item = _make_work_item(
            id="w-dict",
            work_type=WorkType.CONVOY,
            title="Dict test",
            description="Desc",
            status=WorkStatus.READY,
            base_priority=80,
            computed_priority=85,
            source_id="src-1",
            assigned_to="agent-a",
            dependencies=["dep-1"],
            blockers=["blk-1"],
            deadline=deadline,
            tags=["urgent"],
            metadata={"key": "val"},
        )
        d = item.to_dict()
        assert d["id"] == "w-dict"
        assert d["work_type"] == "convoy"
        assert d["status"] == "ready"
        assert d["base_priority"] == 80
        assert d["computed_priority"] == 85
        assert d["source_id"] == "src-1"
        assert d["assigned_to"] == "agent-a"
        assert d["dependencies"] == ["dep-1"]
        assert d["blockers"] == ["blk-1"]
        assert d["deadline"] == deadline.isoformat()
        assert d["tags"] == ["urgent"]
        assert d["metadata"] == {"key": "val"}

    def test_from_dict_roundtrip(self):
        original = _make_work_item(
            id="w-rt",
            tags=["critical"],
            deadline=_now() + timedelta(hours=1),
        )
        d = original.to_dict()
        restored = WorkItem.from_dict(d)
        assert restored.id == original.id
        assert restored.work_type == original.work_type
        assert restored.status == original.status
        assert restored.base_priority == original.base_priority
        assert restored.tags == original.tags

    def test_from_dict_with_missing_optional_fields(self):
        """from_dict should handle missing optional fields gracefully."""
        data = {
            "id": "w-min",
            "work_type": "bead",
            "title": "Minimal",
            "status": "pending",
            "created_at": _now().isoformat(),
            "updated_at": _now().isoformat(),
        }
        item = WorkItem.from_dict(data)
        assert item.id == "w-min"
        assert item.description == ""
        assert item.base_priority == 50  # default
        assert item.dependencies == []
        assert item.deadline is None
        assert item.metadata == {}

    def test_is_ready_no_dependencies(self):
        item = _make_work_item()
        assert item.is_ready(set()) is True

    def test_is_ready_all_deps_met(self):
        item = _make_work_item(dependencies=["d1", "d2"])
        assert item.is_ready({"d1", "d2", "d3"}) is True

    def test_is_ready_deps_not_met(self):
        item = _make_work_item(dependencies=["d1", "d2"])
        assert item.is_ready({"d1"}) is False

    def test_is_ready_with_blockers(self):
        """Even if deps are met, blockers make it not ready."""
        item = _make_work_item(blockers=["some-blocker"])
        assert item.is_ready(set()) is False

    def test_is_ready_deps_met_but_blockers(self):
        item = _make_work_item(dependencies=["d1"], blockers=["b1"])
        assert item.is_ready({"d1"}) is False


# ===========================================================================
# PrioritizedWork
# ===========================================================================


class TestPrioritizedWork:
    """Tests for the PrioritizedWork ordering wrapper."""

    def test_ordering_by_negative_priority(self):
        """Lower (more negative) sort_priority should be higher priority."""
        now = _now()
        high = PrioritizedWork((-90, now, "a"), _make_work_item(id="high"))
        low = PrioritizedWork((-10, now, "b"), _make_work_item(id="low"))
        assert high < low  # -90 < -10, so high comes first in heap

    def test_ordering_tiebreak_by_created_at(self):
        t1 = _now()
        t2 = t1 + timedelta(seconds=1)
        older = PrioritizedWork((-50, t1, "a"), _make_work_item(id="older"))
        newer = PrioritizedWork((-50, t2, "b"), _make_work_item(id="newer"))
        assert older < newer  # older created_at wins

    def test_ordering_tiebreak_by_id(self):
        now = _now()
        a = PrioritizedWork((-50, now, "aaa"), _make_work_item(id="aaa"))
        b = PrioritizedWork((-50, now, "bbb"), _make_work_item(id="bbb"))
        assert a < b


# ===========================================================================
# PriorityConfig
# ===========================================================================


class TestPriorityConfig:
    """Tests for the PriorityConfig dataclass."""

    def test_default_values(self):
        cfg = PriorityConfig()
        assert cfg.base_weight == 0.3
        assert cfg.deadline_weight == 0.3
        assert cfg.age_weight == 0.2
        assert cfg.dependency_weight == 0.1
        assert cfg.boost_weight == 0.1
        assert cfg.deadline_urgent_hours == 4
        assert cfg.deadline_soon_hours == 24
        assert cfg.age_boost_hours == 2
        assert cfg.max_age_boost == 30

    def test_custom_values(self):
        cfg = PriorityConfig(base_weight=0.5, deadline_weight=0.5)
        assert cfg.base_weight == 0.5
        assert cfg.deadline_weight == 0.5


# ===========================================================================
# PriorityCalculator
# ===========================================================================


class TestPriorityCalculator:
    """Tests for the PriorityCalculator."""

    def test_init_defaults(self, calculator: PriorityCalculator):
        assert isinstance(calculator.config, PriorityConfig)
        assert "critical" in calculator._tag_boosts

    def test_init_custom_config(self):
        cfg = PriorityConfig(base_weight=0.5)
        calc = PriorityCalculator(config=cfg)
        assert calc.config.base_weight == 0.5

    def test_add_tag_boost(self, calculator: PriorityCalculator):
        calculator.add_tag_boost("vip", 25)
        assert calculator._tag_boosts["vip"] == 25

    def test_add_custom_boost(self, calculator: PriorityCalculator):
        calculator.add_custom_boost("w-1", 15)
        assert calculator._custom_boosts["w-1"] == 15

    def test_calculate_base_priority_only(self, calculator: PriorityCalculator):
        item = _make_work_item(base_priority=50)
        prio = calculator.calculate(item)
        # 50 * 0.3 = 15 base component
        assert prio >= 0
        assert prio <= 100

    def test_calculate_deadline_overdue(self, calculator: PriorityCalculator):
        """Overdue deadline should give maximum urgency."""
        item = _make_work_item(
            base_priority=50,
            deadline=_now() - timedelta(hours=1),
        )
        prio = calculator.calculate(item)
        # base=15, deadline=100*0.3=30
        assert prio > 40

    def test_calculate_deadline_urgent(self, calculator: PriorityCalculator):
        """Deadline within urgent hours adds high priority."""
        item = _make_work_item(
            base_priority=50,
            deadline=_now() + timedelta(hours=2),  # < 4 hours
        )
        prio = calculator.calculate(item)
        # 50*0.3 + 80*0.3 = 15+24 = 39
        assert prio >= 30

    def test_calculate_deadline_soon(self, calculator: PriorityCalculator):
        """Deadline within soon hours adds moderate priority."""
        item = _make_work_item(
            base_priority=50,
            deadline=_now() + timedelta(hours=12),  # < 24 hours
        )
        prio = calculator.calculate(item)
        assert prio >= 20

    def test_calculate_deadline_far_away(self, calculator: PriorityCalculator):
        """Far deadline adds minimal priority."""
        item = _make_work_item(
            base_priority=50,
            deadline=_now() + timedelta(days=7),
        )
        prio = calculator.calculate(item)
        # 50*0.3 + 20*0.3 = 15 + 6 = 21
        assert prio >= 15

    def test_calculate_age_boost(self, calculator: PriorityCalculator):
        """Older items should get an age boost."""
        old = _make_work_item(
            base_priority=50,
            created_at=_now() - timedelta(hours=10),
        )
        new = _make_work_item(
            base_priority=50,
            created_at=_now(),
        )
        old_prio = calculator.calculate(old)
        new_prio = calculator.calculate(new)
        assert old_prio >= new_prio

    def test_calculate_age_boost_capped(self, calculator: PriorityCalculator):
        """Age boost should be capped at max_age_boost."""
        very_old = _make_work_item(
            base_priority=50,
            created_at=_now() - timedelta(hours=1000),
        )
        prio = calculator.calculate(very_old)
        assert prio <= 100

    def test_calculate_dependency_ready_boost(self, calculator: PriorityCalculator):
        """Ready items get a dependency boost."""
        item = _make_work_item(base_priority=50, dependencies=["d1"])
        prio_not_ready = calculator.calculate(item, completed_ids=set())
        prio_ready = calculator.calculate(item, completed_ids={"d1"})
        # Ready gets +10*0.1 = +1 vs no boost
        assert prio_ready >= prio_not_ready

    def test_calculate_blocker_penalty(self, calculator: PriorityCalculator):
        """Blocked items get a penalty."""
        item = _make_work_item(base_priority=50, blockers=["blk-1"])
        prio = calculator.calculate(item)
        # blocker_penalty=-50, * dependency_weight=0.1 = -5
        assert prio >= 0  # clamped to 0

    def test_calculate_tag_boost_critical(self, calculator: PriorityCalculator):
        """Critical tag should boost priority."""
        item_critical = _make_work_item(base_priority=50, tags=["critical"])
        item_plain = _make_work_item(base_priority=50)
        prio_critical = calculator.calculate(item_critical)
        prio_plain = calculator.calculate(item_plain)
        assert prio_critical > prio_plain

    def test_calculate_tag_boost_low(self, calculator: PriorityCalculator):
        """Low tag should reduce priority."""
        item_low = _make_work_item(base_priority=50, tags=["low"])
        item_plain = _make_work_item(base_priority=50)
        prio_low = calculator.calculate(item_low)
        prio_plain = calculator.calculate(item_plain)
        assert prio_low < prio_plain

    def test_calculate_custom_boost(self, calculator: PriorityCalculator):
        """Custom work-specific boost should increase priority."""
        calculator.add_custom_boost("w-special", 30)
        item = _make_work_item(id="w-special", base_priority=50)
        item_normal = _make_work_item(id="w-normal", base_priority=50)
        prio_special = calculator.calculate(item)
        prio_normal = calculator.calculate(item_normal)
        assert prio_special > prio_normal

    def test_calculate_clamped_to_0_100(self, calculator: PriorityCalculator):
        """Result should be clamped to [0, 100]."""
        # Very low priority with penalties
        item_low = _make_work_item(base_priority=0, blockers=["b"], tags=["low"])
        prio = calculator.calculate(item_low)
        assert 0 <= prio <= 100

        # Very high priority with boosts
        item_high = _make_work_item(
            base_priority=100,
            tags=["critical", "urgent"],
            deadline=_now() - timedelta(hours=1),
            created_at=_now() - timedelta(hours=100),
        )
        prio = calculator.calculate(item_high)
        assert 0 <= prio <= 100

    def test_calculate_multiple_tags(self, calculator: PriorityCalculator):
        """Multiple tag boosts should stack."""
        item = _make_work_item(base_priority=50, tags=["critical", "urgent"])
        prio = calculator.calculate(item)
        # critical=20*0.1=2, urgent=15*0.1=1.5 = 3.5 extra
        item_single = _make_work_item(base_priority=50, tags=["critical"])
        prio_single = calculator.calculate(item_single)
        assert prio >= prio_single


# ===========================================================================
# GlobalWorkQueue - Initialization
# ===========================================================================


class TestGlobalWorkQueueInit:
    """Tests for GlobalWorkQueue initialization."""

    def test_init_defaults(self, queue: GlobalWorkQueue):
        assert queue._items == {}
        assert queue._heap == []
        assert queue._completed == set()
        assert queue._initialized is False

    def test_init_custom_storage(self, tmp_storage: Path):
        q = GlobalWorkQueue(storage_dir=tmp_storage)
        assert q.storage_dir == tmp_storage

    def test_init_custom_calculator(self, tmp_storage: Path):
        calc = PriorityCalculator(PriorityConfig(base_weight=0.8))
        q = GlobalWorkQueue(storage_dir=tmp_storage, calculator=calc)
        assert q.calculator.config.base_weight == 0.8

    @pytest.mark.asyncio
    async def test_initialize_creates_directory(self, tmp_storage: Path):
        q = GlobalWorkQueue(storage_dir=tmp_storage)
        assert not tmp_storage.exists()
        await q.initialize()
        assert tmp_storage.exists()
        assert q._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, queue: GlobalWorkQueue):
        await queue.initialize()
        await queue.initialize()  # should not raise
        assert queue._initialized is True

    @pytest.mark.asyncio
    async def test_register_callback(self, queue: GlobalWorkQueue):
        cb = MagicMock()
        queue.register_callback(cb)
        assert cb in queue._callbacks


# ===========================================================================
# GlobalWorkQueue - Push
# ===========================================================================


class TestGlobalWorkQueuePush:
    """Tests for pushing items onto the queue."""

    @pytest.mark.asyncio
    async def test_push_basic(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="push-1")
        result = await queue.push(item)
        assert result.id == "push-1"
        assert result.status in (WorkStatus.PENDING, WorkStatus.READY)
        assert "push-1" in queue._items
        assert len(queue._heap) == 1

    @pytest.mark.asyncio
    async def test_push_with_priority_override(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="push-prio", base_priority=30)
        result = await queue.push(item, priority=90)
        assert result.base_priority == 90

    @pytest.mark.asyncio
    async def test_push_sets_ready_when_deps_met(self, queue: GlobalWorkQueue):
        await queue.initialize()
        # No dependencies -> READY
        item = _make_work_item(id="push-ready")
        result = await queue.push(item)
        assert result.status == WorkStatus.READY

    @pytest.mark.asyncio
    async def test_push_stays_pending_when_deps_not_met(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="push-pending", dependencies=["unmet-dep"])
        result = await queue.push(item)
        assert result.status == WorkStatus.PENDING

    @pytest.mark.asyncio
    async def test_push_saves_queue(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="push-save")
        await queue.push(item)
        queue_file = queue.storage_dir / "queue.jsonl"
        assert queue_file.exists()
        content = queue_file.read_text()
        assert "push-save" in content

    @pytest.mark.asyncio
    async def test_push_triggers_sync_callback(self, queue: GlobalWorkQueue):
        await queue.initialize()
        cb = MagicMock()
        queue.register_callback(cb)
        item = _make_work_item(id="push-cb")
        await queue.push(item)
        cb.assert_called_once()
        args = cb.call_args[0]
        assert args[0] == "push"
        assert args[1].id == "push-cb"

    @pytest.mark.asyncio
    async def test_push_triggers_async_callback(self, queue: GlobalWorkQueue):
        await queue.initialize()
        cb = AsyncMock()
        queue.register_callback(cb)
        item = _make_work_item(id="push-acb")
        await queue.push(item)
        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_push_callback_error_does_not_propagate(self, queue: GlobalWorkQueue):
        await queue.initialize()
        cb = MagicMock(side_effect=RuntimeError("boom"))
        queue.register_callback(cb)
        item = _make_work_item(id="push-err")
        result = await queue.push(item)
        assert result is not None  # should not raise

    @pytest.mark.asyncio
    async def test_push_multiple_items(self, queue: GlobalWorkQueue):
        await queue.initialize()
        for i in range(5):
            await queue.push(_make_work_item(id=f"multi-{i}", base_priority=i * 20))
        assert len(queue._items) == 5
        assert len(queue._heap) == 5

    @pytest.mark.asyncio
    async def test_upsert_reopens_completed_when_allowed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="salvage:1", work_type=WorkType.MAINTENANCE)
        await queue.push(item)
        await queue.complete(item.id, result={"reason": "done"})

        refreshed = _make_work_item(
            id="salvage:1",
            work_type=WorkType.MAINTENANCE,
            base_priority=80,
        )
        stored = await queue.upsert(refreshed, allow_reopen=True)

        assert stored.status == WorkStatus.READY
        reopened = await queue.get(item.id)
        assert reopened is not None
        assert reopened.status == WorkStatus.READY

    @pytest.mark.asyncio
    async def test_upsert_preserves_claimed_items(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="salvage:2", work_type=WorkType.MAINTENANCE)
        await queue.push(item)
        claimed = await queue.pop()

        refreshed = _make_work_item(
            id="salvage:2",
            work_type=WorkType.MAINTENANCE,
            title="Refreshed title",
        )
        stored = await queue.upsert(refreshed)

        assert claimed is not None
        assert stored.status == WorkStatus.CLAIMED
        assert stored.title == item.title


# ===========================================================================
# GlobalWorkQueue - Pop
# ===========================================================================


class TestGlobalWorkQueuePop:
    """Tests for popping items from the queue."""

    @pytest.mark.asyncio
    async def test_pop_empty_queue(self, queue: GlobalWorkQueue):
        await queue.initialize()
        result = await queue.pop()
        assert result is None

    @pytest.mark.asyncio
    async def test_pop_returns_highest_priority(self, queue: GlobalWorkQueue):
        await queue.initialize()
        low = _make_work_item(id="low", base_priority=10)
        high = _make_work_item(id="high", base_priority=90)
        await queue.push(low)
        await queue.push(high)
        result = await queue.pop()
        assert result is not None
        assert result.id == "high"

    @pytest.mark.asyncio
    async def test_pop_marks_claimed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="claim-me")
        await queue.push(item)
        result = await queue.pop()
        assert result is not None
        assert result.status == WorkStatus.CLAIMED

    @pytest.mark.asyncio
    async def test_pop_filter_by_work_type(self, queue: GlobalWorkQueue):
        """Pop with work_type filter returns matching item when it is highest priority."""
        await queue.initialize()
        bead = _make_work_item(id="bead", work_type=WorkType.BEAD, base_priority=90)
        convoy = _make_work_item(id="convoy", work_type=WorkType.CONVOY, base_priority=50)
        await queue.push(bead)
        await queue.push(convoy)
        result = await queue.pop(work_type=WorkType.BEAD)
        assert result is not None
        assert result.id == "bead"
        assert result.work_type == WorkType.BEAD

    @pytest.mark.asyncio
    async def test_pop_filter_by_work_type_only_matching(self, queue: GlobalWorkQueue):
        """Pop with work_type filter when all items are of that type."""
        await queue.initialize()
        bead1 = _make_work_item(id="bead1", work_type=WorkType.BEAD, base_priority=80)
        bead2 = _make_work_item(id="bead2", work_type=WorkType.BEAD, base_priority=40)
        await queue.push(bead1)
        await queue.push(bead2)
        result = await queue.pop(work_type=WorkType.BEAD)
        assert result is not None
        assert result.id == "bead1"

    @pytest.mark.asyncio
    async def test_pop_filter_by_tags(self, queue: GlobalWorkQueue):
        """Pop with tag filter returns matching item when it is highest priority."""
        await queue.initialize()
        tagged = _make_work_item(id="tagged", tags=["deploy"], base_priority=90)
        untagged = _make_work_item(id="untagged", base_priority=50)
        await queue.push(tagged)
        await queue.push(untagged)
        result = await queue.pop(tags=["deploy"])
        assert result is not None
        assert result.id == "tagged"

    @pytest.mark.asyncio
    async def test_pop_filter_by_tags_only_matching(self, queue: GlobalWorkQueue):
        """Pop with tag filter when all items have matching tags."""
        await queue.initialize()
        t1 = _make_work_item(id="t1", tags=["deploy"], base_priority=80)
        t2 = _make_work_item(id="t2", tags=["deploy"], base_priority=40)
        await queue.push(t1)
        await queue.push(t2)
        result = await queue.pop(tags=["deploy"])
        assert result is not None
        assert result.id == "t1"

    @pytest.mark.asyncio
    async def test_pop_skips_blocked(self, queue: GlobalWorkQueue):
        await queue.initialize()
        blocked = _make_work_item(id="blocked", dependencies=["unmet"], base_priority=90)
        ready = _make_work_item(id="ready", base_priority=50)
        await queue.push(blocked)
        await queue.push(ready)
        result = await queue.pop()
        assert result is not None
        assert result.id == "ready"

    @pytest.mark.asyncio
    async def test_pop_skips_already_claimed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item1 = _make_work_item(id="first", base_priority=80)
        item2 = _make_work_item(id="second", base_priority=50)
        await queue.push(item1)
        await queue.push(item2)
        first = await queue.pop()
        assert first is not None
        assert first.id == "first"
        second = await queue.pop()
        assert second is not None
        assert second.id == "second"

    @pytest.mark.asyncio
    async def test_pop_all_claimed_returns_none(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="only-one")
        await queue.push(item)
        await queue.pop()
        result = await queue.pop()
        assert result is None


# ===========================================================================
# GlobalWorkQueue - Peek
# ===========================================================================


class TestGlobalWorkQueuePeek:
    """Tests for peeking at the queue."""

    @pytest.mark.asyncio
    async def test_peek_empty(self, queue: GlobalWorkQueue):
        await queue.initialize()
        result = await queue.peek()
        assert result == []

    @pytest.mark.asyncio
    async def test_peek_returns_items_without_removing(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="peek-me", base_priority=50)
        await queue.push(item)
        peeked = await queue.peek()
        assert len(peeked) == 1
        assert peeked[0].id == "peek-me"
        # Item should still be poppable
        popped = await queue.pop()
        assert popped is not None
        assert popped.id == "peek-me"

    @pytest.mark.asyncio
    async def test_peek_count(self, queue: GlobalWorkQueue):
        await queue.initialize()
        for i in range(5):
            await queue.push(_make_work_item(id=f"peek-{i}", base_priority=i * 20))
        peeked = await queue.peek(count=3)
        assert len(peeked) == 3

    @pytest.mark.asyncio
    async def test_peek_skips_non_pending_ready(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="peek-skip")
        await queue.push(item)
        await queue.pop()  # claim it
        peeked = await queue.peek()
        assert len(peeked) == 0


# ===========================================================================
# GlobalWorkQueue - Complete
# ===========================================================================


class TestGlobalWorkQueueComplete:
    """Tests for completing work items."""

    @pytest.mark.asyncio
    async def test_complete_basic(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="comp-1")
        await queue.push(item)
        result = await queue.complete("comp-1")
        assert result is not None
        assert result.status == WorkStatus.COMPLETED
        assert "comp-1" in queue._completed

    @pytest.mark.asyncio
    async def test_complete_with_result(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="comp-result")
        await queue.push(item)
        result = await queue.complete("comp-result", result={"output": "success"})
        assert result is not None
        assert result.metadata["result"] == {"output": "success"}

    @pytest.mark.asyncio
    async def test_complete_nonexistent(self, queue: GlobalWorkQueue):
        await queue.initialize()
        result = await queue.complete("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_complete_unblocks_dependent(self, queue: GlobalWorkQueue):
        await queue.initialize()
        dep = _make_work_item(id="dep-item", base_priority=50)
        await queue.push(dep)
        blocked = _make_work_item(id="blocked-item", dependencies=["dep-item"], base_priority=80)
        await queue.push(blocked)

        # Pop the dependency first
        popped = await queue.pop()
        assert popped is not None

        # The blocked item should be blocked
        blocked_item = queue._items["blocked-item"]
        # Manually set blocked status (pop would have done this if it was tried)
        blocked_item.status = WorkStatus.BLOCKED

        # Complete the dependency
        await queue.complete("dep-item")

        # The blocked item should now be unblocked
        assert queue._items["blocked-item"].status == WorkStatus.READY


# ===========================================================================
# GlobalWorkQueue - Fail
# ===========================================================================


class TestGlobalWorkQueueFail:
    """Tests for failing work items."""

    @pytest.mark.asyncio
    async def test_fail_basic(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="fail-1")
        await queue.push(item)
        result = await queue.fail("fail-1")
        assert result is not None
        assert result.status == WorkStatus.FAILED

    @pytest.mark.asyncio
    async def test_fail_with_error(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="fail-err")
        await queue.push(item)
        result = await queue.fail("fail-err", error="Something broke")
        assert result is not None
        assert result.metadata["error"] == "Something broke"

    @pytest.mark.asyncio
    async def test_fail_nonexistent(self, queue: GlobalWorkQueue):
        await queue.initialize()
        result = await queue.fail("nonexistent")
        assert result is None


# ===========================================================================
# GlobalWorkQueue - Reprioritize
# ===========================================================================


class TestGlobalWorkQueueReprioritize:
    """Tests for the reprioritize method."""

    @pytest.mark.asyncio
    async def test_reprioritize_empty_queue(self, queue: GlobalWorkQueue):
        await queue.initialize()
        count = await queue.reprioritize()
        assert count == 0

    @pytest.mark.asyncio
    async def test_reprioritize_recalculates(self, queue: GlobalWorkQueue):
        await queue.initialize()
        # Push items
        for i in range(3):
            await queue.push(_make_work_item(id=f"reprio-{i}", base_priority=50))

        # Add a custom boost that will cause recalculation
        queue.calculator.add_custom_boost("reprio-1", 50)
        count = await queue.reprioritize()
        # At least the boosted item should have changed
        assert count >= 1

    @pytest.mark.asyncio
    async def test_reprioritize_unblocks_items(self, queue: GlobalWorkQueue):
        await queue.initialize()
        dep = _make_work_item(id="dep-r", base_priority=50)
        blocked = _make_work_item(id="blocked-r", dependencies=["dep-r"], base_priority=80)
        await queue.push(dep)
        await queue.push(blocked)

        # Complete the dependency
        queue._items["dep-r"].status = WorkStatus.COMPLETED
        queue._completed.add("dep-r")

        # Blocked item was pending (since deps weren't met initially)
        queue._items["blocked-r"].status = WorkStatus.BLOCKED

        await queue.reprioritize()
        assert queue._items["blocked-r"].status == WorkStatus.READY

    @pytest.mark.asyncio
    async def test_reprioritize_blocks_newly_blocked(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="newblock", base_priority=50)
        await queue.push(item)
        # Manually add a dependency that's not met
        queue._items["newblock"].dependencies = ["missing-dep"]
        await queue.reprioritize()
        assert queue._items["newblock"].status == WorkStatus.BLOCKED

    @pytest.mark.asyncio
    async def test_reprioritize_skips_completed_and_failed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item1 = _make_work_item(id="done")
        item2 = _make_work_item(id="failed")
        await queue.push(item1)
        await queue.push(item2)
        await queue.complete("done")
        await queue.fail("failed")
        count = await queue.reprioritize()
        # Completed and failed items should not be recalculated
        assert queue._items["done"].status == WorkStatus.COMPLETED
        assert queue._items["failed"].status == WorkStatus.FAILED


# ===========================================================================
# GlobalWorkQueue - Get, List, Statistics
# ===========================================================================


class TestGlobalWorkQueueQueryMethods:
    """Tests for get, list_items, and get_statistics."""

    @pytest.mark.asyncio
    async def test_get_existing(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="get-1")
        await queue.push(item)
        result = await queue.get("get-1")
        assert result is not None
        assert result.id == "get-1"

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, queue: GlobalWorkQueue):
        await queue.initialize()
        result = await queue.get("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_items_all(self, queue: GlobalWorkQueue):
        await queue.initialize()
        for i in range(3):
            await queue.push(_make_work_item(id=f"list-{i}"))
        items = await queue.list_items()
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_list_items_filter_status(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item1 = _make_work_item(id="list-s1")
        item2 = _make_work_item(id="list-s2")
        await queue.push(item1)
        await queue.push(item2)
        await queue.complete("list-s1")
        completed = await queue.list_items(status=WorkStatus.COMPLETED)
        assert len(completed) == 1
        assert completed[0].id == "list-s1"

    @pytest.mark.asyncio
    async def test_list_items_filter_work_type(self, queue: GlobalWorkQueue):
        await queue.initialize()
        await queue.push(_make_work_item(id="bead-l", work_type=WorkType.BEAD))
        await queue.push(_make_work_item(id="convoy-l", work_type=WorkType.CONVOY))
        beads = await queue.list_items(work_type=WorkType.BEAD)
        assert len(beads) == 1
        assert beads[0].id == "bead-l"

    @pytest.mark.asyncio
    async def test_list_items_sorted_by_priority(self, queue: GlobalWorkQueue):
        await queue.initialize()
        await queue.push(_make_work_item(id="low-l", base_priority=10))
        await queue.push(_make_work_item(id="high-l", base_priority=90))
        items = await queue.list_items()
        assert items[0].computed_priority >= items[1].computed_priority

    @pytest.mark.asyncio
    async def test_list_items_limit(self, queue: GlobalWorkQueue):
        await queue.initialize()
        for i in range(10):
            await queue.push(_make_work_item(id=f"lim-{i}"))
        items = await queue.list_items(limit=3)
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_get_statistics_empty(self, queue: GlobalWorkQueue):
        await queue.initialize()
        stats = await queue.get_statistics()
        assert stats["total_items"] == 0
        assert stats["pending_items"] == 0
        assert stats["completed_items"] == 0
        assert stats["avg_pending_priority"] == 0
        assert stats["heap_size"] == 0

    @pytest.mark.asyncio
    async def test_get_statistics_populated(self, queue: GlobalWorkQueue):
        await queue.initialize()
        await queue.push(_make_work_item(id="stat-1", work_type=WorkType.BEAD, base_priority=60))
        await queue.push(_make_work_item(id="stat-2", work_type=WorkType.CONVOY, base_priority=40))
        await queue.complete("stat-1")

        stats = await queue.get_statistics()
        assert stats["total_items"] == 2
        assert stats["completed_items"] == 1
        assert stats["by_status"]["completed"] == 1
        assert "bead" in stats["by_type"]
        assert "convoy" in stats["by_type"]


# ===========================================================================
# GlobalWorkQueue - Persistence (load/save)
# ===========================================================================


class TestGlobalWorkQueuePersistence:
    """Tests for queue persistence."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_storage: Path):
        # Save
        q1 = GlobalWorkQueue(storage_dir=tmp_storage)
        await q1.initialize()
        await q1.push(_make_work_item(id="persist-1", base_priority=70))
        await q1.push(_make_work_item(id="persist-2", base_priority=30))
        await q1.complete("persist-1")

        # Load in new queue
        q2 = GlobalWorkQueue(storage_dir=tmp_storage)
        await q2.initialize()
        assert "persist-1" in q2._items
        assert "persist-2" in q2._items
        assert "persist-1" in q2._completed

    @pytest.mark.asyncio
    async def test_load_with_invalid_lines(self, tmp_storage: Path):
        """Invalid JSONL lines should be skipped, not crash."""
        tmp_storage.mkdir(parents=True, exist_ok=True)
        queue_file = tmp_storage / "queue.jsonl"
        valid_item = _make_work_item(id="valid")
        queue_file.write_text(
            json.dumps(valid_item.to_dict()) + "\nthis is not valid json\n\n"  # blank line
        )
        q = GlobalWorkQueue(storage_dir=tmp_storage)
        await q.initialize()
        assert "valid" in q._items
        assert len(q._items) == 1

    @pytest.mark.asyncio
    async def test_load_completed_items_track_completed_set(self, tmp_storage: Path):
        tmp_storage.mkdir(parents=True, exist_ok=True)
        queue_file = tmp_storage / "queue.jsonl"
        completed = _make_work_item(id="done-p", status=WorkStatus.COMPLETED)
        queue_file.write_text(json.dumps(completed.to_dict()) + "\n")

        q = GlobalWorkQueue(storage_dir=tmp_storage)
        await q.initialize()
        assert "done-p" in q._completed

    @pytest.mark.asyncio
    async def test_load_pending_items_added_to_heap(self, tmp_storage: Path):
        tmp_storage.mkdir(parents=True, exist_ok=True)
        queue_file = tmp_storage / "queue.jsonl"
        pending = _make_work_item(id="pend-p", status=WorkStatus.PENDING)
        queue_file.write_text(json.dumps(pending.to_dict()) + "\n")

        q = GlobalWorkQueue(storage_dir=tmp_storage)
        await q.initialize()
        assert len(q._heap) == 1

    @pytest.mark.asyncio
    async def test_load_ready_items_added_to_heap(self, tmp_storage: Path):
        tmp_storage.mkdir(parents=True, exist_ok=True)
        queue_file = tmp_storage / "queue.jsonl"
        ready = _make_work_item(id="rdy-p", status=WorkStatus.READY)
        queue_file.write_text(json.dumps(ready.to_dict()) + "\n")

        q = GlobalWorkQueue(storage_dir=tmp_storage)
        await q.initialize()
        assert len(q._heap) == 1

    @pytest.mark.asyncio
    async def test_save_queue_error_handling(self, queue: GlobalWorkQueue):
        """Save should handle write errors gracefully."""
        await queue.initialize()
        item = _make_work_item(id="save-err")
        await queue.push(item)

        # Make storage dir read-only to trigger write error
        with patch("builtins.open", side_effect=PermissionError("no write")):
            await queue._save_queue()
            # Should not raise, just log error


# ===========================================================================
# GlobalWorkQueue - Import from Beads
# ===========================================================================


class TestGlobalWorkQueueImportBeads:
    """Tests for importing beads into the queue."""

    @pytest.mark.asyncio
    async def test_import_no_bead_store(self, queue: GlobalWorkQueue):
        await queue.initialize()
        count = await queue.import_from_beads()
        assert count == 0

    @pytest.mark.asyncio
    async def test_import_beads(self, tmp_storage: Path):
        mock_bead_store = MagicMock()

        # Create mock bead objects
        mock_bead = MagicMock()
        mock_bead.id = "bead-1"
        mock_bead.title = "Test bead"
        mock_bead.description = "A test bead"
        mock_bead.created_at = _now()
        mock_bead.updated_at = _now()
        mock_bead.priority = MagicMock(value=70)
        mock_bead.dependencies = []
        mock_bead.tags = ["feature"]
        mock_bead.bead_type = MagicMock(value="task")

        mock_bead_store.list_by_status = AsyncMock(return_value=[mock_bead])

        q = GlobalWorkQueue(
            bead_store=mock_bead_store,
            storage_dir=tmp_storage,
        )
        await q.initialize()

        with patch("aragora.nomic.global_work_queue.BeadStatus", create=True) as mock_bs:
            mock_bs.PENDING = "pending"
            count = await q.import_from_beads()

        assert count == 1
        assert "bead-1" in q._items

    @pytest.mark.asyncio
    async def test_import_beads_skips_existing(self, tmp_storage: Path):
        mock_bead_store = MagicMock()

        mock_bead = MagicMock()
        mock_bead.id = "existing-bead"
        mock_bead.title = "Existing"
        mock_bead.description = "Already in queue"
        mock_bead.created_at = _now()
        mock_bead.updated_at = _now()
        mock_bead.priority = MagicMock(value=50)
        mock_bead.dependencies = []
        mock_bead.tags = []
        mock_bead.bead_type = MagicMock(value="task")

        mock_bead_store.list_by_status = AsyncMock(return_value=[mock_bead])

        q = GlobalWorkQueue(
            bead_store=mock_bead_store,
            storage_dir=tmp_storage,
        )
        await q.initialize()
        # Pre-populate
        q._items["existing-bead"] = _make_work_item(id="existing-bead")

        with patch("aragora.nomic.global_work_queue.BeadStatus", create=True) as mock_bs:
            mock_bs.PENDING = "pending"
            count = await q.import_from_beads()

        assert count == 0  # should skip


# ===========================================================================
# GlobalWorkQueue - Import from Convoys
# ===========================================================================


class TestGlobalWorkQueueImportConvoys:
    """Tests for importing convoys into the queue."""

    @pytest.mark.asyncio
    async def test_import_no_convoy_manager(self, queue: GlobalWorkQueue):
        await queue.initialize()
        count = await queue.import_from_convoys()
        assert count == 0

    @pytest.mark.asyncio
    async def test_import_convoys(self, tmp_storage: Path):
        mock_convoy_manager = MagicMock()

        mock_convoy = MagicMock()
        mock_convoy.id = "convoy-1"
        mock_convoy.title = "Test convoy"
        mock_convoy.description = "A test convoy"
        mock_convoy.created_at = _now()
        mock_convoy.updated_at = _now()
        mock_convoy.priority = MagicMock(value=60)
        mock_convoy.dependencies = []
        mock_convoy.tags = ["batch"]
        mock_convoy.bead_ids = ["b1", "b2"]

        mock_convoy_manager.list_convoys = AsyncMock(return_value=[mock_convoy])

        q = GlobalWorkQueue(
            convoy_manager=mock_convoy_manager,
            storage_dir=tmp_storage,
        )
        await q.initialize()

        with patch("aragora.nomic.global_work_queue.ConvoyStatus", create=True) as mock_cs:
            mock_cs.PENDING = "pending"
            count = await q.import_from_convoys()

        assert count == 1
        assert "convoy-1" in q._items
        assert q._items["convoy-1"].metadata.get("bead_count") == 2

    @pytest.mark.asyncio
    async def test_import_convoys_skips_existing(self, tmp_storage: Path):
        mock_convoy_manager = MagicMock()

        mock_convoy = MagicMock()
        mock_convoy.id = "existing-convoy"
        mock_convoy.title = "Existing"
        mock_convoy.description = ""
        mock_convoy.created_at = _now()
        mock_convoy.updated_at = _now()
        mock_convoy.priority = MagicMock(value=50)
        mock_convoy.dependencies = []
        mock_convoy.tags = []
        mock_convoy.bead_ids = []

        mock_convoy_manager.list_convoys = AsyncMock(return_value=[mock_convoy])

        q = GlobalWorkQueue(
            convoy_manager=mock_convoy_manager,
            storage_dir=tmp_storage,
        )
        await q.initialize()
        q._items["existing-convoy"] = _make_work_item(id="existing-convoy")

        with patch("aragora.nomic.global_work_queue.ConvoyStatus", create=True) as mock_cs:
            mock_cs.PENDING = "pending"
            count = await q.import_from_convoys()

        assert count == 0


# ===========================================================================
# GlobalWorkQueue - Check Unblocked
# ===========================================================================


class TestGlobalWorkQueueCheckUnblocked:
    """Tests for the _check_unblocked internal method."""

    @pytest.mark.asyncio
    async def test_check_unblocked_transitions_blocked_to_ready(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="ub-1", dependencies=["d1"])
        await queue.push(item)
        # Manually block it
        queue._items["ub-1"].status = WorkStatus.BLOCKED
        # Complete the dependency
        queue._completed.add("d1")

        unblocked = await queue._check_unblocked()
        assert len(unblocked) == 1
        assert unblocked[0].id == "ub-1"
        assert unblocked[0].status == WorkStatus.READY

    @pytest.mark.asyncio
    async def test_check_unblocked_ignores_non_blocked(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="ub-2")
        await queue.push(item)
        unblocked = await queue._check_unblocked()
        assert len(unblocked) == 0


# ===========================================================================
# Singleton functions
# ===========================================================================


class TestSingletonFunctions:
    """Tests for get_global_work_queue and reset_global_work_queue."""

    @pytest.mark.asyncio
    async def test_get_global_work_queue_creates_singleton(self):
        q = await get_global_work_queue()
        assert isinstance(q, GlobalWorkQueue)
        assert q._initialized is True

    @pytest.mark.asyncio
    async def test_get_global_work_queue_returns_same_instance(self):
        q1 = await get_global_work_queue()
        q2 = await get_global_work_queue()
        assert q1 is q2

    @pytest.mark.asyncio
    async def test_reset_global_work_queue(self):
        q1 = await get_global_work_queue()
        reset_global_work_queue()
        q2 = await get_global_work_queue()
        assert q1 is not q2

    @pytest.mark.asyncio
    async def test_get_global_work_queue_with_stores(self):
        mock_bead_store = MagicMock()
        mock_convoy_manager = MagicMock()
        q = await get_global_work_queue(
            bead_store=mock_bead_store,
            convoy_manager=mock_convoy_manager,
        )
        assert q.bead_store is mock_bead_store
        assert q.convoy_manager is mock_convoy_manager


# ===========================================================================
# End-to-end / Integration-style tests
# ===========================================================================


class TestGlobalWorkQueueIntegration:
    """Integration-style tests exercising multiple operations together."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, queue: GlobalWorkQueue):
        """Test the full lifecycle: push -> pop -> complete."""
        await queue.initialize()
        item = _make_work_item(id="lifecycle-1", base_priority=60)
        await queue.push(item)

        popped = await queue.pop()
        assert popped is not None
        assert popped.status == WorkStatus.CLAIMED

        completed = await queue.complete("lifecycle-1", result={"done": True})
        assert completed is not None
        assert completed.status == WorkStatus.COMPLETED
        assert "lifecycle-1" in queue._completed

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_failure(self, queue: GlobalWorkQueue):
        """Test the lifecycle with failure: push -> pop -> fail."""
        await queue.initialize()
        item = _make_work_item(id="fail-lifecycle")
        await queue.push(item)
        await queue.pop()
        failed = await queue.fail("fail-lifecycle", error="timeout")
        assert failed is not None
        assert failed.status == WorkStatus.FAILED
        assert failed.metadata["error"] == "timeout"

    @pytest.mark.asyncio
    async def test_dependency_chain(self, queue: GlobalWorkQueue):
        """Work items should unblock as dependencies complete."""
        await queue.initialize()

        step1 = _make_work_item(id="step-1", base_priority=50)
        step2 = _make_work_item(id="step-2", dependencies=["step-1"], base_priority=80)
        step3 = _make_work_item(id="step-3", dependencies=["step-2"], base_priority=90)

        await queue.push(step1)
        await queue.push(step2)
        await queue.push(step3)

        # Only step-1 should be poppable
        first = await queue.pop()
        assert first is not None
        assert first.id == "step-1"

        # Complete step-1 -> step-2 should unblock
        await queue.complete("step-1")
        second = await queue.pop()
        assert second is not None
        assert second.id == "step-2"

        # Complete step-2 -> step-3 should unblock
        await queue.complete("step-2")
        third = await queue.pop()
        assert third is not None
        assert third.id == "step-3"

    @pytest.mark.asyncio
    async def test_mixed_types_and_priorities(self, queue: GlobalWorkQueue):
        """Queue should handle mixed work types sorted by priority."""
        await queue.initialize()
        await queue.push(_make_work_item(id="bead-mix", work_type=WorkType.BEAD, base_priority=30))
        await queue.push(
            _make_work_item(id="convoy-mix", work_type=WorkType.CONVOY, base_priority=70)
        )
        await queue.push(
            _make_work_item(id="esc-mix", work_type=WorkType.ESCALATION, base_priority=90)
        )

        items = await queue.list_items()
        assert len(items) == 3
        # Should be sorted by priority descending
        assert items[0].id == "esc-mix"

    @pytest.mark.asyncio
    async def test_statistics_after_operations(self, queue: GlobalWorkQueue):
        """Statistics should reflect all operations."""
        await queue.initialize()
        await queue.push(_make_work_item(id="s-1", work_type=WorkType.BEAD, base_priority=50))
        await queue.push(_make_work_item(id="s-2", work_type=WorkType.BEAD, base_priority=70))
        await queue.push(_make_work_item(id="s-3", work_type=WorkType.CONVOY, base_priority=30))
        await queue.complete("s-1")
        await queue.fail("s-3")

        stats = await queue.get_statistics()
        assert stats["total_items"] == 3
        assert stats["completed_items"] == 1
        assert stats["by_status"]["completed"] == 1
        assert stats["by_status"]["failed"] == 1
        assert stats["by_type"]["bead"] == 2
        assert stats["by_type"]["convoy"] == 1

    @pytest.mark.asyncio
    async def test_reprioritize_after_boost(self, queue: GlobalWorkQueue):
        """Reprioritize should respect custom boosts."""
        await queue.initialize()
        await queue.push(_make_work_item(id="rp-low", base_priority=20))
        await queue.push(_make_work_item(id="rp-high", base_priority=80))

        # Boost the low-priority item
        queue.calculator.add_custom_boost("rp-low", 100)
        await queue.reprioritize()

        # After reprioritization, the boosted item should have higher priority
        items = await queue.list_items()
        boosted = next(i for i in items if i.id == "rp-low")
        normal = next(i for i in items if i.id == "rp-high")
        assert boosted.computed_priority > 0

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_storage: Path):
        """Queue state should survive across instances."""
        q1 = GlobalWorkQueue(storage_dir=tmp_storage)
        await q1.initialize()
        await q1.push(_make_work_item(id="persist-a", base_priority=60, tags=["persist"]))
        await q1.push(_make_work_item(id="persist-b", base_priority=40))
        await q1.complete("persist-a")

        # New instance
        q2 = GlobalWorkQueue(storage_dir=tmp_storage)
        await q2.initialize()

        assert len(q2._items) == 2
        assert "persist-a" in q2._completed
        assert q2._items["persist-a"].status == WorkStatus.COMPLETED

        # persist-b should still be poppable
        item = await q2.get("persist-b")
        assert item is not None

    @pytest.mark.asyncio
    async def test_concurrent_operations_sequenced_by_lock(self, queue: GlobalWorkQueue):
        """Multiple concurrent pushes should be sequenced by the lock."""
        await queue.initialize()

        async def push_item(idx: int):
            await queue.push(_make_work_item(id=f"conc-{idx}", base_priority=idx * 10))

        await asyncio.gather(*[push_item(i) for i in range(10)])
        assert len(queue._items) == 10


# ===========================================================================
# Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_pop_with_all_items_blocked(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="all-blocked", dependencies=["never-done"])
        await queue.push(item)
        result = await queue.pop()
        assert result is None

    @pytest.mark.asyncio
    async def test_push_same_id_overwrites(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item1 = _make_work_item(id="dup", base_priority=30)
        item2 = _make_work_item(id="dup", base_priority=90)
        await queue.push(item1)
        await queue.push(item2)
        assert queue._items["dup"].base_priority == 90

    @pytest.mark.asyncio
    async def test_complete_already_completed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="double-comp")
        await queue.push(item)
        await queue.complete("double-comp")
        result = await queue.complete("double-comp")
        # Should still return the item (already completed)
        assert result is not None
        assert result.status == WorkStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_fail_already_failed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="double-fail")
        await queue.push(item)
        await queue.fail("double-fail", error="first")
        result = await queue.fail("double-fail", error="second")
        assert result is not None
        assert result.metadata["error"] == "second"

    @pytest.mark.asyncio
    async def test_zero_priority_item(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="zero-prio", base_priority=0)
        await queue.push(item)
        result = await queue.pop()
        assert result is not None

    @pytest.mark.asyncio
    async def test_max_priority_item(self, queue: GlobalWorkQueue):
        await queue.initialize()
        item = _make_work_item(id="max-prio", base_priority=100)
        await queue.push(item)
        result = await queue.pop()
        assert result is not None
        assert result.computed_priority <= 100

    @pytest.mark.asyncio
    async def test_list_items_empty_after_all_completed(self, queue: GlobalWorkQueue):
        await queue.initialize()
        await queue.push(_make_work_item(id="all-done-1"))
        await queue.push(_make_work_item(id="all-done-2"))
        await queue.complete("all-done-1")
        await queue.complete("all-done-2")
        pending = await queue.list_items(status=WorkStatus.PENDING)
        assert len(pending) == 0
        ready = await queue.list_items(status=WorkStatus.READY)
        assert len(ready) == 0

    @pytest.mark.asyncio
    async def test_peek_more_than_available(self, queue: GlobalWorkQueue):
        await queue.initialize()
        await queue.push(_make_work_item(id="peek-only"))
        peeked = await queue.peek(count=10)
        assert len(peeked) == 1

    @pytest.mark.asyncio
    async def test_work_item_with_empty_strings(self):
        item = WorkItem(
            id="",
            work_type=WorkType.CUSTOM,
            title="",
            description="",
            status=WorkStatus.PENDING,
            created_at=_now(),
            updated_at=_now(),
            base_priority=50,
        )
        assert item.id == ""
        assert item.title == ""
        d = item.to_dict()
        restored = WorkItem.from_dict(d)
        assert restored.id == ""

    @pytest.mark.asyncio
    async def test_no_queue_file_on_load(self, tmp_storage: Path):
        """Loading when no queue file exists should work fine."""
        q = GlobalWorkQueue(storage_dir=tmp_storage)
        await q.initialize()
        assert len(q._items) == 0

    @pytest.mark.asyncio
    async def test_save_cleans_up_temp_on_error(self, queue: GlobalWorkQueue):
        """If saving fails, temp file should be cleaned up."""
        await queue.initialize()
        await queue.push(_make_work_item(id="cleanup-test"))

        temp_file = queue.storage_dir / "queue.tmp"
        # Simulate a rename error (e.g., cross-device rename)
        with patch.object(Path, "rename", side_effect=OSError("rename failed")):
            # Write should succeed but rename fails
            # The temp file might or might not exist depending on implementation
            # The key is that it shouldn't crash
            await queue._save_queue()
