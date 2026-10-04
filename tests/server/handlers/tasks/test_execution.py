"""Tests for Task Execution Handler.

Validates:
- Route matching (can_handle)
- POST /api/v2/tasks/execute (validation, creation, events)
- GET /api/v2/tasks/<task_id> (retrieval, not-found)
- GET /api/v2/tasks (listing, filtering, pagination)
- POST /api/v2/tasks/<task_id>/approve (approval flow, conflict)
- TaskRouter (default routes, custom routes, fallback)
- TaskRecord (creation, transitions, serialization)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.tasks.execution import (
    MAX_GOAL_LENGTH,
    VALID_TASK_TYPES,
    TaskExecutionHandler,
    TaskRoute,
    TaskRouter,
    TaskRecord,
    _clear_tasks,
    _tasks,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_task_store():
    """Ensure each test starts with an empty task store."""
    _clear_tasks()
    yield
    _clear_tasks()


@pytest.fixture
def handler():
    """Create a TaskExecutionHandler with minimal context."""
    ctx: dict = {"storage": None, "elo_system": None}
    return TaskExecutionHandler(server_context=ctx)


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler for POST requests."""
    h = MagicMock()
    h.client_address = ("127.0.0.1", 12345)
    h.headers = {"Content-Type": "application/json", "Content-Length": "200"}
    return h


def _make_body(
    goal: str = "Test task",
    task_type: str = "debate",
    **overrides: object,
) -> dict:
    body: dict = {"goal": goal, "type": task_type}
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# TestTaskExecutionHandler - can_handle
# ---------------------------------------------------------------------------


class TestTaskExecutionHandlerRouting:
    """Tests for route matching logic."""

    def test_can_handle_tasks_root(self, handler: TaskExecutionHandler):
        assert handler.can_handle("/api/v2/tasks") is True

    def test_can_handle_tasks_execute(self, handler: TaskExecutionHandler):
        assert handler.can_handle("/api/v2/tasks/execute") is True

    def test_can_handle_tasks_with_id(self, handler: TaskExecutionHandler):
        assert handler.can_handle("/api/v2/tasks/abc-123") is True

    def test_can_handle_tasks_approve(self, handler: TaskExecutionHandler):
        assert handler.can_handle("/api/v2/tasks/abc-123/approve") is True

    def test_cannot_handle_other_paths(self, handler: TaskExecutionHandler):
        assert handler.can_handle("/api/v2/debates") is False
        assert handler.can_handle("/api/v1/tasks") is False
        assert handler.can_handle("/health") is False


# ---------------------------------------------------------------------------
# TestTaskExecutionHandler - POST execute
# ---------------------------------------------------------------------------


