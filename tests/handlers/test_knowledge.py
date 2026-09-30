"""Tests for knowledge handler endpoints.

Tests the knowledge base API endpoints including:
- GET /api/knowledge/facts - List facts
- GET /api/knowledge/facts/:id - Get specific fact
- POST /api/knowledge/facts - Create a new fact
- PUT /api/knowledge/facts/:id - Update a fact
- DELETE /api/knowledge/facts/:id - Delete a fact
- POST /api/knowledge/query - Natural language query
- GET /api/knowledge/search - Search chunks
- GET /api/knowledge/stats - Get statistics
"""

import io
import json
from datetime import datetime
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def enable_real_auth_for_knowledge_tests(monkeypatch):
    """Enable real auth for knowledge tests.

    The @require_permission decorator has a test bypass mode. We need to disable it
    to properly test authentication behavior.
    """
    monkeypatch.setenv("ARAGORA_TEST_REAL_AUTH", "1")
    yield


def parse_body(result) -> dict:
    """Parse JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


class MockHandler:
    """Mock HTTP handler."""

    def __init__(self, method: str = "GET", body: dict | None = None):
        self.client_address = ("127.0.0.1", 12345)
        self.command = method
        self.headers = {"Content-Length": "0"}
        self._body = body or {}

        if body:
            body_bytes = json.dumps(body).encode("utf-8")
            self.headers["Content-Length"] = str(len(body_bytes))
            self.rfile = io.BytesIO(body_bytes)
        else:
            self.rfile = io.BytesIO(b"")


@pytest.fixture
def mock_handler():
    """Create mock GET handler."""
    return MockHandler()


@pytest.fixture
def mock_post_handler():
    """Create mock POST handler with body."""

    def _create(body: dict):
        return MockHandler(method="POST", body=body)

    return _create


@pytest.fixture
def mock_put_handler():
    """Create mock PUT handler with body."""

    def _create(body: dict):
        return MockHandler(method="PUT", body=body)

    return _create


@pytest.fixture
def mock_delete_handler():
    """Create mock DELETE handler."""
    return MockHandler(method="DELETE")


@pytest.fixture
def mock_fact():
    """Create a mock fact object."""

    class MockFact:
        def __init__(self, fact_id: str, statement: str):
            self.fact_id = fact_id
            self.statement = statement
            self.workspace_id = "default"
            self.confidence = 0.9
            self.topics = ["test"]
            self.sources: list[Any] = []
            self.created_at = datetime.now()
            self.updated_at = datetime.now()

        def to_dict(self) -> dict:
            return {
                "fact_id": self.fact_id,
                "statement": self.statement,
                "workspace_id": self.workspace_id,
                "confidence": self.confidence,
                "topics": self.topics,
                "sources": self.sources,
                "created_at": self.created_at.isoformat(),
                "updated_at": self.updated_at.isoformat(),
            }

    return MockFact


@pytest.fixture
def mock_fact_store(mock_fact):
    """Create a mock fact store."""
    store = MagicMock()

    facts = [
        mock_fact("fact-1", "The sky is blue"),
        mock_fact("fact-2", "Water is wet"),
    ]

    store.list_facts.return_value = facts
    store.get_fact.return_value = facts[0]
    store.add_fact.return_value = facts[0]
    store.update_fact.return_value = facts[0]
    store.delete_fact.return_value = True
    store.get_contradictions.return_value = []
    store.get_relations.return_value = []
    store.get_stats.return_value = {"total_facts": 2, "workspaces": 1}

    return store


@pytest.fixture
def mock_query_engine():
    """Create a mock query engine."""
    engine = MagicMock()

    class MockQueryResult:
        def to_dict(self):
            return {
                "answer": "Test answer",
                "facts_used": [],
                "confidence": 0.85,
            }

    # Make query awaitable
    async def async_query(*args, **kwargs):
        return MockQueryResult()

    engine.query = MagicMock(side_effect=lambda *a, **k: MockQueryResult())

    return engine


@pytest.fixture
def knowledge_handler(mock_fact_store, mock_query_engine):
    """Create KnowledgeHandler for testing."""
    from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

    ctx = {}
    handler = KnowledgeHandler(ctx)

    # Inject mocks
    handler._fact_store = mock_fact_store
    handler._query_engine = mock_query_engine

    return handler


# =============================================================================
# Tests for routing
# =============================================================================


class TestKnowledgeHandlerRouting:
    """Test routing logic for knowledge handler."""

    def test_can_handle_query(self):
        """Test can_handle for /api/knowledge/query."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler.can_handle("/api/v1/knowledge/query") is True

    def test_can_handle_facts(self):
        """Test can_handle for /api/knowledge/facts."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler.can_handle("/api/v1/knowledge/facts") is True

    def test_can_handle_facts_with_id(self):
        """Test can_handle for /api/knowledge/facts/:id."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler.can_handle("/api/v1/knowledge/facts/fact-123") is True

    def test_can_handle_search(self):
        """Test can_handle for /api/knowledge/search."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler.can_handle("/api/v1/knowledge/search") is True

    def test_can_handle_stats(self):
        """Test can_handle for /api/knowledge/stats."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler.can_handle("/api/v1/knowledge/stats") is True

    def test_cannot_handle_unrelated(self):
        """Test can_handle returns False for unrelated paths."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler.can_handle("/api/v1/debates") is False
        assert handler.can_handle("/api/v1/users") is False


# =============================================================================
# Tests for list facts
# =============================================================================


class TestListFacts:
    """Test GET /api/knowledge/facts."""

    def test_list_facts_success(self, knowledge_handler, mock_handler):
        """Test listing facts returns expected data."""
        result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "facts" in data
        assert len(data["facts"]) == 2
        assert data["total"] == 2

    def test_list_facts_with_filters(self, knowledge_handler, mock_handler):
        """Test listing facts with query parameters."""
        params = {
            "workspace_id": ["default"],
            "topic": ["test"],
            "min_confidence": ["0.5"],
            "limit": ["10"],
            "offset": ["0"],
        }

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, mock_handler)

        assert result is not None
        assert result.status_code == 200

    def test_list_facts_calls_store(self, knowledge_handler, mock_handler, mock_fact_store):
        """Test that list_facts calls the fact store correctly."""
        knowledge_handler.handle("/api/v1/knowledge/facts", {}, mock_handler)

        mock_fact_store.list_facts.assert_called_once()


# =============================================================================
# Tests for get fact
# =============================================================================


class TestGetFact:
    """Test GET /api/knowledge/facts/:id."""

    def test_get_fact_success(self, knowledge_handler, mock_handler):
        """Test getting a specific fact."""
        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, mock_handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert data["fact_id"] == "fact-1"

    def test_get_fact_not_found(self, knowledge_handler, mock_handler, mock_fact_store):
        """Test getting a non-existent fact."""
        mock_fact_store.get_fact.return_value = None

        result = knowledge_handler.handle("/api/v1/knowledge/facts/nonexistent", {}, mock_handler)

        assert result is not None
        assert result.status_code == 404


# =============================================================================
# Tests for create fact
# =============================================================================


class MockUnauthenticatedContext:
    """Mock unauthenticated user context."""

    is_authenticated = False
    user_id = None
    role = None
    error_reason = "No auth token provided"


class TestCreateFact:
    """Test POST /api/knowledge/facts."""

    @pytest.mark.no_auto_auth
    def test_create_fact_requires_auth(self, knowledge_handler, mock_post_handler):
        """Test that creating a fact requires authentication."""
        handler = mock_post_handler({"statement": "Test fact"})

        # Without auth context, the @require_permission denial answers 403
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result.status_code == 403
        assert json.loads(result.body) == {"error": "Permission denied"}

    def test_create_fact_with_auth(self, knowledge_handler, mock_post_handler):
        """Test creating a fact with valid auth."""
        handler = mock_post_handler({"statement": "Test fact", "workspace_id": "default"})

        # Mock auth
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(MagicMock(), None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        # 201 Created is the correct status code for resource creation
        assert result.status_code == 201

    def test_create_fact_missing_statement(self, knowledge_handler, mock_post_handler):
        """Test creating a fact without statement."""
        handler = mock_post_handler({})

        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(MagicMock(), None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400


# =============================================================================
# Tests for update fact
# =============================================================================


class TestUpdateFact:
    """Test PUT /api/knowledge/facts/:id."""

    @pytest.mark.no_auto_auth
    def test_update_fact_requires_auth(self, knowledge_handler, mock_put_handler):
        """Test that updating a fact requires authentication."""
        handler = mock_put_handler({"statement": "Updated fact"})

        # Without auth context, the @require_permission denial answers 403
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, handler)

        assert result.status_code == 403
        assert json.loads(result.body) == {"error": "Permission denied"}


# =============================================================================
# Tests for delete fact
# =============================================================================


class TestDeleteFact:
    """Test DELETE /api/knowledge/facts/:id."""

    @pytest.mark.no_auto_auth
    def test_delete_fact_requires_auth(self, knowledge_handler, mock_delete_handler):
        """Test that deleting a fact requires authentication."""
        # Without auth context, the @require_permission denial answers 403
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            result = knowledge_handler.handle(
                "/api/v1/knowledge/facts/fact-1", {}, mock_delete_handler
            )

        assert result.status_code == 403
        assert json.loads(result.body) == {"error": "Permission denied"}


# =============================================================================
# Tests for query
# =============================================================================


class TestQuery:
    """Test POST /api/knowledge/query."""

    def test_query_success(self, knowledge_handler, mock_post_handler):
        """Test natural language query."""
        handler = mock_post_handler(
            {
                "question": "What is the sky color?",
                "workspace_id": "default",
            }
        )

        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=MagicMock(to_dict=lambda: {"answer": "blue", "confidence": 0.9}),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "answer" in data

    def test_query_missing_question(self, knowledge_handler, mock_post_handler):
        """Test query without question."""
        handler = mock_post_handler({})

        result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_query_with_options(self, knowledge_handler, mock_post_handler):
        """Test query with custom options."""
        handler = mock_post_handler(
            {
                "question": "Test question",
                "options": {
                    "max_chunks": 5,
                    "use_agents": True,
                    "include_citations": True,
                },
            }
        )

        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=MagicMock(to_dict=lambda: {"answer": "test", "confidence": 0.9}),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 200


# =============================================================================
# Tests for stats
# =============================================================================


class TestStats:
    """Test GET /api/knowledge/stats."""

    def test_stats_success(self, knowledge_handler, mock_handler, mock_fact_store):
        """Test getting knowledge base statistics."""
        mock_fact_store.get_stats.return_value = {
            "total_facts": 100,
            "workspaces": 3,
            "topics": 10,
        }

        result = knowledge_handler.handle("/api/v1/knowledge/stats", {}, mock_handler)

        assert result is not None
        # Note: _handle_stats may need fact_store.get_stats() to exist
        # The implementation uses query engine stats

    def test_stats_with_workspace(self, knowledge_handler, mock_handler):
        """Test getting stats for specific workspace."""
        params = {"workspace_id": ["test-workspace"]}

        result = knowledge_handler.handle("/api/v1/knowledge/stats", params, mock_handler)

        assert result is not None


# =============================================================================
# Tests for rate limiting
# =============================================================================


class TestRateLimiting:
    """Test rate limiting for knowledge endpoints."""

    def test_rate_limit_respected(self, knowledge_handler):
        """Test that rate limiter is checked."""
        from aragora.server.handlers.knowledge_base.handler import _knowledge_limiter

        # Verify limiter exists and has expected configuration
        assert _knowledge_limiter is not None
        assert _knowledge_limiter.rpm == 60  # rpm is the attribute name


# =============================================================================
# Tests for fact routes
# =============================================================================


class TestFactRoutes:
    """Test dynamic fact routes."""

    def test_verify_route(self, knowledge_handler, mock_handler):
        """Test /api/knowledge/facts/:id/verify route parsing."""
        # Verify is POST
        handler = MockHandler(method="POST", body={})
        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/verify", {}, handler)

        # Will require auth or other validation
        assert result is not None

    def test_contradictions_route(self, knowledge_handler, mock_handler, mock_fact_store):
        """Test /api/knowledge/facts/:id/contradictions route."""
        mock_fact_store.get_contradictions.return_value = []

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/fact-1/contradictions", {}, mock_handler
        )

        assert result is not None

    def test_relations_route(self, knowledge_handler, mock_handler, mock_fact_store):
        """Test /api/knowledge/facts/:id/relations route."""
        mock_fact_store.get_relations.return_value = []

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/fact-1/relations", {}, mock_handler
        )

        assert result is not None


# =============================================================================
# Tests for fact store initialization
# =============================================================================


class TestFactStoreInitialization:
    """Test fact store lazy initialization."""

    def test_get_fact_store_fallback_to_memory(self):
        """Test fallback to InMemoryFactStore when FactStore fails."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})

        # Patch FactStore to fail
        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("DB not available"),
        ):
            store = handler._get_fact_store()

        # Should fall back to InMemoryFactStore
        from aragora.knowledge import InMemoryFactStore

        assert isinstance(store, InMemoryFactStore)

    def test_get_fact_store_caches_instance(self):
        """Test that fact store is cached after first access."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("DB not available"),
        ):
            store1 = handler._get_fact_store()
            store2 = handler._get_fact_store()

        # Should be same instance
        assert store1 is store2


# =============================================================================
# Tests for query engine initialization
# =============================================================================


class TestQueryEngineInitialization:
    """Test query engine lazy initialization."""

    def test_get_query_engine_creates_simple_engine(self):
        """Test that query engine is created with fact store."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("DB not available"),
        ):
            engine = handler._get_query_engine()

        # Should be SimpleQueryEngine
        from aragora.knowledge import SimpleQueryEngine

        assert isinstance(engine, SimpleQueryEngine)

    def test_get_query_engine_caches_instance(self):
        """Test that query engine is cached after first access."""
        from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("DB not available"),
        ):
            engine1 = handler._get_query_engine()
            engine2 = handler._get_query_engine()

        # Should be same instance
        assert engine1 is engine2
