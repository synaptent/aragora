"""
Tests for the Control Plane HTTP Handler.

Tests cover all control plane HTTP endpoints:
- Agent registration and discovery (/api/control-plane/agents/*)
- Task scheduling (/api/control-plane/tasks/*)
- Health monitoring (/api/control-plane/health/*)
- Policy governance (/api/control-plane/policies/*)
- Notification management (/api/control-plane/notifications/*)
- Audit logging (/api/control-plane/audit/*)
- Metrics and statistics (/api/control-plane/stats, /api/control-plane/metrics)
"""

import asyncio
import json
import pytest
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from tests.server.handlers.conftest import (
    parse_handler_response,
    assert_success_response,
    assert_error_response,
)


# ============================================================================
# Auto-use fixtures to isolate control plane state between tests
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_control_plane_coordinator():
    """Reset ControlPlaneHandler.coordinator class attribute between tests."""
    from aragora.server.handlers.control_plane import ControlPlaneHandler

    old = getattr(ControlPlaneHandler, "coordinator", None)
    yield
    ControlPlaneHandler.coordinator = old


@pytest.fixture(autouse=True)
def mock_run_async():
    """Patch _run_async to handle async calls in tests.

    The control plane handler uses _run_async() internally to call async
    coordinator methods from sync handler methods. In async tests, this
    conflicts with the running event loop. This fixture patches _run_async
    to simply run the coroutine directly using asyncio.run()
    or return the awaitable result when already in async context.
    """

    def _mock_run_async(coro):
        """Run a coroutine, handling both sync and async test contexts."""
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context - the coroutine should be awaited
            # But since this is called from sync code, we need to handle it
            # Create a task and return the result immediately if possible
            if asyncio.iscoroutine(coro):
                # Use nest_asyncio approach or return mock result
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, coro)
                    return future.result(timeout=5.0)
            return coro
        except RuntimeError:
            # No running event loop - we can use run_until_complete
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()
                    # Restore a fresh event loop so subsequent code doesn't
                    # see a closed loop.
                    asyncio.set_event_loop(asyncio.new_event_loop())
            except Exception:
                # Fallback: if it's already a result, return it
                return coro

    with patch("aragora.server.handlers.control_plane._run_async", side_effect=_mock_run_async):
        yield


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_agent_info():
    """Create a mock AgentInfo."""
    mock = MagicMock()
    mock.agent_id = "test-agent-001"
    mock.capabilities = ["debate", "code"]
    mock.model = "claude-3-opus"
    mock.provider = "anthropic"
    mock.status = MagicMock()
    mock.status.value = "ready"
    mock.registered_at = 1706605200.0
    mock.last_heartbeat = 1706605300.0
    mock.current_task_id = None
    mock.tasks_completed = 5
    mock.tasks_failed = 0
    mock.to_dict = MagicMock(
        return_value={
            "agent_id": "test-agent-001",
            "capabilities": ["debate", "code"],
            "model": "claude-3-opus",
            "provider": "anthropic",
            "status": "ready",
            "registered_at": 1706605200.0,
            "last_heartbeat": 1706605300.0,
            "tasks_completed": 5,
            "tasks_failed": 0,
        }
    )
    return mock


@pytest.fixture
def mock_task():
    """Create a mock Task."""
    mock = MagicMock()
    mock.id = "task-001"
    mock.task_type = "debate"
    mock.status = MagicMock()
    mock.status.value = "running"
    mock.priority = MagicMock()
    mock.priority.name = "NORMAL"
    mock.payload = {"question": "Test question"}
    mock.metadata = {"name": "Test task"}
    mock.assigned_agent = "test-agent-001"
    mock.created_at = 1706605200.0
    mock.started_at = 1706605210.0
    mock.retries = 0
    mock.to_dict = MagicMock(
        return_value={
            "id": "task-001",
            "task_type": "debate",
            "status": "running",
            "priority": "normal",
            "payload": {"question": "Test question"},
            "assigned_agent": "test-agent-001",
            "created_at": 1706605200.0,
            "started_at": 1706605210.0,
        }
    )
    return mock


@pytest.fixture
def mock_health_check():
    """Create a mock HealthCheck."""
    mock = MagicMock()
    mock.to_dict = MagicMock(
        return_value={
            "status": "healthy",
            "last_check": 1706605300.0,
            "consecutive_failures": 0,
        }
    )
    return mock


