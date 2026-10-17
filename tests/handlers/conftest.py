"""Fixtures for handler tests."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, NonCallableMock

import pytest

from aragora.rbac.models import AuthorizationContext

# ============================================================================
# Mock side_effect Descriptor Guard
# ============================================================================
#
# Capture the original side_effect property descriptor before any test can
# destroy it.  Some tests incorrectly set MagicMock.side_effect on a CLASS
# (e.g. via ``spec.adapter_class = MagicMock; spec.adapter_class.side_effect = ...``),
# which replaces the property descriptor with a plain value on the class dict,
# breaking list-to-iterator conversion for ALL future MagicMock instances.

_handler_side_effect_descriptor = None
for _klass in NonCallableMock.__mro__:
    if "side_effect" in _klass.__dict__:
        _handler_side_effect_descriptor = _klass.__dict__["side_effect"]
        break


@pytest.fixture(autouse=True)
def _restore_mock_side_effect_descriptor():
    """Restore the side_effect property descriptor after each test.

    Runs before AND after every test in ``tests/handlers/`` to repair the
    ``NonCallableMock.side_effect`` property descriptor if it was destroyed
    by a test that set ``side_effect`` on a mock CLASS instead of an instance.
    """
    # Setup: repair before the test runs
    if _handler_side_effect_descriptor is not None:
        current = NonCallableMock.__dict__.get("side_effect")
        if current is not _handler_side_effect_descriptor:
            NonCallableMock.side_effect = _handler_side_effect_descriptor

    yield

    # Teardown: repair after the test runs
    if _handler_side_effect_descriptor is not None:
        current = NonCallableMock.__dict__.get("side_effect")
        if current is not _handler_side_effect_descriptor:
            NonCallableMock.side_effect = _handler_side_effect_descriptor


# ============================================================================
# RBAC Auto-Bypass Fixture
# ============================================================================


@pytest.fixture(autouse=True)
def mock_auth_for_handler_tests(request, monkeypatch):
    """Bypass RBAC authentication for handler unit tests.

    This autouse fixture patches get_auth_context to return an authenticated
    admin context by default, and patches _get_context_from_args to inject
    context into already-decorated functions.

    To test authentication/authorization behavior specifically, use the
    @pytest.mark.no_auto_auth marker to opt-out of auto-mocking:

        @pytest.mark.no_auto_auth
        def test_unauthenticated_returns_401(handler, mock_http_handler):
            # get_auth_context will NOT be mocked for this test
            result = handler.handle("/api/v1/resource", {}, mock_http_handler)
            assert result.status_code == 401
    """
    # Check if test has opted out of auto-auth
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        yield
        return

    # Create a mock auth context with admin permissions
    mock_auth_ctx = AuthorizationContext(
        user_id="test-user-001",
        user_email="test@example.com",
        org_id="test-org-001",
        roles={"admin", "owner"},
        permissions={"*"},  # Wildcard grants all permissions
    )

    async def mock_get_auth_context(self, request, require_auth=False):
        """Mock get_auth_context that returns admin context."""
        return mock_auth_ctx

    # Patch _get_context_from_args to return mock context when no context found
    try:
        from aragora.rbac import decorators

        original_get_context = decorators._get_context_from_args

        def patched_get_context_from_args(args, kwargs, context_param):
            result = original_get_context(args, kwargs, context_param)
            if result is None:
                return mock_auth_ctx
            return result

        monkeypatch.setattr(decorators, "_get_context_from_args", patched_get_context_from_args)
    except (ImportError, AttributeError):
        pass

    # Bypass @require_permission decorator (from server.handlers.utils.decorators)
    try:
        from aragora.server.handlers.utils import decorators as handler_decorators

        monkeypatch.setattr(handler_decorators, "_test_user_context_override", mock_auth_ctx)
    except (ImportError, AttributeError):
        pass

    # Also bypass has_permission to always grant access
    try:
        from aragora.server.handlers.utils import decorators as handler_decorators

        monkeypatch.setattr(handler_decorators, "has_permission", lambda role, perm: True)
    except (ImportError, AttributeError):
        pass

    # Patch SecureHandler.get_auth_context for handlers extending SecureHandler
    try:
        from aragora.server.handlers.secure import SecureHandler

        monkeypatch.setattr(SecureHandler, "get_auth_context", mock_get_auth_context)
    except (ImportError, AttributeError):
        pass

    # Patch standalone get_auth_context in billing.auth
    try:
        from aragora.billing import auth

        monkeypatch.setattr(auth, "get_auth_context", mock_get_auth_context)
    except (ImportError, AttributeError):
        pass

    # Patch get_auth_context in handlers.utils.auth (used by autonomous handlers, etc.)
    try:
        from aragora.server.handlers.utils import auth as handlers_auth

        async def mock_handlers_get_auth_context(request, require_auth=False):
            """Mock get_auth_context that returns admin context."""
            return mock_auth_ctx

        monkeypatch.setattr(handlers_auth, "get_auth_context", mock_handlers_get_auth_context)
    except (ImportError, AttributeError):
        pass

    # Patch get_auth_context in modules that import it directly (Python caches imports)
    # These modules use "from ... import get_auth_context" so we need to patch where used
    auth_modules_to_patch = [
        "aragora.server.handlers.autonomous.approvals",
        "aragora.server.handlers.autonomous.alerts",
        "aragora.server.handlers.autonomous.triggers",
        "aragora.server.handlers.autonomous.monitoring",
        "aragora.server.handlers.autonomous.learning",
        "aragora.server.handlers.debates.intervention",
    ]

    async def mock_direct_get_auth_context(request, require_auth=False):
        """Mock get_auth_context that returns admin context."""
        return mock_auth_ctx

    for module_path in auth_modules_to_patch:
        try:
            import importlib

            module = importlib.import_module(module_path)
            monkeypatch.setattr(module, "get_auth_context", mock_direct_get_auth_context)
        except (ImportError, AttributeError):
            pass

    # Create a mock UserAuthContext for BaseHandler auth methods
    try:
        from aragora.billing.auth.context import UserAuthContext

        mock_user_ctx = UserAuthContext(
            authenticated=True,
            user_id="test-user-001",
            email="test@example.com",
            org_id="test-org-001",
            role="admin",
            token_type="access",
            client_ip="127.0.0.1",
        )
        # Add extra attributes that some handlers expect (roles plural, permissions)
        # These are accessed via getattr in KnowledgeHandler._check_permission
        object.__setattr__(mock_user_ctx, "roles", ["admin", "owner"])
        object.__setattr__(
            mock_user_ctx,
            "permissions",
            ["*", "admin", "knowledge.read", "knowledge.write", "knowledge.delete"],
        )

        # Patch BaseHandler auth methods
        from aragora.server.handlers.base import BaseHandler

        def mock_require_auth_or_error(self, handler):
            """Mock require_auth_or_error that returns authenticated user."""
            return mock_user_ctx, None

        def mock_require_admin_or_error(self, handler):
            """Mock require_admin_or_error that returns admin user."""
            return mock_user_ctx, None

        def mock_get_current_user(self, handler):
            """Mock get_current_user that returns authenticated user."""
            return mock_user_ctx

        monkeypatch.setattr(BaseHandler, "require_auth_or_error", mock_require_auth_or_error)
        monkeypatch.setattr(BaseHandler, "require_admin_or_error", mock_require_admin_or_error)
        monkeypatch.setattr(BaseHandler, "get_current_user", mock_get_current_user)

        # Also patch _check_permission to bypass permission checks in tests
        # This handles KnowledgeHandler and similar handlers that do inline permission checks
        def mock_check_permission(self, handler, permission):
            """Mock _check_permission that always allows access."""
            return None  # None means no error, permission granted

        # Patch KnowledgeHandler._check_permission if it exists
        try:
            from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

            monkeypatch.setattr(KnowledgeHandler, "_check_permission", mock_check_permission)
        except (ImportError, AttributeError):
            pass

    except (ImportError, AttributeError):
        pass

    yield mock_auth_ctx


@pytest.fixture
def org_scoped_request_user(request, monkeypatch):
    """Authenticate org-scoped handler requests as test-user-001 of test-org-001.

    Handlers that scope records with ``aragora.tenancy.record_scope.require_org_scope``
    identify the caller through ``aragora.billing.jwt_auth.extract_user_from_request``,
    which ``mock_auth_for_handler_tests`` does not patch. Opt in per module with
    ``pytestmark = pytest.mark.usefixtures("org_scoped_request_user")``; tests marked
    ``no_auto_auth`` stay anonymous.
    """
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        yield None
        return

    from aragora.billing.auth.context import UserAuthContext

    user = UserAuthContext(
        authenticated=True,
        user_id="test-user-001",
        email="test@example.com",
        org_id="test-org-001",
        role="admin",
        token_type="access",
    )
    monkeypatch.setattr(
        "aragora.billing.jwt_auth.extract_user_from_request",
        lambda handler, user_store=None: user,
    )
    yield user


class AgentStatus(Enum):
    """Mock agent status enum."""

    IDLE = "idle"
    BUSY = "busy"
    OFFLINE = "offline"


class TaskStatus(Enum):
    """Mock task status enum."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskPriority(Enum):
    """Mock task priority enum."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class HealthStatus(Enum):
    """Mock health status enum."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class MockAgentInfo:
    """Mock agent info."""

    agent_id: str
    capabilities: list[str]
    model: str
    provider: str
    status: AgentStatus
    last_heartbeat: datetime
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capabilities": self.capabilities,
            "model": self.model,
            "provider": self.provider,
            "status": self.status.value,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class MockTask:
    """Mock task."""

    task_id: str
    task_type: str
    payload: dict[str, Any]
    status: TaskStatus
    priority: TaskPriority
    required_capabilities: list[str]
    assigned_agent: str | None
    result: Any | None
    error: str | None
    created_at: datetime
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "payload": self.payload,
            "status": self.status.value,
            "priority": self.priority.value,
            "required_capabilities": self.required_capabilities,
            "assigned_agent": self.assigned_agent,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class MockHealthCheck:
    """Mock health check."""

    agent_id: str
    status: HealthStatus
    last_check: datetime
    latency_ms: float
    error_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "last_check": self.last_check.isoformat(),
            "latency_ms": self.latency_ms,
            "error_rate": self.error_rate,
        }


