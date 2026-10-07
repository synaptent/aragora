"""
Tests for aragora.server.handlers.control_plane - Control Plane HTTP handlers.

Tests cover:
- Agent registration and discovery
- Task scheduling and distribution
- Health monitoring endpoints
- Policy violation management
- Deliberation submission (sync and async)
- Notification and audit log endpoints
- Error handling paths
- Authentication and authorization checks
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.control_plane import ControlPlaneHandler
from aragora.tenancy.record_scope import OrgScope

SCOPE = OrgScope(org_id="org-1", user_id="user-1", role="admin")


# ===========================================================================
# Mock Classes
# ===========================================================================


class MockTaskStatus(Enum):
    """Mock task status enum."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MockTaskPriority(Enum):
    """Mock task priority enum."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class MockAgentStatus(Enum):
    """Mock agent status enum."""

    AVAILABLE = "available"
    BUSY = "busy"
    OFFLINE = "offline"


class MockHealthStatus(Enum):
    """Mock health status enum."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class MockUser:
    """Mock user for testing."""

    id: str = "user-123"
    user_id: str = "user-123"
    email: str = "user@example.com"
    role: str = "admin"
    is_authenticated: bool = True


@dataclass
class MockAgentInfo:
    """Mock agent info for testing."""

    agent_id: str
    capabilities: list[str] = field(default_factory=list)
    model: str = "claude-3-opus"
    provider: str = "anthropic"
    status: str = "available"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capabilities": self.capabilities,
            "model": self.model,
            "provider": self.provider,
            "status": self.status,
            "metadata": self.metadata,
        }


@dataclass
class MockTask:
    """Mock task for testing."""

    id: str
    task_type: str
    status: MockTaskStatus = MockTaskStatus.PENDING
    priority: MockTaskPriority = MockTaskPriority.NORMAL
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    assigned_agent: str | None = None
    created_at: float = 1700000000.0
    started_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "status": self.status.value,
            "priority": self.priority.name.lower(),
            "payload": self.payload,
            "metadata": self.metadata,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at,
            "started_at": self.started_at,
        }


@dataclass
class MockHealthCheck:
    """Mock health check for testing."""

    healthy: bool = True
    latency_ms: int = 10
    last_check: float = 1700000000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check,
        }


class MockCoordinator:
    """Mock control plane coordinator."""

    def __init__(self):
        self.agents: dict[str, MockAgentInfo] = {}
        self.tasks: dict[str, MockTask] = {}
        self._health_monitor = MagicMock()
        self._health_monitor.get_all_health.return_value = {}
        self._scheduler = MagicMock()

    async def list_agents(
        self, capability: str | None = None, only_available: bool = True
    ) -> list[MockAgentInfo]:
        agents = list(self.agents.values())
        if capability:
            agents = [a for a in agents if capability in a.capabilities]
        if only_available:
            agents = [a for a in agents if a.status == "available"]
        return agents

    async def get_agent(self, agent_id: str) -> MockAgentInfo | None:
        return self.agents.get(agent_id)

    async def register_agent(
        self,
        agent_id: str,
        capabilities: list[str],
        model: str,
        provider: str,
        metadata: dict,
    ) -> MockAgentInfo:
        agent = MockAgentInfo(
            agent_id=agent_id,
            capabilities=capabilities,
            model=model,
            provider=provider,
            metadata=metadata,
        )
        self.agents[agent_id] = agent
        return agent

    async def unregister_agent(self, agent_id: str) -> bool:
        if agent_id in self.agents:
            del self.agents[agent_id]
            return True
        return False

    async def heartbeat(self, agent_id: str, status: Any = None) -> bool:
        return agent_id in self.agents

    async def get_task(self, task_id: str) -> MockTask | None:
        return self.tasks.get(task_id)

    async def submit_task(
        self,
        task_type: str,
        payload: dict,
        required_capabilities: list[str],
        priority: Any,
        timeout_seconds: int | None = None,
        metadata: dict | None = None,
    ) -> str:
        task_id = f"task-{len(self.tasks) + 1}"
        task = MockTask(
            id=task_id,
            task_type=task_type,
            payload=payload,
            metadata=metadata or {},
        )
        self.tasks[task_id] = task
        return task_id

    async def claim_task(
        self, agent_id: str, capabilities: list[str], block_ms: int = 5000
    ) -> MockTask | None:
        for task in self.tasks.values():
            if task.status == MockTaskStatus.PENDING:
                task.status = MockTaskStatus.RUNNING
                task.assigned_agent = agent_id
                return task
        return None

    async def complete_task(
        self,
        task_id: str,
        result: Any = None,
        agent_id: str | None = None,
        latency_ms: int | None = None,
    ) -> bool:
        if task_id in self.tasks:
            self.tasks[task_id].status = MockTaskStatus.COMPLETED
            return True
        return False

    async def fail_task(
        self,
        task_id: str,
        error: str,
        agent_id: str | None = None,
        latency_ms: int | None = None,
        requeue: bool = True,
    ) -> bool:
        if task_id in self.tasks:
            self.tasks[task_id].status = MockTaskStatus.FAILED
            return True
        return False

    async def cancel_task(self, task_id: str) -> bool:
        if task_id in self.tasks:
            self.tasks[task_id].status = MockTaskStatus.CANCELLED
            return True
        return False

    def get_system_health(self) -> MockHealthStatus:
        return MockHealthStatus.HEALTHY

    def get_agent_health(self, agent_id: str) -> MockHealthCheck | None:
        if agent_id in self.agents:
            return MockHealthCheck()
        return None

    async def get_stats(self) -> dict[str, Any]:
        return {
            "scheduler": {
                "by_status": {
                    "pending": sum(
                        1 for t in self.tasks.values() if t.status == MockTaskStatus.PENDING
                    ),
                    "running": sum(
                        1 for t in self.tasks.values() if t.status == MockTaskStatus.RUNNING
                    ),
                    "completed": sum(
                        1 for t in self.tasks.values() if t.status == MockTaskStatus.COMPLETED
                    ),
                },
                "by_type": {},
            },
            "registry": {
                "total_agents": len(self.agents),
                "available_agents": sum(1 for a in self.agents.values() if a.status == "available"),
                "by_status": {},
            },
        }


