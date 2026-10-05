"""
Tests for KnowledgeHandler class.

Comprehensive tests covering:
- Handler initialization and routing
- can_handle method for various paths
- Rate limiting enforcement
- RBAC permission checks (knowledge.read, knowledge.write, knowledge.delete)
- GET/POST/PUT/DELETE routing for facts
- Query endpoint routing
- Search endpoint routing
- Stats endpoint routing
- Dynamic fact routes (/facts/:id, /facts/:id/verify, etc.)

Run with:
    python -m pytest tests/server/handlers/knowledge_base/test_handler.py -v --timeout=30
"""

from __future__ import annotations

import json
import sys
import types as _types_mod
from io import BytesIO
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

# Pre-stub Slack modules to prevent import chain failures
_SLACK_ATTRS = [
    "SlackHandler",
    "get_slack_handler",
    "get_slack_integration",
    "get_workspace_store",
    "resolve_workspace",
    "create_tracked_task",
    "_validate_slack_url",
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    "SLACK_WEBHOOK_URL",
    "SLACK_ALLOWED_DOMAINS",
    "SignatureVerifierMixin",
    "CommandsMixin",
    "EventsMixin",
    "init_slack_handler",
]
for _mod_name in (
    "aragora.server.handlers.social.slack.handler",
    "aragora.server.handlers.social.slack",
    "aragora.server.handlers.social._slack_impl",
):
    if _mod_name not in sys.modules:
        _m = _types_mod.ModuleType(_mod_name)
        for _a in _SLACK_ATTRS:
            setattr(_m, _a, None)
        sys.modules[_mod_name] = _m

from aragora.knowledge import InMemoryFactStore, ScopedFactStore
from aragora.server.handlers.knowledge_base.handler import (
    KnowledgeHandler,
    _knowledge_limiter,
)
from aragora.server.handlers.base import error_response


# =============================================================================
# Mock Classes and Helpers
# =============================================================================


class MockAuthenticatedUser:
    """Mock authenticated user with full knowledge permissions."""

    org_id = "test-org-001"

    def __init__(
        self,
        user_id: str = "test-user-001",
        permissions: set[str] | None = None,
        roles: set[str] | None = None,
    ):
        self.user_id = user_id
        self.permissions = permissions or {
            "*",
            "admin",
            "knowledge.read",
            "knowledge.write",
            "knowledge.delete",
        }
        self.roles = roles or {"admin", "owner"}


class MockReadOnlyUser:
    """Mock user with only read permission."""

    def __init__(self, user_id: str = "readonly-user"):
        self.user_id = user_id
        self.permissions = {"knowledge.read"}
        self.roles = {"viewer"}


class MockNoPermissionsUser:
    """Mock user with no permissions."""

    def __init__(self, user_id: str = "restricted-user"):
        self.user_id = user_id
        self.permissions: set[str] = set()
        self.roles: set[str] = set()


