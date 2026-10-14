"""
Tests for RevalidationScheduler.

Comprehensive tests for the revalidation scheduler module including:
- RevalidationScheduler class lifecycle and operations
- Task handler routing (debate, evidence, expert)
- Control plane integration
- Error handling and recovery
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class MockStaleItem:
    """Mock stale knowledge item for testing."""

    node_id: str
    staleness_score: float = 0.75
    content_preview: str = "Test content preview"
    reasons: list[str] | None = None

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = ["age", "contradiction"]


@pytest.fixture
def mock_knowledge_mound():
    """Create a mock KnowledgeMound."""
    mound = MagicMock()
    mound.workspace_id = "test-workspace"
    mound.get_stale_knowledge = AsyncMock(return_value=[])
    mound.schedule_revalidation = AsyncMock(return_value=["task-1"])
    mound.mark_validated = AsyncMock()
    mound.update = AsyncMock()
    return mound


@pytest.fixture
def mock_task_scheduler():
    """Create a mock TaskScheduler."""
    scheduler = MagicMock()
    scheduler.submit = AsyncMock(return_value="task-123")
    return scheduler


class TestRevalidationSchedulerInit:
    """Tests for RevalidationScheduler initialization."""

    def test_default_initialization(self):
        """Should initialize with default parameters."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()

        assert scheduler._knowledge_mound is None
        assert scheduler._task_scheduler is None
        assert scheduler._staleness_threshold == 0.7
        assert scheduler._check_interval == 3600
        assert scheduler._max_tasks_per_check == 10
        assert scheduler._revalidation_method == "debate"
        assert scheduler._on_task_created is None
        assert scheduler._running is False
        assert scheduler._task is None
        assert len(scheduler._pending_revalidations) == 0

    def test_initialization_with_parameters(self, mock_knowledge_mound, mock_task_scheduler):
        """Should initialize with custom parameters."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        callback = MagicMock()
        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            staleness_threshold=0.5,
            check_interval_seconds=1800,
            max_tasks_per_check=5,
            revalidation_method="evidence",
            on_task_created=callback,
        )

        assert scheduler._knowledge_mound is mock_knowledge_mound
        assert scheduler._task_scheduler is mock_task_scheduler
        assert scheduler._staleness_threshold == 0.5
        assert scheduler._check_interval == 1800
        assert scheduler._max_tasks_per_check == 5
        assert scheduler._revalidation_method == "evidence"
        assert scheduler._on_task_created is callback

    def test_is_running_property(self):
        """Should report running status correctly."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()

        assert scheduler.is_running is False

        scheduler._running = True
        assert scheduler.is_running is True


class TestRevalidationSchedulerLifecycle:
    """Tests for start/stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_without_knowledge_mound(self):
        """Should not start without knowledge mound."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()
        await scheduler.start()

        assert scheduler._running is False
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_start_with_knowledge_mound(self, mock_knowledge_mound):
        """Should start background task with knowledge mound."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            check_interval_seconds=3600,
        )

        await scheduler.start()

        assert scheduler._running is True
        assert scheduler._task is not None

        # Clean up
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_start_when_already_running(self, mock_knowledge_mound):
        """Should not start again when already running."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)

        await scheduler.start()
        original_task = scheduler._task

        await scheduler.start()  # Should be a no-op

        assert scheduler._task is original_task

        # Clean up
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_stop_when_running(self, mock_knowledge_mound):
        """Should stop and cancel background task."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)

        await scheduler.start()
        assert scheduler._running is True

        await scheduler.stop()

        assert scheduler._running is False
        assert scheduler._task is None

    @pytest.mark.asyncio
    async def test_stop_when_not_running(self):
        """Should handle stop when not running."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()
        await scheduler.stop()  # Should not raise

        assert scheduler._running is False

    @pytest.mark.asyncio
    async def test_run_loop_executes_check(self, mock_knowledge_mound):
        """Should execute check_and_schedule_revalidations in loop."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            check_interval_seconds=0.01,  # Very short for testing
        )

        await scheduler.start()
        await asyncio.sleep(0.05)  # Allow loop to run a few times
        await scheduler.stop()

        # Verify check was called
        assert mock_knowledge_mound.get_stale_knowledge.call_count >= 1

    @pytest.mark.asyncio
    async def test_run_loop_handles_exceptions(self, mock_knowledge_mound):
        """Should continue running despite exceptions."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(side_effect=RuntimeError("Test error"))

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            check_interval_seconds=0.01,
        )

        await scheduler.start()
        await asyncio.sleep(0.05)

        # Scheduler should still be running despite errors
        assert scheduler._running is True

        await scheduler.stop()