# ===========================================================================
# Helper Functions
# ===========================================================================


def get_status(result) -> int:
    """Extract status code from HandlerResult."""
    if hasattr(result, "status_code"):
        return result.status_code
    return result[1]


def get_body(result) -> dict:
    """Extract body from HandlerResult."""
    if hasattr(result, "body"):
        body = result.body
        if isinstance(body, bytes):
            return json.loads(body.decode("utf-8"))
        return json.loads(body)
    body = result[0]
    if isinstance(body, dict):
        return body
    return json.loads(body)


def make_mock_handler(
    body: dict | None = None,
    method: str = "GET",
    headers: dict | None = None,
):
    """Create a mock HTTP handler."""
    handler = MagicMock()
    handler.command = method
    handler.headers = headers or {"Authorization": "Bearer test-token"}
    handler.client_address = ("127.0.0.1", 12345)

    if body is not None:
        body_bytes = json.dumps(body).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_bytes))
        handler.rfile = BytesIO(body_bytes)
        handler.request_body = body_bytes
    else:
        handler.rfile = BytesIO(b"{}")
        handler.headers["Content-Length"] = "2"
        handler.request_body = b"{}"

    return handler


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_coordinator():
    """Create mock coordinator with sample data."""
    coordinator = MockCoordinator()

    # Add sample agents
    coordinator.agents["agent-1"] = MockAgentInfo(
        agent_id="agent-1",
        capabilities=["reasoning", "coding"],
        model="claude-3-opus",
        provider="anthropic",
    )
    coordinator.agents["agent-2"] = MockAgentInfo(
        agent_id="agent-2",
        capabilities=["reasoning"],
        model="gpt-4",
        provider="openai",
    )

    # Add sample tasks
    coordinator.tasks["task-1"] = MockTask(
        id="task-1",
        task_type="deliberation",
        status=MockTaskStatus.PENDING,
    )

    return coordinator


@pytest.fixture
def mock_user():
    """Create mock authenticated user."""
    return MockUser()


@pytest.fixture
def control_plane_handler(mock_coordinator):
    """Create ControlPlaneHandler with mock context."""
    ctx = {"control_plane_coordinator": mock_coordinator}
    handler = ControlPlaneHandler(ctx)
    return handler


@pytest.fixture
def authed_handler(control_plane_handler, mock_user):
    """Handler with mocked authentication."""

    def _require_auth(*args, **kwargs):
        return (mock_user, None)

    control_plane_handler.require_auth_or_error = _require_auth
    return control_plane_handler


