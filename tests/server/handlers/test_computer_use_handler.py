"""
Tests for ComputerUseHandler - Computer use orchestration HTTP endpoints.

Tests cover:
- Task creation and execution
- Task listing with filters
- Task status retrieval
- Task cancellation
- Action statistics
- Policy management
- RBAC protection
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import tempfile
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest

# Import directly to avoid circular import in handlers package
import importlib.util
import sys


def _find_repo_root(start: Path) -> Path | None:
    for parent in (start, *start.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


_handler_spec = importlib.util.find_spec(
    "aragora.server.handlers.integrations.computer_use_handler"
)
if _handler_spec and _handler_spec.origin:
    _handler_path = Path(_handler_spec.origin)
else:
    repo_root = _find_repo_root(Path(__file__).resolve())
    if repo_root is None:
        repo_root = Path(tempfile.gettempdir())
    _handler_path = (
        repo_root / "aragora" / "server" / "handlers" / "integrations" / "computer_use_handler.py"
    )
_spec = importlib.util.spec_from_file_location("computer_use_handler", str(_handler_path))
if _spec and _spec.loader:
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["computer_use_handler"] = _module
    _spec.loader.exec_module(_module)
    ComputerUseHandler = _module.ComputerUseHandler
else:
    # Fallback for type checking
    ComputerUseHandler = None  # type: ignore


# ===========================================================================
# Test Fixtures and Mocks
# ===========================================================================


@dataclass
class MockTaskResult:
    """Mock task result for testing."""

    success: bool = True
    message: str = "Task completed successfully"
    steps_taken: int = 5
    steps: list[Any] = field(default_factory=list)


@dataclass
class MockStep:
    """Mock step for testing."""

    action: MagicMock = field(default_factory=lambda: MagicMock(value="click"))
    success: bool = True


class MockComputerUseOrchestrator:
    """Mock computer use orchestrator for testing."""

    def __init__(self, policy=None, config=None):
        self.policy = policy
        self.config = config

    async def run_task(
        self,
        goal: str,
        max_steps: int = 10,
    ) -> MockTaskResult:
        return MockTaskResult(
            success=True,
            message="Task completed",
            steps_taken=3,
            steps=[MockStep(), MockStep(), MockStep()],
        )


class MockComputerPolicy:
    """Mock computer policy for testing."""

    name: str = "Test Policy"
    description: str = "A test policy"
    allowed_actions: list[str] = ["screenshot", "click", "type"]


class MockRequestHandler:
    """Mock HTTP request handler."""

    def __init__(self, body: dict | None = None, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    def read_body(self):
        return json.dumps(self._body).encode() if self._body else b"{}"


@pytest.fixture
def mock_server_context():
    """Create mock server context."""
    return MagicMock()


@pytest.fixture
def mock_orchestrator():
    """Create mock computer use orchestrator."""
    return MockComputerUseOrchestrator()


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test_computer_use.db")


@pytest.fixture
def handler(mock_server_context, mock_orchestrator, temp_db_path):
    """Create handler with mocked dependencies."""
    from aragora.computer_use.storage import ComputerUseStorage

    h = ComputerUseHandler(mock_server_context)
    h._orchestrator = mock_orchestrator
    # Use temporary database for storage
    storage = ComputerUseStorage(db_path=temp_db_path, backend="sqlite")
    h._storage = storage

    # Seed some tasks via storage
    storage.save_task(
        {
            "task_id": "task-001",
            "goal": "Open settings",
            "max_steps": 10,
            "dry_run": False,
            "status": "completed",
            "created_at": "2025-01-29T10:00:00Z",
            "steps": [{"action": "click", "success": True}],
            "result": {"success": True, "message": "Done", "steps_taken": 1},
        }
    )
    storage.save_task(
        {
            "task_id": "task-002",
            "goal": "Enable dark mode",
            "max_steps": 5,
            "dry_run": False,
            "status": "running",
            "created_at": "2025-01-29T11:00:00Z",
            "steps": [],
            "result": None,
        }
    )
    return h


# ===========================================================================
# Handler Tests
# ===========================================================================


class TestComputerUseHandlerRouting:
    """Test request routing."""

    def test_can_handle_computer_use_paths(self, handler):
        """Test that handler recognizes computer use paths."""
        assert handler.can_handle("/api/v1/computer-use/tasks")
        assert handler.can_handle("/api/v1/computer-use/tasks/task-001")
        assert handler.can_handle("/api/v1/computer-use/tasks/task-001/cancel")
        assert handler.can_handle("/api/v1/computer-use/actions/stats")
        assert handler.can_handle("/api/v1/computer-use/policies")

    def test_cannot_handle_other_paths(self, handler):
        """Test that handler rejects non-computer-use paths."""
        assert not handler.can_handle("/api/v1/debates")
        assert not handler.can_handle("/api/v1/gateway/devices")
        assert not handler.can_handle("/api/computer-use/tasks")  # Missing v1


class TestListTasks:
    """Test list tasks endpoint."""

    def test_list_tasks_success(self, handler):
        """Test listing tasks returns correct format."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/tasks",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "tasks" in body
        assert "total" in body
        assert body["total"] == 2

    def test_list_tasks_with_status_filter(self, handler):
        """Test listing tasks with status filter."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/tasks",
                {"status": "completed"},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert body["total"] == 1

    def test_list_tasks_with_limit(self, handler):
        """Test listing tasks with limit."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/tasks",
                {"limit": "1"},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert len(body["tasks"]) == 1