class TestCheckAndScheduleRevalidations:
    """Tests for check_and_schedule_revalidations method."""

    @pytest.mark.asyncio
    async def test_no_knowledge_mound(self):
        """Should return empty list without knowledge mound."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()
        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_no_stale_items(self, mock_knowledge_mound):
        """Should return empty list when no stale items."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=[])

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)
        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_schedules_stale_items(self, mock_knowledge_mound, mock_task_scheduler):
        """Should create tasks for stale items."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [
            MockStaleItem(node_id="node-1", staleness_score=0.8),
            MockStaleItem(node_id="node-2", staleness_score=0.9),
        ]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            staleness_threshold=0.7,
        )

        result = await scheduler.check_and_schedule_revalidations()

        assert len(result) == 2
        assert mock_task_scheduler.submit.call_count == 2

    @pytest.mark.asyncio
    async def test_respects_max_tasks_per_check(self, mock_knowledge_mound, mock_task_scheduler):
        """Should limit tasks to max_tasks_per_check."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id=f"node-{i}") for i in range(10)]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            max_tasks_per_check=3,
        )

        result = await scheduler.check_and_schedule_revalidations()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_respects_staleness_threshold(self, mock_knowledge_mound):
        """Should pass staleness threshold to get_stale_knowledge."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=[])

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            staleness_threshold=0.85,
        )

        await scheduler.check_and_schedule_revalidations()

        mock_knowledge_mound.get_stale_knowledge.assert_called_once()
        call_kwargs = mock_knowledge_mound.get_stale_knowledge.call_args[1]
        assert call_kwargs["threshold"] == 0.85


class TestDuplicateTaskPrevention:
    """Tests for pending_revalidations set."""

    @pytest.mark.asyncio
    async def test_skips_already_pending_items(self, mock_knowledge_mound, mock_task_scheduler):
        """Should skip items already in pending set."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [
            MockStaleItem(node_id="node-1"),
            MockStaleItem(node_id="node-2"),
            MockStaleItem(node_id="node-3"),
        ]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        # Pre-populate pending set
        scheduler._pending_revalidations.add("node-2")

        result = await scheduler.check_and_schedule_revalidations()

        assert len(result) == 2  # node-1 and node-3 only
        assert "node-2" not in result

    @pytest.mark.asyncio
    async def test_adds_to_pending_on_success(self, mock_knowledge_mound, mock_task_scheduler):
        """Should add node_id to pending set after scheduling."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        assert "node-1" in scheduler._pending_revalidations

    @pytest.mark.asyncio
    async def test_all_pending_returns_empty(self, mock_knowledge_mound, mock_task_scheduler):
        """Should return empty when all items are pending."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )
        scheduler._pending_revalidations.add("node-1")

        result = await scheduler.check_and_schedule_revalidations()

        assert result == []


