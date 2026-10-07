"""Comprehensive tests for control plane task management handlers.

Tests the TaskHandlerMixin endpoints:
- GET  /api/control-plane/tasks/{task_id}
- POST /api/control-plane/tasks (submit)
- POST /api/control-plane/tasks/claim
- POST /api/control-plane/tasks/{task_id}/complete
- POST /api/control-plane/tasks/{task_id}/fail
- POST /api/control-plane/tasks/{task_id}/cancel
- GET  /api/control-plane/queue
- GET  /api/control-plane/queue/metrics
- GET  /api/control-plane/tasks/history
- GET  /api/control-plane/deliberations/{request_id}
- GET  /api/control-plane/deliberations/{request_id}/status
- POST /api/control-plane/deliberations
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.control_plane import ControlPlaneHandler
from aragora.tenancy.record_scope import OrgScope


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
# Mock Domain Objects
# ============================================================================


class MockTaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class MockTaskPriority(Enum):
    LOW = 0
    NORMAL = 50
    HIGH = 75
    URGENT = 100


@dataclass
class MockTask:
    """Mocked task object returned by the coordinator."""

    id: str
    task_type: str
    status: MockTaskStatus = MockTaskStatus.PENDING
    priority: MockTaskPriority = MockTaskPriority.NORMAL
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    assigned_agent: str | None = None
    result: Any = None
    error: str | None = None
    retries: int = 0
    created_at: float | None = None
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "status": self.status.value,
            "priority": self.priority.name.lower(),
            "payload": self.payload,
            "metadata": self.metadata,
            "assigned_agent": self.assigned_agent,
            "result": self.result,
            "error": self.error,
            "retries": self.retries,
        }


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator with standard async methods."""
    coord = MagicMock()
    coord.get_task = AsyncMock(return_value=None)
    coord.submit_task = AsyncMock(return_value="task-001")
    coord.claim_task = AsyncMock(return_value=None)
    coord.complete_task = AsyncMock(return_value=True)
    coord.fail_task = AsyncMock(return_value=True)
    coord.cancel_task = AsyncMock(return_value=True)
    coord.get_stats = AsyncMock(
        return_value={
            "pending_tasks": 5,
            "running_tasks": 2,
            "completed_tasks": 100,
            "failed_tasks": 3,
            "avg_wait_time_ms": 150,
            "avg_execution_time_ms": 500,
            "throughput_per_minute": 10,
        }
    )

    scheduler = MagicMock()
    scheduler.list_by_status = AsyncMock(return_value=[])
    coord._scheduler = scheduler

    return coord


@pytest.fixture
def handler(mock_coordinator):
    """Create a ControlPlaneHandler with a mock coordinator in context."""
    ctx: dict[str, Any] = {
        "control_plane_coordinator": mock_coordinator,
    }
    return ControlPlaneHandler(ctx)


@pytest.fixture
def handler_no_coord():
    """Create a ControlPlaneHandler with NO coordinator (not initialized)."""
    ctx: dict[str, Any] = {}
    return ControlPlaneHandler(ctx)


@pytest.fixture
def mock_http_handler():
    """Create a minimal mock HTTP handler."""
    m = MagicMock()
    m.path = "/api/control-plane/tasks"
    m.headers = {"Content-Type": "application/json"}
    return m


@pytest.fixture
def sample_task():
    """Create a representative task object."""
    return MockTask(
        id="task-001",
        task_type="analysis",
        status=MockTaskStatus.PENDING,
        priority=MockTaskPriority.NORMAL,
        payload={"document_count": 5},
        metadata={"name": "Test analysis task"},
        created_at=time.time(),
    )


@pytest.fixture
def running_task():
    """Create a running task."""
    return MockTask(
        id="task-002",
        task_type="deliberation",
        status=MockTaskStatus.RUNNING,
        priority=MockTaskPriority.HIGH,
        payload={"document_count": 3},
        metadata={"name": "Running deliberation", "progress": 0.75},
        assigned_agent="agent-A",
        created_at=time.time() - 60,
        started_at=time.time() - 30,
    )


@pytest.fixture
def completed_task():
    """Create a completed task."""
    now = time.time()
    return MockTask(
        id="task-003",
        task_type="review",
        status=MockTaskStatus.COMPLETED,
        priority=MockTaskPriority.NORMAL,
        payload={},
        metadata={"name": "Review task", "workspace_id": "ws-1"},
        assigned_agent="agent-B",
        result={"summary": "all good"},
        retries=0,
        created_at=now - 120,
        started_at=now - 60,
        completed_at=now,
    )


@pytest.fixture
def failed_task():
    """Create a failed task."""
    now = time.time()
    return MockTask(
        id="task-004",
        task_type="indexing",
        status=MockTaskStatus.FAILED,
        priority=MockTaskPriority.LOW,
        payload={},
        metadata={"name": "Failed indexing"},
        assigned_agent="agent-C",
        error="timeout exceeded",
        retries=3,
        created_at=now - 300,
        started_at=now - 240,
        completed_at=now - 180,
    )


# ============================================================================
# GET /api/control-plane/tasks/{task_id}
# ============================================================================