# ===========================================================================
# Test Routing
# ===========================================================================


class TestControlPlaneHandlerRouting:
    """Tests for ControlPlaneHandler routing."""

    def test_can_handle_control_plane_paths(self, control_plane_handler):
        """Handler should recognize control plane paths."""
        assert control_plane_handler.can_handle("/api/control-plane/agents") is True
        assert control_plane_handler.can_handle("/api/control-plane/tasks") is True
        assert control_plane_handler.can_handle("/api/control-plane/health") is True
        assert control_plane_handler.can_handle("/api/control-plane/stats") is True
        assert control_plane_handler.can_handle("/api/control-plane/queue") is True
        assert control_plane_handler.can_handle("/api/control-plane/metrics") is True

    def test_can_handle_v1_paths(self, control_plane_handler):
        """Handler should recognize v1 versioned paths."""
        assert control_plane_handler.can_handle("/api/v1/control-plane/agents") is True
        assert control_plane_handler.can_handle("/api/v1/control-plane/tasks") is True
        assert control_plane_handler.can_handle("/api/v1/control-plane/health") is True

    def test_cannot_handle_non_control_plane_paths(self, control_plane_handler):
        """Handler should not recognize non-control-plane paths."""
        assert control_plane_handler.can_handle("/api/debates") is False
        assert control_plane_handler.can_handle("/api/agents") is False
        assert control_plane_handler.can_handle("/api/v1/billing") is False

    def test_normalize_path_v1(self, control_plane_handler):
        """Should normalize v1 paths to legacy form."""
        assert (
            control_plane_handler._normalize_path("/api/v1/control-plane/agents")
            == "/api/control-plane/agents"
        )
        assert (
            control_plane_handler._normalize_path("/api/v1/control-plane") == "/api/control-plane"
        )

    def test_normalize_path_legacy(self, control_plane_handler):
        """Should leave legacy paths unchanged."""
        assert (
            control_plane_handler._normalize_path("/api/control-plane/agents")
            == "/api/control-plane/agents"
        )


# ===========================================================================
# Test Agent Endpoints (GET)
# ===========================================================================


class TestListAgents:
    """Tests for GET /api/control-plane/agents."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_list_agents_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should list all agents."""
        http_handler = make_mock_handler()

        result = authed_handler._handle_list_agents({})

        assert get_status(result) == 200
        body = get_body(result)
        assert "agents" in body
        assert "total" in body
        assert body["total"] == 2

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_list_agents_with_capability_filter(self, mock_perm, authed_handler, mock_coordinator):
        """Should filter agents by capability."""
        result = authed_handler._handle_list_agents({"capability": "coding"})

        assert get_status(result) == 200
        body = get_body(result)
        assert body["total"] == 1

    def test_list_agents_no_coordinator(self, control_plane_handler):
        """Should return 503 when coordinator not initialized."""
        control_plane_handler.ctx = {}
        ControlPlaneHandler.coordinator = None

        result = control_plane_handler._handle_list_agents({})

        assert get_status(result) == 503


class TestGetAgent:
    """Tests for GET /api/control-plane/agents/:id."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_agent_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should get specific agent."""
        result = authed_handler._handle_get_agent("agent-1")

        assert get_status(result) == 200
        body = get_body(result)
        assert body["agent_id"] == "agent-1"

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_agent_not_found(self, mock_perm, authed_handler, mock_coordinator):
        """Should return 404 for unknown agent."""
        result = authed_handler._handle_get_agent("nonexistent")

        assert get_status(result) == 404


# ===========================================================================
# Test Agent Endpoints (POST/DELETE)
# ===========================================================================


class TestRegisterAgent:
    """Tests for POST /api/control-plane/agents."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_register_agent_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should register new agent."""
        http_handler = make_mock_handler(
            body={
                "agent_id": "new-agent",
                "capabilities": ["reasoning"],
                "model": "gemini-pro",
                "provider": "google",
            }
        )

        result = authed_handler._handle_register_agent(
            {
                "agent_id": "new-agent",
                "capabilities": ["reasoning"],
                "model": "gemini-pro",
                "provider": "google",
            },
            http_handler,
        )

        assert get_status(result) == 201
        body = get_body(result)
        assert body["agent_id"] == "new-agent"
        assert "new-agent" in mock_coordinator.agents

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_register_agent_missing_id(self, mock_perm, authed_handler):
        """Should return 400 when agent_id missing."""
        http_handler = make_mock_handler(body={"capabilities": ["reasoning"]})

        result = authed_handler._handle_register_agent(
            {"capabilities": ["reasoning"]}, http_handler
        )

        assert get_status(result) == 400

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=False)
    def test_register_agent_permission_denied(self, mock_perm, authed_handler):
        """Should return 403 when permission denied."""
        http_handler = make_mock_handler(body={"agent_id": "new-agent"})

        result = authed_handler._handle_register_agent({"agent_id": "new-agent"}, http_handler)

        assert get_status(result) == 403