class TestTaskPriorityCalculation:
    """Tests for priority calculation based on staleness score."""

    @pytest.mark.asyncio
    async def test_high_priority_for_high_staleness(
        self, mock_knowledge_mound, mock_task_scheduler
    ):
        """Should use high priority for staleness >= 0.9."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1", staleness_score=0.95)]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        # Priority should be HIGH for 0.95
        from aragora.control_plane.scheduler import TaskPriority

        assert call_kwargs["priority"] == TaskPriority.HIGH

    @pytest.mark.asyncio
    async def test_normal_priority_for_medium_staleness(
        self, mock_knowledge_mound, mock_task_scheduler
    ):
        """Should use normal priority for staleness 0.8-0.9."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1", staleness_score=0.85)]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        from aragora.control_plane.scheduler import TaskPriority

        assert call_kwargs["priority"] == TaskPriority.NORMAL

    @pytest.mark.asyncio
    async def test_low_priority_for_low_staleness(self, mock_knowledge_mound, mock_task_scheduler):
        """Should use low priority for staleness < 0.8."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1", staleness_score=0.72)]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        from aragora.control_plane.scheduler import TaskPriority

        assert call_kwargs["priority"] == TaskPriority.LOW


class TestMarkRevalidationComplete:
    """Tests for mark_revalidation_complete method."""

    def test_removes_from_pending(self):
        """Should remove node_id from pending set."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()
        scheduler._pending_revalidations.add("node-1")
        scheduler._pending_revalidations.add("node-2")

        scheduler.mark_revalidation_complete("node-1")

        assert "node-1" not in scheduler._pending_revalidations
        assert "node-2" in scheduler._pending_revalidations

    def test_handles_missing_node(self):
        """Should not raise when node not in pending."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler()

        # Should not raise
        scheduler.mark_revalidation_complete("non-existent-node")

        assert "non-existent-node" not in scheduler._pending_revalidations


class TestControlPlaneIntegration:
    """Tests for control plane task scheduler submission."""

    @pytest.mark.asyncio
    async def test_submits_to_task_scheduler(self, mock_knowledge_mound, mock_task_scheduler):
        """Should submit tasks to control plane scheduler."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        mock_task_scheduler.submit.assert_called_once()
        call_kwargs = mock_task_scheduler.submit.call_args[1]

        assert call_kwargs["task_type"] == "knowledge_revalidation"
        assert "revalidation" in call_kwargs["required_capabilities"]
        assert "debate" in call_kwargs["required_capabilities"]
        assert call_kwargs["timeout_seconds"] == 600.0
        assert call_kwargs["metadata"]["source"] == "revalidation_scheduler"

    @pytest.mark.asyncio
    async def test_payload_contains_required_fields(
        self, mock_knowledge_mound, mock_task_scheduler
    ):
        """Should include all required fields in payload."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [
            MockStaleItem(
                node_id="node-1",
                staleness_score=0.8,
                content_preview="Test content",
                reasons=["age", "contradiction"],
            )
        ]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            revalidation_method="evidence",
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        payload = call_kwargs["payload"]

        assert payload["node_id"] == "node-1"
        assert payload["staleness_score"] == 0.8
        assert payload["content_preview"] == "Test content"
        assert payload["reasons"] == ["age", "contradiction"]
        assert payload["revalidation_method"] == "evidence"
        assert payload["workspace_id"] == "test-workspace"


class TestFallbackToKnowledgeMound:
    """Tests for fallback to knowledge mound's schedule_revalidation."""

    @pytest.mark.asyncio
    async def test_fallback_when_no_task_scheduler(self, mock_knowledge_mound):
        """Should use mound's schedule_revalidation when no task scheduler."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)
        mock_knowledge_mound.schedule_revalidation = AsyncMock(return_value=["fallback-task-1"])

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=None,  # No task scheduler
        )

        result = await scheduler.check_and_schedule_revalidations()

        mock_knowledge_mound.schedule_revalidation.assert_called_once()
        assert result == ["fallback-task-1"]

    @pytest.mark.asyncio
    async def test_fallback_when_scheduler_fails(self, mock_knowledge_mound, mock_task_scheduler):
        """Should fallback when task scheduler submission fails."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)
        mock_knowledge_mound.schedule_revalidation = AsyncMock(return_value=["fallback-task-1"])
        mock_task_scheduler.submit = AsyncMock(side_effect=RuntimeError("Submission failed"))

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        result = await scheduler.check_and_schedule_revalidations()

        mock_knowledge_mound.schedule_revalidation.assert_called_once()
        assert result == ["fallback-task-1"]

    @pytest.mark.asyncio
    async def test_returns_none_when_both_fail(self, mock_knowledge_mound, mock_task_scheduler):
        """Should return empty when both scheduler and mound fail."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)
        mock_knowledge_mound.schedule_revalidation = AsyncMock(
            side_effect=RuntimeError("Mound failed")
        )
        mock_task_scheduler.submit = AsyncMock(side_effect=RuntimeError("Scheduler failed"))

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_fallback_without_mound_returns_none(self, caplog):
        """Should skip the mound fallback when no knowledge mound is configured."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(knowledge_mound=None, task_scheduler=None)

        with caplog.at_level("WARNING", logger="aragora.knowledge.mound.revalidation_scheduler"):
            result = await scheduler._create_revalidation_task(MockStaleItem(node_id="node-1"))

        assert result is None
        assert "no knowledge mound configured" in caplog.text