class TestGetTask:
    """Tests for _handle_get_task."""

    def test_get_task_success(self, handler, mock_coordinator, sample_task):
        mock_coordinator.get_task = AsyncMock(return_value=sample_task)
        result = handler._handle_get_task("task-001")
        assert _status(result) == 200
        body = _body(result)
        assert body["id"] == "task-001"
        assert body["task_type"] == "analysis"

    def test_get_task_not_found(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(return_value=None)
        result = handler._handle_get_task("nonexistent")
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_get_task_no_coordinator(self, handler_no_coord):
        result = handler_no_coord._handle_get_task("task-001")
        assert _status(result) == 503

    def test_get_task_value_error(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(side_effect=ValueError("bad id"))
        result = handler._handle_get_task("bad-id")
        assert _status(result) == 400

    def test_get_task_key_error(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(side_effect=KeyError("missing"))
        result = handler._handle_get_task("missing-key")
        assert _status(result) == 400

    def test_get_task_attribute_error(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(side_effect=AttributeError("no attr"))
        result = handler._handle_get_task("attr-err")
        assert _status(result) == 400

    def test_get_task_runtime_error(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(side_effect=RuntimeError("boom"))
        result = handler._handle_get_task("runtime-err")
        assert _status(result) == 500

    def test_get_task_os_error(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(side_effect=OSError("disk failure"))
        result = handler._handle_get_task("os-err")
        assert _status(result) == 500

    def test_get_task_type_error(self, handler, mock_coordinator):
        mock_coordinator.get_task = AsyncMock(side_effect=TypeError("wrong type"))
        result = handler._handle_get_task("type-err")
        assert _status(result) == 500

    def test_get_task_to_dict_called(self, handler, mock_coordinator, sample_task):
        """Verify task.to_dict() is called for serialization."""
        mock_task = MagicMock()
        mock_task.to_dict.return_value = {"id": "task-x", "task_type": "test"}
        mock_coordinator.get_task = AsyncMock(return_value=mock_task)
        result = handler._handle_get_task("task-x")
        assert _status(result) == 200
        mock_task.to_dict.assert_called_once()


# ============================================================================
# POST /api/control-plane/tasks (submit)
# ============================================================================


class TestSubmitTask:
    """Tests for _handle_submit_task."""

    def test_submit_task_success(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "payload": {"doc": "data"}, "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async", return_value="task-001"
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 201
        assert _body(result)["task_id"] == "task-001"

    def test_submit_task_missing_task_type(self, handler, mock_http_handler):
        body = {"payload": {}}
        result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 400
        assert "task_type" in _body(result).get("error", "").lower()

    def test_submit_task_empty_task_type(self, handler, mock_http_handler):
        body = {"task_type": ""}
        result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 400

    def test_submit_task_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"task_type": "analysis"}
        result = handler_no_coord._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 503

    def test_submit_task_invalid_priority(self, handler, mock_http_handler):
        body = {"task_type": "analysis", "priority": "invalid_priority"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 400
        assert "priority" in _body(result).get("error", "").lower()

    def test_submit_task_default_priority(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async", return_value="task-002"
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 201

    def test_submit_task_with_capabilities(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "required_capabilities": ["reasoning", "search"]}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async", return_value="task-cap"
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 201

    def test_submit_task_with_metadata(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "metadata": {"user_id": "u1", "tags": ["urgent"]}}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async", return_value="task-meta"
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 201

    def test_submit_task_with_timeout(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "timeout_seconds": 300}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async", return_value="task-to"
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 201

    def test_submit_task_runtime_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async",
                side_effect=RuntimeError("connection refused"),
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 500

    def test_submit_task_emits_event(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async", return_value="task-evt"
            ):
                with patch.object(handler, "_emit_event") as mock_emit:
                    result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 201
        mock_emit.assert_called_once_with(
            "emit_task_submitted",
            task_id="task-evt",
            task_type="analysis",
            priority="normal",
            required_capabilities=[],
        )


# ============================================================================
# POST /api/control-plane/tasks (submit) - async variant
# ============================================================================


class TestSubmitTaskAsync:
    """Tests for _handle_submit_task_async."""

    @pytest.mark.asyncio
    async def test_submit_task_async_success(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.submit_task = AsyncMock(return_value="task-async-001")
        body = {"task_type": "analysis", "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            result = await handler._handle_submit_task_async(body, mock_http_handler)
        assert _status(result) == 201
        assert _body(result)["task_id"] == "task-async-001"

    @pytest.mark.asyncio
    async def test_submit_task_async_missing_task_type(self, handler, mock_http_handler):
        body = {"payload": {}}
        result = await handler._handle_submit_task_async(body, mock_http_handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_submit_task_async_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"task_type": "analysis"}
        result = await handler_no_coord._handle_submit_task_async(body, mock_http_handler)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_submit_task_async_invalid_priority(self, handler, mock_http_handler):
        body = {"task_type": "analysis", "priority": "mega"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            result = await handler._handle_submit_task_async(body, mock_http_handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_submit_task_async_runtime_error(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_coordinator.submit_task = AsyncMock(side_effect=RuntimeError("fail"))
        body = {"task_type": "analysis", "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            result = await handler._handle_submit_task_async(body, mock_http_handler)
        assert _status(result) == 500

    @pytest.mark.asyncio
    async def test_submit_task_async_emits_event(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_coordinator.submit_task = AsyncMock(return_value="task-ae")
        body = {
            "task_type": "deliberation",
            "priority": "high",
            "required_capabilities": ["reasoning"],
        }
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch.object(handler, "_emit_event") as mock_emit:
                result = await handler._handle_submit_task_async(body, mock_http_handler)
        assert _status(result) == 201
        mock_emit.assert_called_once()


# ============================================================================
# POST /api/control-plane/tasks/claim
# ============================================================================


class TestClaimTask:
    """Tests for _handle_claim_task."""

    def test_claim_task_success(self, handler, mock_coordinator, mock_http_handler, sample_task):
        sample_task.status = MockTaskStatus.RUNNING
        sample_task.assigned_agent = "agent-A"
        mock_coordinator.claim_task = AsyncMock(return_value=sample_task)
        body = {"agent_id": "agent-A", "capabilities": ["reasoning"]}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async", return_value=sample_task
        ):
            result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 200
        data = _body(result)
        assert data["task"] is not None
        assert data["task"]["id"] == "task-001"

    def test_claim_task_no_task_available(self, handler, mock_coordinator, mock_http_handler):
        body = {"agent_id": "agent-A", "capabilities": ["reasoning"]}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=None):
            result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["task"] is None

    def test_claim_task_missing_agent_id(self, handler, mock_http_handler):
        body = {"capabilities": ["reasoning"]}
        result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 400
        assert "agent_id" in _body(result).get("error", "").lower()

    def test_claim_task_empty_agent_id(self, handler, mock_http_handler):
        body = {"agent_id": "", "capabilities": []}
        result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 400

    def test_claim_task_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"agent_id": "agent-A"}
        result = handler_no_coord._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 503

    def test_claim_task_default_capabilities(self, handler, mock_coordinator, mock_http_handler):
        body = {"agent_id": "agent-A"}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=None):
            result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 200

    def test_claim_task_custom_block_ms(self, handler, mock_coordinator, mock_http_handler):
        body = {"agent_id": "agent-A", "block_ms": 10000}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=None):
            result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 200

    def test_claim_task_runtime_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"agent_id": "agent-A"}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=RuntimeError("scheduler down"),
        ):
            result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 500

    def test_claim_task_emits_event(
        self, handler, mock_coordinator, mock_http_handler, sample_task
    ):
        sample_task.status = MockTaskStatus.RUNNING
        body = {"agent_id": "agent-A"}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async", return_value=sample_task
        ):
            with patch.object(handler, "_emit_event") as mock_emit:
                result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 200
        mock_emit.assert_called_once_with(
            "emit_task_claimed",
            task_id="task-001",
            agent_id="agent-A",
        )


# ============================================================================
# POST /api/control-plane/tasks/claim (async variant)
# ============================================================================


class TestClaimTaskAsync:
    """Tests for _handle_claim_task_async."""

    @pytest.mark.asyncio
    async def test_claim_task_async_success(
        self, handler, mock_coordinator, mock_http_handler, sample_task
    ):
        mock_coordinator.claim_task = AsyncMock(return_value=sample_task)
        body = {"agent_id": "agent-A", "capabilities": ["reasoning"]}
        result = await handler._handle_claim_task_async(body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["task"]["id"] == "task-001"

    @pytest.mark.asyncio
    async def test_claim_task_async_no_task(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.claim_task = AsyncMock(return_value=None)
        body = {"agent_id": "agent-A"}
        result = await handler._handle_claim_task_async(body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["task"] is None

    @pytest.mark.asyncio
    async def test_claim_task_async_missing_agent_id(self, handler, mock_http_handler):
        body = {}
        result = await handler._handle_claim_task_async(body, mock_http_handler)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_claim_task_async_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"agent_id": "agent-A"}
        result = await handler_no_coord._handle_claim_task_async(body, mock_http_handler)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_claim_task_async_error(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.claim_task = AsyncMock(side_effect=OSError("network"))
        body = {"agent_id": "agent-A"}
        result = await handler._handle_claim_task_async(body, mock_http_handler)
        assert _status(result) == 500


# ============================================================================
# POST /api/control-plane/tasks/{task_id}/complete
# ============================================================================


class TestCompleteTask:
    """Tests for _handle_complete_task."""

    def test_complete_task_success(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {"summary": "done"}, "agent_id": "agent-A", "latency_ms": 450}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["completed"] is True

    def test_complete_task_not_found(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {}}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=False):
            result = handler._handle_complete_task("nonexistent", body, mock_http_handler)
        assert _status(result) == 404

    def test_complete_task_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"result": {}}
        result = handler_no_coord._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 503

    def test_complete_task_no_result(self, handler, mock_coordinator, mock_http_handler):
        body = {}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 200

    def test_complete_task_no_agent_id(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {"data": "x"}}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            with patch.object(handler, "_emit_event") as mock_emit:
                result = handler._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 200
        # agent_id defaults to "unknown" in emit
        mock_emit.assert_called_once_with(
            "emit_task_completed",
            task_id="task-001",
            agent_id="unknown",
            result={"data": "x"},
        )

    def test_complete_task_runtime_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {}}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=RuntimeError("crash"),
        ):
            result = handler._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 500

    def test_complete_task_emits_event(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {"ok": True}, "agent_id": "agent-B"}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            with patch.object(handler, "_emit_event") as mock_emit:
                result = handler._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 200
        mock_emit.assert_called_once_with(
            "emit_task_completed",
            task_id="task-001",
            agent_id="agent-B",
            result={"ok": True},
        )


# ============================================================================
# POST /api/control-plane/tasks/{task_id}/complete (async variant)
# ============================================================================


class TestCompleteTaskAsync:
    """Tests for _handle_complete_task_async."""

    @pytest.mark.asyncio
    async def test_complete_task_async_success(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.complete_task = AsyncMock(return_value=True)
        body = {"result": {"ok": True}, "agent_id": "agent-A"}
        result = await handler._handle_complete_task_async("task-001", body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["completed"] is True

    @pytest.mark.asyncio
    async def test_complete_task_async_not_found(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_coordinator.complete_task = AsyncMock(return_value=False)
        body = {"result": {}}
        result = await handler._handle_complete_task_async("task-gone", body, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_complete_task_async_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"result": {}}
        result = await handler_no_coord._handle_complete_task_async(
            "task-001", body, mock_http_handler
        )
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_complete_task_async_error(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.complete_task = AsyncMock(side_effect=TypeError("wrong arg"))
        body = {"result": {}}
        result = await handler._handle_complete_task_async("task-001", body, mock_http_handler)
        assert _status(result) == 500


# ============================================================================
# POST /api/control-plane/tasks/{task_id}/fail
# ============================================================================


class TestFailTask:
    """Tests for _handle_fail_task."""

    def test_fail_task_success(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "out of memory", "agent_id": "agent-A", "latency_ms": 1200}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["failed"] is True

    def test_fail_task_not_found(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "timeout"}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=False):
            result = handler._handle_fail_task("nonexistent", body, mock_http_handler)
        assert _status(result) == 404

    def test_fail_task_default_error(self, handler, mock_coordinator, mock_http_handler):
        body = {}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 200

    def test_fail_task_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"error": "some error"}
        result = handler_no_coord._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 503

    def test_fail_task_requeue_true(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "retry me", "requeue": True}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 200

    def test_fail_task_requeue_false(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "permanent failure", "requeue": False}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 200

    def test_fail_task_runtime_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "bad"}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=ValueError("invalid state"),
        ):
            result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 500

    def test_fail_task_emits_event(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "timeout", "agent_id": "agent-X"}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            with patch.object(handler, "_emit_event") as mock_emit:
                result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 200
        mock_emit.assert_called_once_with(
            "emit_task_failed",
            task_id="task-001",
            agent_id="agent-X",
            error="timeout",
            retries_left=0,
        )

    def test_fail_task_no_agent_id_uses_unknown(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "crash"}
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            with patch.object(handler, "_emit_event") as mock_emit:
                result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 200
        mock_emit.assert_called_once_with(
            "emit_task_failed",
            task_id="task-001",
            agent_id="unknown",
            error="crash",
            retries_left=0,
        )


# ============================================================================
# POST /api/control-plane/tasks/{task_id}/fail (async variant)
# ============================================================================


class TestFailTaskAsync:
    """Tests for _handle_fail_task_async."""

    @pytest.mark.asyncio
    async def test_fail_task_async_success(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.fail_task = AsyncMock(return_value=True)
        body = {"error": "overload", "agent_id": "agent-A"}
        result = await handler._handle_fail_task_async("task-001", body, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["failed"] is True

    @pytest.mark.asyncio
    async def test_fail_task_async_not_found(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.fail_task = AsyncMock(return_value=False)
        body = {"error": "missing"}
        result = await handler._handle_fail_task_async("gone", body, mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_fail_task_async_no_coordinator(self, handler_no_coord, mock_http_handler):
        body = {"error": "err"}
        result = await handler_no_coord._handle_fail_task_async("task-001", body, mock_http_handler)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_fail_task_async_error(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.fail_task = AsyncMock(side_effect=KeyError("no key"))
        body = {"error": "err"}
        result = await handler._handle_fail_task_async("task-001", body, mock_http_handler)
        assert _status(result) == 500


# ============================================================================
# POST /api/control-plane/tasks/{task_id}/cancel
# ============================================================================


class TestCancelTask:
    """Tests for _handle_cancel_task."""

    def test_cancel_task_success(self, handler, mock_coordinator, mock_http_handler):
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=True):
            result = handler._handle_cancel_task("task-001", mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["cancelled"] is True

    def test_cancel_task_not_found(self, handler, mock_coordinator, mock_http_handler):
        with patch("aragora.server.handlers.control_plane.tasks._run_async", return_value=False):
            result = handler._handle_cancel_task("nonexistent", mock_http_handler)
        assert _status(result) == 404
        assert "not found" in _body(result).get("error", "").lower()

    def test_cancel_task_no_coordinator(self, handler_no_coord, mock_http_handler):
        result = handler_no_coord._handle_cancel_task("task-001", mock_http_handler)
        assert _status(result) == 503

    def test_cancel_task_runtime_error(self, handler, mock_coordinator, mock_http_handler):
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=RuntimeError("connection lost"),
        ):
            result = handler._handle_cancel_task("task-001", mock_http_handler)
        assert _status(result) == 500

    def test_cancel_task_value_error(self, handler, mock_coordinator, mock_http_handler):
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=ValueError("invalid task state"),
        ):
            result = handler._handle_cancel_task("task-001", mock_http_handler)
        assert _status(result) == 500


# ============================================================================
# POST /api/control-plane/tasks/{task_id}/cancel (async variant)
# ============================================================================


class TestCancelTaskAsync:
    """Tests for _handle_cancel_task_async."""

    @pytest.mark.asyncio
    async def test_cancel_task_async_success(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.cancel_task = AsyncMock(return_value=True)
        result = await handler._handle_cancel_task_async("task-001", mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["cancelled"] is True

    @pytest.mark.asyncio
    async def test_cancel_task_async_not_found(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.cancel_task = AsyncMock(return_value=False)
        result = await handler._handle_cancel_task_async("already-done", mock_http_handler)
        assert _status(result) == 404

    @pytest.mark.asyncio
    async def test_cancel_task_async_no_coordinator(self, handler_no_coord, mock_http_handler):
        result = await handler_no_coord._handle_cancel_task_async("task-001", mock_http_handler)
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_cancel_task_async_error(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.cancel_task = AsyncMock(side_effect=OSError("disk"))
        result = await handler._handle_cancel_task_async("task-001", mock_http_handler)
        assert _status(result) == 500


# ============================================================================
# GET /api/control-plane/queue
# ============================================================================


class TestGetQueue:
    """Tests for _handle_get_queue."""

    def test_get_queue_empty(self, handler, mock_coordinator):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        assert _status(result) == 200
        data = _body(result)
        assert data["jobs"] == []
        assert data["total"] == 0

    def test_get_queue_with_running_tasks(self, handler, mock_coordinator, running_task):
        def _list_by_status(status, limit=50):
            if status.value == "running":
                return [running_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        assert _status(result) == 200
        data = _body(result)
        assert data["total"] == 1
        job = data["jobs"][0]
        assert job["id"] == "task-002"
        assert job["status"] == "running"
        assert job["progress"] == 0.75

    def test_get_queue_with_pending_tasks(self, handler, mock_coordinator, sample_task):
        def _list_by_status(status, limit=50):
            if status.value == "pending":
                return [sample_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        assert _status(result) == 200
        data = _body(result)
        assert data["total"] == 1
        job = data["jobs"][0]
        assert job["status"] == "pending"
        assert job["progress"] == 0.0

    def test_get_queue_running_before_pending(
        self, handler, mock_coordinator, running_task, sample_task
    ):
        """Running jobs should appear before pending jobs."""

        def _list_by_status(status, limit=50):
            if status.value == "running":
                return [running_task]
            elif status.value == "pending":
                return [sample_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        data = _body(result)
        assert data["total"] == 2
        assert data["jobs"][0]["status"] == "running"
        assert data["jobs"][1]["status"] == "pending"

    def test_get_queue_with_limit(self, handler, mock_coordinator):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({"limit": "10"})
        assert _status(result) == 200

    def test_get_queue_no_coordinator(self, handler_no_coord):
        result = handler_no_coord._handle_get_queue({})
        assert _status(result) == 503

    def test_get_queue_scheduler_error(self, handler, mock_coordinator):
        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=RuntimeError("db down"))
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        assert _status(result) == 500

    def test_get_queue_task_without_started_at(self, handler, mock_coordinator):
        """Task without started_at should have null in response."""
        task = MockTask(
            id="t1",
            task_type="test",
            status=MockTaskStatus.PENDING,
            payload={},
            metadata={},
            created_at=time.time(),
        )
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[])

        def _list_by_status(status, limit=50):
            if status.value == "pending":
                return [task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        data = _body(result)
        job = data["jobs"][0]
        assert job["started_at"] is None
        assert job["created_at"] is not None

    def test_get_queue_task_with_assigned_agent(self, handler, mock_coordinator, running_task):
        def _list_by_status(status, limit=50):
            if status.value == "running":
                return [running_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        data = _body(result)
        assert data["jobs"][0]["agents_assigned"] == ["agent-A"]

    def test_get_queue_task_without_assigned_agent(self, handler, mock_coordinator, sample_task):
        def _list_by_status(status, limit=50):
            if status.value == "pending":
                return [sample_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        data = _body(result)
        assert data["jobs"][0]["agents_assigned"] == []


# ============================================================================
# GET /api/control-plane/queue/metrics
# ============================================================================


class TestQueueMetrics:
    """Tests for _handle_queue_metrics."""

    def test_queue_metrics_with_coordinator(self, handler, mock_coordinator):
        result = handler._handle_queue_metrics()
        assert _status(result) == 200
        data = _body(result)
        assert data["pending"] == 5
        assert data["running"] == 2
        assert data["completed_today"] == 100
        assert data["failed_today"] == 3
        assert data["avg_wait_time_ms"] == 150
        assert data["avg_execution_time_ms"] == 500
        assert data["throughput_per_minute"] == 10

    def test_queue_metrics_no_coordinator(self, handler_no_coord):
        result = handler_no_coord._handle_queue_metrics()
        assert _status(result) == 200
        data = _body(result)
        assert data["pending"] == 0
        assert data["running"] == 0
        assert data["completed_today"] == 0
        assert data["failed_today"] == 0

    def test_queue_metrics_no_scheduler(self, handler):
        """Coordinator exists but has no _scheduler attribute."""
        coord = MagicMock(spec=[])  # No attributes
        handler.ctx["control_plane_coordinator"] = coord
        result = handler._handle_queue_metrics()
        assert _status(result) == 200
        data = _body(result)
        assert data["pending"] == 0

    def test_queue_metrics_error(self, handler, mock_coordinator):
        mock_coordinator.get_stats = AsyncMock(side_effect=RuntimeError("stats unavailable"))
        result = handler._handle_queue_metrics()
        assert _status(result) == 500


# ============================================================================
# GET /api/control-plane/tasks/history
# ============================================================================


class TestTaskHistory:
    """Tests for _handle_task_history.

    Note: safe_query_int clamps offset to min_val=1, so when no offset is
    provided, offset=1. Tests that need to access history entries must ensure
    total > 1 by returning tasks from multiple status queries, or by returning
    multiple tasks from a single query.
    """

    @pytest.fixture(autouse=True)
    def _ensure_auth_bypass(self, monkeypatch):
        """Ensure @require_permission decorator is bypassed for task history tests.

        _handle_task_history takes only (self, query_params) with no HTTP handler
        argument. The @require_permission decorator scans args for an object with
        a ``headers`` attribute; since ControlPlaneHandler lacks one, the decorator
        falls back to ``_test_user_context_override``. When test ordering causes
        the conftest autouse fixture to not yet be active or to be torn down, the
        override can be None, resulting in a spurious 401. This fixture adds a
        direct patch as a safety net.
        """
        from aragora.server.handlers.utils import decorators as _dec

        mock_ctx = MagicMock()
        mock_ctx.role = "admin"
        mock_ctx.user_id = "test-user"
        mock_ctx.is_authenticated = True
        monkeypatch.setattr(_dec, "_test_user_context_override", mock_ctx)
        monkeypatch.setattr(_dec, "has_permission", lambda role, perm: True)

    def test_task_history_empty(self, handler, mock_coordinator):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        assert _status(result) == 200
        data = _body(result)
        assert data["history"] == []
        assert data["total"] == 0
        assert data["has_more"] is False

    def test_task_history_with_completed_task(self, handler, mock_coordinator, completed_task):
        # Return task for all status queries so total=4 (offset=1 gives 3 entries)
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        assert _status(result) == 200
        data = _body(result)
        assert data["total"] >= 1
        # offset=1 due to safe_query_int min_val clamp; with 4 copies total we get entries
        assert len(data["history"]) >= 1
        entry = data["history"][0]
        assert entry["id"] == "task-003"
        assert entry["status"] == "completed"
        assert entry["result"] == {"summary": "all good"}
        assert entry["error"] is None
        assert entry["duration_ms"] is not None

    def test_task_history_with_failed_task(self, handler, mock_coordinator, failed_task):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[failed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        data = _body(result)
        assert len(data["history"]) >= 1
        entry = data["history"][0]
        assert entry["status"] == "failed"
        assert entry["error"] == "timeout exceeded"
        assert entry["result"] is None

    def test_task_history_status_filter_total(self, handler, mock_coordinator, completed_task):
        """Status filter narrows query to one status; verify total count."""
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"status": "completed"})
        data = _body(result)
        # Only completed status queried, returns 1 task
        assert data["total"] == 1

    def test_task_history_task_type_filter(self, handler, mock_coordinator, completed_task):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"task_type": "review"})
        data = _body(result)
        assert data["total"] >= 1

    def test_task_history_task_type_filter_no_match(
        self, handler, mock_coordinator, completed_task
    ):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"task_type": "nonexistent"})
        data = _body(result)
        assert data["total"] == 0

    def test_task_history_agent_id_filter(self, handler, mock_coordinator, completed_task):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"agent_id": "agent-B"})
        data = _body(result)
        assert data["total"] >= 1

    def test_task_history_agent_id_filter_no_match(self, handler, mock_coordinator, completed_task):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"agent_id": "agent-NOBODY"})
        data = _body(result)
        assert data["total"] == 0

    def test_task_history_pagination_offset(
        self, handler, mock_coordinator, completed_task, failed_task
    ):
        def _list_by_status(status, limit=100):
            if status.value == "completed":
                return [completed_task]
            if status.value == "failed":
                return [failed_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"offset": "1", "limit": "1"})
        data = _body(result)
        assert data["total"] == 2
        assert len(data["history"]) == 1
        assert data["has_more"] is False

    def test_task_history_pagination_has_more(
        self, handler, mock_coordinator, completed_task, failed_task
    ):
        """With 3+ tasks, offset=1 and limit=1 should show has_more=True."""
        now = time.time()
        cancelled_task = MockTask(
            id="task-cancelled",
            task_type="x",
            status=MockTaskStatus.CANCELLED,
            payload={},
            metadata={},
            created_at=now - 10,
            completed_at=now - 5,
        )

        def _list_by_status(status, limit=100):
            if status.value == "completed":
                return [completed_task]
            if status.value == "failed":
                return [failed_task]
            if status.value == "cancelled":
                return [cancelled_task]
            return []

        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=_list_by_status)
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"offset": "1", "limit": "1"})
        data = _body(result)
        assert data["total"] == 3
        assert len(data["history"]) == 1
        assert data["has_more"] is True

    def test_task_history_no_coordinator(self, handler_no_coord):
        result = handler_no_coord._handle_task_history({})
        assert _status(result) == 503

    def test_task_history_error(self, handler, mock_coordinator):
        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=RuntimeError("db error"))
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        assert _status(result) == 500

    def test_task_history_metadata_filtering(self, handler, mock_coordinator, completed_task):
        """Only name, workspace_id, user_id, tags are included from metadata."""
        completed_task.metadata = {
            "name": "test",
            "workspace_id": "ws-1",
            "user_id": "u-1",
            "tags": ["important"],
            "internal_secret": "should_be_excluded",
        }

        # Return the task for all 4 status queries; offset defaults to min_val=1
        # so total=4 gives paginated = all_tasks[1:101] = 3 entries
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        assert _status(result) == 200
        data = _body(result)
        assert len(data["history"]) >= 1
        entry_meta = data["history"][0]["metadata"]
        assert "name" in entry_meta
        assert "workspace_id" in entry_meta
        assert "user_id" in entry_meta
        assert "tags" in entry_meta
        assert "internal_secret" not in entry_meta

    def test_task_history_duration_ms_calculation(self, handler, mock_coordinator):
        """Duration should be (completed_at - started_at) * 1000."""
        now = time.time()
        task = MockTask(
            id="t-dur",
            task_type="compute",
            status=MockTaskStatus.COMPLETED,
            payload={},
            metadata={},
            assigned_agent="agent-D",
            result="ok",
            created_at=now - 100,
            started_at=now - 50,
            completed_at=now,
        )

        # Return for all 4 statuses so total=4, offset=1 gives 3 entries
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        data = _body(result)
        assert len(data["history"]) >= 1
        assert data["history"][0]["duration_ms"] == 50000

    def test_task_history_no_duration_when_no_started_at(self, handler, mock_coordinator):
        """Duration should be None if started_at is missing."""
        task = MockTask(
            id="t-nod",
            task_type="cancelled",
            status=MockTaskStatus.CANCELLED,
            payload={},
            metadata={},
            created_at=time.time(),
            completed_at=time.time(),
        )

        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({})
        data = _body(result)
        assert len(data["history"]) >= 1
        assert data["history"][0]["duration_ms"] is None

    def test_task_history_invalid_status_filter_returns_all(
        self, handler, mock_coordinator, completed_task
    ):
        """Unknown status filter should still query all history statuses."""
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[completed_task])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_task_history({"status": "unknown_status"})
        data = _body(result)
        # Unknown status doesn't match any known filter, so queries all 4 statuses
        assert data["total"] >= 1


# ============================================================================
# GET /api/control-plane/deliberations/{request_id}
# ============================================================================


SCOPE = OrgScope(org_id="test-org-001", user_id="test-user-001", role="admin")
NOT_FOUND_BODY = {"error": "Deliberation not found", "code": "not_found"}
SCOPE_OWNER = {"org_id": SCOPE.org_id, "created_by": SCOPE.user_id}


class TestGetDeliberation:
    """Tests for _handle_get_deliberation."""

    def test_get_deliberation_found(self, handler, mock_http_handler):
        mock_result = {"request_id": "req-001", "status": "completed", "answer": "yes"}
        with patch(
            "aragora.core.decision_results.get_decision_result_for_org",
            return_value=mock_result,
        ) as mock_get:
            result = handler._handle_get_deliberation("req-001", mock_http_handler, SCOPE)
        assert _status(result) == 200
        assert _body(result)["request_id"] == "req-001"
        mock_get.assert_called_once_with("req-001", "test-org-001")

    def test_get_deliberation_not_found(self, handler, mock_http_handler):
        with patch(
            "aragora.core.decision_results.get_decision_result_for_org",
            return_value=None,
        ):
            result = handler._handle_get_deliberation("nonexistent", mock_http_handler, SCOPE)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY

    def test_get_deliberation_pending_result(self, handler, mock_http_handler):
        with patch(
            "aragora.core.decision_results.get_decision_result_for_org",
            return_value={"status": "pending"},
        ):
            result = handler._handle_get_deliberation("req-002", mock_http_handler, SCOPE)
        assert _status(result) == 200


# ============================================================================
# GET /api/control-plane/deliberations/{request_id}/status
# ============================================================================


class TestGetDeliberationStatus:
    """Tests for _handle_get_deliberation_status."""

    def test_get_deliberation_status_success(self, handler, mock_http_handler):
        mock_status = {"request_id": "req-001", "status": "running", "completed_at": None}
        with patch(
            "aragora.core.decision_results.get_decision_status_for_org",
            return_value=mock_status,
        ) as mock_get:
            result = handler._handle_get_deliberation_status("req-001", mock_http_handler, SCOPE)
        assert _status(result) == 200
        assert _body(result)["status"] == "running"
        mock_get.assert_called_once_with("req-001", "test-org-001")

    def test_get_deliberation_status_completed(self, handler, mock_http_handler):
        mock_status = {"request_id": "req-001", "status": "completed"}
        with patch(
            "aragora.core.decision_results.get_decision_status_for_org",
            return_value=mock_status,
        ):
            result = handler._handle_get_deliberation_status("req-001", mock_http_handler, SCOPE)
        assert _status(result) == 200
        assert _body(result)["status"] == "completed"

    def test_get_deliberation_status_missing_is_404(self, handler, mock_http_handler):
        with patch(
            "aragora.core.decision_results.get_decision_status_for_org",
            return_value=None,
        ):
            result = handler._handle_get_deliberation_status("req-new", mock_http_handler, SCOPE)
        assert _status(result) == 404
        assert _body(result) == NOT_FOUND_BODY


# ============================================================================
# POST /api/control-plane/deliberations (submit)
# ============================================================================


class TestSubmitDeliberation:
    """Tests for _handle_submit_deliberation."""

    @pytest.mark.asyncio
    async def test_submit_deliberation_missing_content(self, handler, mock_http_handler):
        body = {"mode": "async"}
        result = await handler._handle_submit_deliberation(body, mock_http_handler, SCOPE)
        assert _status(result) == 400
        assert "content" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_submit_deliberation_no_coordinator(self, handler_no_coord, mock_http_handler):
        mock_request = MagicMock()
        mock_request.request_id = "req-001"
        mock_request.context = MagicMock(user_id="u1", workspace_id="ws1")
        mock_request.to_dict.return_value = {}

        body = {"content": "Should we deploy?", "async": True}
        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(authenticated=False)
                result = await handler_no_coord._handle_submit_deliberation(
                    body, mock_http_handler, SCOPE
                )
        assert _status(result) == 503

    @pytest.mark.asyncio
    async def test_submit_deliberation_async_success(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_request = MagicMock()
        mock_request.request_id = "req-async-001"
        mock_request.context = MagicMock(user_id="u1", workspace_id="ws1")
        mock_request.to_dict.return_value = {"content": "Should we deploy?"}

        body = {"content": "Should we deploy?", "async": True, "priority": "normal"}

        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(authenticated=False)
                with patch(
                    "aragora.server.handlers.control_plane.tasks.TaskPriority",
                    MockTaskPriority,
                    create=True,
                ):
                    with patch(
                        "aragora.server.handlers.control_plane.tasks._run_async",
                        return_value="task-delib-001",
                    ):
                        result = await handler._handle_submit_deliberation(
                            body, mock_http_handler, SCOPE
                        )
        assert _status(result) == 202
        data = _body(result)
        assert data["status"] == "queued"
        assert data["request_id"] == "req-async-001"
        assert data["task_id"] == "task-delib-001"

    @pytest.mark.asyncio
    async def test_submit_deliberation_async_mode_via_mode_field(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_request = MagicMock()
        mock_request.request_id = "req-mode"
        mock_request.context = MagicMock(user_id=None, workspace_id=None)
        mock_request.to_dict.return_value = {}

        body = {"content": "Is this viable?", "mode": "async", "priority": "high"}

        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(
                    authenticated=True, user_id="u2", org_id="org-2"
                )
                with patch(
                    "aragora.server.handlers.control_plane.tasks.TaskPriority",
                    MockTaskPriority,
                    create=True,
                ):
                    with patch(
                        "aragora.server.handlers.control_plane.tasks._run_async",
                        return_value="task-mode",
                    ):
                        result = await handler._handle_submit_deliberation(
                            body, mock_http_handler, SCOPE
                        )
        assert _status(result) == 202

    @pytest.mark.asyncio
    async def test_submit_deliberation_async_invalid_priority(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_request = MagicMock()
        mock_request.request_id = "req-bad-pri"
        mock_request.context = MagicMock(user_id="u1", workspace_id="ws1")
        mock_request.to_dict.return_value = {}

        body = {"content": "Test", "async": True, "priority": "ultra_mega"}

        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(authenticated=False)
                with patch(
                    "aragora.server.handlers.control_plane.tasks.TaskPriority",
                    MockTaskPriority,
                    create=True,
                ):
                    result = await handler._handle_submit_deliberation(
                        body, mock_http_handler, SCOPE
                    )
        assert _status(result) == 400
        assert "priority" in _body(result).get("error", "").lower()

    @pytest.mark.asyncio
    async def test_submit_deliberation_sync_success(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_request = MagicMock()
        mock_request.request_id = "req-sync"
        mock_request.context = MagicMock(user_id="u1", workspace_id="ws1")

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.decision_type = MagicMock(value="consensus")
        mock_result.answer = "Yes, proceed"
        mock_result.confidence = 0.9
        mock_result.consensus_reached = True
        mock_result.reasoning = "Agents agree"
        mock_result.evidence_used = ["doc1"]
        mock_result.duration_seconds = 5.2
        mock_result.error = None

        body = {"content": "Should we proceed?"}

        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(authenticated=False)
                with patch(
                    "aragora.control_plane.deliberation.run_deliberation",
                    new_callable=AsyncMock,
                    return_value=mock_result,
                ):
                    with patch("aragora.control_plane.deliberation.record_deliberation_error"):
                        result = await handler._handle_submit_deliberation(
                            body, mock_http_handler, SCOPE
                        )
        assert _status(result) == 200
        data = _body(result)
        assert data["status"] == "completed"
        assert data["answer"] == "Yes, proceed"
        assert data["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_submit_deliberation_sync_timeout(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_request = MagicMock()
        mock_request.request_id = "req-timeout"
        mock_request.context = MagicMock(user_id="u1", workspace_id="ws1")

        body = {"content": "Test timeout"}

        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(authenticated=False)
                with patch(
                    "aragora.control_plane.deliberation.run_deliberation",
                    new_callable=AsyncMock,
                    side_effect=asyncio.TimeoutError(),
                ):
                    with patch(
                        "aragora.control_plane.deliberation.record_deliberation_error"
                    ) as mock_record:
                        result = await handler._handle_submit_deliberation(
                            body, mock_http_handler, SCOPE
                        )
        assert _status(result) == 408
        mock_record.assert_called_once_with(
            "req-timeout", "Deliberation timed out", "timeout", **SCOPE_OWNER
        )

    @pytest.mark.asyncio
    async def test_submit_deliberation_sync_failure(
        self, handler, mock_coordinator, mock_http_handler
    ):
        mock_request = MagicMock()
        mock_request.request_id = "req-fail"
        mock_request.context = MagicMock(user_id="u1", workspace_id="ws1")

        body = {"content": "Test failure"}

        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.return_value = mock_request
            with patch("aragora.billing.auth.extract_user_from_request") as mock_extract:
                mock_extract.return_value = MagicMock(authenticated=False)
                with patch(
                    "aragora.control_plane.deliberation.run_deliberation",
                    new_callable=AsyncMock,
                    side_effect=RuntimeError("engine crash"),
                ):
                    with patch(
                        "aragora.control_plane.deliberation.record_deliberation_error"
                    ) as mock_record:
                        result = await handler._handle_submit_deliberation(
                            body, mock_http_handler, SCOPE
                        )
        assert _status(result) == 500
        mock_record.assert_called_once_with("req-fail", "Deliberation failed", **SCOPE_OWNER)

    @pytest.mark.asyncio
    async def test_submit_deliberation_parse_error(self, handler, mock_http_handler):
        body = {"content": "test"}
        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.side_effect = ValueError("bad body")
            result = await handler._handle_submit_deliberation(body, mock_http_handler, SCOPE)
        assert _status(result) == 400

    @pytest.mark.asyncio
    async def test_submit_deliberation_import_error_in_parse(self, handler, mock_http_handler):
        body = {"content": "test"}
        with patch("aragora.core.decision.DecisionRequest") as MockDR:
            MockDR.from_http.side_effect = ImportError("missing module")
            result = await handler._handle_submit_deliberation(body, mock_http_handler, SCOPE)
        assert _status(result) == 400


# ============================================================================
# Mixin Internal Methods
# ============================================================================


class TestMixinHelpers:
    """Tests for TaskHandlerMixin internal helper methods."""

    def test_get_coordinator_from_context(self, handler, mock_coordinator):
        assert handler._get_coordinator() is mock_coordinator

    def test_get_coordinator_none_when_missing(self, handler_no_coord):
        assert handler_no_coord._get_coordinator() is None

    def test_require_coordinator_success(self, handler, mock_coordinator):
        coord, err = handler._require_coordinator()
        assert coord is mock_coordinator
        assert err is None

    def test_require_coordinator_error(self, handler_no_coord):
        coord, err = handler_no_coord._require_coordinator()
        assert coord is None
        assert _status(err) == 503

    def test_handle_coordinator_error_value_error(self, handler):
        result = handler._handle_coordinator_error(ValueError("bad"), "test_op")
        assert _status(result) == 400

    def test_handle_coordinator_error_key_error(self, handler):
        result = handler._handle_coordinator_error(KeyError("missing"), "test_op")
        assert _status(result) == 400

    def test_handle_coordinator_error_attribute_error(self, handler):
        result = handler._handle_coordinator_error(AttributeError("no attr"), "test_op")
        assert _status(result) == 400

    def test_handle_coordinator_error_runtime_error(self, handler):
        result = handler._handle_coordinator_error(RuntimeError("crash"), "test_op")
        assert _status(result) == 500

    def test_handle_coordinator_error_os_error(self, handler):
        result = handler._handle_coordinator_error(OSError("disk"), "test_op")
        assert _status(result) == 500

    def test_get_stream_returns_none_when_missing(self, handler):
        assert handler._get_stream() is None

    def test_get_stream_returns_stream(self, handler):
        mock_stream = MagicMock()
        handler.ctx["control_plane_stream"] = mock_stream
        assert handler._get_stream() is mock_stream

    def test_emit_event_no_stream_is_noop(self, handler):
        # Should not raise
        handler._emit_event("emit_something", task_id="t1")


# ============================================================================
# GET /api/control-plane/tasks/{task_id} via handle() routing
# ============================================================================


class TestRouting:
    """Tests for request routing through the main handle() method."""

    def test_route_get_task(self, handler, mock_coordinator, mock_http_handler, sample_task):
        mock_coordinator.get_task = AsyncMock(return_value=sample_task)
        result = handler.handle("/api/control-plane/tasks/task-001", {}, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["id"] == "task-001"

    def test_route_get_task_v1_path(
        self, handler, mock_coordinator, mock_http_handler, sample_task
    ):
        """Versioned /api/v1/control-plane/tasks/{id} normalizes to non-versioned."""
        mock_coordinator.get_task = AsyncMock(return_value=sample_task)
        result = handler.handle("/api/v1/control-plane/tasks/task-001", {}, mock_http_handler)
        assert _status(result) == 200
        assert _body(result)["id"] == "task-001"

    def test_route_get_queue(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[])
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler.handle("/api/control-plane/queue", {}, mock_http_handler)
        assert _status(result) == 200

    def test_route_get_queue_metrics(self, handler, mock_coordinator, mock_http_handler):
        result = handler.handle("/api/control-plane/queue/metrics", {}, mock_http_handler)
        assert _status(result) == 200

    def test_route_get_deliberation(self, handler, mock_http_handler, org_scoped_request_user):
        mock_result = {"request_id": "r1", "status": "done"}
        with patch(
            "aragora.core.decision_results.get_decision_result_for_org",
            return_value=mock_result,
        ):
            result = handler.handle("/api/control-plane/deliberations/r1", {}, mock_http_handler)
        assert _status(result) == 200

    def test_route_get_deliberation_status(
        self, handler, mock_http_handler, org_scoped_request_user
    ):
        mock_status = {"request_id": "r1", "status": "running"}
        with patch(
            "aragora.core.decision_results.get_decision_status_for_org",
            return_value=mock_status,
        ):
            result = handler.handle(
                "/api/control-plane/deliberations/r1/status", {}, mock_http_handler
            )
        assert _status(result) == 200


# ============================================================================
# Async POST routing
# ============================================================================


class TestPostRouting:
    """Tests for POST request routing through handle_post()."""

    @pytest.mark.asyncio
    async def test_route_post_submit_task(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "priority": "normal"}
        mock_coordinator.submit_task = AsyncMock(return_value="task-routed")
        mock_http_handler.rfile.read.return_value = json.dumps(body).encode()
        mock_http_handler.headers = {
            "Content-Length": str(len(json.dumps(body).encode())),
            "Content-Type": "application/json",
        }
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            result = await handler.handle_post("/api/control-plane/tasks", {}, mock_http_handler)
        assert _status(result) == 201

    @pytest.mark.asyncio
    async def test_route_post_submit_task_rejects_array_body(self, handler, mock_http_handler):
        body = ["not", "an", "object"]
        mock_http_handler.rfile.read.return_value = json.dumps(body).encode()
        mock_http_handler.headers = {
            "Content-Length": str(len(json.dumps(body).encode())),
            "Content-Type": "application/json",
        }

        result = await handler.handle_post("/api/control-plane/tasks", {}, mock_http_handler)

        assert _status(result) == 400
        assert _body(result)["error"] == "Request body must be a JSON object"

    @pytest.mark.asyncio
    async def test_route_post_claim_task(self, handler, mock_coordinator, mock_http_handler):
        body = {"agent_id": "agent-A", "capabilities": ["reasoning"]}
        mock_coordinator.claim_task = AsyncMock(return_value=None)
        mock_http_handler.rfile.read.return_value = json.dumps(body).encode()
        mock_http_handler.headers = {
            "Content-Length": str(len(json.dumps(body).encode())),
            "Content-Type": "application/json",
        }
        result = await handler.handle_post("/api/control-plane/tasks/claim", {}, mock_http_handler)
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_post_complete_task(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {"ok": True}, "agent_id": "agent-A"}
        mock_coordinator.complete_task = AsyncMock(return_value=True)
        mock_http_handler.rfile.read.return_value = json.dumps(body).encode()
        mock_http_handler.headers = {
            "Content-Length": str(len(json.dumps(body).encode())),
            "Content-Type": "application/json",
        }
        result = await handler.handle_post(
            "/api/control-plane/tasks/task-001/complete", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_post_fail_task(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "boom", "agent_id": "agent-A"}
        mock_coordinator.fail_task = AsyncMock(return_value=True)
        mock_http_handler.rfile.read.return_value = json.dumps(body).encode()
        mock_http_handler.headers = {
            "Content-Length": str(len(json.dumps(body).encode())),
            "Content-Type": "application/json",
        }
        result = await handler.handle_post(
            "/api/control-plane/tasks/task-001/fail", {}, mock_http_handler
        )
        assert _status(result) == 200

    @pytest.mark.asyncio
    async def test_route_post_cancel_task(self, handler, mock_coordinator, mock_http_handler):
        mock_coordinator.cancel_task = AsyncMock(return_value=True)
        result = await handler.handle_post(
            "/api/control-plane/tasks/task-001/cancel", {}, mock_http_handler
        )
        assert _status(result) == 200


# ============================================================================
# Edge cases and additional coverage
# ============================================================================


class TestEdgeCases:
    """Misc edge cases for coverage completeness."""

    def test_await_if_needed_sync_value(self):
        """_await_if_needed returns sync values directly."""
        from aragora.server.handlers.control_plane.tasks import _await_if_needed

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_await_if_needed(42))
            assert result == 42
        finally:
            loop.close()

    def test_await_if_needed_async_coroutine(self):
        """_await_if_needed awaits coroutines."""
        from aragora.server.handlers.control_plane.tasks import _await_if_needed

        async def coro():
            return "async_result"

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(_await_if_needed(coro()))
            assert result == "async_result"
        finally:
            loop.close()

    def test_get_has_permission_fallback(self):
        """_get_has_permission returns fallback when module not loaded."""
        from aragora.server.handlers.control_plane.tasks import _get_has_permission

        fn = _get_has_permission()
        assert callable(fn)

    def test_submit_task_os_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async",
                side_effect=OSError("disk full"),
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 500

    def test_submit_task_type_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"task_type": "analysis", "priority": "normal"}
        with patch(
            "aragora.control_plane.scheduler.TaskPriority",
            MockTaskPriority,
        ):
            with patch(
                "aragora.server.handlers.control_plane.tasks._run_async",
                side_effect=TypeError("wrong"),
            ):
                result = handler._handle_submit_task(body, mock_http_handler)
        assert _status(result) == 500

    def test_claim_task_type_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"agent_id": "agent-A"}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=TypeError("wrong claim"),
        ):
            result = handler._handle_claim_task(body, mock_http_handler)
        assert _status(result) == 500

    def test_complete_task_os_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"result": {}}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=OSError("io fail"),
        ):
            result = handler._handle_complete_task("task-001", body, mock_http_handler)
        assert _status(result) == 500

    def test_fail_task_os_error(self, handler, mock_coordinator, mock_http_handler):
        body = {"error": "x"}
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=OSError("net fail"),
        ):
            result = handler._handle_fail_task("task-001", body, mock_http_handler)
        assert _status(result) == 500

    def test_cancel_task_key_error(self, handler, mock_coordinator, mock_http_handler):
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=KeyError("bad key"),
        ):
            result = handler._handle_cancel_task("task-001", mock_http_handler)
        assert _status(result) == 500

    def test_cancel_task_type_error(self, handler, mock_coordinator, mock_http_handler):
        with patch(
            "aragora.server.handlers.control_plane.tasks._run_async",
            side_effect=TypeError("type issue"),
        ):
            result = handler._handle_cancel_task("task-001", mock_http_handler)
        assert _status(result) == 500

    def test_get_queue_import_error(self, handler, mock_coordinator):
        """ImportError from scheduler should be caught as 500."""
        mock_coordinator._scheduler.list_by_status = AsyncMock(side_effect=ImportError("no module"))
        with patch("aragora.control_plane.scheduler.TaskStatus", MockTaskStatus):
            result = handler._handle_get_queue({})
        assert _status(result) == 500