class TestTaskExecute:
    """Tests for POST /api/v2/tasks/execute."""

    @patch("aragora.server.handlers.tasks.execution.emit_handler_event")
    def test_execute_success(self, mock_emit, handler: TaskExecutionHandler):
        body = _make_body()
        result = handler._handle_execute(body)
        assert result is not None
        data, status, _ = result
        assert status == 201
        assert "task_id" in data
        assert data["status"] in ("completed", "pending", "running")
        assert data["goal"] == "Test task"
        assert data["type"] == "debate"
        # Event emitted at least once
        assert mock_emit.call_count >= 1

    def test_execute_missing_goal(self, handler: TaskExecutionHandler):
        body = _make_body(goal="")
        result = handler._handle_execute(body)
        data, status, _ = result
        assert status == 400
        assert "goal" in data.get("error", "").lower()

    def test_execute_no_goal_key(self, handler: TaskExecutionHandler):
        result = handler._handle_execute({"type": "debate"})
        data, status, _ = result
        assert status == 400

    def test_execute_goal_too_long(self, handler: TaskExecutionHandler):
        body = _make_body(goal="x" * (MAX_GOAL_LENGTH + 1))
        data, status, _ = handler._handle_execute(body)
        assert status == 400
        assert "maximum length" in data.get("error", "").lower()

    def test_execute_missing_type(self, handler: TaskExecutionHandler):
        result = handler._handle_execute({"goal": "Do something"})
        data, status, _ = result
        assert status == 400
        assert "type" in data.get("error", "").lower()

    def test_execute_invalid_type(self, handler: TaskExecutionHandler):
        body = _make_body(task_type="invalid_type")
        # Need to set type manually since _make_body maps task_type to "type" key
        data, status, _ = handler._handle_execute({"goal": "Test", "type": "invalid_type"})
        assert status == 400
        assert "invalid task type" in data.get("error", "").lower()

    def test_execute_all_valid_types(self, handler: TaskExecutionHandler):
        for task_type in VALID_TASK_TYPES:
            _clear_tasks()
            body = _make_body(task_type=task_type)
            data, status, _ = handler._handle_execute(body)
            assert status == 201, f"Failed for type={task_type}: {data}"

    def test_execute_invalid_agents(self, handler: TaskExecutionHandler):
        body = _make_body(agents="not_a_list")
        data, status, _ = handler._handle_execute(body)
        assert status == 400
        assert "agents" in data.get("error", "").lower()

    def test_execute_agents_with_non_string(self, handler: TaskExecutionHandler):
        body = _make_body(agents=["claude", 42])
        data, status, _ = handler._handle_execute(body)
        assert status == 400

    def test_execute_invalid_max_steps_zero(self, handler: TaskExecutionHandler):
        body = _make_body(max_steps=0)
        data, status, _ = handler._handle_execute(body)
        assert status == 400

    def test_execute_invalid_max_steps_too_large(self, handler: TaskExecutionHandler):
        body = _make_body(max_steps=999)
        data, status, _ = handler._handle_execute(body)
        assert status == 400

    def test_execute_invalid_human_checkpoints(self, handler: TaskExecutionHandler):
        body = _make_body(human_checkpoints="yes")
        data, status, _ = handler._handle_execute(body)
        assert status == 400

    def test_execute_invalid_context(self, handler: TaskExecutionHandler):
        body = _make_body(context="not a dict")
        data, status, _ = handler._handle_execute(body)
        assert status == 400

    def test_execute_context_too_many_keys(self, handler: TaskExecutionHandler):
        big_ctx = {f"key_{i}": i for i in range(60)}
        body = _make_body(context=big_ctx)
        data, status, _ = handler._handle_execute(body)
        assert status == 400
        assert "too many keys" in data.get("error", "").lower()

    @patch("aragora.server.handlers.tasks.execution.emit_handler_event")
    def test_execute_human_checkpoint_sets_waiting(self, mock_emit, handler: TaskExecutionHandler):
        body = _make_body(human_checkpoints=True)
        data, status, _ = handler._handle_execute(body)
        assert status == 201
        assert data["status"] == "waiting_approval"

    @patch("aragora.server.handlers.tasks.execution.emit_handler_event")
    def test_execute_stores_task(self, mock_emit, handler: TaskExecutionHandler):
        body = _make_body()
        data, status, _ = handler._handle_execute(body)
        task_id = data["task_id"]
        assert task_id in _tasks
        assert _tasks[task_id].goal == "Test task"


# ---------------------------------------------------------------------------
# TestTaskExecutionHandler - GET task
# ---------------------------------------------------------------------------


class TestTaskGet:
    """Tests for GET /api/v2/tasks/<task_id>."""

    def test_get_existing_task(self, handler: TaskExecutionHandler):
        task = TaskRecord(id="test-123", goal="Test", type="debate", status="pending")
        _tasks["test-123"] = task
        data, status, _ = handler._handle_get_task("test-123")
        assert status == 200
        assert data["id"] == "test-123"
        assert data["goal"] == "Test"

    def test_get_nonexistent_task(self, handler: TaskExecutionHandler):
        data, status, _ = handler._handle_get_task("does-not-exist")
        assert status == 404
        assert "not found" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# TestTaskExecutionHandler - GET list
# ---------------------------------------------------------------------------


