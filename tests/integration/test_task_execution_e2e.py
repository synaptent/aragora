"""
End-to-end integration tests for the task execution pipeline.

Tests the full flow from task creation through routing to completion,
covering TaskRouter, TaskExecutionHandler, TaskRecord, and status transitions.

Run with:
    python -m pytest tests/integration/test_task_execution_e2e.py -v \
        --override-ini="confcutdir=tests/integration"
"""

from __future__ import annotations

import io
import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.tasks.execution import (
    VALID_TASK_TYPES,
    TaskExecutionHandler,
    TaskRoute,
    TaskRouter,
    TaskRecord,
    _clear_tasks,
    _tasks,
)
from aragora.server.handlers.utils.responses import HandlerResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler_with_body(body: dict[str, Any]) -> MagicMock:
    """Create a mock HTTP handler with a JSON body."""
    raw = json.dumps(body).encode("utf-8")
    mock = MagicMock()
    mock.headers = {"Content-Length": str(len(raw))}
    mock.rfile = io.BytesIO(raw)
    return mock


def _parse_body(result: HandlerResult) -> dict[str, Any]:
    """Decode JSON body from a HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_task_store():
    """Ensure the in-memory task store is empty before and after each test."""
    _clear_tasks()
    yield
    _clear_tasks()


@pytest.fixture()
def handler() -> TaskExecutionHandler:
    """Return a TaskExecutionHandler wired with a minimal server context."""
    ctx: dict[str, Any] = {}
    return TaskExecutionHandler(server_context=ctx)


@pytest.fixture()
def router() -> TaskRouter:
    """Return a fresh TaskRouter with default routes."""
    return TaskRouter()


# ---------------------------------------------------------------------------
# 1. Create a task and verify it appears in the list
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_create_task_appears_in_list(mock_emit: MagicMock, handler: TaskExecutionHandler) -> None:
    """Creating a task via POST /execute should make it visible in GET /tasks."""
    body = {
        "goal": "Decide on a caching strategy",
        "type": "debate",
        "agents": ["claude", "gpt4"],
        "max_steps": 5,
        "human_checkpoints": False,
        "context": {"domain": "infrastructure"},
    }
    mock_handler = _make_handler_with_body(body)

    create_result = handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)
    assert create_result is not None
    assert create_result.status_code == 201

    created = _parse_body(create_result)
    task_id = created["task_id"]

    # List all tasks
    list_result = handler.handle("/api/v2/tasks", {}, None)
    assert list_result is not None
    assert list_result.status_code == 200

    list_data = _parse_body(list_result)
    task_ids = [t["id"] for t in list_data["tasks"]]
    assert task_id in task_ids


# ---------------------------------------------------------------------------
# 2. Task type routing - each type resolves to correct workflow steps
# ---------------------------------------------------------------------------


def test_task_type_routing_all_defaults(router: TaskRouter) -> None:
    """Every default task type should resolve to a TaskRoute with expected steps."""
    expected_step_counts = {
        "debate": 1,
        "code_edit": 3,
        "computer_use": 1,
        "analysis": 1,
        "composite": 3,
    }

    for task_type in VALID_TASK_TYPES:
        route = router.get_route(task_type)
        assert route is not None, f"Missing route for '{task_type}'"
        assert route.task_type == task_type
        assert len(route.workflow_steps) == expected_step_counts[task_type], (
            f"Wrong step count for '{task_type}': "
            f"got {len(route.workflow_steps)}, expected {expected_step_counts[task_type]}"
        )
        assert len(route.required_capabilities) > 0, (
            f"Route '{task_type}' should declare required capabilities"
        )

    # Unknown type via get_route returns None
    assert router.get_route("nonexistent") is None

    # Unknown type via route() returns a fallback
    fallback = router.route("custom_type", "some goal", {})
    assert fallback.task_type == "custom_type"
    assert fallback.workflow_steps[0]["id"] == "fallback_debate_step"


# ---------------------------------------------------------------------------
# 3. Status transitions: pending -> running -> completed
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_status_transitions_pending_to_completed(
    mock_emit: MagicMock, handler: TaskExecutionHandler
) -> None:
    """A task without human_checkpoints should transition pending -> running -> completed."""
    body = {"goal": "Analyze performance bottlenecks", "type": "analysis"}
    mock_handler = _make_handler_with_body(body)

    result = handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)
    assert result is not None
    assert result.status_code == 201

    created = _parse_body(result)
    task_id = created["task_id"]

    # The handler's _start_execution runs synchronously and completes the task
    task = _tasks[task_id]
    assert task.status == "completed"
    assert task.result is not None
    assert "steps_completed" in task.result


# ---------------------------------------------------------------------------
# 4. Human checkpoint flow: create with checkpoints -> approve
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_human_checkpoint_approve_flow(mock_emit: MagicMock, handler: TaskExecutionHandler) -> None:
    """Tasks with human_checkpoints should wait for approval before executing."""
    body = {
        "goal": "Deploy to production",
        "type": "composite",
        "human_checkpoints": True,
    }
    mock_handler = _make_handler_with_body(body)

    # Create task - should be waiting_approval
    create_result = handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)
    assert create_result is not None
    assert create_result.status_code == 201

    created = _parse_body(create_result)
    task_id = created["task_id"]
    assert created["status"] == "waiting_approval"

    # Verify task is actually waiting
    task = _tasks[task_id]
    assert task.status == "waiting_approval"

    # Approve the task
    approve_result = handler.handle_post(f"/api/v2/tasks/{task_id}/approve", {}, MagicMock())
    assert approve_result is not None
    assert approve_result.status_code == 200

    approve_data = _parse_body(approve_result)
    assert approve_data["task_id"] == task_id
    # After approval, _start_execution runs and completes synchronously
    assert task.status == "completed"


# ---------------------------------------------------------------------------
# 5. Task listing with status filter
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_list_tasks_with_status_filter(mock_emit: MagicMock, handler: TaskExecutionHandler) -> None:
    """GET /api/v2/tasks?status=... should filter tasks by status."""
    # Create two tasks: one auto-completed, one waiting approval
    for goal, task_type, checkpoints in [
        ("Analyze logs", "analysis", False),
        ("Review PR", "code_edit", True),
        ("Quick debate", "debate", False),
    ]:
        body = {"goal": goal, "type": task_type, "human_checkpoints": checkpoints}
        mock_handler = _make_handler_with_body(body)
        handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)

    # Filter by completed
    result_completed = handler.handle("/api/v2/tasks", {"status": "completed"}, None)
    assert result_completed is not None
    completed_data = _parse_body(result_completed)
    completed_tasks = completed_data["tasks"]
    assert all(t["status"] == "completed" for t in completed_tasks)
    assert len(completed_tasks) == 2  # analysis + debate both auto-complete

    # Filter by waiting_approval
    result_waiting = handler.handle("/api/v2/tasks", {"status": "waiting_approval"}, None)
    assert result_waiting is not None
    waiting_data = _parse_body(result_waiting)
    waiting_tasks = waiting_data["tasks"]
    assert len(waiting_tasks) == 1
    assert waiting_tasks[0]["status"] == "waiting_approval"
    assert waiting_tasks[0]["goal"] == "Review PR"

    # Invalid status filter
    result_invalid = handler.handle("/api/v2/tasks", {"status": "bogus"}, None)
    assert result_invalid is not None
    assert result_invalid.status_code == 400


# ---------------------------------------------------------------------------
# 6. Task not found returns 404
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_task_not_found_returns_404(mock_emit: MagicMock, handler: TaskExecutionHandler) -> None:
    """GET /api/v2/tasks/<nonexistent_id> should return 404."""
    result = handler.handle("/api/v2/tasks/nonexistent-uuid-12345", {}, None)
    assert result is not None
    assert result.status_code == 404

    body = _parse_body(result)
    assert "not found" in body.get("error", "").lower()


# ---------------------------------------------------------------------------
# 7. Invalid task type returns error
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_invalid_task_type_returns_error(
    mock_emit: MagicMock, handler: TaskExecutionHandler
) -> None:
    """POST with an unsupported task type should return 400."""
    body = {"goal": "Do something", "type": "teleportation"}
    mock_handler = _make_handler_with_body(body)

    result = handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)
    assert result is not None
    assert result.status_code == 400

    data = _parse_body(result)
    assert "invalid task type" in data.get("error", "").lower()


# ---------------------------------------------------------------------------
# 8. Full pipeline: create -> route -> execute -> complete
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_full_pipeline_create_route_execute_complete(
    mock_emit: MagicMock, handler: TaskExecutionHandler
) -> None:
    """End-to-end: create a code_edit task, verify routing, execution, and result."""
    body = {
        "goal": "Refactor the billing module for clarity",
        "type": "code_edit",
        "agents": ["claude"],
        "max_steps": 15,
        "context": {"target_file": "aragora/billing/cost_tracker.py"},
    }
    mock_handler = _make_handler_with_body(body)

    # Step 1: Create task
    create_result = handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)
    assert create_result is not None
    assert create_result.status_code == 201

    created = _parse_body(create_result)
    task_id = created["task_id"]

    # Verify the route returned in the response has code_edit steps
    steps = created["workflow_steps"]
    assert len(steps) == 3  # code_edit has analysis, implementation, verification
    step_types = [s["type"] for s in steps]
    assert "analysis" in step_types
    assert "implementation" in step_types
    assert "verification" in step_types

    # Step 2: Fetch task by ID
    get_result = handler.handle(f"/api/v2/tasks/{task_id}", {}, None)
    assert get_result is not None
    assert get_result.status_code == 200

    task_data = _parse_body(get_result)
    assert task_data["id"] == task_id
    assert task_data["goal"] == "Refactor the billing module for clarity"
    assert task_data["type"] == "code_edit"
    assert task_data["status"] == "completed"
    assert task_data["agents"] == ["claude"]
    assert task_data["max_steps"] == 15

    # Step 3: Verify result payload
    assert task_data["result"] is not None
    assert task_data["result"]["steps_completed"] == 3
    assert "executed successfully" in task_data["result"]["summary"]

    # Step 4: Verify events were emitted in order
    event_actions = [call.args[1] for call in mock_emit.call_args_list]
    assert "created" in event_actions
    assert "started" in event_actions
    assert "completed" in event_actions


# ---------------------------------------------------------------------------
# 9. TaskRecord status transition guards
# ---------------------------------------------------------------------------


def test_task_record_transition_guards() -> None:
    """TaskRecord.transition_to should enforce valid state transitions."""
    task = TaskRecord(goal="test", type="debate", status="pending")

    # Valid: pending -> running
    task.transition_to("running")
    assert task.status == "running"

    # Valid: running -> completed
    task.transition_to("completed")
    assert task.status == "completed"

    # Invalid: completed is terminal
    with pytest.raises(ValueError, match="Cannot transition"):
        task.transition_to("running")

    # Invalid: cannot skip states
    task2 = TaskRecord(goal="test2", type="debate", status="pending")
    with pytest.raises(ValueError, match="Cannot transition"):
        task2.transition_to("completed")

    # Waiting approval -> approved -> running -> completed
    task3 = TaskRecord(goal="test3", type="debate", status="waiting_approval")
    task3.transition_to("approved")
    assert task3.status == "approved"
    task3.transition_to("running")
    assert task3.status == "running"
    task3.transition_to("completed")
    assert task3.status == "completed"


# ---------------------------------------------------------------------------
# 10. Approve on non-waiting task returns 409
# ---------------------------------------------------------------------------


@patch("aragora.server.handlers.tasks.execution.emit_handler_event")
def test_approve_non_waiting_task_returns_conflict(
    mock_emit: MagicMock, handler: TaskExecutionHandler
) -> None:
    """Approving a task that is not in waiting_approval should return 409."""
    # Create a task that auto-completes (no checkpoints)
    body = {"goal": "Quick analysis", "type": "analysis"}
    mock_handler = _make_handler_with_body(body)

    create_result = handler.handle_post("/api/v2/tasks/execute", {}, mock_handler)
    assert create_result is not None
    task_id = _parse_body(create_result)["task_id"]

    # Task is already completed; approve should fail
    approve_result = handler.handle_post(f"/api/v2/tasks/{task_id}/approve", {}, MagicMock())
    assert approve_result is not None
    assert approve_result.status_code == 409

    data = _parse_body(approve_result)
    assert "cannot approve" in data.get("error", "").lower()
