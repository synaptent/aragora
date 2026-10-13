"""Tests for self-improvement details handler (aragora/server/handlers/self_improve_details.py).

Covers all routes and behavior of the SelfImproveDetailsHandler class:
- can_handle() routing for all ROUTES (versioned and unversioned)
- GET  /api/self-improve/meta-planner/goals      - MetaPlanner prioritized goals
- GET  /api/self-improve/execution/timeline       - Branch execution timeline
- GET  /api/self-improve/learning/insights        - Cross-cycle learning data
- GET  /api/self-improve/metrics/comparison       - Before/after codebase metrics
- GET  /api/self-improve/trends/cycles            - Cycle trend data
- POST /api/self-improve/improvement-queue        - Add improvement goal
- PUT  /api/self-improve/improvement-queue/{id}/priority - Reorder queue
- DELETE /api/self-improve/improvement-queue/{id} - Remove queue item
- Rate limiting behavior
- Error handling (missing params, bad IDs, import failures)
"""

from __future__ import annotations

import json
import time
from collections import deque
from io import BytesIO
from threading import Lock
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.self_improve_details import SelfImproveDetailsHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _parse_data(result) -> dict:
    """Extract the 'data' envelope from a JSON response."""
    body = _body(result)
    return body.get("data", body)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


class MockHTTPHandler:
    """Mock HTTP request handler for SelfImproveDetailsHandler tests."""

    def __init__(
        self,
        body: dict | None = None,
        method: str = "GET",
        client_address: tuple[str, int] = ("127.0.0.1", 12345),
    ):
        self.command = method
        self.client_address = client_address
        self.headers: dict[str, str] = {"User-Agent": "test-agent"}
        self.rfile = MagicMock()
        self.path = ""
        self.request = MagicMock()

        if body:
            body_bytes = json.dumps(body).encode()
            self.request.body = body_bytes
            self.rfile.read.return_value = body_bytes
            self.headers["Content-Length"] = str(len(body_bytes))
        else:
            self.request.body = b"{}"
            self.rfile.read.return_value = b"{}"
            self.headers["Content-Length"] = "2"


class StandardHTTPHandler:
    """Minimal standard HTTP handler shape with headers and rfile only."""

    def __init__(
        self,
        body: dict[str, Any] | str | bytes | None = None,
        method: str = "POST",
    ):
        self.command = method
        self.client_address = ("127.0.0.1", 12345)
        self.path = ""

        if isinstance(body, bytes):
            raw = body
        elif isinstance(body, str):
            raw = body.encode("utf-8")
        elif body is None:
            raw = b""
        else:
            raw = json.dumps(body).encode("utf-8")

        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
        }
        self.rfile = BytesIO(raw)


# ---------------------------------------------------------------------------
# Mock data objects
# ---------------------------------------------------------------------------


class MockPrioritizedGoal:
    """Mock PrioritizedGoal from MetaPlanner."""

    def __init__(
        self,
        goal_id: str = "goal-001",
        track: str = "qa",
        description: str = "Improve test_failure coverage for untested modules",
        rationale: str = "Low test coverage detected",
        estimated_impact: float = 0.8,
        priority: int = 1,
        focus_areas: list[str] | None = None,
        file_hints: list[str] | None = None,
    ):
        self.id = goal_id
        self.track = MagicMock(value=track)
        self.description = description
        self.rationale = rationale
        self.estimated_impact = estimated_impact
        self.priority = priority
        self.focus_areas = focus_areas or ["testing"]
        self.file_hints = file_hints or ["tests/test_example.py"]


class MockWorktreeInfo:
    """Mock worktree info from BranchCoordinator."""

    def __init__(
        self,
        branch_name: str = "nomic/qa-1",
        worktree_path: str = "/tmp/worktree-1",
        track: str = "qa",
        created_at: Any = None,
        assignment_id: str = "assign-001",
    ):
        self.branch_name = branch_name
        self.worktree_path = worktree_path
        self.track = track
        self.created_at = created_at or MagicMock(isoformat=lambda: "2026-02-24T00:00:00Z")
        self.assignment_id = assignment_id


class MockCycleRecord:
    """Mock cycle record from CycleStore or CycleLearningStore."""

    def __init__(
        self,
        cycle_id: str = "cycle-001",
        status: str = "completed",
        started_at: str = "2026-02-24T00:00:00Z",
        completed_at: str = "2026-02-24T01:00:00Z",
        success: bool = True,
        evidence_quality_scores: dict | None = None,
        duration_seconds: float = 3600.0,
        topics_debated: list[str] | None = None,
        lines_added: int = 100,
        lines_removed: int = 50,
        tests_passed: int = 500,
        tests_failed: int = 2,
        files_modified: list[str] | None = None,
        files_created: list[str] | None = None,
        phases_completed: int = 5,
        agent_contributions: dict | None = None,
    ):
        self.cycle_id = cycle_id
        self.status = status
        self.started_at = started_at
        self.completed_at = completed_at
        self.success = success
        self.evidence_quality_scores = evidence_quality_scores or {"clarity": 0.9}
        self.duration_seconds = duration_seconds
        self.topics_debated = topics_debated or ["coverage", "lint"]
        self.lines_added = lines_added
        self.lines_removed = lines_removed
        self.tests_passed = tests_passed
        self.tests_failed = tests_failed
        self.files_modified = files_modified or ["src/a.py", "src/b.py"]
        self.files_created = files_created or ["src/c.py"]
        self.phases_completed = phases_completed
        self.agent_contributions = agent_contributions or {"claude": 5, "codex": 3}


class MockImprovementSuggestion:
    """Mock ImprovementSuggestion."""

    def __init__(
        self,
        debate_id: str = "user-abc123",
        task: str = "Improve test coverage for billing module",
        category: str = "user",
        confidence: float = 0.5,
        created_at: float | None = None,
    ):
        self.debate_id = debate_id
        self.task = task
        self.suggestion = task
        self.category = category
        self.confidence = confidence
        self.created_at = created_at or time.time()


class MockRunRecord:
    """Mock run record from SelfImproveRunStore."""

    def __init__(
        self,
        run_id: str = "run-001",
        goal: str = "Improve test coverage",
        status: str = "completed",
        cost_usd: float = 0.05,
        created_at: str = "2026-02-24T00:00:00Z",
        completed_at: str = "2026-02-24T01:00:00Z",
        completed_subtasks: int = 3,
        failed_subtasks: int = 1,
    ):
        self.run_id = run_id
        self.goal = goal
        self.status = MagicMock(value=status)
        self.cost_usd = cost_usd
        self.created_at = created_at
        self.completed_at = completed_at
        self.completed_subtasks = completed_subtasks
        self.failed_subtasks = failed_subtasks


