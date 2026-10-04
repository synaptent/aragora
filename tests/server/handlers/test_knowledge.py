"""Tests for the knowledge handler module (aragora/server/handlers/knowledge.py).

This file tests:
- Deprecated re-export behavior from aragora.server.handlers.knowledge
- KnowledgeHandler route registration and can_handle
- Each endpoint happy path (list, get, create, update, delete facts; query; search; stats)
- Error cases (missing params, invalid input, not found)
- Permission/auth checks
- Edge cases (rate limiting, unknown routes, dynamic fact sub-routes)
"""

import json
import warnings
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from aragora.knowledge import InMemoryFactStore, ScopedFactStore
from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler
from aragora.server.handlers.base import error_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockAuthUser:
    """Mock authenticated user with full knowledge permissions."""

    org_id = "test-org-001"

    def __init__(self, user_id: str = "test-user", permissions=None, roles=None):
        self.user_id = user_id
        self.permissions = permissions or {
            "*",
            "admin",
            "knowledge.read",
            "knowledge.write",
            "knowledge.delete",
        }
        self.roles = roles or {"admin", "owner"}


class MockRestrictedUser:
    """Mock user with no permissions."""

    def __init__(self, user_id: str = "restricted-user"):
        self.user_id = user_id
        self.permissions = set()
        self.roles = set()


def _make_http_handler(method: str = "GET", body: dict | None = None) -> MagicMock:
    """Create a mock HTTP handler with optional JSON body."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 54321)
    handler.command = method
    if body is not None:
        raw = json.dumps(body).encode("utf-8")
        handler.headers = {"Content-Length": str(len(raw))}
        handler.rfile = BytesIO(raw)
    else:
        handler.headers = {"Content-Length": "0"}
    return handler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    """Create a KnowledgeHandler with minimal server context."""
    ctx = {"storage": None, "elo_system": None, "nomic_dir": None}
    h = KnowledgeHandler(ctx)
    h._fact_store = ScopedFactStore(InMemoryFactStore(), "test-org-001")
    return h


@pytest.fixture
def get_handler():
    """Shortcut for a GET mock handler."""
    return _make_http_handler("GET")


@pytest.fixture
def post_handler():
    """Shortcut for a POST mock handler (no body)."""
    return _make_http_handler("POST")


# ---------------------------------------------------------------------------
# 1. Deprecated re-export tests
# ---------------------------------------------------------------------------


class TestDeprecatedModule:
    """Tests for the knowledge_base module re-exports."""

    def test_knowledge_base_exports_knowledge_handler(self):
        """knowledge_base package exports KnowledgeHandler."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler as KH

        assert KH is KnowledgeHandler

    def test_knowledge_base_exports_mound_handler(self):
        """knowledge_base package exports KnowledgeMoundHandler."""
        from aragora.server.handlers.knowledge_base import KnowledgeMoundHandler
        from aragora.server.handlers.knowledge_base.mound.handler import (
            KnowledgeMoundHandler as Original,
        )

        assert KnowledgeMoundHandler is Original

    def test_knowledge_subpackage_exports_analytics(self):
        """knowledge subpackage exports AnalyticsHandler."""
        from aragora.server.handlers.knowledge import AnalyticsHandler

        assert AnalyticsHandler is not None


# ---------------------------------------------------------------------------
# 2. Route registration / can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    """Verify can_handle for every supported path pattern."""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge/query",
            "/api/v1/knowledge/facts",
            "/api/v1/knowledge/search",
            "/api/v1/knowledge/stats",
        ],
    )
    def test_static_routes(self, handler, path):
        assert handler.can_handle(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge/facts/abc-123",
            "/api/v1/knowledge/facts/abc-123/verify",
            "/api/v1/knowledge/facts/abc-123/contradictions",
            "/api/v1/knowledge/facts/abc-123/relations",
        ],
    )
    def test_dynamic_fact_routes(self, handler, path):
        assert handler.can_handle(path)

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/knowledge/unknown",
            "/api/v1/debates",
            "/api/v1/knowledge",
            "/api/knowledge/facts",
        ],
    )
    def test_non_matching_routes(self, handler, path):
        assert not handler.can_handle(path)


# ---------------------------------------------------------------------------
# 3. GET /api/v1/knowledge/facts  (list facts)
# ---------------------------------------------------------------------------