class TestTaskList:
    """Tests for GET /api/v2/tasks."""

    def test_list_empty(self, handler: TaskExecutionHandler):
        data, status, _ = handler._handle_list_tasks({})
        assert status == 200
        assert data["tasks"] == []
        assert data["total"] == 0

    def test_list_returns_tasks(self, handler: TaskExecutionHandler):
        for i in range(3):
            _tasks[f"t-{i}"] = TaskRecord(
                id=f"t-{i}", goal=f"Task {i}", type="debate", status="pending"
            )
        data, status, _ = handler._handle_list_tasks({})
        assert status == 200
        assert data["total"] == 3
        assert len(data["tasks"]) == 3

    def test_list_filter_by_status(self, handler: TaskExecutionHandler):
        _tasks["a"] = TaskRecord(id="a", goal="A", type="debate", status="pending")
        _tasks["b"] = TaskRecord(id="b", goal="B", type="debate", status="running")
        _tasks["c"] = TaskRecord(id="c", goal="C", type="debate", status="pending")

        data, status, _ = handler._handle_list_tasks({"status": "pending"})
        assert status == 200
        assert data["total"] == 2
        assert all(t["status"] == "pending" for t in data["tasks"])

    def test_list_invalid_status_filter(self, handler: TaskExecutionHandler):
        data, status, _ = handler._handle_list_tasks({"status": "bogus"})
        assert status == 400

    def test_list_pagination(self, handler: TaskExecutionHandler):
        for i in range(5):
            _tasks[f"t-{i}"] = TaskRecord(
                id=f"t-{i}",
                goal=f"Task {i}",
                type="debate",
                status="pending",
                created_at=time.time() + i,
            )
        data, status, _ = handler._handle_list_tasks({"limit": "2", "offset": "1"})
        assert status == 200
        assert len(data["tasks"]) == 2
        assert data["total"] == 5
        assert data["limit"] == 2
        assert data["offset"] == 1

    def test_list_limit_clamped(self, handler: TaskExecutionHandler):
        data, status, _ = handler._handle_list_tasks({"limit": "999"})
        assert status == 200
        assert data["limit"] == 100


# ---------------------------------------------------------------------------
# TestTaskExecutionHandler - POST approve
# ---------------------------------------------------------------------------


class TestTaskApprove:
    """Tests for POST /api/v2/tasks/<task_id>/approve."""

    @patch("aragora.server.handlers.tasks.execution.emit_handler_event")
    def test_approve_success(self, mock_emit, handler: TaskExecutionHandler):
        task = TaskRecord(id="appr-1", goal="Approve me", type="debate", status="waiting_approval")
        _tasks["appr-1"] = task
        data, status, _ = handler._handle_approve("appr-1")
        assert status == 200
        assert "approved" in data.get("message", "").lower() or data["status"] in (
            "completed",
            "running",
            "approved",
        )

    def test_approve_not_found(self, handler: TaskExecutionHandler):
        data, status, _ = handler._handle_approve("no-such-task")
        assert status == 404

    def test_approve_wrong_status(self, handler: TaskExecutionHandler):
        task = TaskRecord(id="appr-2", goal="Test", type="debate", status="pending")
        _tasks["appr-2"] = task
        data, status, _ = handler._handle_approve("appr-2")
        assert status == 409
        assert "waiting_approval" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# TestTaskExecutionHandler - handle / handle_post dispatchers
# ---------------------------------------------------------------------------


class TestHandleDispatchers:
    """Test the top-level handle/handle_post methods dispatch correctly."""

    def test_handle_get_list(self, handler: TaskExecutionHandler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {}, mock_http_handler)
        assert result is not None
        data, status, _ = result
        assert status == 200

    def test_handle_get_task_by_id(self, handler: TaskExecutionHandler, mock_http_handler):
        _tasks["xyz"] = TaskRecord(id="xyz", goal="G", type="debate", status="pending")
        result = handler.handle("/api/v2/tasks/xyz", {}, mock_http_handler)
        assert result is not None
        data, status, _ = result
        assert status == 200
        assert data["id"] == "xyz"

    def test_handle_get_unknown_path(self, handler: TaskExecutionHandler, mock_http_handler):
        result = handler.handle("/api/v2/tasks/a/b/c", {}, mock_http_handler)
        assert result is not None
        _, status, _h = result
        assert status == 404

    def test_handle_get_non_matching(self, handler: TaskExecutionHandler, mock_http_handler):
        result = handler.handle("/api/v2/other", {}, mock_http_handler)
        assert result is None

    def test_handle_post_non_matching(self, handler: TaskExecutionHandler, mock_http_handler):
        result = handler.handle_post("/api/v2/other", {}, mock_http_handler)
        assert result is None

    def test_handle_post_unknown_sub_path(self, handler: TaskExecutionHandler, mock_http_handler):
        result = handler.handle_post("/api/v2/tasks/something/weird", {}, mock_http_handler)
        assert result is not None
        _, status, _h = result
        assert status == 404


# ---------------------------------------------------------------------------
# TestTaskRouter
# ---------------------------------------------------------------------------