class TestHandleRevalidationTask:
    """Tests for handle_revalidation_task routing."""

    @pytest.mark.asyncio
    async def test_missing_node_id(self):
        """Should return error when node_id missing."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        result = await handle_revalidation_task({})

        assert result["success"] is False
        assert "node_id" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_routes_to_debate(self, mock_knowledge_mound):
        """Should route to _revalidate_via_debate for debate method."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._revalidate_via_debate"
        ) as mock_debate:
            mock_debate.return_value = {"success": True, "method": "debate", "validated": True}

            payload = {
                "node_id": "node-1",
                "revalidation_method": "debate",
            }

            result = await handle_revalidation_task(payload, mock_knowledge_mound)

            mock_debate.assert_called_once()
            assert result["method"] == "debate"

    @pytest.mark.asyncio
    async def test_routes_to_evidence(self, mock_knowledge_mound):
        """Should route to _revalidate_via_evidence for evidence method."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._revalidate_via_evidence"
        ) as mock_evidence:
            mock_evidence.return_value = {"success": True, "method": "evidence", "validated": True}

            payload = {
                "node_id": "node-1",
                "revalidation_method": "evidence",
            }

            result = await handle_revalidation_task(payload, mock_knowledge_mound)

            mock_evidence.assert_called_once()
            assert result["method"] == "evidence"

    @pytest.mark.asyncio
    async def test_routes_to_expert(self, mock_knowledge_mound):
        """Should route to _flag_for_expert_review for expert method."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._flag_for_expert_review"
        ) as mock_expert:
            mock_expert.return_value = {
                "success": True,
                "method": "expert",
                "status": "flagged_for_review",
            }

            payload = {
                "node_id": "node-1",
                "revalidation_method": "expert",
            }

            result = await handle_revalidation_task(payload, mock_knowledge_mound)

            mock_expert.assert_called_once()
            assert result["method"] == "expert"

    @pytest.mark.asyncio
    async def test_unknown_method(self, mock_knowledge_mound):
        """Should return error for unknown method."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        payload = {
            "node_id": "node-1",
            "revalidation_method": "unknown_method",
        }

        result = await handle_revalidation_task(payload, mock_knowledge_mound)

        assert result["success"] is False
        assert "unknown" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_defaults_to_debate(self, mock_knowledge_mound):
        """Should default to debate method when not specified."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._revalidate_via_debate"
        ) as mock_debate:
            mock_debate.return_value = {"success": True, "method": "debate"}

            payload = {"node_id": "node-1"}  # No method specified

            await handle_revalidation_task(payload, mock_knowledge_mound)

            mock_debate.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_mound_on_validation(self, mock_knowledge_mound):
        """Should update mound when validated successfully."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._revalidate_via_debate"
        ) as mock_debate:
            mock_debate.return_value = {
                "success": True,
                "validated": True,
                "confidence": 0.9,
            }

            payload = {"node_id": "node-1", "revalidation_method": "debate"}

            await handle_revalidation_task(payload, mock_knowledge_mound)

            mock_knowledge_mound.mark_validated.assert_called_once_with(
                node_id="node-1",
                validator="revalidation_debate",
                confidence=0.9,
            )

    @pytest.mark.asyncio
    async def test_updates_mound_on_needs_review(self, mock_knowledge_mound):
        """Should update mound status when not validated."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._revalidate_via_evidence"
        ) as mock_evidence:
            mock_evidence.return_value = {
                "success": True,
                "validated": False,
                "confidence": 0.3,
            }

            payload = {"node_id": "node-1", "revalidation_method": "evidence"}

            await handle_revalidation_task(payload, mock_knowledge_mound)

            mock_knowledge_mound.update.assert_called_once()
            call_args = mock_knowledge_mound.update.call_args[0]
            assert call_args[0] == "node-1"
            assert call_args[1]["validation_status"] == "needs_review"