class TestListFacts:
    def test_list_facts_returns_expected_keys(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts", {}, get_handler)
        assert result is not None
        body = json.loads(result.body)
        assert "facts" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body

    def test_list_facts_respects_limit_and_offset(self, handler, get_handler):
        params = {"limit": "5", "offset": "2"}
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        body = json.loads(result.body)
        assert body["limit"] == 5
        assert body["offset"] == 2

    def test_list_facts_with_topic_filter(self, handler, get_handler):
        params = {"topic": "security", "min_confidence": "0.8"}
        result = handler.handle("/api/v1/knowledge/facts", params, get_handler)
        assert result is not None
        body = json.loads(result.body)
        assert isinstance(body["facts"], list)


# ---------------------------------------------------------------------------
# 4. GET /api/v1/knowledge/facts/:id  (get single fact)
# ---------------------------------------------------------------------------


class TestGetFact:
    def test_get_nonexistent_fact_returns_404(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/does-not-exist", {}, get_handler)
        assert result is not None
        assert result.status_code == 404

    def test_get_existing_fact(self, handler, get_handler):
        store = handler._get_fact_store()
        fact = store.add_fact(
            statement="Earth orbits the Sun",
            workspace_id="default",
            confidence=0.99,
        )
        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, get_handler)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["statement"] == "Earth orbits the Sun"
        assert body["confidence"] == 0.99


# ---------------------------------------------------------------------------
# 5. POST /api/v1/knowledge/facts  (create fact)
# ---------------------------------------------------------------------------


class TestCreateFact:
    def test_create_fact_success(self, handler):
        h = _make_http_handler(
            "POST",
            {"statement": "Water boils at 100C", "workspace_id": "science", "confidence": 0.95},
        )
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle("/api/v1/knowledge/facts", {}, h)
        assert result.status_code == 201
        body = json.loads(result.body)
        assert body["statement"] == "Water boils at 100C"
        assert body["confidence"] == 0.95

    def test_create_fact_missing_statement(self, handler):
        h = _make_http_handler("POST", {"workspace_id": "default"})
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle("/api/v1/knowledge/facts", {}, h)
        assert result.status_code == 400
        assert b"error" in result.body

    def test_create_fact_empty_body(self, handler):
        h = _make_http_handler("POST")
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle("/api/v1/knowledge/facts", {}, h)
        assert result is not None
        assert result.status_code == 400

    def test_create_fact_requires_auth(self, handler):
        h = _make_http_handler("POST", {"statement": "Test"})
        with patch.object(
            handler,
            "require_auth_or_error",
            return_value=(None, error_response("Unauthorized", 401)),
        ):
            result = handler.handle("/api/v1/knowledge/facts", {}, h)
        assert result.status_code == 401


# ---------------------------------------------------------------------------
# 6. PUT /api/v1/knowledge/facts/:id  (update fact)
# ---------------------------------------------------------------------------


class TestUpdateFact:
    def test_update_existing_fact(self, handler):
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Old statement", workspace_id="default", confidence=0.5)

        h = _make_http_handler("PUT", {"confidence": 0.99, "topics": ["updated"]})
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, h)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["confidence"] == 0.99

    def test_update_nonexistent_fact_returns_404(self, handler):
        h = _make_http_handler("PUT", {"confidence": 0.5})
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle("/api/v1/knowledge/facts/no-such-id", {}, h)
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# 7. DELETE /api/v1/knowledge/facts/:id
# ---------------------------------------------------------------------------


class TestDeleteFact:
    def test_delete_existing_fact(self, handler):
        store = handler._get_fact_store()
        fact = store.add_fact(statement="To be deleted", workspace_id="default")
        h = _make_http_handler("DELETE")
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, h)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["deleted"] is True

    def test_delete_nonexistent_fact_returns_404(self, handler):
        h = _make_http_handler("DELETE")
        with patch.object(handler, "require_auth_or_error", return_value=(MockAuthUser(), None)):
            result = handler.handle("/api/v1/knowledge/facts/gone", {}, h)
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# 8. POST /api/v1/knowledge/facts/:id/verify
# ---------------------------------------------------------------------------


class TestVerifyFact:
    def test_verify_nonexistent_fact_404(self, handler, post_handler):
        result = handler.handle("/api/v1/knowledge/facts/missing/verify", {}, post_handler)
        assert result.status_code == 404

    def test_verify_existing_fact_queued(self, handler, post_handler):
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Needs verification", workspace_id="default")
        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}/verify", {}, post_handler)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "queued"


# ---------------------------------------------------------------------------
# 9. GET /api/v1/knowledge/facts/:id/contradictions
# ---------------------------------------------------------------------------


class TestGetContradictions:
    def test_contradictions_nonexistent_fact_404(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/nope/contradictions", {}, get_handler)
        assert result.status_code == 404

    def test_contradictions_existing_fact(self, handler, get_handler):
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Some claim", workspace_id="default")
        result = handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/contradictions", {}, get_handler
        )
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "contradictions" in body
        assert "count" in body


# ---------------------------------------------------------------------------
# 10. GET /api/v1/knowledge/facts/:id/relations
# ---------------------------------------------------------------------------


class TestGetRelations:
    def test_relations_nonexistent_fact_404(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/facts/nope/relations", {}, get_handler)
        assert result.status_code == 404

    def test_relations_existing_fact(self, handler, get_handler):
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Related fact", workspace_id="default")
        result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}/relations", {}, get_handler)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "relations" in body
        assert "count" in body

    def test_relations_with_type_filter(self, handler, get_handler):
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Filtered fact", workspace_id="default")
        result = handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/relations",
            {"type": "supports"},
            get_handler,
        )
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# 11. POST /api/v1/knowledge/query
# ---------------------------------------------------------------------------


