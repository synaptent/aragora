"""Comprehensive tests for the Task Execution Handler.

Tests the TaskExecutionHandler endpoints:
    POST /api/v2/tasks/execute       - Submit a task for execution
    GET  /api/v2/tasks/<task_id>     - Get task status
    GET  /api/v2/tasks               - List tasks (with optional status filter)
    POST /api/v2/tasks/<task_id>/approve - Approve a human checkpoint
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.tasks.execution import (
    DEFAULT_LIST_LIMIT,
    MAX_CONTEXT_SIZE,
    MAX_GOAL_LENGTH,
    MAX_LIST_LIMIT,
    VALID_TASK_TYPES,
    VALID_STATUSES,
    TaskExecutionHandler,
    TaskRouter,
    TaskRecord,
    _clear_tasks,
    _tasks,
)


# ============================================================================
# Helpers
# ============================================================================


def _body(result: object) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if isinstance(result, dict):
        return result
    return json.loads(result.body)


def _status(result: object) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clear_task_store():
    """Ensure each test starts with a clean task store."""
    _clear_tasks()
    yield
    _clear_tasks()


@pytest.fixture
def handler():
    """Create a TaskExecutionHandler with an empty context."""
    return TaskExecutionHandler({})


@pytest.fixture
def mock_http_handler():
    """Create a minimal mock HTTP handler (for BaseHandler auth methods)."""
    m = MagicMock()
    m.headers = {"Content-Type": "application/json", "Content-Length": "2"}
    m.rfile = MagicMock()
    m.rfile.read.return_value = b"{}"
    return m


def _make_http_handler(body: dict[str, Any] | None = None) -> MagicMock:
    """Create a mock HTTP handler with a JSON body."""
    m = MagicMock()
    if body is not None:
        body_bytes = json.dumps(body).encode()
        m.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
        }
        m.rfile.read.return_value = body_bytes
    else:
        m.headers = {"Content-Type": "application/json", "Content-Length": "2"}
        m.rfile.read.return_value = b"{}"
    return m


def _valid_body(**overrides: Any) -> dict[str, Any]:
    """Return a minimal valid task execution body with optional overrides."""
    body: dict[str, Any] = {
        "goal": "Analyze the codebase for security issues",
        "type": "analysis",
    }
    body.update(overrides)
    return body


# ============================================================================
# TaskRecord unit tests
# ============================================================================


class TestTaskRecord:
    """Unit tests for the TaskRecord dataclass."""

    def test_defaults(self):
        task = TaskRecord()
        assert task.goal == ""
        assert task.type == "debate"
        assert task.status == "pending"
        assert task.agents == ["auto"]
        assert task.max_steps == 10
        assert task.human_checkpoints is False
        assert task.context == {}
        assert task.result is None
        assert task.error is None
        assert task.workflow_id is None
        assert task.id  # UUID generated

    def test_to_dict(self):
        task = TaskRecord(goal="test", type="debate")
        d = task.to_dict()
        assert d["goal"] == "test"
        assert d["type"] == "debate"
        assert d["status"] == "pending"
        assert "id" in d
        assert "created_at" in d

    def test_transition_pending_to_running(self):
        task = TaskRecord(status="pending")
        task.transition_to("running")
        assert task.status == "running"

    def test_transition_pending_to_failed(self):
        task = TaskRecord(status="pending")
        task.transition_to("failed")
        assert task.status == "failed"

    def test_transition_pending_to_waiting_approval(self):
        task = TaskRecord(status="pending")
        task.transition_to("waiting_approval")
        assert task.status == "waiting_approval"

    def test_transition_waiting_approval_to_approved(self):
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

    def test_invalid_transition_completed_to_running(self):
        task = TaskRecord(status="completed")
        with pytest.raises(ValueError, match="Cannot transition"):
            task.transition_to("running")

    def test_invalid_transition_failed_to_running(self):
        task = TaskRecord(status="failed")
        with pytest.raises(ValueError, match="none \\(terminal state\\)"):
            task.transition_to("running")

    def test_invalid_transition_pending_to_completed(self):
        task = TaskRecord(status="pending")
        with pytest.raises(ValueError, match="Cannot transition"):
            task.transition_to("completed")

    def test_transition_updates_timestamp(self):
        task = TaskRecord(status="pending")
        old_ts = task.updated_at
        time.sleep(0.01)
        task.transition_to("running")
        assert task.updated_at >= old_ts


# ============================================================================
# can_handle
# ============================================================================


class TestCanHandle:
    """Tests for can_handle path matching."""

    def test_can_handle_tasks_root(self, handler):
        assert handler.can_handle("/api/v2/tasks") is True

    def test_can_handle_tasks_with_id(self, handler):
        assert handler.can_handle("/api/v2/tasks/some-id") is True

    def test_can_handle_tasks_execute(self, handler):
        assert handler.can_handle("/api/v2/tasks/execute") is True

    def test_can_handle_tasks_approve(self, handler):
        assert handler.can_handle("/api/v2/tasks/some-id/approve") is True

    def test_cannot_handle_other_path(self, handler):
        assert handler.can_handle("/api/v2/debates") is False

    def test_cannot_handle_v1_tasks(self, handler):
        assert handler.can_handle("/api/v1/tasks") is False


# ============================================================================
# POST /api/v2/tasks/execute - Success paths
# ============================================================================


class TestExecuteSuccess:
    """Tests for successful task execution submission."""

    def test_submit_debate_task(self, handler, mock_http_handler):
        body = _valid_body(type="debate")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        data = _body(result)
        assert data["status"] in ("completed", "pending", "failed")
        assert data["goal"] == body["goal"]
        assert data["type"] == "debate"
        assert "task_id" in data
        assert "workflow_steps" in data
        assert "created_at" in data

    def test_submit_analysis_task(self, handler, mock_http_handler):
        body = _valid_body(type="analysis")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        assert _body(result)["type"] == "analysis"

    def test_submit_code_edit_task(self, handler, mock_http_handler):
        body = _valid_body(type="code_edit")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        assert _body(result)["type"] == "code_edit"

    def test_submit_computer_use_task(self, handler, mock_http_handler):
        body = _valid_body(type="computer_use")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201

    def test_submit_composite_task(self, handler, mock_http_handler):
        body = _valid_body(type="composite")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        assert _body(result)["type"] == "composite"

    def test_task_stored_in_memory(self, handler, mock_http_handler):
        body = _valid_body()
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        task_id = _body(result)["task_id"]
        assert task_id in _tasks
        assert _tasks[task_id].goal == body["goal"]

    def test_custom_agents(self, handler, mock_http_handler):
        body = _valid_body(agents=["claude", "gpt4"])
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        task_id = _body(result)["task_id"]
        assert _tasks[task_id].agents == ["claude", "gpt4"]

    def test_default_agents_is_auto(self, handler, mock_http_handler):
        body = _valid_body()
        h = _make_http_handler(body)
        handler.handle_post("/api/v2/tasks/execute", {}, h)
        task = list(_tasks.values())[0]
        assert task.agents == ["auto"]

    def test_empty_agents_defaults_to_auto(self, handler, mock_http_handler):
        body = _valid_body(agents=[])
        h = _make_http_handler(body)
        handler.handle_post("/api/v2/tasks/execute", {}, h)
        task = list(_tasks.values())[0]
        assert task.agents == ["auto"]

    def test_custom_max_steps(self, handler, mock_http_handler):
        body = _valid_body(max_steps=50)
        h = _make_http_handler(body)
        handler.handle_post("/api/v2/tasks/execute", {}, h)
        task = list(_tasks.values())[0]
        assert task.max_steps == 50

    def test_with_context(self, handler, mock_http_handler):
        body = _valid_body(context={"workspace_id": "ws-123", "priority": "high"})
        h = _make_http_handler(body)
        handler.handle_post("/api/v2/tasks/execute", {}, h)
        task = list(_tasks.values())[0]
        assert task.context["workspace_id"] == "ws-123"

    def test_human_checkpoints_sets_waiting_approval(self, handler, mock_http_handler):
        body = _valid_body(human_checkpoints=True)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        data = _body(result)
        assert data["status"] == "waiting_approval"
        task_id = data["task_id"]
        assert _tasks[task_id].status == "waiting_approval"

    def test_no_checkpoints_starts_execution(self, handler, mock_http_handler):
        body = _valid_body(human_checkpoints=False)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        task_id = _body(result)["task_id"]
        # Execution completes synchronously
        assert _tasks[task_id].status == "completed"

    def test_goal_is_stripped(self, handler, mock_http_handler):
        body = _valid_body(goal="  spaces around  ")
        h = _make_http_handler(body)
        handler.handle_post("/api/v2/tasks/execute", {}, h)
        task = list(_tasks.values())[0]
        assert task.goal == "spaces around"

    def test_trailing_slash_on_path(self, handler, mock_http_handler):
        body = _valid_body()
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute/", {}, h)
        assert _status(result) == 201


# ============================================================================
# POST /api/v2/tasks/execute - Validation errors
# ============================================================================


class TestExecuteValidation:
    """Tests for input validation on task submission."""

    def test_missing_goal(self, handler, mock_http_handler):
        body = {"type": "debate"}
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "goal" in _body(result).get("error", "").lower()

    def test_empty_goal(self, handler, mock_http_handler):
        body = _valid_body(goal="")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400

    def test_whitespace_only_goal(self, handler, mock_http_handler):
        body = _valid_body(goal="   ")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "blank" in _body(result).get("error", "").lower()

    def test_goal_not_string(self, handler, mock_http_handler):
        body = _valid_body(goal=123)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400

    def test_goal_exceeds_max_length(self, handler, mock_http_handler):
        body = _valid_body(goal="x" * (MAX_GOAL_LENGTH + 1))
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "maximum length" in _body(result).get("error", "").lower()

    def test_goal_at_max_length_accepted(self, handler, mock_http_handler):
        body = _valid_body(goal="x" * MAX_GOAL_LENGTH)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201

    def test_missing_type(self, handler, mock_http_handler):
        body = {"goal": "Do something"}
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "type" in _body(result).get("error", "").lower()

    def test_empty_type(self, handler, mock_http_handler):
        body = _valid_body(type="")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400

    def test_invalid_type(self, handler, mock_http_handler):
        body = _valid_body(type="invalid_task_type")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "invalid task type" in _body(result).get("error", "").lower()

    def test_type_not_string(self, handler, mock_http_handler):
        body = _valid_body(type=42)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400

    def test_agents_not_list(self, handler, mock_http_handler):
        body = _valid_body(agents="claude")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "agents" in _body(result).get("error", "").lower()

    def test_agents_contains_non_string(self, handler, mock_http_handler):
        body = _valid_body(agents=["claude", 42])
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "string" in _body(result).get("error", "").lower()

    def test_max_steps_not_integer(self, handler, mock_http_handler):
        body = _valid_body(max_steps="ten")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "max_steps" in _body(result).get("error", "").lower()

    def test_max_steps_zero(self, handler, mock_http_handler):
        body = _valid_body(max_steps=0)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400

    def test_max_steps_negative(self, handler, mock_http_handler):
        body = _valid_body(max_steps=-5)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400

    def test_max_steps_exceeds_100(self, handler, mock_http_handler):
        body = _valid_body(max_steps=101)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "100" in _body(result).get("error", "")

    def test_max_steps_at_100_accepted(self, handler, mock_http_handler):
        body = _valid_body(max_steps=100)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201

    def test_max_steps_at_1_accepted(self, handler, mock_http_handler):
        body = _valid_body(max_steps=1)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201

    def test_human_checkpoints_not_boolean(self, handler, mock_http_handler):
        body = _valid_body(human_checkpoints="yes")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "boolean" in _body(result).get("error", "").lower()

    def test_context_not_dict(self, handler, mock_http_handler):
        body = _valid_body(context="not a dict")
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "context" in _body(result).get("error", "").lower()

    def test_context_too_many_keys(self, handler, mock_http_handler):
        big_context = {f"key_{i}": i for i in range(MAX_CONTEXT_SIZE + 1)}
        body = _valid_body(context=big_context)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "too many keys" in _body(result).get("error", "").lower()

    def test_context_at_max_keys_accepted(self, handler, mock_http_handler):
        ok_context = {f"key_{i}": i for i in range(MAX_CONTEXT_SIZE)}
        body = _valid_body(context=ok_context)
        h = _make_http_handler(body)
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201

    def test_invalid_json_body(self, handler, mock_http_handler):
        h = MagicMock()
        h.headers = {"Content-Type": "application/json", "Content-Length": "5"}
        h.rfile.read.return_value = b"notjs"
        result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 400
        assert "json" in _body(result).get("error", "").lower()


# ============================================================================
# POST /api/v2/tasks/execute - Execution failures
# ============================================================================


class TestExecuteFailures:
    """Tests for execution failure paths."""

    def test_start_execution_raises_value_error(self, handler):
        body = _valid_body()
        h = _make_http_handler(body)
        with patch.object(handler, "_start_execution", side_effect=ValueError("bad config")):
            result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        task_id = _body(result)["task_id"]
        assert _tasks[task_id].status == "failed"
        assert _tasks[task_id].error == "bad config"

    def test_start_execution_raises_runtime_error(self, handler):
        body = _valid_body()
        h = _make_http_handler(body)
        with patch.object(handler, "_start_execution", side_effect=RuntimeError("engine crash")):
            result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        task_id = _body(result)["task_id"]
        assert _tasks[task_id].status == "failed"

    def test_start_execution_raises_os_error(self, handler):
        body = _valid_body()
        h = _make_http_handler(body)
        with patch.object(handler, "_start_execution", side_effect=OSError("disk full")):
            result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        assert _tasks[_body(result)["task_id"]].status == "failed"

    def test_start_execution_raises_attribute_error(self, handler):
        body = _valid_body()
        h = _make_http_handler(body)
        with patch.object(handler, "_start_execution", side_effect=AttributeError("no attr")):
            result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201
        assert _tasks[_body(result)["task_id"]].status == "failed"

    def test_schedule_task_failure_does_not_block(self, handler):
        """Scheduler failure should not prevent task creation."""
        body = _valid_body()
        h = _make_http_handler(body)
        with (
            patch.object(handler, "_schedule_task", side_effect=RuntimeError("scheduler down")),
            patch("aragora.server.handlers.tasks.execution._HAS_SCHEDULER", True),
        ):
            result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        assert _status(result) == 201


# ============================================================================
# POST /api/v2/tasks/execute - Event emission
# ============================================================================


class TestExecuteEvents:
    """Tests for event emission during task execution."""

    def test_created_event_emitted(self, handler):
        body = _valid_body()
        h = _make_http_handler(body)
        with patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit:
            handler.handle_post("/api/v2/tasks/execute", {}, h)
        # At least the CREATED event should be emitted
        calls = [c for c in mock_emit.call_args_list if c[0][1] == "created"]
        assert len(calls) >= 1

    def test_started_event_emitted_for_non_checkpoint(self, handler):
        body = _valid_body(human_checkpoints=False)
        h = _make_http_handler(body)
        with patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit:
            handler.handle_post("/api/v2/tasks/execute", {}, h)
        actions = [c[0][1] for c in mock_emit.call_args_list]
        assert "started" in actions

    def test_completed_event_emitted(self, handler):
        body = _valid_body(human_checkpoints=False)
        h = _make_http_handler(body)
        with patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit:
            handler.handle_post("/api/v2/tasks/execute", {}, h)
        actions = [c[0][1] for c in mock_emit.call_args_list]
        assert "completed" in actions

    def test_no_started_event_for_checkpoint_task(self, handler):
        body = _valid_body(human_checkpoints=True)
        h = _make_http_handler(body)
        with patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit:
            handler.handle_post("/api/v2/tasks/execute", {}, h)
        actions = [c[0][1] for c in mock_emit.call_args_list]
        assert "started" not in actions
        assert "completed" not in actions

    def test_failed_event_on_execution_error(self, handler):
        body = _valid_body()
        h = _make_http_handler(body)
        with (
            patch.object(handler, "_start_execution", side_effect=RuntimeError("boom")),
            patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit,
        ):
            handler.handle_post("/api/v2/tasks/execute", {}, h)
        actions = [c[0][1] for c in mock_emit.call_args_list]
        assert "failed" in actions


# ============================================================================
# GET /api/v2/tasks/<task_id>
# ============================================================================


class TestGetTask:
    """Tests for getting a single task by ID."""

    def test_get_existing_task(self, handler, mock_http_handler):
        task = TaskRecord(goal="test", type="debate")
        _tasks[task.id] = task
        result = handler.handle(f"/api/v2/tasks/{task.id}", {}, mock_http_handler)
        assert _status(result) == 200
        data = _body(result)
        assert data["id"] == task.id
        assert data["goal"] == "test"
        assert data["type"] == "debate"
        assert data["status"] == "pending"

    def test_get_nonexistent_task(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks/nonexistent-id", {}, mock_http_handler)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_get_task_includes_all_fields(self, handler, mock_http_handler):
        task = TaskRecord(
            goal="full test",
            type="analysis",
            agents=["claude"],
            max_steps=5,
            human_checkpoints=True,
            context={"key": "value"},
        )
        task.status = "waiting_approval"
        _tasks[task.id] = task
        result = handler.handle(f"/api/v2/tasks/{task.id}", {}, mock_http_handler)
        data = _body(result)
        assert data["agents"] == ["claude"]
        assert data["max_steps"] == 5
        assert data["human_checkpoints"] is True
        assert data["context"] == {"key": "value"}
        assert data["status"] == "waiting_approval"

    def test_get_completed_task_with_result(self, handler, mock_http_handler):
        task = TaskRecord(goal="done", type="debate", status="completed")
        task.result = {"summary": "success"}
        _tasks[task.id] = task
        result = handler.handle(f"/api/v2/tasks/{task.id}", {}, mock_http_handler)
        data = _body(result)
        assert data["result"] == {"summary": "success"}

    def test_get_failed_task_with_error(self, handler, mock_http_handler):
        task = TaskRecord(goal="broken", type="debate", status="failed")
        task.error = "something went wrong"
        _tasks[task.id] = task
        result = handler.handle(f"/api/v2/tasks/{task.id}", {}, mock_http_handler)
        data = _body(result)
        assert data["error"] == "something went wrong"


# ============================================================================
# GET /api/v2/tasks - List tasks
# ============================================================================


class TestListTasks:
    """Tests for listing tasks with filters and pagination."""

    def test_list_empty(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {}, mock_http_handler)
        assert _status(result) == 200
        data = _body(result)
        assert data["tasks"] == []
        assert data["total"] == 0
        assert data["limit"] == DEFAULT_LIST_LIMIT
        assert data["offset"] == 0

    def test_list_returns_tasks(self, handler, mock_http_handler):
        for i in range(3):
            task = TaskRecord(goal=f"task {i}", type="debate")
            _tasks[task.id] = task
        result = handler.handle("/api/v2/tasks", {}, mock_http_handler)
        data = _body(result)
        assert data["total"] == 3
        assert len(data["tasks"]) == 3

    def test_list_ordered_newest_first(self, handler, mock_http_handler):
        t1 = TaskRecord(goal="old", type="debate")
        t1.created_at = 1000.0
        t2 = TaskRecord(goal="new", type="debate")
        t2.created_at = 2000.0
        _tasks[t1.id] = t1
        _tasks[t2.id] = t2
        result = handler.handle("/api/v2/tasks", {}, mock_http_handler)
        data = _body(result)
        assert data["tasks"][0]["goal"] == "new"
        assert data["tasks"][1]["goal"] == "old"

    def test_list_filter_by_status(self, handler, mock_http_handler):
        pending = TaskRecord(goal="p", type="debate", status="pending")
        running = TaskRecord(goal="r", type="debate", status="running")
        _tasks[pending.id] = pending
        _tasks[running.id] = running
        result = handler.handle("/api/v2/tasks", {"status": "pending"}, mock_http_handler)
        data = _body(result)
        assert data["total"] == 1
        assert data["tasks"][0]["status"] == "pending"

    def test_list_filter_by_running_status(self, handler, mock_http_handler):
        running = TaskRecord(goal="r", type="debate", status="running")
        _tasks[running.id] = running
        result = handler.handle("/api/v2/tasks", {"status": "running"}, mock_http_handler)
        data = _body(result)
        assert data["total"] == 1

    def test_list_invalid_status_filter(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {"status": "bogus"}, mock_http_handler)
        assert _status(result) == 400
        assert "invalid status" in _body(result).get("error", "").lower()

    def test_list_pagination_limit(self, handler, mock_http_handler):
        for i in range(5):
            t = TaskRecord(goal=f"task {i}", type="debate")
            _tasks[t.id] = t
        result = handler.handle("/api/v2/tasks", {"limit": "2"}, mock_http_handler)
        data = _body(result)
        assert data["total"] == 5
        assert len(data["tasks"]) == 2
        assert data["limit"] == 2

    def test_list_pagination_offset(self, handler, mock_http_handler):
        for i in range(5):
            t = TaskRecord(goal=f"task {i}", type="debate")
            t.created_at = float(1000 + i)
            _tasks[t.id] = t
        result = handler.handle("/api/v2/tasks", {"offset": "3"}, mock_http_handler)
        data = _body(result)
        assert data["total"] == 5
        assert len(data["tasks"]) == 2  # 5 total, offset=3, so 2 remaining
        assert data["offset"] == 3

    def test_list_limit_clamped_to_max(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {"limit": "999"}, mock_http_handler)
        data = _body(result)
        assert data["limit"] == MAX_LIST_LIMIT

    def test_list_limit_clamped_to_min_1(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {"limit": "0"}, mock_http_handler)
        data = _body(result)
        assert data["limit"] == 1

    def test_list_invalid_limit_uses_default(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {"limit": "abc"}, mock_http_handler)
        data = _body(result)
        assert data["limit"] == DEFAULT_LIST_LIMIT

    def test_list_negative_offset_clamped_to_zero(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {"offset": "-5"}, mock_http_handler)
        data = _body(result)
        assert data["offset"] == 0

    def test_list_invalid_offset_defaults_to_zero(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks", {"offset": "abc"}, mock_http_handler)
        data = _body(result)
        assert data["offset"] == 0

    def test_list_all_valid_statuses_accepted(self, handler, mock_http_handler):
        for status in VALID_STATUSES:
            result = handler.handle("/api/v2/tasks", {"status": status}, mock_http_handler)
            assert _status(result) == 200

    def test_list_with_trailing_slash(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks/", {}, mock_http_handler)
        assert _status(result) == 200


# ============================================================================
# POST /api/v2/tasks/<task_id>/approve
# ============================================================================


class TestApproveTask:
    """Tests for approving a task at a human checkpoint."""

    def test_approve_waiting_task(self, handler, mock_http_handler):
        task = TaskRecord(goal="needs approval", type="debate", human_checkpoints=True)
        task.status = "waiting_approval"
        _tasks[task.id] = task
        result = handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        assert _status(result) == 200
        data = _body(result)
        assert data["task_id"] == task.id
        assert "message" in data
        assert "approved" in data["message"].lower()

    def test_approve_transitions_and_completes(self, handler, mock_http_handler):
        task = TaskRecord(goal="approve me", type="analysis", human_checkpoints=True)
        task.status = "waiting_approval"
        _tasks[task.id] = task
        handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        # After approval, execution runs and completes synchronously
        assert task.status == "completed"
        assert task.result is not None

    def test_approve_nonexistent_task(self, handler, mock_http_handler):
        result = handler.handle_post("/api/v2/tasks/does-not-exist/approve", {}, mock_http_handler)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_approve_task_not_waiting_approval(self, handler, mock_http_handler):
        task = TaskRecord(goal="running task", type="debate", status="running")
        _tasks[task.id] = task
        result = handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        assert _status(result) == 409
        assert "waiting_approval" in _body(result).get("error", "").lower()

    def test_approve_completed_task_returns_409(self, handler, mock_http_handler):
        task = TaskRecord(goal="done", type="debate", status="completed")
        _tasks[task.id] = task
        result = handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        assert _status(result) == 409

    def test_approve_failed_task_returns_409(self, handler, mock_http_handler):
        task = TaskRecord(goal="failed", type="debate", status="failed")
        _tasks[task.id] = task
        result = handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        assert _status(result) == 409

    def test_approve_pending_task_returns_409(self, handler, mock_http_handler):
        task = TaskRecord(goal="pending", type="debate", status="pending")
        _tasks[task.id] = task
        result = handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        assert _status(result) == 409

    def test_approve_emits_approved_event(self, handler, mock_http_handler):
        task = TaskRecord(goal="approve event", type="debate", human_checkpoints=True)
        task.status = "waiting_approval"
        _tasks[task.id] = task
        with patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit:
            handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        actions = [c[0][1] for c in mock_emit.call_args_list]
        assert "approved" in actions

    def test_approve_then_execution_failure(self, handler, mock_http_handler):
        task = TaskRecord(goal="will fail after approval", type="debate", human_checkpoints=True)
        task.status = "waiting_approval"
        _tasks[task.id] = task
        with patch.object(handler, "_start_execution", side_effect=RuntimeError("engine down")):
            result = handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        assert _status(result) == 200  # Still returns 200 with status
        assert task.status == "failed"
        assert task.error == "engine down"

    def test_approve_emits_failed_event_on_execution_error(self, handler, mock_http_handler):
        task = TaskRecord(goal="fail after approve", type="debate", human_checkpoints=True)
        task.status = "waiting_approval"
        _tasks[task.id] = task
        with (
            patch.object(handler, "_start_execution", side_effect=OSError("disk error")),
            patch("aragora.server.handlers.tasks.execution.emit_handler_event") as mock_emit,
        ):
            handler.handle_post(f"/api/v2/tasks/{task.id}/approve", {}, mock_http_handler)
        actions = [c[0][1] for c in mock_emit.call_args_list]
        assert "failed" in actions


# ============================================================================
# GET routing - edge cases
# ============================================================================


class TestGetRouting:
    """Tests for GET request routing."""

    def test_get_unknown_path_returns_404(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks/some-id/unknown", {}, mock_http_handler)
        assert _status(result) == 404

    def test_get_deeply_nested_returns_404(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/tasks/a/b/c/d", {}, mock_http_handler)
        assert _status(result) == 404

    def test_get_non_matching_path_returns_none(self, handler, mock_http_handler):
        result = handler.handle("/api/v2/debates", {}, mock_http_handler)
        assert result is None


# ============================================================================
# POST routing - edge cases
# ============================================================================


class TestPostRouting:
    """Tests for POST request routing."""

    def test_post_unknown_path_returns_404(self, handler, mock_http_handler):
        result = handler.handle_post("/api/v2/tasks/some-id/unknown-action", {}, mock_http_handler)
        assert _status(result) == 404

    def test_post_non_matching_path_returns_none(self, handler, mock_http_handler):
        result = handler.handle_post("/api/v2/debates", {}, mock_http_handler)
        assert result is None

    def test_post_tasks_root_returns_404(self, handler, mock_http_handler):
        """POST to /api/v2/tasks (without /execute) should return 404."""
        result = handler.handle_post("/api/v2/tasks", {}, mock_http_handler)
        assert _status(result) == 404


# ============================================================================
# Internal helpers - _start_execution
# ============================================================================


class TestStartExecution:
    """Tests for the _start_execution internal method."""

    def test_pending_task_transitions_to_running(self, handler):
        router = TaskRouter()
        route = router.route("debate", "test", {})
        task = TaskRecord(goal="test", type="debate", status="pending")
        handler._start_execution(task, route)
        # After execution, task should be completed
        assert task.status == "completed"
        assert task.result is not None

    def test_approved_task_transitions_to_running(self, handler):
        router = TaskRouter()
        route = router.route("debate", "test", {})
        task = TaskRecord(goal="test", type="debate", status="approved")
        handler._start_execution(task, route)
        assert task.status == "completed"

    def test_execution_result_contains_summary(self, handler):
        router = TaskRouter()
        route = router.route("debate", "my goal", {})
        task = TaskRecord(goal="my goal", type="debate", status="pending")
        handler._start_execution(task, route)
        assert "my goal" in task.result["summary"]
        assert task.result["steps_completed"] == len(route.workflow_steps)

    def test_workflow_engine_integration(self, handler):
        router = TaskRouter()
        route = router.route("debate", "test", {})
        task = TaskRecord(goal="test", type="debate", status="pending")
        with (
            patch("aragora.server.handlers.tasks.execution._HAS_WORKFLOW_ENGINE", True),
            patch(
                "aragora.server.handlers.tasks.execution._get_workflow_engine",
                return_value=MagicMock(),
            ),
        ):
            handler._start_execution(task, route)
        assert task.workflow_id is not None
        assert task.workflow_id.startswith("wf-")

    def test_workflow_engine_failure_does_not_block(self, handler):
        router = TaskRouter()
        route = router.route("debate", "test", {})
        task = TaskRecord(goal="test", type="debate", status="pending")
        with (
            patch("aragora.server.handlers.tasks.execution._HAS_WORKFLOW_ENGINE", True),
            patch(
                "aragora.server.handlers.tasks.execution._get_workflow_engine",
                side_effect=RuntimeError("engine unavailable"),
            ),
        ):
            handler._start_execution(task, route)
        assert task.status == "completed"
        assert task.workflow_id is None


# ============================================================================
# Internal helpers - _schedule_task
# ============================================================================


class TestScheduleTask:
    """Tests for _schedule_task."""

    def test_schedule_noop_when_no_scheduler(self, handler):
        router = TaskRouter()
        route = router.route("debate", "test", {})
        task = TaskRecord(goal="test", type="debate")
        # Should not raise
        handler._schedule_task(task, route)


# ============================================================================
# _clear_tasks utility
# ============================================================================


class TestClearTasks:
    """Tests for the _clear_tasks utility."""

    def test_clear_removes_all_tasks(self):
        _tasks["a"] = TaskRecord(goal="x", type="debate")
        _tasks["b"] = TaskRecord(goal="y", type="debate")
        assert len(_tasks) == 2
        _clear_tasks()
        assert len(_tasks) == 0


# ============================================================================
# Constants verification
# ============================================================================


class TestConstants:
    """Verify module-level constants are correct."""

    def test_valid_statuses(self):
        expected = {"pending", "running", "completed", "failed", "waiting_approval", "approved"}
        assert VALID_STATUSES == expected

    def test_valid_task_types(self):
        expected = {"debate", "code_edit", "computer_use", "analysis", "composite"}
        assert VALID_TASK_TYPES == expected

    def test_max_goal_length(self):
        assert MAX_GOAL_LENGTH == 5000

    def test_max_context_size(self):
        assert MAX_CONTEXT_SIZE == 50

    def test_max_list_limit(self):
        assert MAX_LIST_LIMIT == 100

    def test_default_list_limit(self):
        assert DEFAULT_LIST_LIMIT == 20


# ============================================================================
# Full integration (execute -> get -> list -> approve)
# ============================================================================


class TestIntegrationFlow:
    """End-to-end integration tests across multiple endpoints."""

    def test_execute_then_get(self, handler, mock_http_handler):
        body = _valid_body()
        h = _make_http_handler(body)
        exec_result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        task_id = _body(exec_result)["task_id"]

        get_result = handler.handle(f"/api/v2/tasks/{task_id}", {}, mock_http_handler)
        assert _status(get_result) == 200
        assert _body(get_result)["id"] == task_id

    def test_execute_then_list(self, handler, mock_http_handler):
        body = _valid_body()
        h = _make_http_handler(body)
        handler.handle_post("/api/v2/tasks/execute", {}, h)

        list_result = handler.handle("/api/v2/tasks", {}, mock_http_handler)
        data = _body(list_result)
        assert data["total"] == 1

    def test_execute_with_checkpoint_then_approve(self, handler, mock_http_handler):
        body = _valid_body(human_checkpoints=True)
        h = _make_http_handler(body)
        exec_result = handler.handle_post("/api/v2/tasks/execute", {}, h)
        task_id = _body(exec_result)["task_id"]
        assert _body(exec_result)["status"] == "waiting_approval"

        approve_result = handler.handle_post(
            f"/api/v2/tasks/{task_id}/approve", {}, mock_http_handler
        )
        assert _status(approve_result) == 200
        assert _tasks[task_id].status == "completed"

    def test_multiple_tasks_with_status_filter(self, handler, mock_http_handler):
        # Create a completed task (no checkpoints)
        h1 = _make_http_handler(_valid_body(type="debate"))
        handler.handle_post("/api/v2/tasks/execute", {}, h1)

        # Create a waiting_approval task (with checkpoints)
        h2 = _make_http_handler(_valid_body(type="analysis", human_checkpoints=True))
        handler.handle_post("/api/v2/tasks/execute", {}, h2)

        # Filter completed
        completed = handler.handle("/api/v2/tasks", {"status": "completed"}, mock_http_handler)
        assert _body(completed)["total"] == 1
        assert _body(completed)["tasks"][0]["status"] == "completed"

        # Filter waiting_approval
        waiting = handler.handle("/api/v2/tasks", {"status": "waiting_approval"}, mock_http_handler)
        assert _body(waiting)["total"] == 1
        assert _body(waiting)["tasks"][0]["status"] == "waiting_approval"

    def test_execute_multiple_then_paginate(self, handler, mock_http_handler):
        for i in range(5):
            h = _make_http_handler(_valid_body(goal=f"Task {i}"))
            handler.handle_post("/api/v2/tasks/execute", {}, h)

        # Page 1
        r1 = handler.handle("/api/v2/tasks", {"limit": "2", "offset": "0"}, mock_http_handler)
        d1 = _body(r1)
        assert d1["total"] == 5
        assert len(d1["tasks"]) == 2

        # Page 2
        r2 = handler.handle("/api/v2/tasks", {"limit": "2", "offset": "2"}, mock_http_handler)
        d2 = _body(r2)
        assert len(d2["tasks"]) == 2

        # Page 3 (partial)
        r3 = handler.handle("/api/v2/tasks", {"limit": "2", "offset": "4"}, mock_http_handler)
        d3 = _body(r3)
        assert len(d3["tasks"]) == 1