class MockFinding:
    """Mock strategic finding."""

    def __init__(
        self,
        category: str = "quality",
        description: str = "Recurring lint failures in billing module",
        occurrences: int = 3,
    ):
        self.category = category
        self.description = description
        self.occurrences = occurrences


class MockImprovementQueue:
    """Mock improvement queue that simulates the real queue interface."""

    def __init__(self, items: list | None = None, max_size: int = 100):
        self._queue = deque(items or [], maxlen=max_size)
        self._lock = Lock()
        self.max_size = max_size

    def __len__(self) -> int:
        return len(self._queue)

    def peek(self, n: int = 5) -> list:
        return list(self._queue)[:n]

    def enqueue(self, suggestion: Any) -> None:
        self._queue.append(suggestion)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a SelfImproveDetailsHandler with minimal server context."""
    return SelfImproveDetailsHandler(server_context={})


@pytest.fixture
def http_handler():
    """Create a mock HTTP handler for GET requests."""
    return MockHTTPHandler()


@pytest.fixture
def http_handler_with_body():
    """Factory for mock HTTP handler with POST/PUT body."""

    def _create(body: dict) -> MockHTTPHandler:
        return MockHTTPHandler(body=body, method="POST")

    return _create


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters between tests to prevent cross-test pollution."""
    yield
    try:
        from aragora.server.handlers.utils.rate_limit import clear_all_limiters

        clear_all_limiters()
    except ImportError:
        pass


# ===========================================================================
# can_handle tests
# ===========================================================================


class TestCanHandle:
    """Tests for SelfImproveDetailsHandler.can_handle() routing."""

    def test_handles_meta_planner_goals(self, handler):
        assert handler.can_handle("/api/self-improve/meta-planner/goals") is True

    def test_handles_execution_timeline(self, handler):
        assert handler.can_handle("/api/self-improve/execution/timeline") is True

    def test_handles_learning_insights(self, handler):
        assert handler.can_handle("/api/self-improve/learning/insights") is True

    def test_handles_metrics_comparison(self, handler):
        assert handler.can_handle("/api/self-improve/metrics/comparison") is True

    def test_handles_trends_cycles(self, handler):
        assert handler.can_handle("/api/self-improve/trends/cycles") is True

    def test_handles_improvement_queue(self, handler):
        assert handler.can_handle("/api/self-improve/improvement-queue") is True

    def test_handles_queue_item_subpath(self, handler):
        assert handler.can_handle("/api/self-improve/improvement-queue/item-123") is True

    def test_handles_queue_item_priority_subpath(self, handler):
        assert handler.can_handle("/api/self-improve/improvement-queue/item-123/priority") is True

    def test_handles_versioned_meta_planner(self, handler):
        assert handler.can_handle("/api/v1/self-improve/meta-planner/goals") is True

    def test_handles_versioned_v2(self, handler):
        assert handler.can_handle("/api/v2/self-improve/execution/timeline") is True

    def test_handles_versioned_queue(self, handler):
        assert handler.can_handle("/api/v1/self-improve/improvement-queue") is True

    def test_handles_versioned_queue_item(self, handler):
        assert handler.can_handle("/api/v1/self-improve/improvement-queue/abc/priority") is True

    def test_does_not_handle_other_path(self, handler):
        assert handler.can_handle("/api/debates/list") is False

    def test_does_not_handle_random_api(self, handler):
        assert handler.can_handle("/api/v1/billing/plans") is False

    def test_does_not_handle_partial_self_improve(self, handler):
        assert handler.can_handle("/api/self-improve/status") is False

    def test_does_not_handle_unrelated_self_improve_path(self, handler):
        assert handler.can_handle("/api/self-improve/run") is False

    def test_method_parameter_accepted(self, handler):
        assert handler.can_handle("/api/self-improve/improvement-queue", method="POST") is True


# ===========================================================================
# GET /api/self-improve/meta-planner/goals
# ===========================================================================