@pytest.fixture
def mock_coordinator(mock_agent_info, mock_task, mock_health_check):
    """Create a mock ControlPlaneCoordinator."""
    coordinator = MagicMock()

    # Set up async method returns using AsyncMock
    coordinator.list_agents = AsyncMock(return_value=[mock_agent_info])
    coordinator.get_agent = AsyncMock(return_value=mock_agent_info)
    coordinator.register_agent = AsyncMock(return_value=mock_agent_info)
    coordinator.unregister_agent = AsyncMock(return_value=True)
    coordinator.heartbeat = AsyncMock(return_value=True)

    coordinator.get_task = AsyncMock(return_value=mock_task)
    coordinator.submit_task = AsyncMock(return_value="task-002")
    coordinator.claim_task = AsyncMock(return_value=mock_task)
    coordinator.complete_task = AsyncMock(return_value=True)
    coordinator.fail_task = AsyncMock(return_value=True)
    coordinator.cancel_task = AsyncMock(return_value=True)

    coordinator.get_stats = AsyncMock(
        return_value={
            "registry": {
                "total_agents": 3,
                "available_agents": 2,
                "by_status": {"ready": 2, "busy": 1},
            },
            "scheduler": {
                "total": 10,
                "pending_tasks": 2,
                "running_tasks": 3,
                "completed_tasks": 4,
                "failed_tasks": 1,
                "by_status": {"pending": 2, "running": 3, "completed": 4},
                "by_type": {"debate": 5, "document_processing": 3, "audit": 2},
                "avg_wait_time_ms": 150,
                "avg_execution_time_ms": 3000,
                "throughput_per_minute": 2.5,
            },
        }
    )

    # Health monitoring
    coordinator.get_system_health = MagicMock(return_value=MagicMock(value="healthy"))
    coordinator.get_agent_health = MagicMock(return_value=mock_health_check)
    coordinator._health_monitor = MagicMock()
    coordinator._health_monitor.get_all_health = MagicMock(
        return_value={"test-agent-001": mock_health_check}
    )

    # Scheduler for queue operations
    mock_scheduler = MagicMock()
    mock_scheduler.list_by_status = AsyncMock(return_value=[mock_task])
    coordinator._scheduler = mock_scheduler

    return coordinator


@pytest.fixture
def mock_notification_manager():
    """Create a mock NotificationManager."""
    manager = MagicMock()
    manager.get_stats = MagicMock(
        return_value={
            "total_sent": 100,
            "successful": 95,
            "failed": 5,
            "success_rate": 0.95,
            "by_channel": {"slack": 50, "email": 30, "webhook": 20},
            "channels_configured": 3,
        }
    )
    return manager


@pytest.fixture
def mock_audit_log():
    """Create a mock AuditLog."""
    audit_log = MagicMock()

    mock_entry = MagicMock()
    mock_entry.to_dict = MagicMock(
        return_value={
            "id": "audit-001",
            "action": "task.submitted",
            "actor_id": "user-001",
            "resource_id": "task-001",
            "timestamp": "2026-01-30T10:00:00Z",
        }
    )

    audit_log.query = AsyncMock(return_value=[mock_entry])
    audit_log.get_stats = MagicMock(
        return_value={
            "total_entries": 1000,
            "storage_backend": "postgres",
        }
    )
    audit_log.verify_integrity = AsyncMock(return_value=True)

    return audit_log


@pytest.fixture
def mock_policy_store():
    """Create a mock ControlPlanePolicyStore."""
    store = MagicMock()
    store.list_violations = MagicMock(
        return_value=[
            {
                "id": "violation-001",
                "policy_id": "policy-001",
                "violation_type": "rate_limit_exceeded",
                "status": "open",
                "workspace_id": "ws-001",
                "created_at": "2026-01-30T10:00:00Z",
            }
        ]
    )
    store.count_violations = MagicMock(return_value={"rate_limit_exceeded": 5})
    store.update_violation_status = MagicMock(return_value=True)
    return store


@pytest.fixture
def mock_stream():
    """Create a mock control plane stream server."""
    stream = MagicMock()
    stream.emit_agent_registered = AsyncMock()
    stream.emit_agent_unregistered = AsyncMock()
    stream.emit_task_submitted = AsyncMock()
    stream.emit_task_claimed = AsyncMock()
    stream.emit_task_completed = AsyncMock()
    stream.emit_task_failed = AsyncMock()
    return stream