class TestQuery:
    def test_query_missing_question_returns_400(self, handler):
        h = _make_http_handler("POST", {})
        result = handler.handle("/api/v1/knowledge/query", {}, h)
        assert result.status_code == 400
        assert b"error" in result.body

    def test_query_with_valid_question(self, handler):
        h = _make_http_handler(
            "POST",
            {"question": "What is the security policy?", "workspace_id": "default"},
        )
        result = handler.handle("/api/v1/knowledge/query", {}, h)
        assert result is not None
        body = json.loads(result.body)
        assert isinstance(body, dict)

    def test_query_with_options(self, handler):
        h = _make_http_handler(
            "POST",
            {
                "question": "Compliance rules?",
                "workspace_id": "compliance",
                "options": {"max_chunks": 3, "use_agents": False},
            },
        )
        result = handler.handle("/api/v1/knowledge/query", {}, h)
        assert result is not None


# ---------------------------------------------------------------------------
# 12. GET /api/v1/knowledge/search
# ---------------------------------------------------------------------------


class TestSearch:
    def test_search_without_query_returns_400(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/search", {}, get_handler)
        assert result is not None
        assert result.status_code == 400

    def test_search_with_query(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/search", {"q": "security"}, get_handler)
        assert result is not None
        body = json.loads(result.body)
        assert isinstance(body, dict)


# ---------------------------------------------------------------------------
# 13. GET /api/v1/knowledge/stats
# ---------------------------------------------------------------------------


class TestStats:
    def test_stats_default(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/stats", {}, get_handler)
        assert result is not None
        assert result.status_code == 200

    def test_stats_with_workspace(self, handler, get_handler):
        result = handler.handle("/api/v1/knowledge/stats", {"workspace_id": "ws-1"}, get_handler)
        assert result.status_code == 200


# ---------------------------------------------------------------------------
# 14. Permission / auth checks
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_write_permission_denied(self, handler):
        """POST to create fact should fail when user lacks write permission."""
        h = _make_http_handler("POST", {"statement": "Not allowed"})
        restricted = MockRestrictedUser()
        with patch.object(handler, "require_auth_or_error", return_value=(restricted, None)):
            result = handler.handle("/api/v1/knowledge/facts", {}, h)
        assert result is not None
        assert result.status_code == 403

    def test_delete_permission_denied(self, handler):
        """DELETE should fail when user lacks delete permission."""
        store = handler._get_fact_store()
        fact = store.add_fact(statement="Protected", workspace_id="default")
        h = _make_http_handler("DELETE")
        restricted = MockRestrictedUser()
        with patch.object(handler, "require_auth_or_error", return_value=(restricted, None)):
            result = handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, h)
        assert result is not None
        assert result.status_code == 403


# ---------------------------------------------------------------------------
# 15. Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_dynamic_route_returns_404(self, handler, get_handler):
        """A deeply nested unknown sub-route should return 404."""
        result = handler.handle("/api/v1/knowledge/facts/some-id/unknown-action", {}, get_handler)
        assert result is not None
        assert result.status_code == 404

    def test_handle_returns_none_for_unmatched_static_path(self, handler, get_handler):
        """Handle returns None for a path not in ROUTES and not facts sub-route."""
        result = handler.handle("/api/v1/knowledge/other", {}, get_handler)
        assert result is None

    def test_fact_store_falls_back_to_inmemory(self, handler):
        """If FactStore() fails, handler falls back to InMemoryFactStore."""
        import importlib

        handler._fact_store = None  # reset
        handler_mod = importlib.import_module("aragora.server.handlers.knowledge_base.handler")
        with patch.object(handler_mod, "FactStore", side_effect=ValueError("DB unavailable")):
            store = handler._get_fact_store()
        from aragora.knowledge import InMemoryFactStore

        assert isinstance(store, InMemoryFactStore)

    def test_query_engine_uses_simple_engine(self, handler):
        """Query engine should be a SimpleQueryEngine with InMemoryFactStore."""
        handler._query_engine = None
        engine = handler._get_query_engine()
        from aragora.knowledge import SimpleQueryEngine

        assert isinstance(engine, SimpleQueryEngine)

    def test_routes_class_attribute(self, handler):
        """ROUTES should contain the four main static endpoints."""
        assert "/api/v1/knowledge/query" in handler.ROUTES
        assert "/api/v1/knowledge/facts" in handler.ROUTES
        assert "/api/v1/knowledge/search" in handler.ROUTES
        assert "/api/v1/knowledge/stats" in handler.ROUTES

    def test_permission_constants(self, handler):
        """Permission constants should be defined."""
        assert handler.KNOWLEDGE_READ_PERMISSION == "knowledge.read"
        assert handler.KNOWLEDGE_WRITE_PERMISSION == "knowledge.write"
        assert handler.KNOWLEDGE_DELETE_PERMISSION == "knowledge.delete"