class TestGetTask:
    """Test get single task endpoint."""

    def test_get_task_success(self, handler):
        """Test getting a specific task."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/tasks/task-001",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "task" in body
        assert body["task"]["task_id"] == "task-001"

    def test_get_task_not_found(self, handler):
        """Test getting non-existent task returns 404."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/tasks/nonexistent",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 404


class TestCreateTask:
    """Test create task endpoint."""

    def test_create_task_success(self, handler):
        """Test creating a new task."""
        mock_handler = MockRequestHandler(
            body={
                "goal": "Open browser and go to example.com",
                "max_steps": 10,
            }
        )

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(
                handler,
                "read_json_body",
                return_value={
                    "goal": "Open browser and go to example.com",
                    "max_steps": 10,
                },
            ):
                result = handler.handle_post(
                    "/api/v1/computer-use/tasks",
                    {},
                    mock_handler,
                )

        assert result is not None
        assert result.status_code == 201

        body = json.loads(result.body)
        assert "task_id" in body
        assert "status" in body
        assert "message" in body

    def test_create_task_dry_run(self, handler):
        """Test creating a task with dry run."""
        mock_handler = MockRequestHandler(
            body={
                "goal": "Test task",
                "dry_run": True,
            }
        )

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(
                handler,
                "read_json_body",
                return_value={
                    "goal": "Test task",
                    "dry_run": True,
                },
            ):
                result = handler.handle_post(
                    "/api/v1/computer-use/tasks",
                    {},
                    mock_handler,
                )

        assert result is not None
        assert result.status_code == 201

        body = json.loads(result.body)
        assert body["status"] == "completed"

    def test_create_task_missing_goal(self, handler):
        """Test creating task without goal fails."""
        mock_handler = MockRequestHandler(body={})

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(handler, "read_json_body", return_value={}):
                result = handler.handle_post(
                    "/api/v1/computer-use/tasks",
                    {},
                    mock_handler,
                )

        assert result is not None
        assert result.status_code == 400

    def test_create_task_invalid_json_returns_400(self, handler):
        """Malformed JSON should fail before task validation."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(handler, "read_json_body", return_value=None):
                result = handler.handle_post(
                    "/api/v1/computer-use/tasks",
                    {},
                    mock_handler,
                )

        assert result is not None
        assert result.status_code == 400
        assert "json" in json.loads(result.body)["error"].lower()


class TestCancelTask:
    """Test cancel task endpoint."""

    def test_cancel_task_success(self, handler):
        """Test cancelling a running task."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle_post(
                "/api/v1/computer-use/tasks/task-002/cancel",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert body["message"] == "Task cancelled"

        # Verify task status was updated via storage
        task = handler._get_storage().get_task("task-002")
        assert task is not None
        assert task.status == "cancelled"

    def test_cancel_task_not_found(self, handler):
        """Test cancelling non-existent task returns 404."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle_post(
                "/api/v1/computer-use/tasks/nonexistent/cancel",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 404

    def test_cancel_completed_task_fails(self, handler):
        """Test cancelling completed task returns 400."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle_post(
                "/api/v1/computer-use/tasks/task-001/cancel",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 400