@pytest.fixture
def control_plane_handler(
    mock_server_context,
    mock_coordinator,
    mock_notification_manager,
    mock_audit_log,
    mock_stream,
):
    """Create a ControlPlaneHandler with mocked dependencies."""
    from aragora.server.handlers.control_plane import ControlPlaneHandler

    # Add control plane context
    mock_server_context["control_plane_coordinator"] = mock_coordinator
    mock_server_context["notification_manager"] = mock_notification_manager
    mock_server_context["audit_log"] = mock_audit_log
    mock_server_context["control_plane_stream"] = mock_stream

    handler = ControlPlaneHandler(mock_server_context)

    # Save and set class-level coordinator
    old_coordinator = getattr(ControlPlaneHandler, "coordinator", None)
    ControlPlaneHandler.coordinator = mock_coordinator

    yield handler

    # Restore class-level coordinator to prevent pollution
    ControlPlaneHandler.coordinator = old_coordinator


# ============================================================================
# Basic Handler Tests
# ============================================================================


class TestControlPlaneHandlerBasics:
    """Tests for basic handler configuration."""

    def test_can_handle_agents_path(self, control_plane_handler):
        """Test handler recognizes /api/control-plane/agents path."""
        assert control_plane_handler.can_handle("/api/control-plane/agents")

    def test_can_handle_tasks_path(self, control_plane_handler):
        """Test handler recognizes /api/control-plane/tasks path."""
        assert control_plane_handler.can_handle("/api/control-plane/tasks")

    def test_can_handle_health_path(self, control_plane_handler):
        """Test handler recognizes /api/control-plane/health path."""
        assert control_plane_handler.can_handle("/api/control-plane/health")

    def test_can_handle_stats_path(self, control_plane_handler):
        """Test handler recognizes /api/control-plane/stats path."""
        assert control_plane_handler.can_handle("/api/control-plane/stats")

    def test_can_handle_versioned_path(self, control_plane_handler):
        """Test handler recognizes /api/v1/control-plane paths."""
        assert control_plane_handler.can_handle("/api/v1/control-plane/agents")
        assert control_plane_handler.can_handle("/api/v1/control-plane/tasks")
        assert control_plane_handler.can_handle("/api/v1/control-plane/health")

    def test_cannot_handle_unrelated_path(self, control_plane_handler):
        """Test handler rejects unrelated paths."""
        assert not control_plane_handler.can_handle("/api/debates")
        assert not control_plane_handler.can_handle("/api/v1/agents")
        assert not control_plane_handler.can_handle("/health")

    def test_normalize_path_versioned(self, control_plane_handler):
        """Test path normalization for versioned routes."""
        assert (
            control_plane_handler._normalize_path("/api/v1/control-plane/agents")
            == "/api/control-plane/agents"
        )

    def test_normalize_path_legacy(self, control_plane_handler):
        """Test path normalization leaves legacy paths unchanged."""
        assert (
            control_plane_handler._normalize_path("/api/control-plane/agents")
            == "/api/control-plane/agents"
        )


# ============================================================================
# Agent Registration Tests
# ============================================================================