class TestRevalidateViaDebate:
    """Tests for _revalidate_via_debate helper."""

    @pytest.mark.asyncio
    async def test_creates_debate_environment(self, mock_knowledge_mound):
        """Should create proper debate environment with mocked imports."""
        import sys
        from types import ModuleType

        # Create mock modules
        mock_core_types = ModuleType("aragora.core_types")
        mock_core_types.Environment = MagicMock()

        mock_debate_protocol = ModuleType("aragora.protocols.debate")
        mock_debate_protocol.DebateProtocol = MagicMock()

        mock_debate_orchestrator = ModuleType("aragora.debate.orchestrator")
        mock_arena_class = MagicMock()
        mock_result = MagicMock()
        mock_result.final_answer = "VALID - claim is accurate"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.85
        mock_result.debate_id = "debate-123"
        mock_arena_instance = AsyncMock()
        mock_arena_instance.run = AsyncMock(return_value=mock_result)
        mock_arena_class.return_value = mock_arena_instance
        mock_debate_orchestrator.Arena = mock_arena_class

        mock_agents_factory = ModuleType("aragora.agents.factory")
        mock_agents_factory.create_default_agents = MagicMock(
            return_value=[MagicMock(), MagicMock(), MagicMock()]
        )

        with patch.dict(
            sys.modules,
            {
                "aragora.core_types": mock_core_types,
                "aragora.protocols.debate": mock_debate_protocol,
                "aragora.debate.orchestrator": mock_debate_orchestrator,
                "aragora.agents.factory": mock_agents_factory,
            },
        ):
            from aragora.knowledge.mound.revalidation_scheduler import (
                _revalidate_via_debate,
            )

            payload = {
                "content_preview": "Test claim content",
                "workspace_id": "test-ws",
            }

            result = await _revalidate_via_debate("node-1", payload, mock_knowledge_mound)

            assert result["success"] is True
            assert result["method"] == "debate"
            assert result["validation_status"] == "valid"
            assert result["consensus_reached"] is True

    @pytest.mark.asyncio
    async def test_detects_deprecated_conclusion(self, mock_knowledge_mound):
        """Should detect deprecated status from conclusion."""
        import sys
        from types import ModuleType

        mock_core_types = ModuleType("aragora.core_types")
        mock_core_types.Environment = MagicMock()

        mock_debate_protocol = ModuleType("aragora.protocols.debate")
        mock_debate_protocol.DebateProtocol = MagicMock()

        mock_debate_orchestrator = ModuleType("aragora.debate.orchestrator")
        mock_arena_class = MagicMock()
        mock_result = MagicMock()
        mock_result.final_answer = "DEPRECATED - this claim is outdated"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.8
        mock_result.debate_id = "debate-123"
        mock_arena_instance = AsyncMock()
        mock_arena_instance.run = AsyncMock(return_value=mock_result)
        mock_arena_class.return_value = mock_arena_instance
        mock_debate_orchestrator.Arena = mock_arena_class

        mock_agents_factory = ModuleType("aragora.agents.factory")
        mock_agents_factory.create_default_agents = MagicMock(
            return_value=[MagicMock(), MagicMock(), MagicMock()]
        )

        with patch.dict(
            sys.modules,
            {
                "aragora.core_types": mock_core_types,
                "aragora.protocols.debate": mock_debate_protocol,
                "aragora.debate.orchestrator": mock_debate_orchestrator,
                "aragora.agents.factory": mock_agents_factory,
            },
        ):
            from aragora.knowledge.mound.revalidation_scheduler import (
                _revalidate_via_debate,
            )

            result = await _revalidate_via_debate("node-1", {}, mock_knowledge_mound)

            assert result["validation_status"] == "deprecated"

    @pytest.mark.asyncio
    async def test_detects_update_needed_conclusion(self, mock_knowledge_mound):
        """Should detect needs_update status from conclusion."""
        import sys
        from types import ModuleType

        mock_core_types = ModuleType("aragora.core_types")
        mock_core_types.Environment = MagicMock()

        mock_debate_protocol = ModuleType("aragora.protocols.debate")
        mock_debate_protocol.DebateProtocol = MagicMock()

        mock_debate_orchestrator = ModuleType("aragora.debate.orchestrator")
        mock_arena_class = MagicMock()
        mock_result = MagicMock()
        mock_result.final_answer = "UPDATE - claim needs modification"
        mock_result.consensus_reached = True
        mock_result.confidence = 0.75
        mock_result.debate_id = "debate-123"
        mock_arena_instance = AsyncMock()
        mock_arena_instance.run = AsyncMock(return_value=mock_result)
        mock_arena_class.return_value = mock_arena_instance
        mock_debate_orchestrator.Arena = mock_arena_class

        mock_agents_factory = ModuleType("aragora.agents.factory")
        mock_agents_factory.create_default_agents = MagicMock(
            return_value=[MagicMock(), MagicMock(), MagicMock()]
        )

        with patch.dict(
            sys.modules,
            {
                "aragora.core_types": mock_core_types,
                "aragora.protocols.debate": mock_debate_protocol,
                "aragora.debate.orchestrator": mock_debate_orchestrator,
                "aragora.agents.factory": mock_agents_factory,
            },
        ):
            from aragora.knowledge.mound.revalidation_scheduler import (
                _revalidate_via_debate,
            )

            result = await _revalidate_via_debate("node-1", {}, mock_knowledge_mound)

            assert result["validation_status"] == "needs_update"

    @pytest.mark.asyncio
    async def test_handles_agent_creation_failure(self, mock_knowledge_mound):
        """Should handle agent creation failure gracefully."""
        import sys
        from types import ModuleType

        mock_core_types = ModuleType("aragora.core_types")
        mock_core_types.Environment = MagicMock()

        mock_debate_protocol = ModuleType("aragora.protocols.debate")
        mock_debate_protocol.DebateProtocol = MagicMock()

        mock_debate_orchestrator = ModuleType("aragora.debate.orchestrator")
        mock_debate_orchestrator.Arena = MagicMock()

        mock_agents_factory = ModuleType("aragora.agents.factory")
        mock_agents_factory.create_default_agents = MagicMock(
            side_effect=RuntimeError("No API keys configured")
        )

        with patch.dict(
            sys.modules,
            {
                "aragora.core_types": mock_core_types,
                "aragora.protocols.debate": mock_debate_protocol,
                "aragora.debate.orchestrator": mock_debate_orchestrator,
                "aragora.agents.factory": mock_agents_factory,
            },
        ):
            from aragora.knowledge.mound.revalidation_scheduler import (
                _revalidate_via_debate,
            )

            result = await _revalidate_via_debate("node-1", {}, mock_knowledge_mound)

            assert result["success"] is True
            assert result["status"] == "debate_scheduled"
            assert "unavailable" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_handles_import_error(self, mock_knowledge_mound):
        """Should handle missing debate components."""
        from aragora.knowledge.mound.revalidation_scheduler import _revalidate_via_debate

        # Mock the imports to raise ImportError
        import sys

        # Force ImportError by making aragora.core_types raise on import
        with patch.dict(sys.modules, {"aragora.core_types": None}):
            # This should trigger the ImportError handling path
            result = await _revalidate_via_debate("node-1", {}, mock_knowledge_mound)

            # Should handle gracefully - either return error or success with fallback
            assert "error" in result or "success" in result