class TestTaskRouter:
    """Tests for the TaskRouter."""

    def test_default_routes_registered(self):
        router = TaskRouter()
        for task_type in VALID_TASK_TYPES:
            route = router.get_route(task_type)
            assert route is not None, f"Missing default route for {task_type}"
            assert route.task_type == task_type
            assert len(route.workflow_steps) >= 1

    def test_route_returns_registered(self):
        router = TaskRouter()
        route = router.route("debate", "Test goal", {})
        assert route.task_type == "debate"
        assert route.workflow_steps[0]["type"] == "debate"

    def test_route_unknown_type_falls_back(self):
        router = TaskRouter()
        route = router.route("unknown_type", "Some goal", {})
        assert route.task_type == "unknown_type"
        assert route.workflow_steps[0]["type"] == "debate"  # fallback

    def test_route_empty_type_raises(self):
        router = TaskRouter()
        with pytest.raises(ValueError, match="must not be empty"):
            router.route("", "Goal", {})

    def test_register_custom_route(self):
        router = TaskRouter()
        custom = TaskRoute(
            task_type="custom",
            workflow_steps=[{"id": "s1", "type": "custom_step", "name": "Custom"}],
            required_capabilities=["magic"],
        )
        router.register(custom)
        route = router.route("custom", "Goal", {})
        assert route.task_type == "custom"
        assert route.workflow_steps[0]["type"] == "custom_step"

    def test_registered_types(self):
        router = TaskRouter()
        types = router.registered_types
        assert isinstance(types, list)
        assert types == sorted(types)  # alphabetical
        for t in VALID_TASK_TYPES:
            assert t in types

    def test_get_route_none_for_missing(self):
        router = TaskRouter()
        assert router.get_route("nonexistent") is None

    def test_code_edit_route_has_multiple_steps(self):
        router = TaskRouter()
        route = router.get_route("code_edit")
        assert route is not None
        assert len(route.workflow_steps) == 3

    def test_composite_route_has_multiple_steps(self):
        router = TaskRouter()
        route = router.get_route("composite")
        assert route is not None
        assert len(route.workflow_steps) == 3


# ---------------------------------------------------------------------------
# TestTaskRecord
# ---------------------------------------------------------------------------


class TestTaskRecord:
    """Tests for the TaskRecord dataclass."""

    def test_default_creation(self):
        task = TaskRecord()
        assert task.id  # non-empty UUID
        assert task.status == "pending"
        assert task.goal == ""
        assert task.agents == ["auto"]
        assert task.result is None
        assert task.error is None

    def test_custom_creation(self):
        task = TaskRecord(
            id="custom-id",
            goal="Do something",
            type="analysis",
            status="pending",
            agents=["claude", "gpt4"],
            max_steps=5,
        )
        assert task.id == "custom-id"
        assert task.type == "analysis"
        assert task.agents == ["claude", "gpt4"]
        assert task.max_steps == 5

    def test_to_dict(self):
        task = TaskRecord(id="d-1", goal="G", type="debate")
        d = task.to_dict()
        assert isinstance(d, dict)
        assert d["id"] == "d-1"
        assert d["goal"] == "G"
        assert "created_at" in d
        assert "updated_at" in d

    def test_transition_pending_to_running(self):
        task = TaskRecord(status="pending")
        task.transition_to("running")
        assert task.status == "running"

    def test_transition_waiting_to_approved(self):
        task = TaskRecord(status="waiting_approval")
        task.transition_to("approved")
        assert task.status == "approved"

    def test_transition_approved_to_running(self):
        task = TaskRecord(status="approved")
        task.transition_to("running")
        assert task.status == "running"

    def test_transition_running_to_completed(self):
        task = TaskRecord(status="running")
        task.transition_to("completed")
        assert task.status == "completed"

    def test_transition_running_to_failed(self):
        task = TaskRecord(status="running")
        task.transition_to("failed")
        assert task.status == "failed"

    def test_invalid_transition_raises(self):
        task = TaskRecord(status="completed")
        with pytest.raises(ValueError, match="Cannot transition"):
            task.transition_to("running")

    def test_transition_updates_timestamp(self):
        task = TaskRecord(status="pending")
        old_ts = task.updated_at
        # Ensure time moves forward
        import time

        time.sleep(0.01)
        task.transition_to("running")
        assert task.updated_at >= old_ts