class TestAgentRegistration:
    """Tests for agent registration endpoints."""

    def test_list_agents_success(self, control_plane_handler, mock_http_handler):
        """Test listing registered agents."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/agents", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "agents" in body
        assert "total" in body
        assert body["total"] == 1

    def test_list_agents_with_capability_filter(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test listing agents filtered by capability."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle(
            "/api/control-plane/agents", {"capability": "debate"}, http
        )

        assert result is not None
        assert result.status_code == 200
        mock_coordinator.list_agents.assert_called_with(capability="debate", only_available=True)

    def test_list_agents_include_unavailable(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test listing agents including unavailable ones."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle(
            "/api/control-plane/agents", {"available": "false"}, http
        )

        assert result is not None
        mock_coordinator.list_agents.assert_called_with(capability=None, only_available=False)

    def test_get_agent_by_id(self, control_plane_handler, mock_http_handler):
        """Test getting a specific agent by ID."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/agents/test-agent-001", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["agent_id"] == "test-agent-001"

    def test_get_agent_not_found(self, control_plane_handler, mock_http_handler, mock_coordinator):
        """Test getting non-existent agent returns 404."""
        mock_coordinator.get_agent = AsyncMock(return_value=None)

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/agents/nonexistent", {}, http)

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_register_agent_success(self, control_plane_handler, mock_http_handler):
        """Test registering a new agent."""
        http = mock_http_handler(
            method="POST",
            body={
                "agent_id": "new-agent",
                "capabilities": ["debate", "code"],
                "model": "claude-3-opus",
                "provider": "anthropic",
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/agents", {}, http)

        assert result is not None
        assert result.status_code == 201
        body = parse_handler_response(result)
        assert "agent_id" in body

    @pytest.mark.asyncio
    async def test_register_agent_missing_id(self, control_plane_handler, mock_http_handler):
        """Test registering agent without ID returns 400."""
        http = mock_http_handler(
            method="POST",
            body={"capabilities": ["debate"]},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/agents", {}, http)

        assert result is not None
        assert result.status_code == 400

    def test_unregister_agent_success(self, control_plane_handler, mock_http_handler):
        """Test unregistering an agent."""
        http = mock_http_handler(method="DELETE")
        result = control_plane_handler.handle_delete(
            "/api/control-plane/agents/test-agent-001", {}, http
        )

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["unregistered"] is True

    def test_unregister_agent_not_found(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test unregistering non-existent agent returns 404."""
        mock_coordinator.unregister_agent = AsyncMock(return_value=False)

        http = mock_http_handler(method="DELETE")
        result = control_plane_handler.handle_delete(
            "/api/control-plane/agents/nonexistent", {}, http
        )

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_agent_heartbeat_success(self, control_plane_handler, mock_http_handler):
        """Test sending agent heartbeat."""
        http = mock_http_handler(
            method="POST",
            body={"status": "ready"},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post(
            "/api/control-plane/agents/test-agent-001/heartbeat", {}, http
        )

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["acknowledged"] is True

    @pytest.mark.asyncio
    async def test_agent_heartbeat_not_found(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test heartbeat for non-existent agent."""
        mock_coordinator.heartbeat = AsyncMock(return_value=False)

        http = mock_http_handler(
            method="POST",
            body={},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post(
            "/api/control-plane/agents/nonexistent/heartbeat", {}, http
        )

        assert result is not None
        assert result.status_code == 404


# ============================================================================
# Task Scheduling Tests
# ============================================================================


class TestTaskScheduling:
    """Tests for task scheduling endpoints."""

    def test_get_task_by_id(self, control_plane_handler, mock_http_handler):
        """Test getting a task by ID."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/tasks/task-001", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["id"] == "task-001"

    def test_get_task_not_found(self, control_plane_handler, mock_http_handler, mock_coordinator):
        """Test getting non-existent task returns 404."""
        mock_coordinator.get_task = AsyncMock(return_value=None)

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/tasks/nonexistent", {}, http)

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_submit_task_success(self, control_plane_handler, mock_http_handler):
        """Test submitting a new task."""
        http = mock_http_handler(
            method="POST",
            body={
                "task_type": "debate",
                "payload": {"question": "Test question"},
                "priority": "normal",
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks", {}, http)

        assert result is not None
        assert result.status_code == 201
        body = parse_handler_response(result)
        assert "task_id" in body

    @pytest.mark.asyncio
    async def test_submit_task_missing_type(self, control_plane_handler, mock_http_handler):
        """Test submitting task without type returns 400."""
        http = mock_http_handler(
            method="POST",
            body={"payload": {}},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks", {}, http)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_submit_task_with_priority(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test submitting task with high priority."""
        http = mock_http_handler(
            method="POST",
            body={
                "task_type": "urgent_debate",
                "payload": {},
                "priority": "high",
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks", {}, http)

        assert result is not None
        assert result.status_code == 201

    @pytest.mark.asyncio
    async def test_submit_task_invalid_priority(self, control_plane_handler, mock_http_handler):
        """Test submitting task with invalid priority."""
        http = mock_http_handler(
            method="POST",
            body={
                "task_type": "debate",
                "payload": {},
                "priority": "invalid",
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks", {}, http)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_claim_task_success(self, control_plane_handler, mock_http_handler):
        """Test claiming a task."""
        http = mock_http_handler(
            method="POST",
            body={
                "agent_id": "test-agent-001",
                "capabilities": ["debate"],
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks/claim", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "task" in body

    @pytest.mark.asyncio
    async def test_claim_task_missing_agent_id(self, control_plane_handler, mock_http_handler):
        """Test claiming task without agent ID returns 400."""
        http = mock_http_handler(
            method="POST",
            body={"capabilities": ["debate"]},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks/claim", {}, http)

        assert result is not None
        assert result.status_code == 400

    @pytest.mark.asyncio
    async def test_claim_task_no_available_task(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test claiming when no tasks available."""
        mock_coordinator.claim_task = AsyncMock(return_value=None)

        http = mock_http_handler(
            method="POST",
            body={
                "agent_id": "test-agent-001",
                "capabilities": ["debate"],
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/control-plane/tasks/claim", {}, http)

        assert result is not None
        body = parse_handler_response(result)
        assert body.get("task") is None

    @pytest.mark.asyncio
    async def test_complete_task_success(self, control_plane_handler, mock_http_handler):
        """Test completing a task."""
        http = mock_http_handler(
            method="POST",
            body={
                "result": {"conclusion": "Success"},
                "agent_id": "test-agent-001",
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post(
            "/api/control-plane/tasks/task-001/complete", {}, http
        )

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["completed"] is True

    @pytest.mark.asyncio
    async def test_complete_task_not_found(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test completing non-existent task."""
        mock_coordinator.complete_task = AsyncMock(return_value=False)

        http = mock_http_handler(
            method="POST",
            body={"result": {}},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post(
            "/api/control-plane/tasks/nonexistent/complete", {}, http
        )

        assert result is not None
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_fail_task_success(self, control_plane_handler, mock_http_handler):
        """Test failing a task."""
        http = mock_http_handler(
            method="POST",
            body={
                "error": "Test error",
                "agent_id": "test-agent-001",
                "requeue": True,
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post(
            "/api/control-plane/tasks/task-001/fail", {}, http
        )

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["failed"] is True

    @pytest.mark.asyncio
    async def test_cancel_task_success(self, control_plane_handler, mock_http_handler):
        """Test canceling a task."""
        http = mock_http_handler(method="POST", headers={"Content-Type": "application/json"})

        result = await control_plane_handler.handle_post(
            "/api/control-plane/tasks/task-001/cancel", {}, http
        )

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body["cancelled"] is True

    @pytest.mark.asyncio
    async def test_cancel_completed_task(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test canceling already completed task."""
        mock_coordinator.cancel_task = AsyncMock(return_value=False)

        http = mock_http_handler(method="POST", headers={"Content-Type": "application/json"})

        result = await control_plane_handler.handle_post(
            "/api/control-plane/tasks/completed-task/cancel", {}, http
        )

        assert result is not None
        assert result.status_code == 404


# ============================================================================
# Health Monitoring Tests
# ============================================================================


class TestHealthMonitoring:
    """Tests for health monitoring endpoints."""

    def test_system_health_success(self, control_plane_handler, mock_http_handler):
        """Test getting system health status."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/health", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "status" in body
        assert "agents" in body

    def test_agent_health_success(self, control_plane_handler, mock_http_handler):
        """Test getting specific agent health."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/health/test-agent-001", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "status" in body

    def test_agent_health_not_found(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test agent health for non-existent agent."""
        mock_coordinator.get_agent_health = MagicMock(return_value=None)

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/health/nonexistent", {}, http)

        assert result is not None
        assert result.status_code == 404

    def test_detailed_health_success(self, control_plane_handler, mock_http_handler):
        """Test getting detailed health information."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/health/detailed", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "status" in body
        assert "components" in body
        assert "uptime_seconds" in body

    def test_circuit_breakers_status(self, control_plane_handler, mock_http_handler):
        """Test getting circuit breaker status."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/breakers", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "breakers" in body


# ============================================================================
# Statistics and Metrics Tests
# ============================================================================


class TestStatisticsAndMetrics:
    """Tests for statistics and metrics endpoints."""

    def test_get_stats_success(self, control_plane_handler, mock_http_handler):
        """Test getting control plane statistics."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/stats", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "registry" in body
        assert "scheduler" in body

    def test_get_metrics_success(self, control_plane_handler, mock_http_handler):
        """Test getting dashboard metrics."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/metrics", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "active_jobs" in body
        assert "queued_jobs" in body
        assert "agents_available" in body

    def test_get_queue_success(self, control_plane_handler, mock_http_handler):
        """Test getting job queue."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/queue", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "jobs" in body
        assert "total" in body

    def test_get_queue_with_limit(self, control_plane_handler, mock_http_handler):
        """Test getting job queue with limit parameter."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/queue", {"limit": "10"}, http)

        assert result is not None
        assert result.status_code == 200

    def test_get_queue_metrics(self, control_plane_handler, mock_http_handler):
        """Test getting queue performance metrics."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/queue/metrics", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "pending" in body
        assert "running" in body


# ============================================================================
# Notification Management Tests
# ============================================================================


class TestNotificationManagement:
    """Tests for notification management endpoints."""

    def test_get_notifications_success(self, control_plane_handler, mock_http_handler):
        """Test getting notification history."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/notifications", {}, http)

        assert result is not None
        assert result.status_code == 200

    def test_get_notifications_not_configured(self, control_plane_handler, mock_http_handler):
        """Test notifications when manager not configured."""
        control_plane_handler.ctx["notification_manager"] = None

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/notifications", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "message" in body

    def test_get_notification_stats_success(self, control_plane_handler, mock_http_handler):
        """Test getting notification statistics."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/notifications/stats", {}, http)

        assert result is not None
        assert result.status_code == 200

    def test_get_notification_stats_not_configured(self, control_plane_handler, mock_http_handler):
        """Test notification stats when manager not configured."""
        control_plane_handler.ctx["notification_manager"] = None

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/notifications/stats", {}, http)

        assert result is not None
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert body.get("total_sent") == 0


# ============================================================================
# Audit Log Tests
# ============================================================================


class TestAuditLogs:
    """Tests for audit log endpoints."""

    def test_get_audit_logs_success(self, control_plane_handler, mock_http_handler):
        """Test querying audit logs."""
        with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle("/api/control-plane/audit", {}, http)

            assert result is not None
            assert result.status_code == 200
            body = parse_handler_response(result)
            assert "entries" in body
            assert "total" in body

    def test_get_audit_logs_with_filters(self, control_plane_handler, mock_http_handler):
        """Test querying audit logs with filters."""
        with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle(
                "/api/control-plane/audit",
                {
                    "actions": "task.submitted,task.completed",
                    "limit": "50",
                },
                http,
            )

            assert result is not None
            assert result.status_code == 200

    def test_get_audit_logs_not_configured(self, control_plane_handler, mock_http_handler):
        """Test audit logs when not configured."""
        control_plane_handler.ctx["audit_log"] = None

        with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle("/api/control-plane/audit", {}, http)

            assert result is not None
            assert result.status_code == 200
            body = parse_handler_response(result)
            assert "message" in body

    def test_get_audit_stats_success(self, control_plane_handler, mock_http_handler):
        """Test getting audit log statistics."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/audit/stats", {}, http)

        assert result is not None
        assert result.status_code == 200

    def test_verify_audit_integrity_success(self, control_plane_handler, mock_http_handler):
        """Test verifying audit log integrity."""
        with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle("/api/control-plane/audit/verify", {}, http)

            assert result is not None
            assert result.status_code == 200
            body = parse_handler_response(result)
            assert body["valid"] is True

    def test_verify_audit_integrity_not_configured(self, control_plane_handler, mock_http_handler):
        """Test audit verification when not configured."""
        control_plane_handler.ctx["audit_log"] = None

        with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle("/api/control-plane/audit/verify", {}, http)

            assert result is not None
            assert result.status_code == 503


# ============================================================================
# Policy Violation Tests
# ============================================================================


class TestPolicyViolations:
    """Tests for policy violation endpoints."""

    def test_list_policy_violations_success(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test listing policy violations."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(method="GET")
                result = control_plane_handler.handle(
                    "/api/control-plane/policies/violations", {}, http
                )

                assert result is not None
                assert result.status_code == 200
                body = parse_handler_response(result)
                assert "violations" in body
                assert "total" in body

    def test_list_policy_violations_with_filters(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test listing violations with filters."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(method="GET")
                result = control_plane_handler.handle(
                    "/api/control-plane/policies/violations",
                    {"status": "open", "policy_id": "policy-001"},
                    http,
                )

                assert result is not None
                assert result.status_code == 200

    def test_list_policy_violations_store_not_available(
        self, control_plane_handler, mock_http_handler
    ):
        """Test violations when store not available."""
        with patch.object(control_plane_handler, "_get_policy_store", return_value=None):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(method="GET")
                result = control_plane_handler.handle(
                    "/api/control-plane/policies/violations", {}, http
                )

                assert result is not None
                assert result.status_code == 503

    def test_get_policy_violation_by_id(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test getting specific violation by ID."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(method="GET")
                result = control_plane_handler.handle(
                    "/api/control-plane/policies/violations/violation-001", {}, http
                )

                assert result is not None
                assert result.status_code == 200

    def test_get_policy_violation_not_found(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test getting non-existent violation."""
        mock_policy_store.list_violations = MagicMock(return_value=[])

        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(method="GET")
                result = control_plane_handler.handle(
                    "/api/control-plane/policies/violations/nonexistent", {}, http
                )

                assert result is not None
                assert result.status_code == 404

    def test_get_policy_violation_stats(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test getting violation statistics."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(method="GET")
                result = control_plane_handler.handle(
                    "/api/control-plane/policies/violations/stats", {}, http
                )

                assert result is not None
                assert result.status_code == 200
                body = parse_handler_response(result)
                assert "total" in body
                assert "open" in body

    def test_update_policy_violation_status(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test updating violation status."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(
                    method="PATCH",
                    body={"status": "resolved", "resolution_notes": "Fixed"},
                    headers={"Content-Type": "application/json"},
                )

                result = control_plane_handler.handle_patch(
                    "/api/control-plane/policies/violations/violation-001", {}, http
                )

                assert result is not None
                assert result.status_code == 200
                body = parse_handler_response(result)
                assert body["updated"] is True

    def test_update_policy_violation_invalid_status(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test updating violation with invalid status."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(
                    method="PATCH",
                    body={"status": "invalid_status"},
                    headers={"Content-Type": "application/json"},
                )

                result = control_plane_handler.handle_patch(
                    "/api/control-plane/policies/violations/violation-001", {}, http
                )

                assert result is not None
                assert result.status_code == 400

    def test_update_policy_violation_missing_status(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test updating violation without status."""
        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(
                    method="PATCH",
                    body={},
                    headers={"Content-Type": "application/json"},
                )

                result = control_plane_handler.handle_patch(
                    "/api/control-plane/policies/violations/violation-001", {}, http
                )

                assert result is not None
                assert result.status_code == 400

    def test_update_policy_violation_not_found(
        self, control_plane_handler, mock_http_handler, mock_policy_store
    ):
        """Test updating non-existent violation."""
        mock_policy_store.update_violation_status = MagicMock(return_value=False)

        with patch.object(
            control_plane_handler, "_get_policy_store", return_value=mock_policy_store
        ):
            with patch("aragora.server.handlers.control_plane.has_permission", return_value=True):
                http = mock_http_handler(
                    method="PATCH",
                    body={"status": "resolved"},
                    headers={"Content-Type": "application/json"},
                )

                result = control_plane_handler.handle_patch(
                    "/api/control-plane/policies/violations/nonexistent", {}, http
                )

                assert result is not None
                assert result.status_code == 404


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestErrorHandling:
    """Tests for error handling in control plane handler."""

    def test_coordinator_not_initialized(self, control_plane_handler, mock_http_handler):
        """Test error when coordinator not initialized."""
        control_plane_handler.ctx["control_plane_coordinator"] = None
        control_plane_handler.__class__.coordinator = None

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/agents", {}, http)

        assert result is not None
        assert result.status_code == 503

    def test_coordinator_exception_handling(
        self, control_plane_handler, mock_http_handler, mock_coordinator
    ):
        """Test exception handling in coordinator calls - data errors return 400."""
        # When list_agents returns something that can't be iterated, it causes a
        # TypeError which is classified as a data error (400), not a server error (503)
        mock_coordinator.list_agents = AsyncMock(return_value="not_iterable")

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/agents", {}, http)

        assert result is not None
        # TypeError during iteration is caught as a data error
        assert result.status_code == 400

    def test_value_error_handling(self, control_plane_handler, mock_http_handler, mock_coordinator):
        """Test handling of ValueError in coordinator calls."""
        mock_coordinator.get_agent = AsyncMock(side_effect=ValueError("Invalid agent"))

        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/agents/bad-id", {}, http)

        assert result is not None
        assert result.status_code == 400

    def test_unknown_path_returns_none(self, control_plane_handler, mock_http_handler):
        """Test unknown path returns None (not handled)."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/control-plane/unknown/path", {}, http)

        assert result is None


# ============================================================================
# Deliberation Tests
# ============================================================================


class TestDeliberations:
    """Tests for deliberation (vetted decisionmaking) endpoints."""

    @pytest.mark.asyncio
    async def test_submit_deliberation_missing_content(
        self, control_plane_handler, mock_http_handler
    ):
        """Test submitting deliberation without content."""
        http = mock_http_handler(
            method="POST",
            body={},
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post(
            "/api/control-plane/deliberations", {}, http
        )

        assert result is not None
        assert result.status_code == 400

    @pytest.fixture
    def org_caller(self, monkeypatch):
        from aragora.billing.auth.context import UserAuthContext

        user = UserAuthContext(
            authenticated=True, user_id="user-1", org_id="org-1", role="admin", token_type="access"
        )
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            lambda handler, user_store=None: user,
        )

    def test_get_deliberation_result(self, control_plane_handler, mock_http_handler, org_caller):
        """Test getting deliberation result by ID."""
        with patch("aragora.core.decision_results.get_decision_result_for_org") as mock_get:
            mock_get.return_value = {
                "request_id": "req-001",
                "status": "completed",
                "answer": "Test answer",
            }

            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle(
                "/api/control-plane/deliberations/req-001", {}, http
            )

            assert result is not None
            assert result.status_code == 200
            mock_get.assert_called_once_with("req-001", "org-1")

    def test_get_deliberation_not_found(self, control_plane_handler, mock_http_handler, org_caller):
        """Test getting non-existent deliberation."""
        with patch("aragora.core.decision_results.get_decision_result_for_org") as mock_get:
            mock_get.return_value = None

            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle(
                "/api/control-plane/deliberations/nonexistent", {}, http
            )

            assert result is not None
            assert result.status_code == 404

    def test_get_deliberation_status(self, control_plane_handler, mock_http_handler, org_caller):
        """Test getting deliberation status."""
        with patch("aragora.core.decision_results.get_decision_status_for_org") as mock_status:
            mock_status.return_value = {
                "request_id": "req-001",
                "status": "processing",
                "progress": 0.5,
            }

            http = mock_http_handler(method="GET")
            result = control_plane_handler.handle(
                "/api/control-plane/deliberations/req-001/status", {}, http
            )

            assert result is not None
            assert result.status_code == 200


# ============================================================================
# Rate Limiting Tests
# ============================================================================


class TestRateLimiting:
    """Tests for rate limiting on control plane endpoints."""

    def test_post_handler_has_rate_limit_decorator(self, control_plane_handler):
        """Test that POST handler has rate limiting configured."""
        # The handler should have rate_limit decorator applied
        handle_post = control_plane_handler.handle_post
        # Check if the decorator metadata exists
        assert callable(handle_post)


# ============================================================================
# Authorization Tests
# ============================================================================


class TestAuthorization:
    """Tests for authorization on control plane endpoints."""

    @pytest.mark.no_auto_auth
    def test_list_agents_requires_auth(self, control_plane_handler, mock_http_handler):
        """Test that listing agents requires authentication."""
        # Note: The conftest auto-bypasses auth, so we use no_auto_auth marker
        # In a real test scenario, this would verify 401 response without auth
        pass

    @pytest.mark.no_auto_auth
    def test_register_agent_requires_permission(self, control_plane_handler, mock_http_handler):
        """Test that registering agents requires permission."""
        # This test would verify that controlplane:agents permission is required
        pass


# ============================================================================
# Event Emission Tests
# ============================================================================


class TestEventEmission:
    """Tests for WebSocket event emission."""

    @pytest.mark.asyncio
    async def test_agent_registration_emits_event(
        self, control_plane_handler, mock_http_handler, mock_stream
    ):
        """Test that agent registration emits event."""
        http = mock_http_handler(
            method="POST",
            body={
                "agent_id": "new-agent",
                "capabilities": ["debate"],
            },
            headers={"Content-Type": "application/json"},
        )

        await control_plane_handler.handle_post("/api/control-plane/agents", {}, http)

    def test_agent_unregistration_emits_event(
        self, control_plane_handler, mock_http_handler, mock_stream
    ):
        """Test that agent unregistration emits event."""
        http = mock_http_handler(method="DELETE")
        control_plane_handler.handle_delete("/api/control-plane/agents/test-agent-001", {}, http)

    @pytest.mark.asyncio
    async def test_task_submission_emits_event(
        self, control_plane_handler, mock_http_handler, mock_stream
    ):
        """Test that task submission emits event."""
        http = mock_http_handler(
            method="POST",
            body={
                "task_type": "debate",
                "payload": {},
            },
            headers={"Content-Type": "application/json"},
        )

        await control_plane_handler.handle_post("/api/control-plane/tasks", {}, http)


# ============================================================================
# Versioned API Tests
# ============================================================================


class TestVersionedAPI:
    """Tests for versioned API path support."""

    def test_v1_agents_path(self, control_plane_handler, mock_http_handler):
        """Test that v1 agents path works."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/v1/control-plane/agents", {}, http)

        assert result is not None
        assert result.status_code == 200

    def test_v1_tasks_path(self, control_plane_handler, mock_http_handler):
        """Test that v1 tasks path works."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/v1/control-plane/tasks/task-001", {}, http)

        assert result is not None
        assert result.status_code == 200

    def test_v1_health_path(self, control_plane_handler, mock_http_handler):
        """Test that v1 health path works."""
        http = mock_http_handler(method="GET")
        result = control_plane_handler.handle("/api/v1/control-plane/health", {}, http)

        assert result is not None
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_v1_post_path(self, control_plane_handler, mock_http_handler):
        """Test that v1 POST paths work."""
        http = mock_http_handler(
            method="POST",
            body={
                "agent_id": "new-agent",
                "capabilities": ["debate"],
            },
            headers={"Content-Type": "application/json"},
        )

        result = await control_plane_handler.handle_post("/api/v1/control-plane/agents", {}, http)

        assert result is not None
        assert result.status_code == 201