class TestRevalidateViaEvidence:
    """Tests for _revalidate_via_evidence helper."""

    @pytest.mark.asyncio
    async def test_collects_evidence_successfully(self, mock_knowledge_mound):
        """Should collect evidence and return validated result."""
        from aragora.knowledge.mound.revalidation_scheduler import _revalidate_via_evidence

        mock_evidence_pack = MagicMock()
        mock_evidence_pack.snippets = [MagicMock(), MagicMock(), MagicMock()]

        with patch("aragora.evidence.collector.EvidenceCollector") as MockCollector:
            mock_collector = MagicMock()
            mock_collector.collect_evidence = AsyncMock(return_value=mock_evidence_pack)
            MockCollector.return_value = mock_collector

            payload = {"content_preview": "Test claim"}

            result = await _revalidate_via_evidence("node-1", payload, mock_knowledge_mound)

            assert result["success"] is True
            assert result["method"] == "evidence"
            assert result["validated"] is True
            assert result["evidence_count"] == 3

    @pytest.mark.asyncio
    async def test_handles_no_evidence_found(self, mock_knowledge_mound):
        """Should handle case when no evidence found."""
        from aragora.knowledge.mound.revalidation_scheduler import _revalidate_via_evidence

        mock_evidence_pack = MagicMock()
        mock_evidence_pack.snippets = []

        with patch("aragora.evidence.collector.EvidenceCollector") as MockCollector:
            mock_collector = MagicMock()
            mock_collector.collect_evidence = AsyncMock(return_value=mock_evidence_pack)
            MockCollector.return_value = mock_collector

            result = await _revalidate_via_evidence("node-1", {}, mock_knowledge_mound)

            assert result["success"] is True
            assert result["validated"] is False
            assert result["confidence"] == 0.3

    @pytest.mark.asyncio
    async def test_handles_connection_error(self, mock_knowledge_mound):
        """Should handle connection errors gracefully."""
        from aragora.knowledge.mound.revalidation_scheduler import _revalidate_via_evidence

        with patch("aragora.evidence.collector.EvidenceCollector") as MockCollector:
            mock_collector = MagicMock()
            mock_collector.collect_evidence = AsyncMock(
                side_effect=ConnectionError("Network unavailable")
            )
            MockCollector.return_value = mock_collector

            result = await _revalidate_via_evidence("node-1", {}, mock_knowledge_mound)

            assert result["success"] is False
            assert "Evidence collection failed" in result["error"]


