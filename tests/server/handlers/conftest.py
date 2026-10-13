"""
Shared fixtures for server handler tests.

This module provides common fixtures for testing HTTP handlers,
reducing duplication and ensuring consistent test setup.

Common patterns:
    @pytest.fixture
    def handler(mock_server_context):
        from aragora.server.handlers.example import ExampleHandler
        return ExampleHandler(server_context=mock_server_context)

    def test_can_handle_route(handler):
        assert handler.can_handle("/api/v1/example") is True

    def test_endpoint(handler, mock_http_handler):
        result = handler.handle("/api/v1/example", {}, mock_http_handler, "GET")
        assert result.status_code == 200
        body = parse_handler_response(result)
        assert "data" in body
"""

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional, cast
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from aragora.rbac.models import AuthorizationContext

if TYPE_CHECKING:
    from aragora.server.handlers.base import BaseHandler


# ============================================================================
# RBAC Auto-Bypass Helpers
# ============================================================================


def _patch_handler_rbac(monkeypatch, mock_user_ctx):
    """Patch all three RBAC systems used by handlers.

    1. server.handlers.utils.decorators.require_permission - test hook + has_permission
    2. aragora.rbac.checker.PermissionChecker - check_permission always allows
    3. aragora.rbac.enforcer.RBACEnforcer - check/require always allows
    """
    # 1. Patch handler-level require_permission decorator
    try:
        from aragora.server.handlers.utils import decorators as handler_decorators

        monkeypatch.setattr(handler_decorators, "_test_user_context_override", mock_user_ctx)
        monkeypatch.setattr(handler_decorators, "has_permission", lambda role, perm: True)
    except (ImportError, AttributeError):
        pass

    # 2. Patch aragora.rbac PermissionChecker
    try:
        from aragora.rbac.checker import get_permission_checker
        from aragora.rbac.models import AuthorizationDecision

        checker = get_permission_checker()

        def _checker_allow(context, permission_key, resource_id=None):
            from datetime import datetime

            return AuthorizationDecision(
                allowed=True,
                reason="Test bypass",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
                checked_at=datetime.now(),
                cached=False,
            )

        monkeypatch.setattr(checker, "check_permission", _checker_allow)
    except (ImportError, AttributeError):
        pass

    # 3. Patch RBACEnforcer class methods
    try:
        from aragora.rbac.enforcer import RBACEnforcer

        async def _enforcer_check(self, *args, **kwargs):
            return True

        async def _enforcer_require(self, *args, **kwargs):
            pass

        monkeypatch.setattr(RBACEnforcer, "check", _enforcer_check)
        monkeypatch.setattr(RBACEnforcer, "require", _enforcer_require)
    except (ImportError, AttributeError):
        pass


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

    async def mock_get_auth_context(request, require_auth=False):
        """Mock get_auth_context that returns admin context."""
        return mock_auth_ctx

    # Patch _get_context_from_args to return mock context when no context found
    # This is critical for functions that are already decorated at import time
    try:
        from aragora.rbac import decorators

        original_get_context = decorators._get_context_from_args

        def patched_get_context_from_args(args, kwargs, context_param):
            """Return mock context if no real context found."""
            result = original_get_context(args, kwargs, context_param)
            if result is None:
                return mock_auth_ctx
            return result

        monkeypatch.setattr(decorators, "_get_context_from_args", patched_get_context_from_args)
    except (ImportError, AttributeError):
        pass

    # Patch get_auth_context at various locations
    try:
        from aragora.server.handlers.utils import auth as utils_auth

        monkeypatch.setattr(utils_auth, "get_auth_context", mock_get_auth_context)
    except (ImportError, AttributeError):
        pass

    try:
        from aragora.server.handlers import secure

        monkeypatch.setattr(secure, "get_auth_context", mock_get_auth_context)
    except (ImportError, AttributeError):
        pass

    # Patch autonomous handlers which import get_auth_context directly
    autonomous_modules = ["triggers", "alerts", "approvals", "learning", "monitoring"]
    for mod_name in autonomous_modules:
        try:
            from aragora.server.handlers import autonomous

            mod = getattr(autonomous, mod_name, None)
            if mod and hasattr(mod, "get_auth_context"):
                monkeypatch.setattr(mod, "get_auth_context", mock_get_auth_context)
        except (ImportError, AttributeError):
            pass

    # Patch extract_user_from_request for JWT-based user auth (separate from RBAC)
    # This fixes tests that use require_auth_or_error() / get_current_user()
    try:
        from aragora.billing.auth.context import UserAuthContext

        mock_user_ctx = UserAuthContext(
            authenticated=True,
            user_id="test-user-001",
            email="test@example.com",
            org_id="test-org-001",
            role="admin",
            token_type="access",
        )
        # Add permissions and roles for _check_permission in handlers
        mock_user_ctx.permissions = {
            "*",
            "admin",
            "knowledge.read",
            "knowledge.write",
            "knowledge.delete",
        }  # type: ignore[attr-defined]
        mock_user_ctx.roles = {"admin", "owner"}  # type: ignore[attr-defined]

        def mock_extract_user(handler, user_store=None):
            """Mock extract_user_from_request returning authenticated context."""
            return mock_user_ctx

        # Patch at the source module
        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            mock_extract_user,
        )
    except (ImportError, AttributeError):
        pass  # UserAuthContext may not be available in all test contexts

    # Patch all RBAC/auth systems for handler tests.
    # 1. require_permission from server.handlers.utils.decorators
    # 2. PermissionChecker from aragora.rbac.checker
    # 3. RBACEnforcer from aragora.rbac.enforcer
    _patch_handler_rbac(monkeypatch, mock_user_ctx)

    yield mock_auth_ctx


# ============================================================================
# RBAC Checker and Enforcer Bypass
# ============================================================================


@pytest.fixture(autouse=True)
def _bypass_rbac_checker_and_enforcer(request, monkeypatch):
    """Bypass aragora.rbac PermissionChecker and RBACEnforcer for handler tests.

    This is separate from mock_auth_for_handler_tests because that fixture
    handles the server.handlers.utils.decorators RBAC, while this handles
    the aragora.rbac module's PermissionChecker and RBACEnforcer.
    """
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        yield
        return

    # Patch PermissionChecker.check_permission to always allow
    try:
        from aragora.rbac.checker import get_permission_checker
        from aragora.rbac.models import AuthorizationDecision

        checker = get_permission_checker()

        def _always_allow(context, permission_key, resource_id=None):
            from datetime import datetime

            return AuthorizationDecision(
                allowed=True,
                reason="Test bypass",
                permission_key=permission_key,
                resource_id=resource_id,
                context=context,
                checked_at=datetime.now(),
                cached=False,
            )

        monkeypatch.setattr(checker, "check_permission", _always_allow)
    except (ImportError, AttributeError):
        pass

    # Patch RBACEnforcer methods to always allow
    try:
        from aragora.rbac.enforcer import RBACEnforcer

        async def _enforcer_check(self, *args, **kwargs):
            return True

        async def _enforcer_require(self, *args, **kwargs):
            pass

        monkeypatch.setattr(RBACEnforcer, "check", _enforcer_check)
        monkeypatch.setattr(RBACEnforcer, "require", _enforcer_require)
    except (ImportError, AttributeError):
        pass

    yield