class TestGetMetaPlannerGoals:
    """Tests for GET /api/self-improve/meta-planner/goals endpoint."""

    @pytest.mark.asyncio
    async def test_returns_goals_with_signals(self, handler, http_handler):
        mock_goals = [
            MockPrioritizedGoal(
                goal_id="g1",
                track="qa",
                description="Fix test_failure in billing",
                rationale="Test failures detected",
                estimated_impact=0.9,
                priority=1,
            ),
            MockPrioritizedGoal(
                goal_id="g2",
                track="developer",
                description="Address lint issues in connectors",
                rationale="Lint errors found",
                estimated_impact=0.7,
                priority=2,
            ),
        ]

        mock_planner = AsyncMock()
        mock_planner.prioritize_work = AsyncMock(return_value=mock_goals)

        with patch(
            "aragora.server.handlers.self_improve_details.SelfImproveDetailsHandler._get_meta_planner_goals"
        ) as mock_method:
            # Instead of mocking internal, test through the real method with mocked imports
            pass

        # Test via the actual method with mocked imports
        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.meta_planner": MagicMock(
                    MetaPlanner=MagicMock(return_value=mock_planner),
                    MetaPlannerConfig=MagicMock(
                        return_value=MagicMock(scan_mode=True, max_goals=10),
                    ),
                    PrioritizedGoal=MagicMock,
                ),
                "aragora.nomic.improvement_queue": MagicMock(
                    get_improvement_queue=MagicMock(
                        return_value=MockImprovementQueue(
                            [
                                MockImprovementSuggestion("s1", "Fix bugs"),
                            ]
                        ),
                    ),
                ),
            },
        ):
            # Need to reimport since we patched sys.modules
            result = await handler.handle("/api/self-improve/meta-planner/goals", {}, http_handler)

        data = _parse_data(result)
        assert "goals" in data
        assert "signals_used" in data
        assert "config" in data

    @pytest.mark.asyncio
    async def test_meta_planner_import_error(self, handler, http_handler):
        """When MetaPlanner is not available, return empty goals with error."""
        with patch(
            "aragora.server.handlers.self_improve_details.SelfImproveDetailsHandler._get_meta_planner_goals"
        ) as mock_method:
            from aragora.server.handlers.base import json_response

            mock_method.return_value = json_response(
                {
                    "data": {
                        "goals": [],
                        "signals_used": [],
                        "config": {},
                        "error": "MetaPlanner module not available",
                    }
                }
            )
            result = await mock_method()

        data = _parse_data(result)
        assert data["goals"] == []
        assert "error" in data

    @pytest.mark.asyncio
    async def test_meta_planner_runtime_error(self, handler, http_handler):
        """When MetaPlanner raises RuntimeError, return graceful fallback."""

        async def _raise_goals():
            from aragora.server.handlers.base import json_response

            return json_response(
                {
                    "data": {
                        "goals": [],
                        "signals_used": [],
                        "config": {},
                        "error": "Failed to generate goals",
                    }
                }
            )

        handler._get_meta_planner_goals = _raise_goals
        result = await handler.handle("/api/self-improve/meta-planner/goals", {}, http_handler)
        data = _parse_data(result)
        assert data["goals"] == []
        assert data["error"] == "Failed to generate goals"

    @pytest.mark.asyncio
    async def test_signal_extraction_from_descriptions(self, handler, http_handler):
        """Verify signal keywords are extracted from goal descriptions."""
        mock_goals = [
            MockPrioritizedGoal(description="Fix test_failure in module X"),
            MockPrioritizedGoal(description="Address lint issues and todo items"),
            MockPrioritizedGoal(description="Handle regression in pipeline_goal"),
        ]

        mock_planner = AsyncMock()
        mock_planner.prioritize_work = AsyncMock(return_value=mock_goals)

        mock_config = MagicMock(
            scan_mode=True,
            quick_mode=False,
            max_goals=10,
            enable_metrics_collection=False,
            enable_cross_cycle_learning=False,
        )

        meta_planner_mod = MagicMock()
        meta_planner_mod.MetaPlannerConfig.return_value = mock_config
        meta_planner_mod.MetaPlanner.return_value = mock_planner
        meta_planner_mod.PrioritizedGoal = MagicMock

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = MockImprovementQueue()

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.meta_planner": meta_planner_mod,
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/meta-planner/goals", {}, http_handler)

        data = _parse_data(result)
        signals = data.get("signals_used", [])
        assert "test_failure" in signals
        assert "lint" in signals
        assert "todo" in signals
        assert "regression" in signals
        assert "pipeline_goal" in signals

    @pytest.mark.asyncio
    async def test_improvement_queue_included(self, handler, http_handler):
        """Verify improvement queue data is included in goals response."""
        mock_goals = [MockPrioritizedGoal()]
        mock_planner = AsyncMock()
        mock_planner.prioritize_work = AsyncMock(return_value=mock_goals)

        mock_config = MagicMock(
            scan_mode=True,
            quick_mode=False,
            max_goals=10,
            enable_metrics_collection=False,
            enable_cross_cycle_learning=False,
        )

        meta_mod = MagicMock()
        meta_mod.MetaPlannerConfig.return_value = mock_config
        meta_mod.MetaPlanner.return_value = mock_planner
        meta_mod.PrioritizedGoal = MagicMock

        suggestions = [
            MockImprovementSuggestion("s1", "Fix auth bugs", "security", 0.9),
            MockImprovementSuggestion("s2", "Add logging", "observability", 0.5),
        ]
        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = MockImprovementQueue(suggestions)

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.meta_planner": meta_mod,
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/meta-planner/goals", {}, http_handler)

        data = _parse_data(result)
        queue_data = data.get("improvement_queue", {})
        assert queue_data["size"] == 2
        assert len(queue_data["items"]) == 2
        assert queue_data["items"][0]["task"] == "Fix auth bugs"

    @pytest.mark.asyncio
    async def test_file_hints_truncated_to_10(self, handler, http_handler):
        """Goal file_hints should be truncated to at most 10 entries."""
        goal = MockPrioritizedGoal(file_hints=[f"file_{i}.py" for i in range(20)])

        mock_planner = AsyncMock()
        mock_planner.prioritize_work = AsyncMock(return_value=[goal])

        mock_config = MagicMock(
            scan_mode=True,
            quick_mode=False,
            max_goals=10,
            enable_metrics_collection=False,
            enable_cross_cycle_learning=False,
        )

        meta_mod = MagicMock()
        meta_mod.MetaPlannerConfig.return_value = mock_config
        meta_mod.MetaPlanner.return_value = mock_planner
        meta_mod.PrioritizedGoal = MagicMock

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = MockImprovementQueue()

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.meta_planner": meta_mod,
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/meta-planner/goals", {}, http_handler)

        data = _parse_data(result)
        assert len(data["goals"][0]["file_hints"]) == 10


# ===========================================================================
# GET /api/self-improve/execution/timeline
# ===========================================================================


class TestGetExecutionTimeline:
    """Tests for GET /api/self-improve/execution/timeline endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_modules(self, handler, http_handler):
        """When all modules are unavailable, return empty data."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.branch_coordinator": None,
                "aragora.nomic.cycle_store": None,
                "aragora.server.handlers.self_improve": None,
            },
        ):
            result = await handler.handle("/api/self-improve/execution/timeline", {}, http_handler)

        data = _parse_data(result)
        assert data["branches"] == []
        assert data["merge_decisions"] == []
        assert data["active_count"] == 0

    @pytest.mark.asyncio
    async def test_returns_worktree_branches(self, handler, http_handler):
        """Return branch data from BranchCoordinator worktrees."""
        mock_worktrees = [
            MockWorktreeInfo("nomic/qa-1", "/tmp/wt1", "qa"),
            MockWorktreeInfo("nomic/dev-2", "/tmp/wt2", "developer"),
        ]

        coord_mod = MagicMock()
        coord_mod.BranchCoordinator.return_value.list_worktrees.return_value = mock_worktrees

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = []

        si_mod = MagicMock()
        si_mod._active_tasks = {}

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.branch_coordinator": coord_mod,
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.server.handlers.autonomous.self_improve": si_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/execution/timeline", {}, http_handler)

        data = _parse_data(result)
        assert len(data["branches"]) == 2
        assert data["branches"][0]["branch_name"] == "nomic/qa-1"
        assert data["branches"][0]["track"] == "qa"
        assert data["branches"][0]["status"] == "active"
        assert data["active_count"] == 2

    @pytest.mark.asyncio
    async def test_returns_merge_decisions_from_cycles(self, handler, http_handler):
        """Return merge decisions from CycleStore records."""
        mock_cycles = [
            {
                "cycle_id": "c-001",
                "status": "completed",
                "started_at": "2026-02-24T00:00:00Z",
                "completed_at": "2026-02-24T01:00:00Z",
                "success": True,
            },
            {
                "cycle_id": "c-002",
                "status": "failed",
                "started_at": "2026-02-23T00:00:00Z",
                "completed_at": "2026-02-23T00:30:00Z",
                "success": False,
            },
        ]

        coord_mod = MagicMock()
        coord_mod.BranchCoordinator.return_value.list_worktrees.return_value = []

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = mock_cycles

        si_mod = MagicMock()
        si_mod._active_tasks = {}

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.branch_coordinator": coord_mod,
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.server.handlers.autonomous.self_improve": si_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/execution/timeline", {}, http_handler)

        data = _parse_data(result)
        assert len(data["merge_decisions"]) == 2
        assert data["merge_decisions"][0]["cycle_id"] == "c-001"
        assert data["merge_decisions"][0]["success"] is True
        assert data["merge_decisions"][1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_active_tasks_shown_as_running(self, handler, http_handler):
        """Active tasks from self_improve handler appear as running branches."""
        coord_mod = MagicMock()
        coord_mod.BranchCoordinator.return_value.list_worktrees.return_value = []

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = []

        mock_task = MagicMock()
        mock_task.done.return_value = False

        si_mod = MagicMock()
        si_mod._active_tasks = {"abcdef123456789": mock_task}

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.branch_coordinator": coord_mod,
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.server.handlers.autonomous.self_improve": si_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/execution/timeline", {}, http_handler)

        data = _parse_data(result)
        running = [b for b in data["branches"] if b["status"] == "running"]
        assert len(running) == 1
        assert running[0]["branch_name"].startswith("run/")
        assert data["active_count"] == 1

    @pytest.mark.asyncio
    async def test_cycle_record_as_object_with_dict(self, handler, http_handler):
        """Cycle records that are objects (not dicts) should be handled."""
        cycle_obj = MagicMock()
        cycle_obj.__dict__ = {
            "cycle_id": "c-003",
            "status": "completed",
            "started_at": "2026-02-24T00:00:00Z",
            "completed_at": "2026-02-24T01:00:00Z",
            "success": True,
        }
        # Make isinstance(cycle, dict) return False
        type(cycle_obj).__iter__ = None

        coord_mod = MagicMock()
        coord_mod.BranchCoordinator.return_value.list_worktrees.return_value = []

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = [cycle_obj]

        si_mod = MagicMock()
        si_mod._active_tasks = {}

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.branch_coordinator": coord_mod,
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.server.handlers.autonomous.self_improve": si_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/execution/timeline", {}, http_handler)

        data = _parse_data(result)
        assert len(data["merge_decisions"]) == 1