class MockCoordinator:
    """Mock control plane coordinator for testing."""

    def __init__(self):
        self._agents: dict[str, MockAgentInfo] = {}
        self._tasks: dict[str, MockTask] = {}
        self._health: dict[str, MockHealthCheck] = {}
        self._health_monitor = MagicMock()
        self._health_monitor.get_all_health.return_value = {}

    async def register_agent(
        self,
        agent_id: str,
        capabilities: list[str],
        model: str,
        provider: str,
        metadata: dict[str, Any] = None,
    ) -> MockAgentInfo:
        """Register an agent."""
        agent = MockAgentInfo(
            agent_id=agent_id,
            capabilities=capabilities,
            model=model,
            provider=provider,
            status=AgentStatus.IDLE,
            last_heartbeat=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self._agents[agent_id] = agent
        return agent

    async def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent."""
        if agent_id in self._agents:
            del self._agents[agent_id]
            return True
        return False

    async def get_agent(self, agent_id: str) -> MockAgentInfo | None:
        """Get agent by ID."""
        return self._agents.get(agent_id)

    async def list_agents(
        self,
        capability: str | None = None,
        only_available: bool = True,
    ) -> list[MockAgentInfo]:
        """List agents."""
        agents = list(self._agents.values())
        if capability:
            agents = [a for a in agents if capability in a.capabilities]
        if only_available:
            agents = [a for a in agents if a.status != AgentStatus.OFFLINE]
        return agents

    async def heartbeat(self, agent_id: str, status: AgentStatus | None = None) -> bool:
        """Process agent heartbeat."""
        agent = self._agents.get(agent_id)
        if not agent:
            return False
        agent.last_heartbeat = datetime.now(timezone.utc)
        if status:
            agent.status = status
        return True

    async def submit_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        required_capabilities: list[str] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout_seconds: int | None = None,
        metadata: dict[str, Any] = None,
    ) -> str:
        """Submit a task."""
        import uuid

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = MockTask(
            task_id=task_id,
            task_type=task_type,
            payload=payload,
            status=TaskStatus.PENDING,
            priority=priority,
            required_capabilities=required_capabilities or [],
            assigned_agent=None,
            result=None,
            error=None,
            created_at=datetime.now(timezone.utc),
            metadata=metadata or {},
        )
        self._tasks[task_id] = task
        return task_id

    async def get_task(self, task_id: str) -> MockTask | None:
        """Get task by ID."""
        return self._tasks.get(task_id)

    async def claim_task(
        self,
        agent_id: str,
        capabilities: list[str],
        block_ms: int = 5000,
    ) -> MockTask | None:
        """Claim a task for an agent."""
        for task in self._tasks.values():
            if task.status == TaskStatus.PENDING:
                # Check capabilities match
                if not task.required_capabilities or any(
                    c in capabilities for c in task.required_capabilities
                ):
                    task.status = TaskStatus.RUNNING
                    task.assigned_agent = agent_id
                    return task
        return None

    async def complete_task(
        self,
        task_id: str,
        result: Any = None,
        agent_id: str | None = None,
        latency_ms: float | None = None,
    ) -> bool:
        """Complete a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        task.status = TaskStatus.COMPLETED
        task.result = result
        return True

    async def fail_task(
        self,
        task_id: str,
        error: str,
        agent_id: str | None = None,
        latency_ms: float | None = None,
        requeue: bool = True,
    ) -> bool:
        """Fail a task."""
        task = self._tasks.get(task_id)
        if not task:
            return False
        if requeue:
            task.status = TaskStatus.PENDING
            task.assigned_agent = None
        else:
            task.status = TaskStatus.FAILED
        task.error = error
        return True

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task."""
        task = self._tasks.get(task_id)
        if not task or task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return False
        task.status = TaskStatus.CANCELLED
        return True

    def get_system_health(self) -> HealthStatus:
        """Get overall system health."""
        if not self._agents:
            return HealthStatus.DEGRADED
        healthy_count = sum(1 for h in self._health.values() if h.status == HealthStatus.HEALTHY)
        if healthy_count == 0:
            return HealthStatus.UNHEALTHY
        if healthy_count < len(self._agents):
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def get_agent_health(self, agent_id: str) -> MockHealthCheck | None:
        """Get agent health."""
        return self._health.get(agent_id)

    async def get_stats(self) -> dict[str, Any]:
        """Get control plane statistics."""
        return {
            "agents": {
                "total": len(self._agents),
                "idle": sum(1 for a in self._agents.values() if a.status == AgentStatus.IDLE),
                "busy": sum(1 for a in self._agents.values() if a.status == AgentStatus.BUSY),
            },
            "tasks": {
                "total": len(self._tasks),
                "pending": sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING),
                "running": sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING),
                "completed": sum(
                    1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED
                ),
            },
        }


class MockRequest:
    """Mock HTTP request."""

    def __init__(
        self,
        method: str = "GET",
        path: str = "/",
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ):
        self.method = method
        self.path = path
        self.query = query or {}
        self._body = body

    async def json(self) -> dict[str, Any]:
        """Get JSON body."""
        return self._body or {}

    async def body(self) -> bytes:
        """Get raw body."""
        import json

        return json.dumps(self._body or {}).encode()


class MockHandler:
    """Mock HTTP handler for testing."""

    def __init__(self, body: dict[str, Any] | None = None):
        self.rfile = MagicMock()
        self._body = body
        if body:
            import json

            body_bytes = json.dumps(body).encode()
            self.rfile.read.return_value = body_bytes
            self.headers = {"Content-Length": str(len(body_bytes))}
        else:
            self.rfile.read.return_value = b"{}"
            self.headers = {"Content-Length": "2"}


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    return MockCoordinator()


@pytest.fixture
def mock_request():
    """Factory for creating mock requests."""

    def _create_request(
        method: str = "GET",
        path: str = "/",
        query: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> MockRequest:
        return MockRequest(method=method, path=path, query=query, body=body)

    return _create_request


@pytest.fixture
def mock_handler():
    """Factory for creating mock handlers."""

    def _create_handler(body: dict[str, Any] | None = None) -> MockHandler:
        return MockHandler(body=body)

    return _create_handler


# ============================================================================
# SAST Scanner Isolation
# ============================================================================


@pytest.fixture(autouse=True)
def _mock_sast_scanner(monkeypatch):
    """Prevent real SAST file scanning during handler tests.

    The SASTScanner performs synchronous file I/O across the entire repo
    (thousands of files) which causes hangs when the full handler test suite
    runs together.  This fixture mocks the scanning entry points to return
    empty results immediately.
    """
    try:
        from aragora.analysis.codebase.sast import scanner as sast_mod

        mock_scanner = AsyncMock()
        mock_scanner.initialize = AsyncMock()
        mock_scanner.scan_repository = AsyncMock(
            return_value=MagicMock(
                findings=[],
                scanned_files=0,
                skipped_files=0,
                scan_duration_ms=0,
                languages_detected=[],
                rules_used=[],
                errors=[],
            )
        )
        mock_scanner.scan_file = AsyncMock(return_value=[])
        monkeypatch.setattr(sast_mod, "get_sast_scanner", lambda: mock_scanner)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.server.handlers.features.codebase_audit import scanning

        for fn_name in (
            "run_sast_scan",
            "run_bug_scan",
            "run_secrets_scan",
            "run_dependency_scan",
            "run_metrics_analysis",
        ):
            mock_fn_name = f"_get_mock_{fn_name.removeprefix('run_')}"
            fallback = getattr(scanning, mock_fn_name, None)
            if fallback and hasattr(scanning, fn_name):

                async def _mock(tp, sid, tid, _fb=fallback, _sid_ref=fn_name, **kw):
                    return _fb(sid)

                monkeypatch.setattr(scanning, fn_name, _mock)
    except (ImportError, AttributeError):
        pass