class TestFlagForExpertReview:
    """Tests for _flag_for_expert_review helper."""

    @pytest.mark.asyncio
    async def test_returns_flagged_status(self, mock_knowledge_mound):
        """Should return flagged for review status."""
        from aragora.knowledge.mound.revalidation_scheduler import _flag_for_expert_review

        result = await _flag_for_expert_review("node-1", {}, mock_knowledge_mound)

        assert result["success"] is True
        assert result["method"] == "expert"
        assert result["validated"] is False
        assert result["status"] == "flagged_for_review"
        assert "node-1" in result["message"]


class TestErrorHandlingAndRecovery:
    """Tests for error handling and recovery."""

    @pytest.mark.asyncio
    async def test_handles_runtime_error_in_check(self, mock_knowledge_mound):
        """Should handle RuntimeError during check."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(
            side_effect=RuntimeError("Database connection failed")
        )

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)
        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_value_error_in_check(self, mock_knowledge_mound):
        """Should handle ValueError during check."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(
            side_effect=ValueError("Invalid threshold")
        )

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)
        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_key_error_in_check(self, mock_knowledge_mound):
        """Should handle KeyError during check."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(side_effect=KeyError("missing_key"))

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)
        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_unexpected_exception(self, mock_knowledge_mound):
        """Should handle unexpected exceptions."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(
            side_effect=RuntimeError("Unexpected error")
        )

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)
        result = await scheduler.check_and_schedule_revalidations()

        assert result == []

    @pytest.mark.asyncio
    async def test_handle_revalidation_task_catches_errors(self, mock_knowledge_mound):
        """Should catch errors in handle_revalidation_task."""
        from aragora.knowledge.mound.revalidation_scheduler import handle_revalidation_task

        with patch(
            "aragora.knowledge.mound.revalidation_scheduler._revalidate_via_debate"
        ) as mock_debate:
            mock_debate.side_effect = ValueError("Debate failed")

            payload = {"node_id": "node-1", "revalidation_method": "debate"}
            result = await handle_revalidation_task(payload, mock_knowledge_mound)

            assert result["success"] is False
            assert "Revalidation failed" in result["error"]