# ============================================================================
# Cache Clearing Fixture
# ============================================================================


@pytest.fixture(autouse=True)
def clear_handler_cache():
    """Clear handler TTL cache and class-level attributes before each test.

    This prevents cached results from previous tests from interfering.
    Also clears class-level attributes like elo_system that unified_server sets.
    """
    try:
        from aragora.server.handlers.admin.cache import clear_cache

        clear_cache()  # Clear all cache entries
    except ImportError:
        pass

    # Clear class-level elo_system that might be set by unified_server
    try:
        from aragora.server.handlers.base import BaseHandler

        if hasattr(BaseHandler, "elo_system"):
            BaseHandler.elo_system = None
    except ImportError:
        pass

    yield

    # Also clear after test
    try:
        from aragora.server.handlers.admin.cache import clear_cache

        clear_cache()
    except ImportError:
        pass


# ============================================================================
# Response Helpers
# ============================================================================


def parse_handler_response(result) -> dict[str, Any]:
    """Parse JSON body from a HandlerResult.

    Args:
        result: HandlerResult with body attribute

    Returns:
        Parsed JSON dict, or empty dict if parsing fails

    Example:
        result = handler.handle("/api/v1/test", {}, mock_http, "GET")
        body = parse_handler_response(result)
        assert body["status"] == "ok"
    """
    if result is None:
        return {}
    try:
        body = result.body
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        return json.loads(body) if body else {}
    except (json.JSONDecodeError, AttributeError):
        return {}


def assert_success_response(result, expected_keys: list[str] | None = None):
    """Assert that a handler result is a successful JSON response.

    Args:
        result: HandlerResult to check
        expected_keys: Optional list of keys that should be in response

    Raises:
        AssertionError: If response is not successful or missing keys
    """
    assert result is not None, "Result should not be None"
    assert result.status_code == 200, f"Expected 200, got {result.status_code}"
    assert result.content_type == "application/json"

    if expected_keys:
        body = parse_handler_response(result)
        for key in expected_keys:
            assert key in body, f"Expected key '{key}' in response"


def assert_error_response(result, expected_status: int, error_substring: str | None = None):
    """Assert that a handler result is an error response.

    Args:
        result: HandlerResult to check
        expected_status: Expected HTTP status code
        error_substring: Optional substring to look for in error message
    """
    assert result is not None, "Result should not be None"
    assert result.status_code == expected_status, (
        f"Expected {expected_status}, got {result.status_code}"
    )

    if error_substring:
        body = parse_handler_response(result)
        error_msg = body.get("error", "") or body.get("message", "")
        assert error_substring.lower() in error_msg.lower(), (
            f"Expected '{error_substring}' in error message: {error_msg}"
        )


# ============================================================================
# HTTP Handler Mocks
# ============================================================================