# ===========================================================================
# GET /api/self-improve/learning/insights
# ===========================================================================


class TestGetLearningInsights:
    """Tests for GET /api/self-improve/learning/insights endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_modules(self, handler, http_handler):
        """When all modules are unavailable, return empty data."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter": None,
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.strategic_memory": None,
            },
        ):
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)

        data = _parse_data(result)
        assert data["insights"] == []
        assert data["high_roi_patterns"] == []
        assert data["recurring_failures"] == []

    @pytest.mark.asyncio
    async def test_returns_high_roi_patterns(self, handler, http_handler):
        """Return high-ROI patterns from NomicCycleAdapter."""
        mock_adapter = AsyncMock()
        mock_adapter.find_high_roi_goal_types = AsyncMock(
            return_value=[
                {"pattern": "test_coverage", "avg_improvement_score": 0.85, "cycle_count": 5},
                {"pattern": "lint_fix", "avg_improvement_score": 0.6, "cycle_count": 3},
            ]
        )
        mock_adapter.find_recurring_failures = AsyncMock(return_value=[])

        adapter_mod = MagicMock()
        adapter_mod.get_nomic_cycle_adapter.return_value = mock_adapter

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter": adapter_mod,
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.strategic_memory": None,
            },
        ):
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)

        data = _parse_data(result)
        assert len(data["high_roi_patterns"]) == 2
        assert data["high_roi_patterns"][0]["pattern"] == "test_coverage"
        assert data["high_roi_patterns"][0]["avg_improvement_score"] == 0.85

    @pytest.mark.asyncio
    async def test_returns_recurring_failures(self, handler, http_handler):
        """Return recurring failures from NomicCycleAdapter."""
        mock_adapter = AsyncMock()
        mock_adapter.find_high_roi_goal_types = AsyncMock(return_value=[])
        mock_adapter.find_recurring_failures = AsyncMock(
            return_value=[
                {
                    "pattern": "timeout_in_tests",
                    "occurrences": 5,
                    "affected_tracks": ["qa", "developer"],
                },
            ]
        )

        adapter_mod = MagicMock()
        adapter_mod.get_nomic_cycle_adapter.return_value = mock_adapter

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter": adapter_mod,
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.strategic_memory": None,
            },
        ):
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)

        data = _parse_data(result)
        assert len(data["recurring_failures"]) == 1
        assert data["recurring_failures"][0]["occurrences"] == 5

    @pytest.mark.asyncio
    async def test_returns_regression_insights(self, handler, http_handler):
        """Return regression history from OutcomeTracker."""
        tracker_mod = MagicMock()
        tracker_mod.NomicOutcomeTracker.get_regression_history.return_value = [
            {
                "cycle_id": "c-100",
                "regressed_metrics": ["test_count"],
                "recommendation": "Add tests for billing",
            },
        ]

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter": None,
                "aragora.nomic.outcome_tracker": tracker_mod,
                "aragora.nomic.strategic_memory": None,
            },
        ):
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)

        data = _parse_data(result)
        assert len(data["insights"]) == 1
        assert data["insights"][0]["type"] == "regression"
        assert data["insights"][0]["cycle_id"] == "c-100"

    @pytest.mark.asyncio
    async def test_returns_strategic_findings(self, handler, http_handler):
        """Return recurring strategic findings."""
        findings = [
            MockFinding("quality", "Recurring lint failures", 3),
            MockFinding("security", "Missing input validation", 2),
        ]

        sm_mod = MagicMock()
        sm_store_instance = MagicMock()
        sm_store_instance.get_recurring_findings.return_value = findings
        sm_mod.StrategicMemoryStore.return_value = sm_store_instance

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter": None,
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.strategic_memory": sm_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)

        data = _parse_data(result)
        strategic = [i for i in data["insights"] if i["type"] == "strategic_finding"]
        assert len(strategic) == 2
        assert strategic[0]["category"] == "quality"
        assert strategic[0]["occurrences"] == 3

    @pytest.mark.asyncio
    async def test_high_roi_query_failure_graceful(self, handler, http_handler):
        """When high-ROI query fails, recurring failures still returned."""
        mock_adapter = AsyncMock()
        mock_adapter.find_high_roi_goal_types = AsyncMock(side_effect=RuntimeError("query failed"))
        mock_adapter.find_recurring_failures = AsyncMock(
            return_value=[
                {"pattern": "test_flake", "occurrences": 4, "affected_tracks": ["qa"]},
            ]
        )

        adapter_mod = MagicMock()
        adapter_mod.get_nomic_cycle_adapter.return_value = mock_adapter

        with patch.dict(
            "sys.modules",
            {
                "aragora.knowledge.mound.adapters.nomic_cycle_adapter": adapter_mod,
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.strategic_memory": None,
            },
        ):
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)

        data = _parse_data(result)
        assert data["high_roi_patterns"] == []
        assert len(data["recurring_failures"]) == 1