def make_http_handler(
    method: str = "GET",
    body: dict[str, Any] | None = None,
    client_ip: str = "127.0.0.1",
) -> MagicMock:
    """Create a mock HTTP handler with optional JSON body and client IP."""
    handler = MagicMock()
    handler.client_address = (client_ip, 54321)
    handler.command = method

    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
    else:
        handler.headers = {"Content-Length": "0"}
        handler.rfile = BytesIO(b"")

    return handler


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter state before each test."""
    _knowledge_limiter.clear()
    yield
    _knowledge_limiter.clear()


@pytest.fixture(autouse=True)
def mock_rbac_for_tests(request, monkeypatch):
    """Bypass RBAC authentication for handler tests.

    Tests marked with @pytest.mark.no_auto_auth will skip this bypass
    to allow testing unauthenticated/unauthorized scenarios.
    """
    # Check if test has opted out of auto-auth
    if "no_auto_auth" in [m.name for m in request.node.iter_markers()]:
        yield
        return

    from aragora.rbac.models import AuthorizationContext

    # Create a mock auth context with admin permissions
    mock_auth_ctx = AuthorizationContext(
        user_id="test-user-001",
        user_email="test@example.com",
        org_id="test-org-001",
        roles={"admin", "owner"},
        permissions={"*"},  # Wildcard grants all permissions
    )

    # Patch _get_context_from_args to return mock context when no context found
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

    # Patch extract_user_from_request for JWT-based auth
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
        mock_user_ctx.permissions = {
            "*",
            "admin",
            "knowledge.read",
            "knowledge.write",
            "knowledge.delete",
        }  # type: ignore[attr-defined]
        mock_user_ctx.roles = {"admin", "owner"}  # type: ignore[attr-defined]

        def mock_extract_user(handler, user_store=None):
            return mock_user_ctx

        monkeypatch.setattr(
            "aragora.billing.jwt_auth.extract_user_from_request",
            mock_extract_user,
        )
    except (ImportError, AttributeError):
        pass

    yield mock_auth_ctx


@pytest.fixture
def mock_server_context() -> dict[str, Any]:
    """Create minimal server context for handler initialization."""
    return {
        "storage": None,
        "elo_system": None,
        "nomic_dir": None,
        "user_store": None,
    }


@pytest.fixture
def handler(mock_server_context) -> KnowledgeHandler:
    """Create a KnowledgeHandler instance."""
    h = KnowledgeHandler(mock_server_context)
    # Handler logic over an org-scoped store only: production _get_fact_store() builds an
    # unscoped store, so reads answer 403 (tests/server/fastapi/test_knowledge_org_isolation.py).
    h._fact_store = ScopedFactStore(InMemoryFactStore(), "test-org-001")  # type: ignore[assignment]
    return h


@pytest.fixture
def get_handler() -> MagicMock:
    """Create a GET request mock handler."""
    return make_http_handler("GET")


@pytest.fixture
def post_handler() -> MagicMock:
    """Create a POST request mock handler without body."""
    return make_http_handler("POST")


@pytest.fixture
def delete_handler() -> MagicMock:
    """Create a DELETE request mock handler."""
    return make_http_handler("DELETE")


@pytest.fixture
def put_handler() -> MagicMock:
    """Create a PUT request mock handler."""
    return make_http_handler("PUT")


# =============================================================================
# Handler Initialization Tests
# =============================================================================


class TestKnowledgeHandlerInitialization:
    """Tests for handler initialization and configuration."""

    def test_handler_initializes_with_context(self, mock_server_context):
        """Handler initializes successfully with server context."""
        handler = KnowledgeHandler(mock_server_context)
        assert handler is not None
        assert handler._fact_store is None
        assert handler._query_engine is None

    def test_handler_has_required_routes(self, handler):
        """Handler has all required static routes defined."""
        expected_routes = [
            "/api/v1/knowledge/query",
            "/api/v1/knowledge/facts",
            "/api/v1/knowledge/search",
            "/api/v1/knowledge/stats",
        ]
        for route in expected_routes:
            assert route in handler.ROUTES, f"Missing route: {route}"

    def test_handler_has_permission_constants(self, handler):
        """Handler defines all RBAC permission constants."""
        assert handler.KNOWLEDGE_READ_PERMISSION == "knowledge.read"
        assert handler.KNOWLEDGE_WRITE_PERMISSION == "knowledge.write"
        assert handler.KNOWLEDGE_DELETE_PERMISSION == "knowledge.delete"

    def test_fact_store_lazy_initialization(self, handler):
        """Fact store is lazily initialized on first access."""
        handler._fact_store = None
        store = handler._get_fact_store()
        assert store is not None
        assert not isinstance(store, ScopedFactStore)
        assert handler._fact_store is store

    def test_query_engine_lazy_initialization(self, handler):
        """Query engine is lazily initialized on first access."""
        assert handler._query_engine is None
        engine = handler._get_query_engine()
        assert engine is not None
        assert handler._query_engine is engine


# =============================================================================
# can_handle Method Tests
# =============================================================================


class TestCanHandle:
    """Tests for the can_handle method."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge/query",
            "/api/v1/knowledge/facts",
            "/api/v1/knowledge/search",
            "/api/v1/knowledge/stats",
        ],
    )
    def test_handles_static_routes(self, handler, path):
        """Handler can handle all static routes in ROUTES."""
        assert handler.can_handle(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge/facts/fact-123",
            "/api/v1/knowledge/facts/abc-def-ghi",
            "/api/v1/knowledge/facts/fact_with_underscore",
            "/api/v1/knowledge/facts/12345",
        ],
    )
    def test_handles_fact_id_routes(self, handler, path):
        """Handler can handle /api/v1/knowledge/facts/:id routes."""
        assert handler.can_handle(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge/facts/fact-123/verify",
            "/api/v1/knowledge/facts/fact-123/contradictions",
            "/api/v1/knowledge/facts/fact-123/relations",
        ],
    )
    def test_handles_fact_subresource_routes(self, handler, path):
        """Handler can handle /api/v1/knowledge/facts/:id/* subresource routes."""
        assert handler.can_handle(path) is True

    def test_handles_relations_bulk_route(self, handler):
        """Handler can handle /api/v1/knowledge/facts/relations bulk route."""
        # This is a special case - 5 parts with 'relations' as the ID
        assert handler.can_handle("/api/v1/knowledge/facts/relations") is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge",
            "/api/v1/knowledge/",
            "/api/v1/knowledge/unknown",
            "/api/v1/debates",
            "/api/v2/knowledge/facts",
            "/api/knowledge/facts",
            "/knowledge/facts",
            "",
            "/",
        ],
    )
    def test_rejects_non_matching_paths(self, handler, path):
        """Handler rejects paths that don't match supported routes."""
        assert handler.can_handle(path) is False


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests for rate limiting enforcement."""

    def test_rate_limiter_exists(self):
        """Knowledge limiter is configured."""
        assert _knowledge_limiter is not None
        assert _knowledge_limiter.rpm == 60

    def test_rate_limit_allows_normal_traffic(self, handler, get_handler):
        """Rate limiter allows requests under the limit."""
        # Make a few requests - should all succeed
        for _ in range(5):
            result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
            assert result is not None
            assert result.status_code != 429

    def test_rate_limit_blocks_excessive_traffic(self, handler):
        """Rate limiter blocks requests when limit is exceeded."""
        # Pre-fill the rate limiter to trigger blocking
        test_ip = "192.168.1.100"

        # Exhaust the rate limit by making many rapid requests
        import time

        current_time = time.time()
        # Fill the bucket directly to simulate exhausted rate limit
        _knowledge_limiter._buckets[test_ip] = [current_time] * 60

        http_handler = make_http_handler("GET", client_ip=test_ip)
        result = handler.handle("/api/v1/knowledge/stats", {}, http_handler)

        assert result is not None
        assert result.status_code == 429
        body = json.loads(result.body)
        assert "rate limit" in body.get("error", "").lower()

    def test_rate_limit_different_ips_independent(self, handler):
        """Different IPs have independent rate limits."""
        import time

        current_time = time.time()

        # Exhaust rate limit for IP 1
        ip1 = "192.168.1.1"
        _knowledge_limiter._buckets[ip1] = [current_time] * 60

        # IP 2 should still work
        ip2 = "192.168.1.2"
        http_handler = make_http_handler("GET", client_ip=ip2)
        result = handler.handle("/api/v1/knowledge/stats", {}, http_handler)

        assert result is not None
        assert result.status_code != 429


# =============================================================================
# RBAC Permission Tests
# =============================================================================


class TestRBACPermissions:
    """Tests for RBAC permission enforcement."""

    def test_check_permission_requires_auth(self, handler, get_handler):
        """_check_permission returns 401 when user is not authenticated."""
        with patch.object(
            handler,
            "require_auth_or_error",
            return_value=(None, error_response("Unauthorized", 401)),
        ):
            result = handler._check_permission(get_handler, "knowledge.read")
            assert result is not None
            assert result.status_code == 401

    def test_check_permission_allows_admin(self, handler, get_handler):
        """_check_permission allows users with admin role."""
        admin_user = MockAuthenticatedUser(roles={"admin"}, permissions=set())
        with patch.object(handler, "require_auth_or_error", return_value=(admin_user, None)):
            result = handler._check_permission(get_handler, "knowledge.read")
            assert result is None  # None means allowed

    def test_check_permission_allows_matching_permission(self, handler, get_handler):
        """_check_permission allows users with matching permission."""
        user = MockAuthenticatedUser(roles=set(), permissions={"knowledge.read"})
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler._check_permission(get_handler, "knowledge.read")
            assert result is None  # None means allowed

    def test_check_permission_denies_missing_permission(self, handler, get_handler):
        """_check_permission denies users without required permission."""
        user = MockNoPermissionsUser()
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler._check_permission(get_handler, "knowledge.read")
            assert result is not None
            assert result.status_code == 403

    def test_get_request_requires_read_permission(self, handler, get_handler):
        """GET requests require knowledge.read permission."""
        user = MockNoPermissionsUser()
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
            assert result is not None
            assert result.status_code == 403

    def test_post_fact_requires_write_permission(self, handler):
        """POST /api/v1/knowledge/facts requires knowledge.write permission."""
        user = MockReadOnlyUser()
        http = make_http_handler("POST", {"statement": "test"})
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler.handle("/api/v1/knowledge/facts", {}, http)
            assert result is not None
            assert result.status_code == 403

    def test_post_query_requires_read_permission(self, handler):
        """POST /api/v1/knowledge/query requires knowledge.read (not write)."""
        user = MockReadOnlyUser()
        http = make_http_handler("POST", {"question": "What is X?"})
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler.handle("/api/v1/knowledge/query", {}, http)
            # Should succeed with read permission since query is a read operation
            assert result is not None
            # May return 400 for missing question format, but not 403
            assert result.status_code != 403

    def test_put_requires_write_permission(self, handler):
        """PUT requests require knowledge.write permission."""
        user = MockReadOnlyUser()
        http = make_http_handler("PUT", {"confidence": 0.9})
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler.handle("/api/v1/knowledge/facts/fact-123", {}, http)
            assert result is not None
            assert result.status_code == 403

    def test_delete_requires_delete_permission(self, handler, delete_handler):
        """DELETE requests require knowledge.delete permission."""
        user = MockReadOnlyUser()
        with patch.object(handler, "require_auth_or_error", return_value=(user, None)):
            result = handler.handle("/api/v1/knowledge/facts/fact-123", {}, delete_handler)
            assert result is not None
            assert result.status_code == 403


# =============================================================================
# Facts Endpoint Routing Tests
# =============================================================================


class TestFactsRouting:
    """Tests for /api/v1/knowledge/facts endpoint routing."""

    def test_get_facts_list(self, handler, get_handler):
        """GET /api/v1/knowledge/facts returns fact list."""
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert result is not None
        body = json.loads(result.body)
        assert "facts" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body

    def test_get_facts_with_pagination(self, handler, get_handler):
        """GET /api/v1/knowledge/facts supports pagination params."""
        result = handler.handle(
            "/api/v1/knowledge/facts", {"limit": "10", "offset": "5"}, get_handler
        )
        assert result is not None
        body = json.loads(result.body)
        assert body["limit"] == 10
        assert body["offset"] == 5

    def test_get_facts_with_filters(self, handler, get_handler):
        """GET /api/v1/knowledge/facts supports filtering params."""
        params = {
            "topic": "security",
            "min_confidence": "0.8",
            "workspace_id": "ws-001",
        }
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        assert result is not None
        assert result.status_code == 200

    def test_post_facts_creates_fact(self, handler):
        """POST /api/v1/knowledge/facts creates a new fact."""
        http = make_http_handler(
            "POST",
            {"statement": "Test statement", "workspace_id": "default", "confidence": 0.9},
        )
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert result is not None
        assert result.status_code == 201
        body = json.loads(result.body)
        assert body["statement"] == "Test statement"

    def test_post_facts_requires_statement(self, handler):
        """POST /api/v1/knowledge/facts requires statement field."""
        http = make_http_handler("POST", {"workspace_id": "default"})
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert result is not None
        assert result.status_code == 400


# =============================================================================
# Dynamic Fact Routes Tests
# =============================================================================


class TestDynamicFactRoutes:
    """Tests for /api/v1/knowledge/facts/:id/* dynamic routes."""

    def test_get_fact_by_id(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id returns specific fact."""
        # First create a fact
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Test fact", workspace_id="default")

        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, get_handler)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["statement"] == "Test fact"

    def test_get_fact_not_found(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id returns 404 for unknown fact."""
        result = handler.handle("/api/v1/knowledge/facts/nonexistent-id", {}, get_handler)
        assert result is not None
        assert result.status_code == 404

    def test_put_fact_updates(self, handler):
        """PUT /api/v1/knowledge/facts/:id updates fact."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Original", workspace_id="default", confidence=0.5)

        http = make_http_handler("PUT", {"confidence": 0.95})
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, http)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["confidence"] == 0.95

    def test_put_fact_not_found(self, handler):
        """PUT /api/v1/knowledge/facts/:id returns 404 for unknown fact."""
        http = make_http_handler("PUT", {"confidence": 0.5})
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle("/api/v1/knowledge/facts/nonexistent", {}, http)
        assert result is not None
        assert result.status_code == 404

    def test_delete_fact(self, handler, delete_handler):
        """DELETE /api/v1/knowledge/facts/:id deletes fact."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="To delete", workspace_id="default")

        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, delete_handler)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["deleted"] is True

    def test_delete_fact_not_found(self, handler, delete_handler):
        """DELETE /api/v1/knowledge/facts/:id returns 404 for unknown fact."""
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle("/api/v1/knowledge/facts/nonexistent", {}, delete_handler)
        assert result is not None
        assert result.status_code == 404

    def test_verify_fact_route(self, handler, post_handler):
        """POST /api/v1/knowledge/facts/:id/verify triggers verification."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="To verify", workspace_id="default")

        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}/verify", {}, post_handler)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "status" in body

    def test_verify_fact_not_found(self, handler, post_handler):
        """POST /api/v1/knowledge/facts/:id/verify returns 404 for unknown fact."""
        result = handler.handle("/api/v1/knowledge/facts/nonexistent/verify", {}, post_handler)
        assert result is not None
        assert result.status_code == 404

    def test_get_contradictions_route(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id/contradictions returns contradictions."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Controversial", workspace_id="default")

        result = handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/contradictions", {}, get_handler
        )
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "contradictions" in body
        assert "count" in body

    def test_get_contradictions_not_found(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id/contradictions returns 404 for unknown fact."""
        result = handler.handle(
            "/api/v1/knowledge/facts/nonexistent/contradictions", {}, get_handler
        )
        assert result is not None
        assert result.status_code == 404

    def test_get_relations_route(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id/relations returns relations."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Related", workspace_id="default")

        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}/relations", {}, get_handler)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "relations" in body
        assert "count" in body

    def test_get_relations_with_type_filter(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id/relations supports type filter."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Filtered", workspace_id="default")

        result = handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/relations",
            {"type": "supports"},
            get_handler,
        )
        assert result is not None
        assert result.status_code == 200

    def test_get_relations_not_found(self, handler, get_handler):
        """GET /api/v1/knowledge/facts/:id/relations returns 404 for unknown fact."""
        result = handler.handle("/api/v1/knowledge/facts/nonexistent/relations", {}, get_handler)
        assert result is not None
        assert result.status_code == 404

    def test_post_relations_route(self, handler):
        """POST /api/v1/knowledge/facts/:id/relations adds a relation."""
        store = handler._get_fact_store()
        source = store.add_fact(statement="Source fact", workspace_id="default")
        target = store.add_fact(statement="Target fact", workspace_id="default")

        http = make_http_handler(
            "POST",
            {"target_fact_id": target.id, "relation_type": "supports", "confidence": 0.8},
        )
        result = handler.handle(f"/api/v1/knowledge/facts/{source.id}/relations", {}, http)
        assert result is not None
        assert result.status_code == 201

    def test_unknown_subresource_returns_404(self, handler, get_handler):
        """Unknown subresource under /facts/:id/ returns 404."""
        result = handler.handle("/api/v1/knowledge/facts/some-id/unknown-action", {}, get_handler)
        assert result is not None
        assert result.status_code == 404


# =============================================================================
# Query Endpoint Tests
# =============================================================================


class TestQueryEndpoint:
    """Tests for /api/v1/knowledge/query endpoint."""

    def test_query_requires_question(self, handler):
        """POST /api/v1/knowledge/query requires question in body."""
        http = make_http_handler("POST", {})
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert result is not None
        assert result.status_code == 400

    def test_query_with_valid_question(self, handler):
        """POST /api/v1/knowledge/query with question returns result."""
        http = make_http_handler(
            "POST",
            {"question": "What is the policy?", "workspace_id": "default"},
        )
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert result is not None
        # May fail for other reasons, but should process the question
        body = json.loads(result.body)
        assert isinstance(body, dict)

    def test_query_with_options(self, handler):
        """POST /api/v1/knowledge/query supports options."""
        http = make_http_handler(
            "POST",
            {
                "question": "Security policies?",
                "workspace_id": "security",
                "options": {"max_chunks": 5, "use_agents": False},
            },
        )
        result = handler.handle("/api/v1/knowledge/query", {}, http)
        assert result is not None


# =============================================================================
# Search Endpoint Tests
# =============================================================================


class TestSearchEndpoint:
    """Tests for /api/v1/knowledge/search endpoint."""

    def test_search_requires_query_param(self, handler, get_handler):
        """GET /api/v1/knowledge/search requires q parameter."""
        result = handler.handle("/api/v1/knowledge/search", {}, get_handler)
        assert result is not None
        assert result.status_code == 400

    def test_search_with_query(self, handler, get_handler):
        """GET /api/v1/knowledge/search with q returns results."""
        result = handler.handle("/api/v1/knowledge/search", {"q": "security"}, get_handler)
        assert result is not None
        body = json.loads(result.body)
        assert "query" in body
        assert "results" in body
        assert body["query"] == "security"

    def test_search_with_limit(self, handler, get_handler):
        """GET /api/v1/knowledge/search supports limit param."""
        result = handler.handle(
            "/api/v1/knowledge/search", {"q": "test", "limit": "5"}, get_handler
        )
        assert result is not None

    def test_search_with_workspace(self, handler, get_handler):
        """GET /api/v1/knowledge/search supports workspace_id param."""
        result = handler.handle(
            "/api/v1/knowledge/search",
            {"q": "test", "workspace_id": "ws-001"},
            get_handler,
        )
        assert result is not None


# =============================================================================
# Stats Endpoint Tests
# =============================================================================


class TestStatsEndpoint:
    """Tests for /api/v1/knowledge/stats endpoint."""

    def test_stats_returns_statistics(self, handler, get_handler):
        """GET /api/v1/knowledge/stats returns statistics."""
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert isinstance(body, dict)

    def test_stats_with_workspace_id(self, handler, get_handler):
        """GET /api/v1/knowledge/stats supports workspace_id filter."""
        result = handler.handle("/api/v1/knowledge/stats", {"workspace_id": "ws-001"}, get_handler)
        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body.get("workspace_id") == "ws-001"


# =============================================================================
# Bulk Relations Endpoint Tests
# =============================================================================


class TestBulkRelationsEndpoint:
    """Tests for /api/v1/knowledge/facts/relations bulk endpoint."""

    def test_bulk_add_relation(self, handler):
        """POST /api/v1/knowledge/facts/relations adds relation between facts."""
        store = handler._get_fact_store()
        source = store.add_fact(statement="Source", workspace_id="default")
        target = store.add_fact(statement="Target", workspace_id="default")

        http = make_http_handler(
            "POST",
            {
                "source_fact_id": source.id,
                "target_fact_id": target.id,
                "relation_type": "contradicts",
            },
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert result is not None
        assert result.status_code == 201

    def test_bulk_add_relation_requires_source(self, handler):
        """POST /api/v1/knowledge/facts/relations requires source_fact_id."""
        http = make_http_handler(
            "POST",
            {"target_fact_id": "target-123", "relation_type": "supports"},
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert result is not None
        assert result.status_code == 400

    def test_bulk_add_relation_requires_target(self, handler):
        """POST /api/v1/knowledge/facts/relations requires target_fact_id."""
        http = make_http_handler(
            "POST",
            {"source_fact_id": "source-123", "relation_type": "supports"},
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert result is not None
        assert result.status_code == 400

    def test_bulk_add_relation_requires_type(self, handler):
        """POST /api/v1/knowledge/facts/relations requires relation_type."""
        http = make_http_handler(
            "POST",
            {"source_fact_id": "source-123", "target_fact_id": "target-123"},
        )
        result = handler.handle("/api/v1/knowledge/facts/relations", {}, http)
        assert result is not None
        assert result.status_code == 400


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_handle_returns_none_for_unhandled_path(self, handler, get_handler):
        """handle returns None for paths not in ROUTES or dynamic patterns."""
        result = handler.handle("/api/v1/knowledge/unknown-endpoint", {}, get_handler)
        assert result is None

    def test_invalid_json_body(self, handler):
        """Invalid JSON body returns 400."""
        http = MagicMock()
        http.client_address = ("127.0.0.1", 54321)
        http.command = "POST"
        http.headers = {"Content-Length": "10"}
        http.rfile = BytesIO(b"not valid json")

        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle("/api/v1/knowledge/facts", {}, http)
        assert result is not None
        assert result.status_code == 400

    def test_fact_store_fallback_to_inmemory(self, handler):
        """Handler falls back to InMemoryFactStore if FactStore fails."""
        # The handler._get_fact_store should work regardless
        store = handler._get_fact_store()
        assert store is not None
        # Should be able to add facts
        fact = store.add_fact(statement="Fallback test", workspace_id="default")
        assert fact is not None

    def test_path_with_trailing_slash(self, handler, get_handler):
        """Paths with trailing slashes are handled correctly."""
        # /api/v1/knowledge/facts/ is not the same as /api/v1/knowledge/facts
        result = handler.can_handle("/api/v1/knowledge/facts/")
        # This should match the dynamic pattern since it's facts/ followed by empty
        assert result is True

    def test_deeply_nested_path(self, handler, get_handler):
        """Deeply nested paths return 404."""
        result = handler.handle("/api/v1/knowledge/facts/id/verify/extra/nested", {}, get_handler)
        assert result is not None
        assert result.status_code == 404


# =============================================================================
# Handler Method Integration Tests
# =============================================================================


class TestHandlerMethodIntegration:
    """Integration tests for handler method routing."""

    def test_method_routing_for_facts_endpoint(self, handler):
        """Different HTTP methods route to different handlers for /facts."""
        # GET routes to list
        get_http = make_http_handler("GET")
        result = handler.handle("/api/v1/knowledge/facts", {}, get_http)
        assert result is not None
        body = json.loads(result.body)
        assert "facts" in body  # List response

        # POST routes to create
        post_http = make_http_handler("POST", {"statement": "Created"})
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle("/api/v1/knowledge/facts", {}, post_http)
        assert result is not None
        assert result.status_code == 201

    def test_method_routing_for_fact_id_endpoint(self, handler):
        """Different HTTP methods route correctly for /facts/:id."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Method test", workspace_id="default")

        # GET routes to get single fact
        get_http = make_http_handler("GET")
        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, get_http)
        assert result.status_code == 200

        # PUT routes to update
        put_http = make_http_handler("PUT", {"confidence": 0.99})
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, put_http)
        assert result.status_code == 200

        # DELETE routes to delete
        delete_http = make_http_handler("DELETE")
        with patch.object(
            handler, "require_auth_or_error", return_value=(MockAuthenticatedUser(), None)
        ):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, delete_http)
        assert result.status_code == 200

    def test_method_routing_for_relations_endpoint(self, handler, get_handler):
        """GET and POST both work for /facts/:id/relations."""
        store = handler._get_fact_store()
        source = store.add_fact(statement="Source", workspace_id="default")
        target = store.add_fact(statement="Target", workspace_id="default")

        # GET returns relations
        result = handler.handle(f"/api/v1/knowledge/facts/{source.id}/relations", {}, get_handler)
        assert result.status_code == 200

        # POST adds relation
        post_http = make_http_handler(
            "POST",
            {"target_fact_id": target.id, "relation_type": "supports"},
        )
        result = handler.handle(f"/api/v1/knowledge/facts/{source.id}/relations", {}, post_http)
        assert result.status_code == 201