class TestActionStats:
    """Test action statistics endpoint."""

    def test_action_stats_success(self, handler):
        """Test getting action statistics."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/actions/stats",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "stats" in body
        # Check stat categories exist
        assert "click" in body["stats"]
        assert "type" in body["stats"]
        assert "screenshot" in body["stats"]


class TestListPolicies:
    """Test list policies endpoint."""

    def test_list_policies_success(self, handler):
        """Test listing policies."""
        mock_handler = MockRequestHandler()

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            result = handler.handle(
                "/api/v1/computer-use/policies",
                {},
                mock_handler,
            )

        assert result is not None
        assert result.status_code == 200

        body = json.loads(result.body)
        assert "policies" in body
        assert "total" in body
        # Default policy should always be present
        assert body["total"] >= 1


class TestCreatePolicy:
    """Test create policy endpoint."""

    def test_create_policy_success(self, handler):
        """Test creating a new policy."""
        mock_handler = MockRequestHandler(
            body={
                "name": "Restricted Policy",
                "allowed_actions": ["screenshot"],
            }
        )

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(
                handler,
                "read_json_body",
                return_value={
                    "name": "Restricted Policy",
                    "allowed_actions": ["screenshot"],
                },
            ):
                result = handler.handle_post(
                    "/api/v1/computer-use/policies",
                    {},
                    mock_handler,
                )

        assert result is not None
        assert result.status_code == 201

        body = json.loads(result.body)
        assert "policy_id" in body
        assert "message" in body

    def test_create_policy_missing_name(self, handler):
        """Test creating policy without name fails."""
        mock_handler = MockRequestHandler(body={})

        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(handler, "read_json_body", return_value={}):
                result = handler.handle_post(
                    "/api/v1/computer-use/policies",
                    {},
                    mock_handler,
                )

        assert result is not None
        assert result.status_code == 400


class TestModuleNotAvailable:
    """Test behavior when computer use module is not available."""

    def test_returns_503_when_module_unavailable(self, mock_server_context):
        """Test that 503 is returned when computer use module unavailable."""
        with patch("computer_use_handler.COMPUTER_USE_AVAILABLE", False):
            h = ComputerUseHandler(mock_server_context)
            mock_handler = MockRequestHandler()

            # Bypass RBAC to test module unavailability
            with patch.object(h, "_check_rbac_permission", return_value=None):
                result = h.handle("/api/v1/computer-use/tasks", {}, mock_handler)

            assert result is not None
            assert result.status_code == 503


class TestRBACProtection:
    """Test RBAC permission enforcement."""

    def test_unauthenticated_returns_401(self, handler):
        """Test that unauthenticated requests return 401."""
        mock_handler = MockRequestHandler()

        from aragora.server.handlers.base import error_response

        with patch.object(
            handler, "_check_rbac_permission", return_value=error_response("Not authenticated", 401)
        ):
            result = handler.handle("/api/v1/computer-use/tasks", {}, mock_handler)

        assert result is not None
        assert result.status_code == 401

    def test_unauthorized_returns_403(self, handler):
        """Test that unauthorized requests return 403."""
        mock_handler = MockRequestHandler()

        from aragora.server.handlers.base import error_response

        with patch.object(
            handler, "_check_rbac_permission", return_value=error_response("Permission denied", 403)
        ):
            result = handler.handle("/api/v1/computer-use/tasks", {}, mock_handler)

        assert result is not None
        assert result.status_code == 403


class TestTaskExecution:
    """Test task execution scenarios."""

    def test_task_execution_error_handling(self, handler):
        """Test that task execution errors are captured."""
        mock_handler = MockRequestHandler()

        # Create a handler with an orchestrator that raises an error
        with patch.object(handler, "_check_rbac_permission", return_value=None):
            with patch.object(
                handler,
                "read_json_body",
                return_value={
                    "goal": "Test task",
                },
            ):
                with patch.object(
                    handler._orchestrator, "run_task", side_effect=ValueError("Test error")
                ):
                    with patch(
                        "aragora.server.handlers.computer_use_handler.run_async",
                        side_effect=ValueError("Test error"),
                    ):
                        result = handler.handle_post(
                            "/api/v1/computer-use/tasks",
                            {},
                            mock_handler,
                        )

        assert result is not None
        # Task should be created but marked as failed
        assert result.status_code == 201

        body = json.loads(result.body)
        assert body["status"] == "failed"