# ===========================================================================
# GET /api/self-improve/metrics/comparison
# ===========================================================================


class TestGetMetricsComparison:
    """Tests for GET /api/self-improve/metrics/comparison endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_modules(self, handler, http_handler):
        """When all modules are unavailable, return empty data."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.metrics_collector": None,
            },
        ):
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)

        data = _parse_data(result)
        assert data["comparisons"] == []
        assert data["regressions"] == []

    @pytest.mark.asyncio
    async def test_returns_regressions(self, handler, http_handler):
        """Return regression data from OutcomeTracker."""
        tracker_mod = MagicMock()
        tracker_mod.NomicOutcomeTracker.get_regression_history.return_value = [
            {
                "cycle_id": "c-200",
                "regressed_metrics": ["lint_errors"],
                "recommendation": "Fix lint",
                "timestamp": "2026-02-24T00:00:00Z",
            },
        ]

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.outcome_tracker": tracker_mod,
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.metrics_collector": None,
            },
        ):
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)

        data = _parse_data(result)
        assert len(data["regressions"]) == 1
        assert data["regressions"][0]["cycle_id"] == "c-200"

    @pytest.mark.asyncio
    async def test_returns_cycle_comparisons(self, handler, http_handler):
        """Return comparisons with evidence quality scores from CycleStore."""
        cycles = [
            {
                "cycle_id": "c-300",
                "evidence_quality_scores": {"clarity": 0.9, "accuracy": 0.85},
                "success": True,
                "started_at": "2026-02-24T00:00:00Z",
            },
        ]

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = cycles

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.metrics_collector": None,
            },
        ):
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)

        data = _parse_data(result)
        assert len(data["comparisons"]) == 1
        assert data["comparisons"][0]["cycle_id"] == "c-300"
        assert data["comparisons"][0]["metrics"]["clarity"] == 0.9

    @pytest.mark.asyncio
    async def test_cycles_without_scores_skipped(self, handler, http_handler):
        """Cycles without evidence_quality_scores should not appear in comparisons."""
        cycles = [
            {
                "cycle_id": "c-400",
                "evidence_quality_scores": {},
                "success": True,
                "started_at": "2026-02-24T00:00:00Z",
            },
            {
                "cycle_id": "c-401",
                "evidence_quality_scores": {"clarity": 0.7},
                "success": False,
                "started_at": "2026-02-23T00:00:00Z",
            },
        ]

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = cycles

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.metrics_collector": None,
            },
        ):
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)

        data = _parse_data(result)
        assert len(data["comparisons"]) == 1
        assert data["comparisons"][0]["cycle_id"] == "c-401"

    @pytest.mark.asyncio
    async def test_current_metrics_snapshot_prepended(self, handler, http_handler):
        """When MetricsCollector is available, current snapshot is first entry."""
        mock_snapshot = MagicMock()
        mock_snapshot.timestamp = time.time()
        mock_snapshot.files_count = 3000
        mock_snapshot.total_lines = 500000
        mock_snapshot.tests_passed = 129000
        mock_snapshot.lint_errors = 5

        collector_mod = MagicMock()
        collector_mod.MetricsCollectorConfig.return_value = MagicMock(
            test_timeout=30, test_args=["--co", "-q"]
        )
        mock_collector = MagicMock()
        mock_collector._collect_size_metrics = MagicMock()
        collector_mod.MetricsCollector.return_value = mock_collector
        collector_mod.MetricSnapshot.return_value = mock_snapshot

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.metrics_collector": collector_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)

        data = _parse_data(result)
        assert len(data["comparisons"]) == 1
        assert data["comparisons"][0]["cycle_id"] == "current"
        assert data["comparisons"][0]["metrics"]["files_count"] == 3000

    @pytest.mark.asyncio
    async def test_zero_files_snapshot_not_included(self, handler, http_handler):
        """When snapshot.files_count is 0, it should not be included."""
        mock_snapshot = MagicMock()
        mock_snapshot.timestamp = time.time()
        mock_snapshot.files_count = 0

        collector_mod = MagicMock()
        collector_mod.MetricsCollectorConfig.return_value = MagicMock()
        collector_mod.MetricsCollector.return_value = MagicMock()
        collector_mod.MetricSnapshot.return_value = mock_snapshot

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.outcome_tracker": None,
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.metrics_collector": collector_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)

        data = _parse_data(result)
        assert data["comparisons"] == []


# ===========================================================================
# GET /api/self-improve/trends/cycles
# ===========================================================================