class TestUnregisterAgent:
    """Tests for DELETE /api/control-plane/agents/:id."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_unregister_agent_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should unregister existing agent."""
        http_handler = make_mock_handler()

        result = authed_handler._handle_unregister_agent("agent-1", http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert body["unregistered"] is True
        assert "agent-1" not in mock_coordinator.agents

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_unregister_agent_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown agent."""
        http_handler = make_mock_handler()

        result = authed_handler._handle_unregister_agent("nonexistent", http_handler)

        assert get_status(result) == 404


class TestHeartbeat:
    """Tests for POST /api/control-plane/agents/:id/heartbeat."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    @patch("aragora.control_plane.registry.AgentStatus")
    def test_heartbeat_success(self, mock_status, mock_perm, authed_handler, mock_coordinator):
        """Should process heartbeat."""
        mock_status.return_value = MockAgentStatus.AVAILABLE
        http_handler = make_mock_handler(body={"status": "available"})

        result = authed_handler._handle_heartbeat("agent-1", {"status": "available"}, http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert body["acknowledged"] is True

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_heartbeat_agent_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown agent."""
        http_handler = make_mock_handler(body={})

        result = authed_handler._handle_heartbeat("nonexistent", {}, http_handler)

        assert get_status(result) == 404


# ===========================================================================
# Test Task Endpoints (GET)
# ===========================================================================


class TestGetTask:
    """Tests for GET /api/control-plane/tasks/:id."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_task_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should get specific task."""
        result = authed_handler._handle_get_task("task-1")

        assert get_status(result) == 200
        body = get_body(result)
        assert body["id"] == "task-1"

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_task_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown task."""
        result = authed_handler._handle_get_task("nonexistent")

        assert get_status(result) == 404


# ===========================================================================
# Test Task Endpoints (POST)
# ===========================================================================


class TestSubmitTask:
    """Tests for POST /api/control-plane/tasks."""

    @patch("aragora.control_plane.scheduler.TaskPriority")
    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_submit_task_success(self, mock_perm, mock_priority, authed_handler, mock_coordinator):
        """Should submit new task."""
        mock_priority.__getitem__ = MagicMock(return_value=MockTaskPriority.NORMAL)
        http_handler = make_mock_handler(
            body={
                "task_type": "analysis",
                "payload": {"query": "test"},
                "priority": "normal",
            }
        )

        result = authed_handler._handle_submit_task(
            {
                "task_type": "analysis",
                "payload": {"query": "test"},
                "priority": "normal",
            },
            http_handler,
        )

        assert get_status(result) == 201
        body = get_body(result)
        assert "task_id" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_submit_task_missing_type(self, mock_perm, authed_handler):
        """Should return 400 when task_type missing."""
        http_handler = make_mock_handler(body={"payload": {}})

        result = authed_handler._handle_submit_task({"payload": {}}, http_handler)

        assert get_status(result) == 400

    @patch("aragora.control_plane.scheduler.TaskPriority")
    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_submit_task_invalid_priority(self, mock_perm, mock_priority, authed_handler):
        """Should return 400 for invalid priority."""
        mock_priority.__getitem__ = MagicMock(side_effect=KeyError("INVALID"))
        http_handler = make_mock_handler(body={"task_type": "analysis", "priority": "invalid"})

        result = authed_handler._handle_submit_task(
            {"task_type": "analysis", "priority": "invalid"}, http_handler
        )

        assert get_status(result) == 400


class TestClaimTask:
    """Tests for POST /api/control-plane/tasks/claim."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_claim_task_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should claim available task."""
        http_handler = make_mock_handler(
            body={"agent_id": "agent-1", "capabilities": ["reasoning"]}
        )

        result = authed_handler._handle_claim_task(
            {"agent_id": "agent-1", "capabilities": ["reasoning"]}, http_handler
        )

        assert get_status(result) == 200
        body = get_body(result)
        assert body["task"] is not None

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_claim_task_missing_agent_id(self, mock_perm, authed_handler):
        """Should return 400 when agent_id missing."""
        http_handler = make_mock_handler(body={"capabilities": []})

        result = authed_handler._handle_claim_task({"capabilities": []}, http_handler)

        assert get_status(result) == 400

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_claim_task_no_available(self, mock_perm, authed_handler, mock_coordinator):
        """Should return null task when none available."""
        # Set all tasks to completed
        for task in mock_coordinator.tasks.values():
            task.status = MockTaskStatus.COMPLETED

        http_handler = make_mock_handler(body={"agent_id": "agent-1"})

        result = authed_handler._handle_claim_task({"agent_id": "agent-1"}, http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert body["task"] is None


class TestCompleteTask:
    """Tests for POST /api/control-plane/tasks/:id/complete."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_complete_task_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should complete task."""
        http_handler = make_mock_handler(body={"result": {"answer": "42"}, "agent_id": "agent-1"})

        result = authed_handler._handle_complete_task(
            "task-1",
            {"result": {"answer": "42"}, "agent_id": "agent-1"},
            http_handler,
        )

        assert get_status(result) == 200
        body = get_body(result)
        assert body["completed"] is True

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_complete_task_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown task."""
        http_handler = make_mock_handler(body={"result": {}})

        result = authed_handler._handle_complete_task("nonexistent", {"result": {}}, http_handler)

        assert get_status(result) == 404


class TestFailTask:
    """Tests for POST /api/control-plane/tasks/:id/fail."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_fail_task_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should fail task."""
        http_handler = make_mock_handler(body={"error": "Timeout", "agent_id": "agent-1"})

        result = authed_handler._handle_fail_task(
            "task-1",
            {"error": "Timeout", "agent_id": "agent-1"},
            http_handler,
        )

        assert get_status(result) == 200
        body = get_body(result)
        assert body["failed"] is True

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_fail_task_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown task."""
        http_handler = make_mock_handler(body={"error": "Test"})

        result = authed_handler._handle_fail_task("nonexistent", {"error": "Test"}, http_handler)

        assert get_status(result) == 404


class TestCancelTask:
    """Tests for POST /api/control-plane/tasks/:id/cancel."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_cancel_task_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should cancel task."""
        http_handler = make_mock_handler()

        result = authed_handler._handle_cancel_task("task-1", http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert body["cancelled"] is True

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_cancel_task_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown task."""
        http_handler = make_mock_handler()

        result = authed_handler._handle_cancel_task("nonexistent", http_handler)

        assert get_status(result) == 404


# ===========================================================================
# Test Health Endpoints
# ===========================================================================


class TestSystemHealth:
    """Tests for GET /api/control-plane/health."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_system_health_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should return system health."""
        result = authed_handler._handle_system_health()

        assert get_status(result) == 200
        body = get_body(result)
        assert body["status"] == "healthy"
        assert "agents" in body

    def test_system_health_no_coordinator(self, control_plane_handler):
        """Should return 503 when coordinator not initialized."""
        control_plane_handler.ctx = {}
        ControlPlaneHandler.coordinator = None

        result = control_plane_handler._handle_system_health()

        assert get_status(result) == 503


class TestAgentHealth:
    """Tests for GET /api/control-plane/health/:agent_id."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_agent_health_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should return agent health."""
        result = authed_handler._handle_agent_health("agent-1")

        assert get_status(result) == 200
        body = get_body(result)
        assert "healthy" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_agent_health_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown agent."""
        result = authed_handler._handle_agent_health("nonexistent")

        assert get_status(result) == 404


class TestDetailedHealth:
    """Tests for GET /api/control-plane/health/detailed."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_detailed_health_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should return detailed health."""
        result = authed_handler._handle_detailed_health()

        assert get_status(result) == 200
        body = get_body(result)
        assert "status" in body
        assert "components" in body
        assert "uptime_seconds" in body


class TestCircuitBreakers:
    """Tests for GET /api/control-plane/breakers."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_circuit_breakers_success(self, mock_perm, authed_handler):
        """Should return circuit breakers."""
        result = authed_handler._handle_circuit_breakers()

        assert get_status(result) == 200
        body = get_body(result)
        assert "breakers" in body


class TestQueueMetrics:
    """Tests for GET /api/control-plane/queue/metrics."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_queue_metrics_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should return queue metrics."""
        result = authed_handler._handle_queue_metrics()

        assert get_status(result) == 200
        body = get_body(result)
        assert "pending" in body
        assert "running" in body


# ===========================================================================
# Test Stats and Metrics
# ===========================================================================


class TestStats:
    """Tests for GET /api/control-plane/stats."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_stats_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should return control plane stats."""
        result = authed_handler._handle_stats()

        assert get_status(result) == 200
        body = get_body(result)
        assert "scheduler" in body or "registry" in body


class TestGetQueue:
    """Tests for GET /api/control-plane/queue."""

    @patch("aragora.control_plane.scheduler.TaskStatus")
    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_queue_success(self, mock_perm, mock_status, authed_handler, mock_coordinator):
        """Should return job queue."""
        mock_status.PENDING = MockTaskStatus.PENDING
        mock_status.RUNNING = MockTaskStatus.RUNNING
        mock_coordinator._scheduler.list_by_status = AsyncMock(return_value=[])

        result = authed_handler._handle_get_queue({})

        assert get_status(result) == 200
        body = get_body(result)
        assert "jobs" in body
        assert "total" in body


class TestGetMetrics:
    """Tests for GET /api/control-plane/metrics."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_metrics_success(self, mock_perm, authed_handler, mock_coordinator):
        """Should return dashboard metrics."""
        result = authed_handler._handle_get_metrics()

        assert get_status(result) == 200
        body = get_body(result)
        assert "active_jobs" in body
        assert "agents_available" in body


# ===========================================================================
# Test Notifications
# ===========================================================================


class TestNotifications:
    """Tests for notification endpoints."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_notifications_no_manager(self, mock_perm, authed_handler):
        """Should handle missing notification manager."""
        authed_handler.ctx["notification_manager"] = None

        result = authed_handler._handle_get_notifications({})

        assert get_status(result) == 200
        body = get_body(result)
        assert "notifications" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_notification_stats_no_manager(self, mock_perm, authed_handler):
        """Should handle missing notification manager."""
        authed_handler.ctx["notification_manager"] = None

        result = authed_handler._handle_get_notification_stats()

        assert get_status(result) == 200
        body = get_body(result)
        assert "total_sent" in body


# ===========================================================================
# Test Audit Logs
# ===========================================================================


class TestAuditLogs:
    """Tests for audit log endpoints."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_audit_logs_no_log(self, mock_perm, authed_handler):
        """Should handle missing audit log."""
        authed_handler.ctx["audit_log"] = None
        http_handler = make_mock_handler()

        result = authed_handler._handle_get_audit_logs({}, http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert "entries" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_audit_stats_no_log(self, mock_perm, authed_handler):
        """Should handle missing audit log."""
        authed_handler.ctx["audit_log"] = None

        result = authed_handler._handle_get_audit_stats()

        assert get_status(result) == 200
        body = get_body(result)
        assert "total_entries" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_verify_audit_integrity_no_log(self, mock_perm, authed_handler):
        """Should handle missing audit log."""
        authed_handler.ctx["audit_log"] = None
        http_handler = make_mock_handler()

        result = authed_handler._handle_verify_audit_integrity({}, http_handler)

        assert get_status(result) == 503


# ===========================================================================
# Test Policy Violations
# ===========================================================================


class TestPolicyViolations:
    """Tests for policy violation endpoints."""

    @pytest.fixture
    def mock_policy_store(self):
        """Create mock policy store."""
        store = MagicMock()
        store.list_violations.return_value = [
            {
                "id": "v-1",
                "policy_id": "policy-1",
                "violation_type": "quota_exceeded",
                "status": "open",
            }
        ]
        store.count_violations.return_value = {"quota_exceeded": 1}
        store.update_violation_status.return_value = True
        return store

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_list_violations_no_store(self, mock_perm, authed_handler):
        """Should return 503 when store not available."""
        http_handler = make_mock_handler()

        with patch.object(authed_handler, "_get_policy_store", return_value=None):
            result = authed_handler._handle_list_policy_violations({}, http_handler)

        assert get_status(result) == 503

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_list_violations_success(self, mock_perm, authed_handler, mock_policy_store):
        """Should list policy violations."""
        http_handler = make_mock_handler()

        with patch.object(authed_handler, "_get_policy_store", return_value=mock_policy_store):
            result = authed_handler._handle_list_policy_violations({}, http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert "violations" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_violation_stats_success(self, mock_perm, authed_handler, mock_policy_store):
        """Should return violation statistics."""
        http_handler = make_mock_handler()

        with patch.object(authed_handler, "_get_policy_store", return_value=mock_policy_store):
            result = authed_handler._handle_get_policy_violation_stats(http_handler)

        assert get_status(result) == 200
        body = get_body(result)
        assert "total" in body
        assert "open" in body

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_update_violation_success(self, mock_perm, authed_handler, mock_policy_store):
        """Should update violation status."""
        http_handler = make_mock_handler(body={"status": "resolved"})

        with patch.object(authed_handler, "_get_policy_store", return_value=mock_policy_store):
            result = authed_handler._handle_update_policy_violation(
                "v-1", {"status": "resolved"}, http_handler
            )

        assert get_status(result) == 200
        body = get_body(result)
        assert body["updated"] is True

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_update_violation_invalid_status(self, mock_perm, authed_handler, mock_policy_store):
        """Should reject invalid status."""
        http_handler = make_mock_handler(body={"status": "invalid_status"})

        with patch.object(authed_handler, "_get_policy_store", return_value=mock_policy_store):
            result = authed_handler._handle_update_policy_violation(
                "v-1", {"status": "invalid_status"}, http_handler
            )

        assert get_status(result) == 400

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_update_violation_missing_status(self, mock_perm, authed_handler, mock_policy_store):
        """Should require status field."""
        http_handler = make_mock_handler(body={})

        with patch.object(authed_handler, "_get_policy_store", return_value=mock_policy_store):
            result = authed_handler._handle_update_policy_violation("v-1", {}, http_handler)

        assert get_status(result) == 400


# ===========================================================================
# Test Deliberations
# ===========================================================================


class TestDeliberations:
    """Tests for deliberation endpoints."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_deliberation_not_found(self, mock_perm, authed_handler):
        """Should return 404 for unknown deliberation."""
        http_handler = make_mock_handler()

        with patch(
            "aragora.core.decision_results.get_decision_result_for_org",
            return_value=None,
        ):
            result = authed_handler._handle_get_deliberation("unknown-id", http_handler, SCOPE)

        assert get_status(result) == 404

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_deliberation_success(self, mock_perm, authed_handler):
        """Should return deliberation result."""
        http_handler = make_mock_handler()
        mock_result = {"answer": "42", "confidence": 0.95}

        with patch(
            "aragora.core.decision_results.get_decision_result_for_org",
            return_value=mock_result,
        ):
            result = authed_handler._handle_get_deliberation("req-123", http_handler, SCOPE)

        assert get_status(result) == 200
        body = get_body(result)
        assert body["answer"] == "42"

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_get_deliberation_status(self, mock_perm, authed_handler):
        """Should return deliberation status."""
        http_handler = make_mock_handler()

        with patch(
            "aragora.core.decision_results.get_decision_status_for_org",
            return_value={"status": "running", "progress": 0.5},
        ):
            result = authed_handler._handle_get_deliberation_status("req-123", http_handler, SCOPE)

        assert get_status(result) == 200
        body = get_body(result)
        assert body["status"] == "running"


# ===========================================================================
# Test Authentication
# ===========================================================================


class TestAuthentication:
    """Tests for authentication requirements."""

    def test_unauthenticated_register_agent(self, control_plane_handler):
        """Should require authentication for agent registration."""
        # Mock require_auth_or_error to return error
        control_plane_handler.require_auth_or_error = MagicMock(
            return_value=(None, (json.dumps({"error": "Unauthorized"}).encode(), 401))
        )
        http_handler = make_mock_handler(body={"agent_id": "test"})

        result = control_plane_handler._handle_register_agent({"agent_id": "test"}, http_handler)

        assert get_status(result) == 401

    def test_unauthenticated_submit_task(self, control_plane_handler):
        """Should require authentication for task submission."""
        control_plane_handler.require_auth_or_error = MagicMock(
            return_value=(None, (json.dumps({"error": "Unauthorized"}).encode(), 401))
        )
        http_handler = make_mock_handler(body={"task_type": "test"})

        result = control_plane_handler._handle_submit_task({"task_type": "test"}, http_handler)

        assert get_status(result) == 401


# ===========================================================================
# Test Event Emission
# ===========================================================================


class TestEventEmission:
    """Tests for event emission to stream."""

    def test_emit_event_no_stream(self, authed_handler):
        """Should handle missing stream gracefully."""
        authed_handler.ctx["control_plane_stream"] = None

        # Should not raise
        authed_handler._emit_event("emit_agent_registered", agent_id="test")

    def test_emit_event_with_stream(self, authed_handler):
        """Should emit event when stream available."""
        mock_stream = MagicMock()
        mock_stream.emit_agent_registered = AsyncMock()
        authed_handler.ctx["control_plane_stream"] = mock_stream

        # Schedule emission - won't actually run in sync test
        authed_handler._emit_event("emit_agent_registered", agent_id="test")

        # Stream method should be retrieved
        assert mock_stream.emit_agent_registered is not None


# ===========================================================================
# Test Main Handler Methods
# ===========================================================================


class TestMainHandle:
    """Tests for main handle method routing."""

    def test_handle_returns_none_for_unhandled(self, control_plane_handler):
        """Should return None for unhandled paths."""
        http_handler = make_mock_handler()

        result = control_plane_handler.handle("/api/unhandled", {}, http_handler)

        assert result is None

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_handle_routes_to_list_agents(self, mock_perm, authed_handler):
        """Should route /api/control-plane/agents to list agents."""
        http_handler = make_mock_handler()

        result = authed_handler.handle("/api/control-plane/agents", {}, http_handler)

        assert result is not None
        assert get_status(result) == 200

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_handle_routes_to_get_agent(self, mock_perm, authed_handler):
        """Should route /api/control-plane/agents/:id to get agent."""
        http_handler = make_mock_handler()

        result = authed_handler.handle("/api/control-plane/agents/agent-1", {}, http_handler)

        assert result is not None
        assert get_status(result) == 200


class TestHandleDelete:
    """Tests for DELETE handler routing."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_handle_delete_routes_correctly(self, mock_perm, authed_handler):
        """Should route DELETE /api/control-plane/agents/:id."""
        http_handler = make_mock_handler(method="DELETE")

        result = authed_handler.handle_delete("/api/control-plane/agents/agent-1", {}, http_handler)

        assert result is not None
        assert get_status(result) == 200

    def test_handle_delete_returns_none_for_unhandled(self, control_plane_handler):
        """Should return None for unhandled DELETE paths."""
        http_handler = make_mock_handler(method="DELETE")

        result = control_plane_handler.handle_delete("/api/control-plane/unknown", {}, http_handler)

        assert result is None


class TestHandlePatch:
    """Tests for PATCH handler routing."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_handle_patch_routes_correctly(self, mock_perm, authed_handler):
        """Should route PATCH /api/control-plane/policies/violations/:id."""
        mock_store = MagicMock()
        mock_store.update_violation_status.return_value = True
        http_handler = make_mock_handler(method="PATCH", body={"status": "resolved"})

        with patch.object(authed_handler, "_get_policy_store", return_value=mock_store):
            with patch.object(
                authed_handler,
                "read_json_body_validated",
                return_value=({"status": "resolved"}, None),
            ):
                result = authed_handler.handle_patch(
                    "/api/control-plane/policies/violations/v-1",
                    {},
                    http_handler,
                )

        assert result is not None

    def test_handle_patch_returns_none_for_unhandled(self, control_plane_handler):
        """Should return None for unhandled PATCH paths."""
        http_handler = make_mock_handler(method="PATCH")

        result = control_plane_handler.handle_patch("/api/control-plane/unknown", {}, http_handler)

        assert result is None


# ===========================================================================
# Test Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_handles_coordinator_exception(self, mock_perm, authed_handler, mock_coordinator):
        """Should handle exceptions from coordinator."""
        mock_coordinator.list_agents = AsyncMock(side_effect=RuntimeError("Connection failed"))

        with patch.object(authed_handler, "_get_coordinator", return_value=mock_coordinator):
            result = authed_handler._handle_list_agents({})

        assert get_status(result) == 503

    @patch("aragora.server.handlers.control_plane.has_permission", return_value=True)
    def test_handles_value_error(self, mock_perm, authed_handler, mock_coordinator):
        """Should handle ValueError from coordinator."""
        mock_coordinator.get_agent = AsyncMock(side_effect=ValueError("Invalid ID"))

        with patch.object(authed_handler, "_get_coordinator", return_value=mock_coordinator):
            result = authed_handler._handle_get_agent("bad-id")

        assert get_status(result) == 400