@dataclass
class MockHTTPRequest:
    """Mock HTTP request for handler testing."""

    method: str = "GET"
    path: str = "/"
    headers: dict[str, str] | None = None
    body: bytes = b"{}"
    query_params: dict[str, str] | None = None

    def __post_init__(self):
        if self.headers is None:
            self.headers = {"Content-Length": str(len(self.body))}
        else:
            self.headers.setdefault("Content-Length", str(len(self.body)))
        if self.query_params is None:
            self.query_params = {}


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler for handler testing.

    Returns:
        Factory function to create mock HTTP handlers.

    Example:
        def test_post_endpoint(handler, mock_http_handler):
            http = mock_http_handler(
                method="POST",
                body={"name": "test"},
                headers={"Authorization": "Bearer token123"}
            )
            result = handler.handle("/api/v1/resource", {}, http, "POST")
    """

    def _create_handler(
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        client_address: tuple = ("127.0.0.1", 12345),
    ) -> MagicMock:
        mock = MagicMock()
        mock.command = method

        # Set up body reading
        if body is not None:
            body_bytes = json.dumps(body).encode()
        else:
            body_bytes = b"{}"

        mock.rfile = MagicMock()
        mock.rfile.read = MagicMock(return_value=body_bytes)

        # Set up headers
        mock.headers = headers or {}
        mock.headers.setdefault("Content-Length", str(len(body_bytes)))

        # Set up client address
        mock.client_address = client_address

        return mock

    return _create_handler


@pytest.fixture
def mock_http_get(mock_http_handler):
    """Convenience fixture for GET requests."""
    return mock_http_handler(method="GET")


@pytest.fixture
def mock_http_post(mock_http_handler):
    """Convenience fixture for POST requests with empty body."""
    return mock_http_handler(method="POST", body={})


# ============================================================================
# Server Context Fixtures
# ============================================================================


@pytest.fixture
def mock_debate_storage():
    """Create a mock DebateStorage for handler testing.

    Returns:
        Mock storage with common methods pre-configured.
    """
    storage = MagicMock()

    # List debates
    storage.list_debates.return_value = [
        {
            "id": "debate-001",
            "slug": "test-debate-one",
            "task": "Test task one",
            "created_at": "2026-01-15T10:00:00Z",
            "consensus_reached": False,
        },
        {
            "id": "debate-002",
            "slug": "test-debate-two",
            "task": "Test task two",
            "created_at": "2026-01-14T10:00:00Z",
            "consensus_reached": True,
        },
    ]

    # Get single debate
    storage.get_debate.return_value = {
        "id": "debate-001",
        "slug": "test-debate-one",
        "task": "Test task one",
        "messages": [
            {"agent": "claude", "content": "Initial proposal", "round": 1},
            {"agent": "gemini", "content": "Critique of proposal", "round": 1},
        ],
        "critiques": [],
        "votes": [],
        "consensus_reached": False,
        "rounds_used": 3,
        "created_at": "2026-01-15T10:00:00Z",
    }
    storage.get_debate_by_slug.return_value = storage.get_debate.return_value

    # Search
    storage.search.return_value = storage.list_debates.return_value

    # Public/private
    storage.is_public.return_value = True

    # Save operations
    storage.save_debate.return_value = "debate-new"
    storage.update_debate.return_value = True
    storage.delete_debate.return_value = True

    return storage


@pytest.fixture
def mock_user_store():
    """Create a mock UserStore for handler testing.

    Returns:
        Mock user store with common authentication methods.
    """
    store = MagicMock()

    # User retrieval
    store.get_user.return_value = {
        "user_id": "user-001",
        "email": "test@example.com",
        "username": "testuser",
        "created_at": "2026-01-01T00:00:00Z",
        "is_active": True,
    }
    store.get_user_by_email.return_value = store.get_user.return_value
    store.get_user_by_username.return_value = store.get_user.return_value

    # Authentication
    store.verify_password.return_value = True
    store.create_session.return_value = "session-token-123"
    store.validate_session.return_value = store.get_user.return_value

    # User creation
    store.create_user.return_value = "user-new"
    store.update_user.return_value = True
    store.delete_user.return_value = True

    return store


@pytest.fixture
def mock_elo_system():
    """Create a mock ELO system for handler testing.

    Returns:
        Mock ELO system with leaderboard and rating methods.
    """
    elo = MagicMock()

    # Mock rating object
    mock_rating = MagicMock()
    mock_rating.agent_name = "claude"
    mock_rating.elo = 1650
    mock_rating.wins = 10
    mock_rating.losses = 5
    mock_rating.draws = 3
    mock_rating.games_played = 18
    mock_rating.win_rate = 0.56

    # Methods
    elo.get_rating.return_value = mock_rating
    elo.get_leaderboard.return_value = [mock_rating]
    elo.get_cached_leaderboard.return_value = [
        {
            "agent_name": "claude",
            "elo": 1650,
            "wins": 10,
            "losses": 5,
            "draws": 3,
            "games_played": 18,
            "win_rate": 0.56,
        },
        {
            "agent_name": "gemini",
            "elo": 1580,
            "wins": 8,
            "losses": 7,
            "draws": 2,
            "games_played": 17,
            "win_rate": 0.47,
        },
    ]
    elo.get_recent_matches.return_value = []
    elo.get_head_to_head.return_value = {
        "matches": 5,
        "agent_a_wins": 3,
        "agent_b_wins": 2,
        "draws": 0,
    }
    elo.record_match.return_value = None

    return elo


@pytest.fixture
def mock_knowledge_store():
    """Create a mock KnowledgeStore for handler testing.

    Returns:
        Mock knowledge store with fact/mound operations.
    """
    store = MagicMock()

    # Facts
    store.list_facts.return_value = [
        {
            "fact_id": "fact-001",
            "content": "Test fact one",
            "source": "debate-001",
            "confidence": 0.95,
            "created_at": "2026-01-15T10:00:00Z",
        },
    ]
    store.get_fact.return_value = store.list_facts.return_value[0]
    store.add_fact.return_value = "fact-new"
    store.update_fact.return_value = True
    store.delete_fact.return_value = True

    # Search
    store.search_facts.return_value = store.list_facts.return_value

    return store


@pytest.fixture
def mock_workflow_store():
    """Create a mock WorkflowStore for handler testing."""
    store = MagicMock()

    store.list_workflows.return_value = [
        {
            "workflow_id": "wf-001",
            "name": "Test Workflow",
            "status": "active",
            "created_at": "2026-01-15T10:00:00Z",
        },
    ]
    store.get_workflow.return_value = store.list_workflows.return_value[0]
    store.create_workflow.return_value = "wf-new"
    store.update_workflow.return_value = True
    store.delete_workflow.return_value = True

    return store


@pytest.fixture
def mock_workspace_store():
    """Create a mock WorkspaceStore for handler testing."""
    store = MagicMock()

    store.list_workspaces.return_value = [
        {
            "workspace_id": "ws-001",
            "name": "Test Workspace",
            "owner_id": "user-001",
            "created_at": "2026-01-15T10:00:00Z",
        },
    ]
    store.get_workspace.return_value = store.list_workspaces.return_value[0]
    store.create_workspace.return_value = "ws-new"
    store.update_workspace.return_value = True
    store.delete_workspace.return_value = True

    return store


@pytest.fixture
def mock_audit_store():
    """Create a mock AuditStore for handler testing."""
    store = MagicMock()

    store.list_events.return_value = [
        {
            "event_id": "evt-001",
            "event_type": "debate.created",
            "actor_id": "user-001",
            "resource_id": "debate-001",
            "timestamp": "2026-01-15T10:00:00Z",
        },
    ]
    store.get_event.return_value = store.list_events.return_value[0]
    store.log_event.return_value = "evt-new"

    return store


@pytest.fixture
def mock_server_context(
    mock_debate_storage,
    mock_user_store,
    mock_elo_system,
    mock_knowledge_store,
    mock_workflow_store,
    mock_workspace_store,
    mock_audit_store,
):
    """Create a complete server context with all mock dependencies.

    This provides the standard server_context dict used by handlers.

    Example:
        @pytest.fixture
        def handler(mock_server_context):
            return MyHandler(server_context=mock_server_context)
    """
    return {
        "storage": mock_debate_storage,
        "user_store": mock_user_store,
        "elo_system": mock_elo_system,
        "knowledge_store": mock_knowledge_store,
        "workflow_store": mock_workflow_store,
        "workspace_store": mock_workspace_store,
        "audit_store": mock_audit_store,
        "debate_embeddings": None,
        "critique_store": None,
        "nomic_dir": None,
    }


# ============================================================================
# RBAC Authorization Context Fixtures
# ============================================================================


@dataclass
class MockAuthorizationContext:
    """Mock authorization context for testing RBAC-protected handlers.

    This mirrors the real AuthorizationContext from aragora.rbac.models.
    """

    user_id: str = "test-user-001"
    user_email: str = "test@example.com"
    org_id: str = "test-org-001"
    workspace_id: str = "test-ws-001"
    roles: list[str] | None = None
    permissions: list[str] | None = None
    api_key_scope: str | None = None
    ip_address: str = "127.0.0.1"
    user_agent: str = "test-agent"
    request_id: str = "req-test-001"
    timestamp: str | None = None

    def __post_init__(self):
        if self.roles is None:
            self.roles = ["admin"]
        if self.permissions is None:
            # Default comprehensive permissions for testing
            self.permissions = [
                "debates:read",
                "debates:write",
                "debates:create",
                "debates:delete",
                "agents:read",
                "agents:write",
                "memory.read",
                "memory.write",
                "knowledge:read",
                "knowledge:write",
                "workflows:read",
                "workflows:write",
                "admin:read",
                "admin:write",
                "billing:read",
                "billing:write",
                "costs.read",
                "costs.write",
                "audit:read",
            ]
        if self.timestamp is None:
            from datetime import datetime

            self.timestamp = datetime.now().isoformat()

    # __post_init__ replaces a None roles/permissions with a list, so both are
    # lists by the time these run; cast() records that without a runtime check.
    def has_permission(self, permission: str) -> bool:
        """Check if context has a specific permission."""
        return permission in cast("list[str]", self.permissions)

    def has_role(self, role: str) -> bool:
        """Check if context has a specific role."""
        return role in cast("list[str]", self.roles)


@pytest.fixture
def mock_auth_context():
    """Create a mock authorization context for RBAC-protected handlers.

    Returns:
        Factory function to create customized auth contexts.

    Example:
        def test_with_admin(mock_auth_context):
            ctx = mock_auth_context(roles=["admin"])
            assert ctx.has_role("admin")

        def test_with_limited_permissions(mock_auth_context):
            ctx = mock_auth_context(permissions=["debates:read"])
            assert not ctx.has_permission("debates:write")
    """

    def _create_context(
        user_id: str = "test-user-001",
        org_id: str = "test-org-001",
        workspace_id: str = "test-ws-001",
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
        **kwargs,
    ) -> MockAuthorizationContext:
        return MockAuthorizationContext(
            user_id=user_id,
            org_id=org_id,
            workspace_id=workspace_id,
            roles=roles,
            permissions=permissions,
            **kwargs,
        )

    return _create_context


@pytest.fixture
def admin_auth_context(mock_auth_context):
    """Pre-configured admin authorization context."""
    return mock_auth_context(roles=["admin", "owner"])


@pytest.fixture
def viewer_auth_context(mock_auth_context):
    """Pre-configured viewer authorization context (read-only)."""
    return mock_auth_context(
        roles=["viewer"],
        permissions=[
            "debates:read",
            "agents:read",
            "memory.read",
            "knowledge:read",
            "workflows:read",
        ],
    )


@pytest.fixture
def editor_auth_context(mock_auth_context):
    """Pre-configured editor authorization context (read/write, no admin)."""
    return mock_auth_context(
        roles=["editor"],
        permissions=[
            "debates:read",
            "debates:write",
            "debates:create",
            "agents:read",
            "agents:write",
            "memory.read",
            "memory.write",
            "knowledge:read",
            "knowledge:write",
            "workflows:read",
            "workflows:write",
        ],
    )


@pytest.fixture
def authenticated_handler(mock_auth_context):
    """Patch a handler instance to bypass RBAC authentication.

    This fixture patches the get_auth_context and check_permission methods
    on handler instances so they don't require actual authentication.

    Returns:
        Context manager factory that patches handler auth methods.

    Example:
        def test_protected_endpoint(handler, authenticated_handler, mock_http_get):
            with authenticated_handler(handler):
                result = handler.handle("/api/v1/protected", {}, mock_http_get, "GET")
                assert result.status_code == 200

        def test_with_custom_permissions(handler, authenticated_handler, mock_http_get):
            with authenticated_handler(handler, permissions=["debates:read"]):
                result = handler.handle("/api/v1/debates", {}, mock_http_get, "GET")
    """
    from contextlib import contextmanager
    from unittest.mock import patch

    @contextmanager
    def _patch_handler(
        handler_instance,
        user_id: str = "test-user-001",
        org_id: str = "test-org-001",
        roles: list[str] | None = None,
        permissions: list[str] | None = None,
    ):
        ctx = mock_auth_context(
            user_id=user_id,
            org_id=org_id,
            roles=roles,
            permissions=permissions,
        )

        # Patch get_auth_context to return our mock context
        with patch.object(handler_instance, "get_auth_context", return_value=ctx) as mock_get_auth:
            # Patch check_permission to always return True
            with patch.object(
                handler_instance, "check_permission", return_value=True
            ) as mock_check:
                yield ctx, mock_get_auth, mock_check

    return _patch_handler


@pytest.fixture
def bypass_rbac():
    """Global patch to bypass all RBAC checks.

    Use this when you want to test handler logic without any auth.
    Patches the require_permission decorator to be a no-op.

    Example:
        def test_handler_logic(handler, bypass_rbac, mock_http_get):
            with bypass_rbac:
                result = handler.handle("/api/v1/resource", {}, mock_http_get, "GET")
    """
    from unittest.mock import patch

    def passthrough_decorator(*args, **kwargs):
        """Decorator that does nothing but preserves __wrapped__."""
        import functools

        def decorator(func):
            @functools.wraps(func)
            def wrapper(*a, **kw):
                return func(*a, **kw)

            return wrapper

        return decorator

    return patch("aragora.rbac.decorators.require_permission", passthrough_decorator)


# ============================================================================
# Legacy Auth Mocking Fixtures
# ============================================================================


@pytest.fixture
def mock_auth_disabled():
    """Patch auth_config to disable authentication.

    Use as context manager or with autouse in test class.
    """
    from unittest.mock import patch

    mock_config = MagicMock()
    mock_config.enabled = False
    mock_config.api_token = None

    return patch("aragora.server.auth.auth_config", mock_config)


@pytest.fixture
def mock_auth_enabled():
    """Patch auth_config with authentication enabled.

    Returns a patch context manager and valid token.
    """
    from unittest.mock import patch

    mock_config = MagicMock()
    mock_config.enabled = True
    mock_config.api_token = "test_api_token_12345"
    mock_config.validate_token = MagicMock(return_value=True)

    return patch("aragora.server.auth.auth_config", mock_config), "test_api_token_12345"


@pytest.fixture
def authenticated_http_handler(mock_http_handler):
    """Create a mock HTTP handler with valid auth headers.

    Returns:
        Factory that creates authenticated HTTP handlers.
    """

    def _create_handler(
        method: str = "GET",
        body: dict[str, Any] | None = None,
        token: str = "test_api_token_12345",
    ) -> MagicMock:
        return mock_http_handler(
            method=method,
            body=body,
            headers={"Authorization": f"Bearer {token}"},
        )

    return _create_handler


# ============================================================================
# Rate Limiting Mocks
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """Reset all rate limiter state between tests.

    Rate limiters use module-level singletons that persist across tests.
    Without this fixture, earlier tests consume the rate limit budget,
    causing later tests to receive 429 responses.

    Uses sys.modules lookup because the utils __init__.py exports
    rate_limit as a function name, which shadows the module import.

    Also resets the distributed rate limiter singleton, which coordinates
    across server instances and uses an in-memory fallback in tests.
    The ``@rate_limit`` decorator captures a reference to this singleton
    at decoration time, so its internal state accumulates across tests
    unless explicitly reset.
    """
    import sys

    rl_mod = sys.modules.get("aragora.server.handlers.utils.rate_limit")
    if rl_mod is None:
        try:
            import importlib

            rl_mod = importlib.import_module("aragora.server.handlers.utils.rate_limit")
        except ImportError:
            rl_mod = None

    if rl_mod is not None:
        rl_mod.clear_all_limiters()
        # Ensure rate limiting is NOT globally disabled.  importlib.reload()
        # of rate_limit.py creates a new module object, but existing
        # RateLimiter instances still resolve RATE_LIMITING_DISABLED via
        # their is_allowed method's __globals__ (the ORIGINAL module dict).
        # We must patch BOTH the sys.modules entry AND the original dict.
        rl_mod.RATE_LIMITING_DISABLED = False
        # Also patch the class-level __globals__ which may differ after reload
        if hasattr(rl_mod, "RateLimiter"):
            rl_cls = rl_mod.RateLimiter
            if hasattr(rl_cls, "is_allowed"):
                rl_cls.is_allowed.__globals__["RATE_LIMITING_DISABLED"] = False

    # Also reset the distributed rate limiter singleton so that request
    # counts from prior tests don't cause spurious 429 responses.
    try:
        from aragora.server.middleware.rate_limit.distributed import (
            reset_distributed_limiter,
        )

        reset_distributed_limiter()
    except ImportError:
        pass

    # Reset the per-user rate limiter singleton.  The @user_rate_limit
    # decorator (used by _create_debate, _debate_this, etc.) calls
    # check_user_rate_limit() which uses a global UserRateLimiter.
    # Without reset, earlier tests exhaust the per-user token bucket
    # (e.g. "debate_create" allows only 10/min), causing later tests
    # to receive 429 responses.
    try:
        from aragora.server.middleware.rate_limit.user_limiter import (
            get_user_rate_limiter,
        )

        get_user_rate_limiter().reset()
    except ImportError:
        pass

    yield

    if rl_mod is not None:
        try:
            rl_mod.clear_all_limiters()
        except Exception:
            pass

    try:
        from aragora.server.middleware.rate_limit.distributed import (
            reset_distributed_limiter,
        )

        reset_distributed_limiter()
    except (ImportError, Exception):
        pass

    try:
        from aragora.server.middleware.rate_limit.user_limiter import (
            get_user_rate_limiter,
        )

        get_user_rate_limiter().reset()
    except (ImportError, Exception):
        pass


@pytest.fixture
def disable_rate_limiting():
    """Disable rate limiting for tests.

    Use as context manager to patch rate_limit decorator.
    """
    from unittest.mock import patch

    # Create a pass-through decorator
    def no_rate_limit(**kwargs):
        def decorator(func):
            return func

        return decorator

    return patch("aragora.server.handlers.auth.handler.rate_limit", no_rate_limit)


@pytest.fixture(autouse=True)
def _reset_lockout_tracker():
    """Reset the global lockout tracker between tests.

    The lockout tracker accumulates failed login attempts in a module-level
    singleton. Without reset, auth tests see 429 "account locked" responses
    from attempts recorded by earlier tests.
    """
    try:
        from aragora.auth.lockout import reset_lockout_tracker

        reset_lockout_tracker()
    except ImportError:
        pass
    yield
    try:
        from aragora.auth.lockout import reset_lockout_tracker

        reset_lockout_tracker()
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _reset_sso_state():
    """Reset SSO provider configs and auth sessions between tests.

    SSO handlers store provider configs and auth sessions in module-level
    dicts. Without reset, tests see stale provider configs and OAuth states
    from previous tests.
    """
    try:
        import aragora.server.handlers.auth.sso_handlers as sso_mod

        sso_mod._sso_providers.clear()
        sso_mod._auth_sessions.clear()
        # Reset the LazyStore so it re-initializes on next access
        if hasattr(sso_mod._sso_state_store, "reset"):
            sso_mod._sso_state_store.reset()
    except (ImportError, AttributeError):
        pass
    yield
    try:
        import aragora.server.handlers.auth.sso_handlers as sso_mod

        sso_mod._sso_providers.clear()
        sso_mod._auth_sessions.clear()
        if hasattr(sso_mod._sso_state_store, "reset"):
            sso_mod._sso_state_store.reset()
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _reset_handler_global_state():
    """Reset module-level handler state between tests.

    Clears persistent data structures that accumulate across test runs,
    preventing order-dependent failures. Two-phase cleanup (before and
    after yield) handles pollution from tests in other conftest scopes.
    """
    # Setup phase: clear critical singletons polluted by other scopes
    try:
        import aragora.server.handlers.payments.handler as _ph

        _ph._stripe_connector = None
        _ph._authnet_connector = None
    except (ImportError, AttributeError):
        pass
    try:
        import aragora.server.handlers.email.storage as _es

        _es._user_configs.clear()
        _es._gmail_connector = None
        _es._prioritizer = None
        _es._context_service = None
    except (ImportError, AttributeError):
        pass

    # Clear notification preferences/history state (module-level dicts and
    # standalone rate limiters not registered in _limiters).
    try:
        import aragora.server.handlers.notifications.preferences as _notif_prefs

        _notif_prefs._user_preferences.clear()
        _notif_prefs._preferences_limiter.clear()
    except (ImportError, AttributeError):
        pass
    try:
        import aragora.server.handlers.notifications.history as _notif_hist

        _notif_hist._notification_history_limiter.clear()
    except (ImportError, AttributeError):
        pass

    # Save WhatsApp module-level constants before yield so they can be
    # restored in teardown.  Both bots.whatsapp and social.whatsapp.config
    # capture os.environ values at import time; patching them in tests leaks
    # across modules when running the full handler suite.
    _bots_wa_orig: dict = {}
    try:
        import aragora.server.handlers.bots.whatsapp as _bots_wa

        _bots_wa_orig = {
            "WHATSAPP_VERIFY_TOKEN": _bots_wa.WHATSAPP_VERIFY_TOKEN,
            "WHATSAPP_ACCESS_TOKEN": _bots_wa.WHATSAPP_ACCESS_TOKEN,
            "WHATSAPP_PHONE_NUMBER_ID": _bots_wa.WHATSAPP_PHONE_NUMBER_ID,
            "WHATSAPP_APP_SECRET": _bots_wa.WHATSAPP_APP_SECRET,
        }
    except (ImportError, AttributeError):
        pass

    _social_wa_orig: dict = {}
    _social_wa_singleton_orig = None
    try:
        from aragora.server.handlers.social.whatsapp import config as _social_wa_config
        from aragora.server.handlers.social.whatsapp import handler as _social_wa_handler

        _social_wa_orig = {
            "WHATSAPP_ACCESS_TOKEN": _social_wa_config.WHATSAPP_ACCESS_TOKEN,
            "WHATSAPP_PHONE_NUMBER_ID": _social_wa_config.WHATSAPP_PHONE_NUMBER_ID,
            "WHATSAPP_VERIFY_TOKEN": _social_wa_config.WHATSAPP_VERIFY_TOKEN,
            "WHATSAPP_APP_SECRET": _social_wa_config.WHATSAPP_APP_SECRET,
        }
        _social_wa_singleton_orig = _social_wa_handler._whatsapp_handler
    except (ImportError, AttributeError):
        pass

    yield

    # Reset notification preferences/history state
    try:
        import aragora.server.handlers.notifications.preferences as _notif_prefs

        _notif_prefs._user_preferences.clear()
        _notif_prefs._preferences_limiter.clear()
    except (ImportError, AttributeError):
        pass
    try:
        import aragora.server.handlers.notifications.history as _notif_hist

        _notif_hist._notification_history_limiter.clear()
    except (ImportError, AttributeError):
        pass

    # Reset signup state
    try:
        from aragora.server.handlers.auth import signup_handlers as su_mod

        su_mod._pending_signups.clear()
        su_mod._pending_invites.clear()
        if hasattr(su_mod, "_onboarding_status"):
            su_mod._onboarding_status.clear()
    except (ImportError, AttributeError):
        pass

    # Reset WhatsApp bot handler state (bots.whatsapp)
    try:
        import aragora.server.handlers.bots.whatsapp as _bots_wa

        _bots_wa.WHATSAPP_VERIFY_TOKEN = _bots_wa_orig.get("WHATSAPP_VERIFY_TOKEN")
        _bots_wa.WHATSAPP_ACCESS_TOKEN = _bots_wa_orig.get("WHATSAPP_ACCESS_TOKEN")
        _bots_wa.WHATSAPP_PHONE_NUMBER_ID = _bots_wa_orig.get("WHATSAPP_PHONE_NUMBER_ID")
        _bots_wa.WHATSAPP_APP_SECRET = _bots_wa_orig.get("WHATSAPP_APP_SECRET")
    except (ImportError, AttributeError):
        pass

    # Reset WhatsApp social handler state (social.whatsapp)
    try:
        from aragora.server.handlers.social.whatsapp import config as _social_wa_config
        from aragora.server.handlers.social.whatsapp import handler as _social_wa_handler

        _social_wa_config.WHATSAPP_ACCESS_TOKEN = _social_wa_orig.get("WHATSAPP_ACCESS_TOKEN")
        _social_wa_config.WHATSAPP_PHONE_NUMBER_ID = _social_wa_orig.get("WHATSAPP_PHONE_NUMBER_ID")
        _social_wa_config.WHATSAPP_VERIFY_TOKEN = _social_wa_orig.get("WHATSAPP_VERIFY_TOKEN")
        _social_wa_config.WHATSAPP_APP_SECRET = _social_wa_orig.get("WHATSAPP_APP_SECRET")
        _social_wa_handler._whatsapp_handler = _social_wa_singleton_orig
    except (ImportError, AttributeError):
        pass

    # Reset Slack bot state — only if already imported to avoid shadowing
    # aragora.server.handlers.social.slack (importing bots.slack at collection
    # time causes social.slack imports to resolve to None)
    _slack_mod = sys.modules.get("aragora.server.handlers.bots.slack")
    if _slack_mod is not None:
        slack_state = getattr(_slack_mod, "state", None)
        if slack_state is not None:
            if hasattr(slack_state, "_active_debates"):
                slack_state._active_debates.clear()
            if hasattr(slack_state, "_user_votes"):
                slack_state._user_votes.clear()

    # Reset Teams bot state
    try:
        from aragora.server.handlers.bots import teams_utils

        if hasattr(teams_utils, "_active_debates"):
            teams_utils._active_debates.clear()
        if hasattr(teams_utils, "_user_votes"):
            teams_utils._user_votes.clear()
        if hasattr(teams_utils, "_conversation_references"):
            teams_utils._conversation_references.clear()
    except (ImportError, AttributeError):
        pass

    # Reset task execution state
    try:
        from aragora.server.handlers.tasks import execution

        if hasattr(execution, "_tasks"):
            execution._tasks.clear()
    except (ImportError, AttributeError):
        pass

    # Reset transcription state
    try:
        from aragora.server.handlers import transcription

        if hasattr(transcription, "_transcription_jobs"):
            transcription._transcription_jobs.clear()
    except (ImportError, AttributeError):
        pass

    # Reset code review state
    try:
        from aragora.server.handlers import code_review

        if hasattr(code_review, "_review_results"):
            code_review._review_results.clear()
    except (ImportError, AttributeError):
        pass

    # Reset gastown dashboard cache
    try:
        from aragora.server.handlers import gastown_dashboard

        if hasattr(gastown_dashboard, "_gt_dashboard_cache"):
            gastown_dashboard._gt_dashboard_cache.clear()
    except (ImportError, AttributeError):
        pass

    # Reset onboarding flows
    try:
        from aragora.server.handlers import onboarding

        if hasattr(onboarding, "_onboarding_flows"):
            onboarding._onboarding_flows.clear()
    except (ImportError, AttributeError):
        pass

    # Reset cloud storage tokens
    try:
        from aragora.server.handlers.features import cloud_storage

        if hasattr(cloud_storage, "_tokens"):
            cloud_storage._tokens.clear()
    except (ImportError, AttributeError):
        pass

    # Reset legal handler connector cache
    try:
        from aragora.server.handlers.features.legal import _connector_instances

        _connector_instances.clear()
    except (ImportError, AttributeError):
        pass

    # Reset plugins state
    try:
        from aragora.server.handlers.features import plugins

        if hasattr(plugins, "_installed_plugins"):
            plugins._installed_plugins.clear()
        if hasattr(plugins, "_plugin_submissions"):
            plugins._plugin_submissions.clear()
    except (ImportError, AttributeError):
        pass

    # Reset advertising state
    try:
        from aragora.server.handlers.features import advertising

        if hasattr(advertising, "_platform_credentials"):
            advertising._platform_credentials.clear()
        if hasattr(advertising, "_platform_connectors"):
            advertising._platform_connectors.clear()
    except (ImportError, AttributeError):
        pass

    # Reset email snoozed state
    try:
        from aragora.server.handlers import email_services

        if hasattr(email_services, "_snoozed_emails"):
            email_services._snoozed_emails.clear()
    except (ImportError, AttributeError):
        pass

    # Reset workspace circuit breakers
    try:
        from aragora.server.handlers.workspace import workspace_utils

        if hasattr(workspace_utils, "_workspace_circuit_breakers"):
            workspace_utils._workspace_circuit_breakers.clear()
    except (ImportError, AttributeError):
        pass

    # Reset payment connector singletons
    try:
        import aragora.server.handlers.payments.handler as payments_handler

        payments_handler._stripe_connector = None
        payments_handler._authnet_connector = None
    except (ImportError, AttributeError):
        pass

    # Reset email VIP / user config state
    try:
        import aragora.server.handlers.email.storage as email_storage_mod

        email_storage_mod._user_configs.clear()
        email_storage_mod._gmail_connector = None
        email_storage_mod._prioritizer = None
        email_storage_mod._context_service = None
    except (ImportError, AttributeError):
        pass

    # Reset Slack integration singleton (both package and state module)
    try:
        import aragora.server.handlers.bots.slack as _slack_pkg
        import aragora.server.handlers.bots.slack.state as _slack_state

        _slack_pkg._slack_integration = None
        _slack_state._slack_integration = None
    except (ImportError, AttributeError):
        pass


# ============================================================================
# Module-Level Function Restoration
# ============================================================================


# Capture the real side_effect property descriptor from NonCallableMock.
# If a test accidentally sets MagicMock.side_effect = <value> on the CLASS
# (e.g. by assigning `spec.adapter_class = MagicMock` then setting
# `.adapter_class.side_effect = ...`), the property descriptor is destroyed
# and all future MagicMock instances lose side_effect list-to-iterator
# conversion, causing `TypeError: 'list' object is not an iterator`.
from unittest.mock import NonCallableMock as _NCMock

_real_side_effect_descriptor = (
    type.__dict__["__dict__"]
    .__get__(  # noqa: B009
        _NCMock
    )
    .get("side_effect", None)
)
if _real_side_effect_descriptor is None:
    # Fallback: walk MRO
    for _cls in _NCMock.__mro__:
        if "side_effect" in _cls.__dict__:
            _real_side_effect_descriptor = _cls.__dict__["side_effect"]
            break


# Capture the real run_async function at import time, before any test can
# replace it with a mock.  This reference is immutable for the session.
_real_run_async: Callable[..., Any] | None
try:
    from aragora.utils.async_utils import run_async as _imported_run_async

    _real_run_async = _imported_run_async
except ImportError:
    _real_run_async = None

# Capture real BaseHandler methods at import time for reliable restoration.
_real_extract_path_param = None
_real_extract_path_params = None
_BaseHandler: "type[BaseHandler] | None"
try:
    from aragora.server.handlers.base import BaseHandler as _ImportedBaseHandler

    _BaseHandler = _ImportedBaseHandler
    _real_extract_path_param = getattr(_BaseHandler, "extract_path_param", None)
    _real_extract_path_params = getattr(_BaseHandler, "extract_path_params", None)
except ImportError:
    _BaseHandler = None

_RUN_ASYNC_MODULE_PREFIXES = ("aragora.server.", "aragora.utils.")
_RUN_ASYNC_ATTRS = ("run_async", "_run_async")
_SYS_MODULES_SNAPSHOT_ATTEMPTS = 3


def _snapshot_sys_modules(modules: dict[str, Any] | None = None) -> list[tuple[str, Any]]:
    """Return the ``sys.modules`` items as a list detached from the live dict.

    Walking the live dict (``list(sys.modules.items())``) is not safe on
    CPython 3.11: every item tuple is a GC allocation, so a collection can
    start mid-walk, and an import made by a GC callback, a finalizer, or
    another thread scheduled during that collection resizes the dict and
    raises ``RuntimeError: dictionary changed size during iteration``.
    ``dict.copy`` clones the table without running Python code between
    entries.  Earlier attempts retry a resize observed by the copy itself;
    the final attempt is unguarded so a persistent failure propagates.
    """
    source = sys.modules if modules is None else modules
    for _ in range(_SYS_MODULES_SNAPSHOT_ATTEMPTS - 1):
        try:
            return list(source.copy().items())
        except RuntimeError:
            continue
    return list(source.copy().items())


def _restore_polluted_run_async() -> None:
    """Point every loaded ``run_async``/``_run_async`` back at the real function."""
    if _real_run_async is None:
        return
    for mod_name, mod in _snapshot_sys_modules():
        if mod is None or not mod_name.startswith(_RUN_ASYNC_MODULE_PREFIXES):
            continue
        for attr in _RUN_ASYNC_ATTRS:
            current = getattr(mod, attr, None)
            if current is not None and current is not _real_run_async:
                setattr(mod, attr, _real_run_async)


@pytest.fixture(autouse=True)
def _restore_module_level_functions():
    """Restore module-level functions that may be replaced by mocks.

    Several handler modules import ``run_async`` at the top level from
    ``aragora.server.http_utils``.  If a test patches one of these attributes
    with a ``MagicMock(side_effect=[...])`` and the mock leaks (e.g. because
    an exception prevented the patch context manager from cleaning up, or
    because the module was reloaded while a patch was active), subsequent
    tests see the stale mock and fail with
    ``TypeError: 'list' object is not an iterator``.

    This fixture runs **before** every test and verifies that the critical
    module attributes still point to the real functions.  If they have been
    replaced by *anything* other than the real function, it restores them.

    Also repairs the ``NonCallableMock.side_effect`` property descriptor if
    a test accidentally set ``MagicMock.side_effect`` on the CLASS (e.g.
    via ``spec.adapter_class = MagicMock; spec.adapter_class.side_effect = ...``).
    """
    # Guard: repair MagicMock.side_effect property if destroyed
    if _real_side_effect_descriptor is not None:
        current_descriptor = _NCMock.__dict__.get("side_effect")
        if current_descriptor is not _real_side_effect_descriptor:
            _NCMock.side_effect = _real_side_effect_descriptor

    # Scan ALL loaded aragora modules for polluted run_async references.
    # 51+ handler modules import run_async at module level; rather than
    # maintaining a hardcoded list, we dynamically find and restore them.
    _restore_polluted_run_async()

    # Reset the cached has_permission in control_plane.health
    # This global caches whatever callable it finds on the control_plane
    # module, and that cached value can be a stale mock from a prior test.
    try:
        import aragora.server.handlers.control_plane.health as _cp_health

        _cp_health._cached_has_permission = None
        _cp_health._cache_timestamp = 0
    except (ImportError, AttributeError):
        pass

    # Reset ControlPlaneHandler.coordinator class-level attribute
    # The control_plane_handler fixture sets this on the class, but never
    # resets it.  If a prior test left a mock coordinator, it leaks.
    try:
        from aragora.server.handlers.control_plane import ControlPlaneHandler

        if hasattr(ControlPlaneHandler, "coordinator") and isinstance(
            getattr(ControlPlaneHandler, "coordinator", None), MagicMock
        ):
            ControlPlaneHandler.coordinator = None
    except (ImportError, AttributeError):
        pass

    yield

    # Teardown: repeat the same cleanup in case the test itself polluted

    # Repair MagicMock.side_effect descriptor in teardown too, so the
    # next test's setup guard is not the only line of defence.
    if _real_side_effect_descriptor is not None:
        current_descriptor = _NCMock.__dict__.get("side_effect")
        if current_descriptor is not _real_side_effect_descriptor:
            _NCMock.side_effect = _real_side_effect_descriptor

    _restore_polluted_run_async()

    try:
        import aragora.server.handlers.control_plane.health as _cp_health

        _cp_health._cached_has_permission = None
        _cp_health._cache_timestamp = 0
    except (ImportError, AttributeError):
        pass


@pytest.fixture(autouse=True)
def _prevent_orchestration_handler_http():
    """Prevent the orchestration handler from blocking on real HTTP calls.

    The sync deliberation path calls ``run_async(_execute_deliberation(...))``.
    Under certain test orderings (e.g. seed 99999), this can block on actual
    HTTP requests and hang the test suite indefinitely.

    This fixture replaces ``run_async`` in the orchestration handler module
    with a safe stub.  Tests that explicitly patch ``run_async`` via
    ``with patch(...)`` override this fixture's patch (inner patches win).
    """
    import sys

    orch_handler_mod = sys.modules.get("aragora.server.handlers.orchestration.handler")
    if orch_handler_mod is None:
        try:
            import importlib

            orch_handler_mod = importlib.import_module(
                "aragora.server.handlers.orchestration.handler"
            )
        except ImportError:
            orch_handler_mod = None

    if orch_handler_mod is not None:
        from aragora.server.handlers.orchestration.models import OrchestrationResult

        _orig_run_async = getattr(orch_handler_mod, "run_async", None)

        def _safe_run_async(coro, timeout=30.0):
            if hasattr(coro, "close"):
                coro.close()
            return OrchestrationResult(
                request_id="test-safe-fallback",
                success=True,
                final_answer="Mocked by conftest",
            )

        orch_handler_mod.run_async = _safe_run_async

        yield

        if _orig_run_async is not None:
            orch_handler_mod.run_async = _orig_run_async
    else:
        yield


@pytest.fixture(autouse=True)
def _restore_base_handler_methods():
    """Restore BaseHandler class methods that may be replaced by mocks.

    Uses references captured at import time (before any test can pollute them)
    to reliably restore methods even after cascading pollution.
    """
    # Pre-test: restore if already polluted
    if _BaseHandler is not None:
        if _real_extract_path_param is not None:
            current = getattr(_BaseHandler, "extract_path_param", None)
            if current is not _real_extract_path_param:
                setattr(_BaseHandler, "extract_path_param", _real_extract_path_param)
        if _real_extract_path_params is not None:
            current = getattr(_BaseHandler, "extract_path_params", None)
            if current is not _real_extract_path_params:
                setattr(_BaseHandler, "extract_path_params", _real_extract_path_params)

    yield

    # Post-test: restore if this test polluted
    if _BaseHandler is not None:
        if _real_extract_path_param is not None:
            current = getattr(_BaseHandler, "extract_path_param", None)
            if current is not _real_extract_path_param:
                setattr(_BaseHandler, "extract_path_param", _real_extract_path_param)
        if _real_extract_path_params is not None:
            current = getattr(_BaseHandler, "extract_path_params", None)
            if current is not _real_extract_path_params:
                setattr(_BaseHandler, "extract_path_params", _real_extract_path_params)


# ============================================================================
# Async Handler Support
# ============================================================================


@pytest.fixture
def async_mock_http_handler():
    """Create an async-compatible mock HTTP handler.

    For handlers that use async methods internally.
    """

    def _create_handler(
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> MagicMock:
        mock = MagicMock()
        mock.command = method

        if body is not None:
            body_bytes = json.dumps(body).encode()
        else:
            body_bytes = b"{}"

        mock.rfile = MagicMock()
        mock.rfile.read = MagicMock(return_value=body_bytes)

        mock.headers = headers or {}
        mock.headers.setdefault("Content-Length", str(len(body_bytes)))

        # Async-compatible send methods
        mock.send_response = MagicMock()
        mock.send_header = MagicMock()
        mock.end_headers = MagicMock()
        mock.wfile = MagicMock()
        mock.wfile.write = MagicMock()

        return mock

    return _create_handler


# ============================================================================
# Handler Test Helpers
# ============================================================================


class HandlerTestCase:
    """Base class for handler test cases.

    Provides common assertions and utilities.

    Example:
        class TestMyHandler(HandlerTestCase):
            @pytest.fixture
            def handler(self, mock_server_context):
                from aragora.server.handlers.my import MyHandler
                return MyHandler(server_context=mock_server_context)

            def test_can_handle(self, handler):
                self.assert_can_handle(handler, "/api/v1/my/resource")

            def test_get_resource(self, handler, mock_http_get):
                result = handler.handle("/api/v1/my/resource", {}, mock_http_get, "GET")
                self.assert_success_with_keys(result, ["id", "name"])
    """

    def assert_can_handle(self, handler, path: str, expected: bool = True):
        """Assert handler can/cannot handle a path."""
        result = handler.can_handle(path)
        assert result is expected, f"Expected can_handle('{path}') to be {expected}"

    def assert_routes_include(self, handler, *paths: str):
        """Assert handler ROUTES includes all given paths."""
        for path in paths:
            assert path in handler.ROUTES, f"Expected '{path}' in handler ROUTES"

    def assert_success_with_keys(self, result, keys: list[str]):
        """Assert successful response with expected keys."""
        assert_success_response(result, expected_keys=keys)

    def assert_error(self, result, status: int, message: str | None = None):
        """Assert error response with status and optional message."""
        assert_error_response(result, expected_status=status, error_substring=message)

    def get_response_body(self, result) -> dict[str, Any]:
        """Get parsed response body."""
        return parse_handler_response(result)


# ============================================================================
# Safe Handler Imports (avoid circular imports)
# ============================================================================


def _safe_import_handler(module_path: str, class_name: str):
    """Safely import a handler class, avoiding circular imports.

    Args:
        module_path: Full path to the module file
        class_name: Name of the class to import

    Returns:
        The handler class, or None if import fails
    """
    import importlib.util
    import sys

    module_name = f"_safe_{class_name.lower()}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            return getattr(module, class_name, None)
        except Exception:
            return None
    return None


@pytest.fixture
def computer_use_handler_class():
    """Provide ComputerUseHandler class with safe import.

    This avoids the circular import issue in handlers/__init__.py.
    """
    import os

    handlers_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    module_path = os.path.join(
        handlers_dir, "aragora", "server", "handlers", "computer_use_handler.py"
    )
    handler_class = _safe_import_handler(module_path, "ComputerUseHandler")
    assert handler_class is not None, "ComputerUseHandler should be importable"
    return handler_class