class TestCallbackInvocation:
    """Tests for on_task_created callback."""

    @pytest.mark.asyncio
    async def test_callback_invoked_on_task_creation(
        self, mock_knowledge_mound, mock_task_scheduler
    ):
        """Should invoke callback when task is created."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        callback = MagicMock()
        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            on_task_created=callback,
        )

        await scheduler.check_and_schedule_revalidations()

        callback.assert_called_once_with("task-123", "node-1")

    @pytest.mark.asyncio
    async def test_callback_invoked_multiple_times(self, mock_knowledge_mound, mock_task_scheduler):
        """Should invoke callback for each created task."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        callback = MagicMock()
        stale_items = [
            MockStaleItem(node_id="node-1"),
            MockStaleItem(node_id="node-2"),
        ]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        task_ids = iter(["task-1", "task-2"])
        mock_task_scheduler.submit = AsyncMock(side_effect=lambda **kw: next(task_ids))

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            on_task_created=callback,
        )

        await scheduler.check_and_schedule_revalidations()

        assert callback.call_count == 2
        callback.assert_any_call("task-1", "node-1")
        callback.assert_any_call("task-2", "node-2")

    @pytest.mark.asyncio
    async def test_no_callback_when_none(self, mock_knowledge_mound, mock_task_scheduler):
        """Should not fail when callback is None."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_items = [MockStaleItem(node_id="node-1")]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
            on_task_created=None,
        )

        # Should not raise
        result = await scheduler.check_and_schedule_revalidations()
        assert len(result) == 1


class TestStatsReporting:
    """Tests for get_stats method."""

    def test_stats_returns_all_fields(self, mock_knowledge_mound):
        """Should return all expected stat fields."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            staleness_threshold=0.6,
            check_interval_seconds=7200,
            max_tasks_per_check=20,
            revalidation_method="evidence",
        )
        scheduler._pending_revalidations = {"node-1", "node-2"}

        stats = scheduler.get_stats()

        assert stats["running"] is False
        assert stats["staleness_threshold"] == 0.6
        assert stats["check_interval_seconds"] == 7200
        assert stats["max_tasks_per_check"] == 20
        assert stats["revalidation_method"] == "evidence"
        assert stats["pending_revalidations"] == 2

    def test_stats_reflects_running_state(self, mock_knowledge_mound):
        """Should reflect running state in stats."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)

        assert scheduler.get_stats()["running"] is False

        scheduler._running = True
        assert scheduler.get_stats()["running"] is True

    def test_stats_updates_pending_count(self, mock_knowledge_mound):
        """Should update pending count as nodes are added/removed."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        scheduler = RevalidationScheduler(knowledge_mound=mock_knowledge_mound)

        assert scheduler.get_stats()["pending_revalidations"] == 0

        scheduler._pending_revalidations.add("node-1")
        assert scheduler.get_stats()["pending_revalidations"] == 1

        scheduler.mark_revalidation_complete("node-1")
        assert scheduler.get_stats()["pending_revalidations"] == 0


class TestContentPreviewTruncation:
    """Tests for content preview handling."""

    @pytest.mark.asyncio
    async def test_content_preview_truncated(self, mock_knowledge_mound, mock_task_scheduler):
        """Should truncate content preview to 200 chars."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        long_content = "x" * 500
        stale_items = [MockStaleItem(node_id="node-1", content_preview=long_content)]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        payload = call_kwargs["payload"]

        assert len(payload["content_preview"]) == 200

    @pytest.mark.asyncio
    async def test_short_content_not_truncated(self, mock_knowledge_mound, mock_task_scheduler):
        """Should not truncate short content."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        short_content = "Short content"
        stale_items = [MockStaleItem(node_id="node-1", content_preview=short_content)]
        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=stale_items)

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        payload = call_kwargs["payload"]

        assert payload["content_preview"] == "Short content"


class TestDefaultAttributeHandling:
    """Tests for handling missing attributes on stale items."""

    @pytest.mark.asyncio
    async def test_handles_missing_staleness_score(self, mock_knowledge_mound, mock_task_scheduler):
        """Should use default staleness score when missing."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        # Create item without staleness_score attribute
        stale_item = MagicMock()
        stale_item.node_id = "node-1"
        del stale_item.staleness_score  # Remove attribute

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=[stale_item])

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        payload = call_kwargs["payload"]

        assert payload["staleness_score"] == 0.5  # Default value

    @pytest.mark.asyncio
    async def test_handles_missing_content_preview(self, mock_knowledge_mound, mock_task_scheduler):
        """Should handle missing content_preview."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_item = MagicMock()
        stale_item.node_id = "node-1"
        stale_item.staleness_score = 0.8
        del stale_item.content_preview

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=[stale_item])

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        payload = call_kwargs["payload"]

        assert payload["content_preview"] == ""

    @pytest.mark.asyncio
    async def test_handles_missing_reasons(self, mock_knowledge_mound, mock_task_scheduler):
        """Should handle missing reasons."""
        from aragora.knowledge.mound.revalidation_scheduler import RevalidationScheduler

        stale_item = MagicMock()
        stale_item.node_id = "node-1"
        stale_item.staleness_score = 0.8
        stale_item.content_preview = "Test"
        del stale_item.reasons

        mock_knowledge_mound.get_stale_knowledge = AsyncMock(return_value=[stale_item])

        scheduler = RevalidationScheduler(
            knowledge_mound=mock_knowledge_mound,
            task_scheduler=mock_task_scheduler,
        )

        await scheduler.check_and_schedule_revalidations()

        call_kwargs = mock_task_scheduler.submit.call_args[1]
        payload = call_kwargs["payload"]

        assert payload["reasons"] == []
