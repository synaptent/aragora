"""Tests for control plane task handler mixin.

Covers:
- Task CRUD operations (get, submit, complete, fail, cancel)
- Task claiming
- Queue retrieval and metrics
- Task history with filtering
- Deliberation endpoints
- Error handling (coordinator unavailable, not found)
- Parameter validation
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
)
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="org-1", user_id="user-1", role="admin")


def _body(result) -> dict:
    """Parse HandlerResult.body bytes into dict."""
    return json.loads(result.body)


# ============================================================================
# Mock Task Model
# ============================================================================


class _EnumLike:
    """Mimics an enum with .value and .name attributes."""

    def __init__(self, val: str):
        self.value = val
        self.name = val.upper()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.value == other
        if isinstance(other, _EnumLike):
            return self.value == other.value
        return NotImplemented

    def __str__(self) -> str:
        return self.value


@dataclass
class MockTask:
    """Lightweight mock task for testing."""

    id: str = "task_001"
    task_type: str = "analysis"
    status: Any = field(default_factory=lambda: _EnumLike("pending"))
    priority: Any = field(default_factory=lambda: _EnumLike("normal"))
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    assigned_agent: str | None = None
    required_capabilities: list = field(default_factory=list)
    result: Any = None
    error: str | None = None
    retries: int = 0
    created_at: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "status": self.status.value if hasattr(self.status, "value") else self.status,
            "priority": self.priority.value if hasattr(self.priority, "value") else self.priority,
            "payload": self.payload,
            "metadata": self.metadata,
            "assigned_agent": self.assigned_agent,
            "required_capabilities": self.required_capabilities,
            "result": self.result,
            "error": self.error,
        }


# ============================================================================
# TaskHandlerMixin Concrete Implementation for Testing
# ============================================================================


class _ConcreteTaskHandler:
    """Concrete implementation of TaskHandlerMixin for testing.

    Provides required abstract methods that the mixin expects.
    """

    def __init__(self, coordinator=None, stream=None):
        self._coordinator = coordinator
        self._stream = stream
        self.ctx = {}

    def _get_coordinator(self):
        return self._coordinator

    def _require_coordinator(self):
        if self._coordinator is None:
            return None, error_response("Control plane not initialized", 503)
        return self._coordinator, None

    def _handle_coordinator_error(self, error, operation):
        return error_response(f"Coordinator error: {operation}", 500)

    def _get_stream(self):
        return self._stream

    def _emit_event(self, emit_method, *args, max_retries=3, base_delay=0.1, **kwargs):
        if self._stream:
            method = getattr(self._stream, emit_method, None)
            if method:
                method(*args, **kwargs)

    def require_auth_or_error(self, handler):
        user = MagicMock()
        user.role = "admin"
        user.user_id = "test-user"
        return user, None


# Import TaskHandlerMixin after defining the concrete class
try:
    from aragora.server.handlers.control_plane.tasks import TaskHandlerMixin

    # Dynamically create test handler class
    class TestableTaskHandler(_ConcreteTaskHandler, TaskHandlerMixin):
        pass

    HAS_TASK_HANDLER = True
except ImportError:
    HAS_TASK_HANDLER = False
    TestableTaskHandler = None


pytestmark = pytest.mark.skipif(
    not HAS_TASK_HANDLER,
    reason="TaskHandlerMixin not available",
)


# ============================================================================
# Get Task
# ============================================================================


class TestGetTask:
    """Test GET /api/control-plane/tasks/:id."""

    def test_task_found(self):
        task = MockTask(id="task_123")
        coordinator = MagicMock()
        coordinator.get_task = AsyncMock(return_value=task)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_get_task("task_123")
        assert result.status_code == 200
        body = _body(result)
        assert body["id"] == "task_123"

    def test_task_not_found(self):
        coordinator = MagicMock()
        coordinator.get_task = AsyncMock(return_value=None)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_get_task("nonexistent")
        assert result.status_code == 404

    def test_coordinator_unavailable(self):
        handler = TestableTaskHandler(coordinator=None)
        result = handler._handle_get_task("task_123")
        assert result.status_code == 503


# ============================================================================
# Submit Task
# ============================================================================


class TestSubmitTask:
    """Test POST /api/control-plane/tasks."""

    def test_submit_success(self):
        coordinator = MagicMock()
        coordinator.submit_task = AsyncMock(return_value="task_new_001")
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_submit_task(
            {"task_type": "analysis", "payload": {"data": "test"}},
            MagicMock(),
        )
        assert result.status_code == 201
        body = _body(result)
        assert body["task_id"] == "task_new_001"

    def test_submit_missing_task_type(self):
        coordinator = MagicMock()
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_submit_task({"payload": {}}, MagicMock())
        assert result.status_code == 400
        assert "task_type" in _body(result)["error"].lower()

    def test_submit_coordinator_unavailable(self):
        handler = TestableTaskHandler(coordinator=None)
        result = handler._handle_submit_task(
            {"task_type": "analysis"},
            MagicMock(),
        )
        assert result.status_code == 503

    def test_submit_with_priority(self):
        coordinator = MagicMock()
        coordinator.submit_task = AsyncMock(return_value="task_002")
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_submit_task(
            {"task_type": "analysis", "priority": "high"},
            MagicMock(),
        )
        assert result.status_code == 201


# ============================================================================
# Claim Task
# ============================================================================


class TestClaimTask:
    """Test POST /api/control-plane/tasks/claim."""

    def test_claim_success(self):
        task = MockTask(id="task_claimed", status=_EnumLike("running"), assigned_agent="agent1")
        coordinator = MagicMock()
        coordinator.claim_task = AsyncMock(return_value=task)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_claim_task(
            {"agent_id": "agent1", "capabilities": ["analysis"]},
            MagicMock(),
        )
        assert result.status_code == 200
        body = _body(result)
        assert body["task"]["id"] == "task_claimed"

    def test_claim_no_tasks(self):
        coordinator = MagicMock()
        coordinator.claim_task = AsyncMock(return_value=None)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_claim_task(
            {"agent_id": "agent1"},
            MagicMock(),
        )
        assert result.status_code == 200
        body = _body(result)
        assert body["task"] is None

    def test_claim_missing_agent_id(self):
        coordinator = MagicMock()
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_claim_task({}, MagicMock())
        assert result.status_code == 400
        assert "agent_id" in _body(result)["error"].lower()


# ============================================================================
# Complete Task
# ============================================================================


class TestCompleteTask:
    """Test POST /api/control-plane/tasks/:id/complete."""

    def test_complete_success(self):
        coordinator = MagicMock()
        coordinator.complete_task = AsyncMock(return_value=True)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_complete_task(
            "task_001",
            {"result": {"answer": "42"}, "agent_id": "agent1"},
            MagicMock(),
        )
        assert result.status_code == 200
        assert _body(result)["completed"] is True

    def test_complete_not_found(self):
        coordinator = MagicMock()
        coordinator.complete_task = AsyncMock(return_value=False)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_complete_task(
            "nonexistent",
            {"result": {}},
            MagicMock(),
        )
        assert result.status_code == 404


# ============================================================================
# Fail Task
# ============================================================================


class TestFailTask:
    """Test POST /api/control-plane/tasks/:id/fail."""

    def test_fail_success(self):
        coordinator = MagicMock()
        coordinator.fail_task = AsyncMock(return_value=True)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_fail_task(
            "task_001",
            {"error": "Something went wrong", "requeue": True},
            MagicMock(),
        )
        assert result.status_code == 200
        assert _body(result)["failed"] is True

    def test_fail_not_found(self):
        coordinator = MagicMock()
        coordinator.fail_task = AsyncMock(return_value=False)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_fail_task(
            "nonexistent",
            {"error": "oops"},
            MagicMock(),
        )
        assert result.status_code == 404

    def test_fail_default_error(self):
        coordinator = MagicMock()
        coordinator.fail_task = AsyncMock(return_value=True)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_fail_task("task_001", {}, MagicMock())
        assert result.status_code == 200
        # Coordinator should receive default error message
        call_args = coordinator.fail_task.call_args
        assert call_args is not None


# ============================================================================
# Cancel Task
# ============================================================================


class TestCancelTask:
    """Test POST /api/control-plane/tasks/:id/cancel."""

    def test_cancel_success(self):
        coordinator = MagicMock()
        coordinator.cancel_task = AsyncMock(return_value=True)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_cancel_task("task_001", MagicMock())
        assert result.status_code == 200
        assert _body(result)["cancelled"] is True

    def test_cancel_not_found(self):
        coordinator = MagicMock()
        coordinator.cancel_task = AsyncMock(return_value=False)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_cancel_task("nonexistent", MagicMock())
        assert result.status_code == 404


# ============================================================================
# Queue Metrics
# ============================================================================


class TestQueueMetrics:
    """Test GET /api/control-plane/queue/metrics."""

    def test_metrics_success(self):
        coordinator = MagicMock()
        coordinator.get_stats = AsyncMock(
            return_value={
                "tasks": {
                    "pending": 5,
                    "running": 2,
                    "completed": 100,
                    "failed": 3,
                }
            }
        )
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_queue_metrics()
        assert result.status_code == 200
        body = _body(result)
        assert "pending" in body
        assert "running" in body

    def test_metrics_coordinator_unavailable(self):
        handler = TestableTaskHandler(coordinator=None)
        result = handler._handle_queue_metrics()
        assert result.status_code == 200
        # Should return zeros as fallback
        body = _body(result)
        assert body["pending"] == 0


# ============================================================================
# Get Queue
# ============================================================================


class TestGetQueue:
    """Test GET /api/control-plane/queue."""

    def test_queue_empty(self):
        coordinator = MagicMock()
        coordinator._scheduler = MagicMock()
        coordinator._scheduler.list_by_status = AsyncMock(return_value=[])
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_get_queue({})
        assert result.status_code == 200
        body = _body(result)
        assert body["jobs"] == []
        assert body["total"] == 0

    def test_queue_with_tasks(self):
        task = MockTask(id="task_q1", task_type="analysis", status=_EnumLike("pending"))
        coordinator = MagicMock()
        coordinator._scheduler = MagicMock()
        coordinator._scheduler.list_by_status = AsyncMock(return_value=[task])
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_get_queue({"limit": "10"})
        assert result.status_code == 200
        body = _body(result)
        assert len(body["jobs"]) >= 1

    def test_queue_coordinator_unavailable(self):
        handler = TestableTaskHandler(coordinator=None)
        result = handler._handle_get_queue({})
        assert result.status_code == 503


# ============================================================================
# Task History
# ============================================================================


class TestTaskHistory:
    """Test GET /api/control-plane/tasks/history."""

    def test_history_empty(self):
        coordinator = MagicMock()
        coordinator._scheduler = MagicMock()
        coordinator._scheduler.list_by_status = AsyncMock(return_value=[])
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_task_history({})
        assert result.status_code == 200
        body = _body(result)
        assert body["history"] == []
        assert body["total"] == 0

    def test_history_coordinator_unavailable(self):
        handler = TestableTaskHandler(coordinator=None)
        result = handler._handle_task_history({})
        assert result.status_code == 503

    def test_history_pagination(self):
        tasks = [MockTask(id=f"task_{i}") for i in range(5)]
        coordinator = MagicMock()
        coordinator._scheduler = MagicMock()
        coordinator._scheduler.list_by_status = AsyncMock(return_value=tasks)
        handler = TestableTaskHandler(coordinator=coordinator)

        result = handler._handle_task_history({"limit": "2", "offset": "0"})
        assert result.status_code == 200
        body = _body(result)
        assert "has_more" in body


# ============================================================================
# Deliberation
# ============================================================================


class TestDeliberation:
    """Test deliberation endpoints."""

    def test_get_deliberation_not_found(self):
        handler = TestableTaskHandler(coordinator=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "aragora.core.decision_results": MagicMock(
                    get_decision_result_for_org=MagicMock(return_value=None),
                ),
            },
        ):
            result = handler._handle_get_deliberation("req_nonexistent", MagicMock(), SCOPE)
            assert result.status_code == 404

    def test_get_deliberation_status(self):
        handler = TestableTaskHandler(coordinator=MagicMock())

        mock_status = {"status": "completed", "progress": 100}
        with patch.dict(
            "sys.modules",
            {
                "aragora.core.decision_results": MagicMock(
                    get_decision_status_for_org=MagicMock(return_value=mock_status),
                ),
            },
        ):
            result = handler._handle_get_deliberation_status("req_001", MagicMock(), SCOPE)
            assert result.status_code == 200