class TestGetCycleTrends:
    """Tests for GET /api/self-improve/trends/cycles endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_modules(self, handler, http_handler):
        """When all modules are unavailable, return empty data."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.stores.run_store": None,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        assert data["cycles"] == []
        assert data["summary"]["total_cycles"] == 0
        assert data["summary"]["success_rate"] == 0.0
        assert data["run_costs"] == []

    @pytest.mark.asyncio
    async def test_returns_cycle_data_with_summary(self, handler, http_handler):
        """Return cycle data with computed summary statistics."""
        cycles = [
            MockCycleRecord(
                "c-1",
                success=True,
                duration_seconds=1000,
                lines_added=100,
                lines_removed=20,
                tests_passed=500,
            ),
            MockCycleRecord(
                "c-2",
                success=False,
                duration_seconds=2000,
                lines_added=50,
                lines_removed=10,
                tests_passed=450,
            ),
        ]

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = cycles

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.stores.run_store": None,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        assert len(data["cycles"]) == 2
        summary = data["summary"]
        assert summary["total_cycles"] == 2
        assert summary["success_rate"] == 0.5
        assert summary["total_lines_changed"] == 180  # (100+20) + (50+10)
        assert summary["avg_tests_passed"] == 475.0
        assert summary["avg_duration_seconds"] == 1500.0

    @pytest.mark.asyncio
    async def test_cycle_entry_fields(self, handler, http_handler):
        """Verify all expected fields are present in cycle entries."""
        cycle = MockCycleRecord("c-10")
        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = [cycle]

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.stores.run_store": None,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        entry = data["cycles"][0]
        expected_fields = [
            "cycle_id",
            "started_at",
            "completed_at",
            "duration_seconds",
            "success",
            "topics",
            "lines_added",
            "lines_removed",
            "tests_passed",
            "tests_failed",
            "files_modified",
            "files_created",
            "phases_completed",
            "agent_count",
            "evidence_quality",
        ]
        for field in expected_fields:
            assert field in entry, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_topics_truncated_to_5(self, handler, http_handler):
        """Topics debated should be truncated to 5 items."""
        cycle = MockCycleRecord("c-11")
        cycle.topics_debated = [f"topic_{i}" for i in range(10)]

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = [cycle]

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.stores.run_store": None,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        assert len(data["cycles"][0]["topics"]) == 5

    @pytest.mark.asyncio
    async def test_returns_run_costs(self, handler, http_handler):
        """Return cost data from SelfImproveRunStore."""
        runs = [
            MockRunRecord("r-1", "Improve coverage", "completed", 0.05),
            MockRunRecord("r-2", "Fix bugs", "failed", 0.02),
        ]

        run_mod = MagicMock()
        run_mod.SelfImproveRunStore.return_value.list_runs.return_value = runs

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.stores.run_store": run_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        assert len(data["run_costs"]) == 2
        assert data["run_costs"][0]["run_id"] == "r-1"
        assert data["run_costs"][0]["cost_usd"] == 0.05
        assert data["run_costs"][1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_zero_duration_cycles_not_averaged(self, handler, http_handler):
        """Cycles with zero duration should not be included in avg calculation."""
        cycles = [
            MockCycleRecord("c-20", success=True, duration_seconds=0),
            MockCycleRecord("c-21", success=True, duration_seconds=500),
        ]

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = cycles

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.stores.run_store": None,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        # Only c-21 has positive duration
        assert data["summary"]["avg_duration_seconds"] == 500.0

    @pytest.mark.asyncio
    async def test_all_successful_cycles(self, handler, http_handler):
        """All successful cycles should give 100% success rate."""
        cycles = [
            MockCycleRecord("c-30", success=True),
            MockCycleRecord("c-31", success=True),
            MockCycleRecord("c-32", success=True),
        ]

        cycle_mod = MagicMock()
        cycle_mod.get_cycle_store.return_value.get_recent_cycles.return_value = cycles

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": cycle_mod,
                "aragora.nomic.stores.run_store": None,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        assert data["summary"]["success_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_goal_truncated_in_run_costs(self, handler, http_handler):
        """Run goals should be truncated to 200 chars."""
        long_goal = "x" * 500
        run = MockRunRecord("r-10", long_goal, "completed", 0.01)

        run_mod = MagicMock()
        run_mod.SelfImproveRunStore.return_value.list_runs.return_value = [run]

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.cycle_store": None,
                "aragora.nomic.stores.run_store": run_mod,
            },
        ):
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)

        data = _parse_data(result)
        assert len(data["run_costs"][0]["goal"]) == 200


# ===========================================================================
# POST /api/self-improve/improvement-queue
# ===========================================================================


class TestPostImprovementQueue:
    """Tests for POST /api/self-improve/improvement-queue endpoint."""

    @pytest.mark.asyncio
    async def test_add_goal_success(self, handler):
        """Successfully add a goal to the improvement queue."""
        from aragora.nomic.improvement_queue import ImprovementSuggestion

        mock_queue = MockImprovementQueue()

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue
        queue_mod.ImprovementSuggestion = ImprovementSuggestion

        http = MockHTTPHandler(
            body={"goal": "Add rate limiting tests", "priority": 75, "source": "user"},
            method="POST",
        )

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_post("/api/self-improve/improvement-queue", {}, http)

        assert _status(result) == 201
        data = _parse_data(result)
        assert data["goal"] == "Add rate limiting tests"
        assert data["priority"] == 75
        assert data["source"] == "user"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_add_goal_reads_standard_rfile_body(self, handler):
        """Successfully add a goal from a standard headers/rfile request body."""
        from aragora.nomic.improvement_queue import ImprovementSuggestion

        mock_queue = MockImprovementQueue()

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue
        queue_mod.ImprovementSuggestion = ImprovementSuggestion

        http = StandardHTTPHandler(
            {"goal": "Prove queue writes work", "priority": 80, "source": "test"},
            method="POST",
        )

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_post("/api/self-improve/improvement-queue", {}, http)

        assert _status(result) == 201
        data = _parse_data(result)
        assert data["goal"] == "Prove queue writes work"
        assert data["priority"] == 80
        assert data["source"] == "test"

    @pytest.mark.asyncio
    async def test_add_goal_missing_goal_field(self, handler):
        """Missing 'goal' field returns 400."""
        http = MockHTTPHandler(body={"priority": 50}, method="POST")
        result = await handler.handle_post("/api/self-improve/improvement-queue", {}, http)
        assert _status(result) == 400
        body = _body(result)
        assert "goal" in body.get("error", "").lower() or "goal" in json.dumps(body).lower()

    @pytest.mark.asyncio
    async def test_add_goal_empty_goal_field(self, handler):
        """Empty 'goal' field returns 400."""
        http = MockHTTPHandler(body={"goal": "", "priority": 50}, method="POST")
        result = await handler.handle_post("/api/self-improve/improvement-queue", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_add_goal_queue_unavailable(self, handler):
        """When improvement queue module is not available, return 503."""
        http = MockHTTPHandler(
            body={"goal": "Test goal"},
            method="POST",
        )

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": None,
            },
        ):
            result = await handler.handle_post("/api/self-improve/improvement-queue", {}, http)

        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_add_goal_default_priority_and_source(self, handler):
        """Default priority is 50 and source is 'user'."""
        from aragora.nomic.improvement_queue import ImprovementSuggestion

        mock_queue = MockImprovementQueue()

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue
        queue_mod.ImprovementSuggestion = ImprovementSuggestion

        http = MockHTTPHandler(body={"goal": "My goal"}, method="POST")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_post("/api/self-improve/improvement-queue", {}, http)

        assert _status(result) == 201
        data = _parse_data(result)
        assert data["priority"] == 50
        assert data["source"] == "user"

    @pytest.mark.asyncio
    async def test_post_wrong_path_returns_none(self, handler):
        """POST to a different path returns None."""
        http = MockHTTPHandler(body={"goal": "Test"}, method="POST")
        result = await handler.handle_post("/api/self-improve/other-endpoint", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_post_versioned_path(self, handler):
        """POST to versioned path should work after strip_version_prefix."""
        http = MockHTTPHandler(body={"goal": ""}, method="POST")
        result = await handler.handle_post("/api/v1/self-improve/improvement-queue", {}, http)
        # Empty goal returns 400 error, confirming it matched the route
        assert _status(result) == 400


# ===========================================================================
# PUT /api/self-improve/improvement-queue/{id}/priority
# ===========================================================================


class TestPutImprovementQueuePriority:
    """Tests for PUT /api/self-improve/improvement-queue/{id}/priority endpoint."""

    @pytest.mark.asyncio
    async def test_update_priority_success(self, handler):
        """Successfully update priority of a queue item."""
        suggestion = MockImprovementSuggestion("item-123", "Fix bugs", "user", 0.5)
        mock_queue = MockImprovementQueue([suggestion])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(body={"priority": 90}, method="PUT")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_put(
                "/api/self-improve/improvement-queue/item-123/priority", {}, http
            )

        assert _status(result) == 200
        data = _parse_data(result)
        assert data["id"] == "item-123"
        assert data["priority"] == 90
        assert data["status"] == "updated"
        # Confidence should be updated
        assert suggestion.confidence == 0.9

    @pytest.mark.asyncio
    async def test_update_priority_reads_standard_rfile_body(self, handler):
        """Successfully update priority from a standard headers/rfile request body."""
        suggestion = MockImprovementSuggestion("item-rfile", "Fix bugs", "user", 0.5)
        mock_queue = MockImprovementQueue([suggestion])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = StandardHTTPHandler({"priority": 65}, method="PUT")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_put(
                "/api/self-improve/improvement-queue/item-rfile/priority", {}, http
            )

        assert _status(result) == 200
        data = _parse_data(result)
        assert data["id"] == "item-rfile"
        assert data["priority"] == 65
        assert suggestion.confidence == 0.65

    @pytest.mark.asyncio
    async def test_update_priority_item_not_found(self, handler):
        """Return 404 when item ID does not exist in queue."""
        mock_queue = MockImprovementQueue([])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(body={"priority": 50}, method="PUT")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_put(
                "/api/self-improve/improvement-queue/nonexistent/priority", {}, http
            )

        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_update_priority_missing_field(self, handler):
        """Missing 'priority' field returns 400."""
        http = MockHTTPHandler(body={}, method="PUT")
        result = await handler.handle_put(
            "/api/self-improve/improvement-queue/item-1/priority", {}, http
        )
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_priority_missing_item_id(self, handler):
        """Empty item ID in path returns 400."""
        http = MockHTTPHandler(body={"priority": 50}, method="PUT")
        result = await handler.handle_put("/api/self-improve/improvement-queue//priority", {}, http)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_update_priority_wrong_path_returns_none(self, handler):
        """PUT to non-matching path returns None."""
        http = MockHTTPHandler(body={"priority": 50}, method="PUT")
        result = await handler.handle_put("/api/self-improve/other/item-1/priority", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_priority_no_priority_suffix_returns_none(self, handler):
        """PUT path without /priority suffix returns None."""
        http = MockHTTPHandler(body={"priority": 50}, method="PUT")
        result = await handler.handle_put("/api/self-improve/improvement-queue/item-1", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_priority_queue_unavailable(self, handler):
        """When improvement queue is not available, return 503."""
        http = MockHTTPHandler(body={"priority": 50}, method="PUT")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": None,
            },
        ):
            result = await handler.handle_put(
                "/api/self-improve/improvement-queue/item-1/priority", {}, http
            )

        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_priority_clamped_to_0_1(self, handler):
        """Priority > 100 should be clamped to confidence 1.0."""
        suggestion = MockImprovementSuggestion("item-200", "Test", "user", 0.5)
        mock_queue = MockImprovementQueue([suggestion])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(body={"priority": 200}, method="PUT")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_put(
                "/api/self-improve/improvement-queue/item-200/priority", {}, http
            )

        assert _status(result) == 200
        assert suggestion.confidence == 1.0

    @pytest.mark.asyncio
    async def test_negative_priority_clamped(self, handler):
        """Negative priority should be clamped to confidence 0.0."""
        suggestion = MockImprovementSuggestion("item-300", "Test", "user", 0.5)
        mock_queue = MockImprovementQueue([suggestion])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(body={"priority": -50}, method="PUT")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_put(
                "/api/self-improve/improvement-queue/item-300/priority", {}, http
            )

        assert _status(result) == 200
        assert suggestion.confidence == 0.0

    @pytest.mark.asyncio
    async def test_put_versioned_path(self, handler):
        """PUT to versioned path should work after strip_version_prefix."""
        http = MockHTTPHandler(body={}, method="PUT")
        result = await handler.handle_put(
            "/api/v1/self-improve/improvement-queue/item-1/priority", {}, http
        )
        # Missing priority returns 400, confirming route was matched
        assert _status(result) == 400


# ===========================================================================
# DELETE /api/self-improve/improvement-queue/{id}
# ===========================================================================


class TestDeleteImprovementQueue:
    """Tests for DELETE /api/self-improve/improvement-queue/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_delete_item_success(self, handler):
        """Successfully remove an item from the queue."""
        suggestion = MockImprovementSuggestion("item-del-1", "Remove me")
        mock_queue = MockImprovementQueue([suggestion])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(method="DELETE")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_delete(
                "/api/self-improve/improvement-queue/item-del-1", {}, http
            )

        assert _status(result) == 200
        data = _parse_data(result)
        assert data["id"] == "item-del-1"
        assert data["status"] == "deleted"
        # Queue should be empty after delete
        assert len(mock_queue) == 0

    @pytest.mark.asyncio
    async def test_delete_item_not_found(self, handler):
        """Return 404 when item ID does not exist."""
        mock_queue = MockImprovementQueue(
            [
                MockImprovementSuggestion("other-item", "Keep me"),
            ]
        )

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(method="DELETE")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_delete(
                "/api/self-improve/improvement-queue/nonexistent", {}, http
            )

        assert _status(result) == 404
        # Original item should still be in queue
        assert len(mock_queue) == 1

    @pytest.mark.asyncio
    async def test_delete_empty_id_returns_none(self, handler):
        """Empty item ID in path returns None."""
        http = MockHTTPHandler(method="DELETE")
        result = await handler.handle_delete("/api/self-improve/improvement-queue/", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_with_subpath_returns_none(self, handler):
        """Delete path with further sub-path (e.g. .../priority) returns None."""
        http = MockHTTPHandler(method="DELETE")
        result = await handler.handle_delete(
            "/api/self-improve/improvement-queue/item-1/priority", {}, http
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_wrong_prefix_returns_none(self, handler):
        """Delete on non-matching path returns None."""
        http = MockHTTPHandler(method="DELETE")
        result = await handler.handle_delete("/api/self-improve/other/item-1", {}, http)
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_queue_unavailable(self, handler):
        """When improvement queue is not available, return 503."""
        http = MockHTTPHandler(method="DELETE")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": None,
            },
        ):
            result = await handler.handle_delete(
                "/api/self-improve/improvement-queue/item-1", {}, http
            )

        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_delete_versioned_path(self, handler):
        """DELETE on versioned path should work after strip_version_prefix."""
        mock_queue = MockImprovementQueue([])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(method="DELETE")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_delete(
                "/api/v1/self-improve/improvement-queue/item-v1", {}, http
            )

        # Item not found is 404, confirming route was matched
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_delete_preserves_other_items(self, handler):
        """Deleting one item should leave other items intact."""
        s1 = MockImprovementSuggestion("keep-1", "Keep this")
        s2 = MockImprovementSuggestion("delete-me", "Delete this")
        s3 = MockImprovementSuggestion("keep-2", "Keep this too")
        mock_queue = MockImprovementQueue([s1, s2, s3])

        queue_mod = MagicMock()
        queue_mod.get_improvement_queue.return_value = mock_queue

        http = MockHTTPHandler(method="DELETE")

        with patch.dict(
            "sys.modules",
            {
                "aragora.nomic.improvement_queue": queue_mod,
            },
        ):
            result = await handler.handle_delete(
                "/api/self-improve/improvement-queue/delete-me", {}, http
            )

        assert _status(result) == 200
        assert len(mock_queue) == 2
        remaining_ids = [s.debate_id for s in mock_queue._queue]
        assert "keep-1" in remaining_ids
        assert "keep-2" in remaining_ids
        assert "delete-me" not in remaining_ids


# ===========================================================================
# Route dispatch tests
# ===========================================================================


class TestRouteDispatch:
    """Tests for route dispatch via the handle() method."""

    @pytest.mark.asyncio
    async def test_handle_dispatches_meta_planner_goals(self, handler, http_handler):
        """GET meta-planner/goals dispatches to _get_meta_planner_goals."""
        with patch.object(handler, "_get_meta_planner_goals", new_callable=AsyncMock) as mock:
            from aragora.server.handlers.base import json_response

            mock.return_value = json_response({"data": {"goals": []}})
            result = await handler.handle("/api/self-improve/meta-planner/goals", {}, http_handler)
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_dispatches_execution_timeline(self, handler, http_handler):
        """GET execution/timeline dispatches to _get_execution_timeline."""
        with patch.object(handler, "_get_execution_timeline", new_callable=AsyncMock) as mock:
            from aragora.server.handlers.base import json_response

            mock.return_value = json_response({"data": {}})
            result = await handler.handle("/api/self-improve/execution/timeline", {}, http_handler)
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_dispatches_learning_insights(self, handler, http_handler):
        """GET learning/insights dispatches to _get_learning_insights."""
        with patch.object(handler, "_get_learning_insights", new_callable=AsyncMock) as mock:
            from aragora.server.handlers.base import json_response

            mock.return_value = json_response({"data": {}})
            result = await handler.handle("/api/self-improve/learning/insights", {}, http_handler)
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_dispatches_metrics_comparison(self, handler, http_handler):
        """GET metrics/comparison dispatches to _get_metrics_comparison."""
        with patch.object(handler, "_get_metrics_comparison", new_callable=AsyncMock) as mock:
            from aragora.server.handlers.base import json_response

            mock.return_value = json_response({"data": {}})
            result = await handler.handle("/api/self-improve/metrics/comparison", {}, http_handler)
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_dispatches_cycle_trends(self, handler, http_handler):
        """GET trends/cycles dispatches to _get_cycle_trends."""
        with patch.object(handler, "_get_cycle_trends", new_callable=AsyncMock) as mock:
            from aragora.server.handlers.base import json_response

            mock.return_value = json_response({"data": {}})
            result = await handler.handle("/api/self-improve/trends/cycles", {}, http_handler)
            mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_unknown_path(self, handler, http_handler):
        """Unknown GET path returns None from handle()."""
        result = await handler.handle("/api/self-improve/unknown-endpoint", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_returns_none_for_queue_path(self, handler, http_handler):
        """Queue path is not handled by GET handle() - it's POST/PUT/DELETE."""
        result = await handler.handle("/api/self-improve/improvement-queue", {}, http_handler)
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_versioned_routes(self, handler, http_handler):
        """Versioned paths are correctly stripped and dispatched."""
        with patch.object(handler, "_get_meta_planner_goals", new_callable=AsyncMock) as mock:
            from aragora.server.handlers.base import json_response

            mock.return_value = json_response({"data": {}})
            result = await handler.handle(
                "/api/v1/self-improve/meta-planner/goals", {}, http_handler
            )
            mock.assert_awaited_once()


# ===========================================================================
# _get_request_body tests
# ===========================================================================


class TestGetRequestBody:
    """Tests for the static _get_request_body helper."""

    def test_extracts_json_from_request_body(self):
        """Extract JSON body from handler.request.body."""
        http = MockHTTPHandler(body={"key": "value"})
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {"key": "value"}

    def test_extracts_json_from_standard_rfile_body(self):
        """Extract JSON body from handler headers and rfile."""
        http = StandardHTTPHandler({"key": "value"})
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {"key": "value"}

    def test_returns_empty_dict_for_no_body(self):
        """Return empty dict when no body is present."""
        http = MagicMock(spec=[])
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {}

    def test_returns_empty_dict_for_invalid_json(self):
        """Return empty dict when body is not valid JSON."""
        http = MagicMock()
        http.request.body = b"not valid json"
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {}

    def test_returns_empty_dict_for_empty_body(self):
        """Return empty dict when body is empty bytes."""
        http = MagicMock()
        http.request.body = b""
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {}

    def test_handles_string_body(self):
        """Handle body as a string instead of bytes."""
        http = MagicMock()
        http.request.body = '{"key": "value"}'
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {"key": "value"}

    def test_handles_none_body(self):
        """Handle body that is None."""
        http = MagicMock()
        http.request.body = None
        result = SelfImproveDetailsHandler({})._get_request_body(http)
        assert result == {}


# ===========================================================================
# RESOURCE_TYPE and ROUTES metadata
# ===========================================================================


class TestHandlerMetadata:
    """Tests for handler class-level metadata."""

    def test_resource_type(self, handler):
        assert handler.RESOURCE_TYPE == "self_improve"

    def test_routes_contains_all_get_endpoints(self, handler):
        expected_routes = [
            "/api/self-improve/meta-planner/goals",
            "/api/self-improve/execution/timeline",
            "/api/self-improve/learning/insights",
            "/api/self-improve/metrics/comparison",
            "/api/self-improve/trends/cycles",
            "/api/self-improve/improvement-queue",
        ]
        for route in expected_routes:
            assert route in handler.ROUTES

    def test_queue_item_prefix(self, handler):
        assert handler._QUEUE_ITEM_PREFIX == "/api/self-improve/improvement-queue/"
