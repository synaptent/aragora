"""Integration tests for modular Knowledge Base handlers.

Tests the knowledge_base module handlers:
- handler.py: KnowledgeHandler initialization and routing
- facts.py: FactsOperationsMixin CRUD operations
- query.py: QueryOperationsMixin natural language queries
- search.py: SearchOperationsMixin search and stats

Uses pytest and pytest-asyncio with mocked knowledge mound facade.
"""

import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Helper Functions
# =============================================================================


def parse_body(result) -> dict:
    """Parse JSON body from HandlerResult."""
    return json.loads(result.body.decode("utf-8"))


def create_handler(method: str = "GET", body: dict | None = None) -> MagicMock:
    """Create a mock HTTP handler with configurable method and body."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.command = method
    handler.headers = {"Content-Length": "0", "Host": "localhost:8080"}

    if body:
        body_bytes = json.dumps(body).encode("utf-8")
        handler.headers["Content-Length"] = str(len(body_bytes))
        handler.headers["Content-Type"] = "application/json"
        handler.rfile = io.BytesIO(body_bytes)
    else:
        handler.rfile = io.BytesIO(b"")

    return handler


# =============================================================================
# Mock Knowledge Types
# =============================================================================


@dataclass
class MockFact:
    """Mock fact for testing."""

    id: str
    statement: str
    confidence: float = 0.9
    workspace_id: str = "default"
    topics: list[str] = field(default_factory=lambda: ["test"])
    evidence_ids: list[str] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    validation_status: str = "unverified"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    superseded_by: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "statement": self.statement,
            "confidence": self.confidence,
            "workspace_id": self.workspace_id,
            "topics": self.topics,
            "evidence_ids": self.evidence_ids,
            "source_documents": self.source_documents,
            "validation_status": self.validation_status,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "superseded_by": self.superseded_by,
        }


@dataclass
class MockFactRelation:
    """Mock fact relation for testing."""

    id: str
    source_fact_id: str
    target_fact_id: str
    relation_type: str
    confidence: float = 0.5
    created_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_fact_id": self.source_fact_id,
            "target_fact_id": self.target_fact_id,
            "relation_type": self.relation_type,
            "confidence": self.confidence,
            "created_by": self.created_by,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class MockQueryResult:
    """Mock query result for testing."""

    answer: str
    facts: list[MockFact] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    confidence: float = 0.85
    query: str = ""
    workspace_id: str = "default"
    processing_time_ms: int = 100

    def to_dict(self) -> dict:
        return {
            "answer": self.answer,
            "facts": [f.to_dict() for f in self.facts],
            "evidence_ids": self.evidence_ids,
            "confidence": self.confidence,
            "query": self.query,
            "workspace_id": self.workspace_id,
            "processing_time_ms": self.processing_time_ms,
        }


@dataclass
class MockSearchResult:
    """Mock search result for testing."""

    chunk_id: str
    content: str
    score: float
    document_id: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "content": self.content,
            "score": self.score,
            "document_id": self.document_id,
            "metadata": self.metadata,
        }


@dataclass
class MockVerificationResult:
    """Mock verification result for testing."""

    fact_id: str
    success: bool = True
    new_status: str = "majority_agreed"
    confidence: float = 0.9
    agent_votes: dict[str, bool] = field(default_factory=dict)
    dissenting_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "success": self.success,
            "new_status": self.new_status,
            "confidence": self.confidence,
            "agent_votes": self.agent_votes,
            "dissenting_reasons": self.dissenting_reasons,
        }


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def clear_rate_limits():
    """Clear rate limiters before each test to prevent pollution."""
    from aragora.server.handlers.utils.rate_limit import clear_all_limiters
    from aragora.server.handlers.knowledge_base import handler as kh

    clear_all_limiters()
    # Also clear the module-level knowledge handler limiter
    kh._knowledge_limiter.clear()
    yield
    clear_all_limiters()
    kh._knowledge_limiter.clear()


@pytest.fixture
def mock_fact_store():
    """Create a mock fact store with common operations."""
    store = MagicMock()

    # Sample facts
    facts = [
        MockFact(id="fact-1", statement="The sky is blue"),
        MockFact(id="fact-2", statement="Water is H2O"),
        MockFact(id="fact-3", statement="Python is a programming language"),
    ]

    # Configure store methods
    store.list_facts.return_value = facts[:2]
    store.get_fact.side_effect = lambda fid: next((f for f in facts if f.id == fid), None)
    store.add_fact.return_value = facts[0]
    store.update_fact.return_value = facts[0]
    store.delete_fact.return_value = True
    store.get_contradictions.return_value = []
    store.get_relations.return_value = []
    store.add_relation.return_value = MockFactRelation(
        id="rel-1",
        source_fact_id="fact-1",
        target_fact_id="fact-2",
        relation_type="supports",
    )
    store.get_statistics.return_value = {
        "total_facts": 3,
        "workspaces": 1,
        "topics": 2,
        "verified_facts": 1,
    }

    return store


@pytest.fixture
def mock_query_engine():
    """Create a mock query engine."""
    engine = MagicMock()

    # Configure async query method
    async def async_query(*args, **kwargs):
        return MockQueryResult(
            answer="The sky appears blue due to Rayleigh scattering.",
            query=args[0] if args else "",
        )

    async def async_search(*args, **kwargs):
        return [
            MockSearchResult(
                chunk_id="chunk-1",
                content="The sky is blue because...",
                score=0.95,
                document_id="doc-1",
            ),
            MockSearchResult(
                chunk_id="chunk-2",
                content="Blue light scatters more...",
                score=0.87,
                document_id="doc-2",
            ),
        ]

    async def async_verify(*args, **kwargs):
        return MockVerificationResult(fact_id=args[0] if args else "fact-1")

    engine.query = AsyncMock(side_effect=async_query)
    engine.search = AsyncMock(side_effect=async_search)
    engine.verify_fact = AsyncMock(side_effect=async_verify)

    return engine


@pytest.fixture
def mock_embedding_service():
    """Create a mock embedding service."""
    service = MagicMock()
    service.embed.return_value = [0.1, 0.2, 0.3]  # Mock embedding vector
    service.embed_batch.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    return service


@pytest.fixture
def knowledge_handler(mock_fact_store, mock_query_engine):
    """Create KnowledgeHandler with mocked dependencies."""
    from aragora.server.handlers.knowledge_base import KnowledgeHandler

    handler = KnowledgeHandler({})
    handler._fact_store = mock_fact_store
    handler._query_engine = mock_query_engine
    return handler


@pytest.fixture
def authenticated_handler(knowledge_handler):
    """Create handler with mocked authentication."""
    mock_user = MagicMock()
    mock_user.user_id = "user-123"
    mock_user.email = "test@example.com"
    mock_user.is_authenticated = True

    with patch.object(knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)):
        yield knowledge_handler


# =============================================================================
# Tests: KnowledgeHandler Initialization
# =============================================================================


class TestKnowledgeHandlerInitialization:
    """Test KnowledgeHandler initialization and lazy loading."""

    def test_initialization_with_empty_context(self):
        """Test handler initializes with empty server context."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        handler = KnowledgeHandler({})
        assert handler._fact_store is None
        assert handler._query_engine is None

    def test_initialization_preserves_context(self):
        """Test handler preserves server context."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        ctx = {"storage": MagicMock(), "user_store": MagicMock()}
        handler = KnowledgeHandler(ctx)
        assert handler.ctx == ctx

    def test_get_fact_store_creates_instance(self):
        """Test lazy initialization of fact store."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        handler = KnowledgeHandler({})

        # Mock the FactStore to avoid database dependency
        with patch("aragora.server.handlers.knowledge_base.handler.FactStore") as MockFactStore:
            MockFactStore.return_value = MagicMock()
            store = handler._get_fact_store()
            assert store is not None
            MockFactStore.assert_called_once()

    def test_get_fact_store_fallback_to_inmemory(self):
        """Test fallback to InMemoryFactStore when FactStore fails."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("Database unavailable"),
        ):
            store = handler._get_fact_store()

        from aragora.knowledge import InMemoryFactStore

        assert isinstance(store, InMemoryFactStore)

    def test_get_fact_store_caches_instance(self):
        """Test that fact store is cached after creation."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("Database unavailable"),
        ):
            store1 = handler._get_fact_store()
            store2 = handler._get_fact_store()

        assert store1 is store2

    def test_get_query_engine_creates_instance(self):
        """Test lazy initialization of query engine."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("Database unavailable"),
        ):
            engine = handler._get_query_engine()

        from aragora.knowledge import SimpleQueryEngine

        assert isinstance(engine, SimpleQueryEngine)

    def test_get_query_engine_caches_instance(self):
        """Test that query engine is cached after creation."""
        from aragora.server.handlers.knowledge_base import KnowledgeHandler

        handler = KnowledgeHandler({})

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("Database unavailable"),
        ):
            engine1 = handler._get_query_engine()
            engine2 = handler._get_query_engine()

        assert engine1 is engine2


# =============================================================================
# Tests: Routing
# =============================================================================


class TestKnowledgeHandlerRouting:
    """Test routing logic for knowledge handler."""

    def test_can_handle_query_endpoint(self, knowledge_handler):
        """Test can_handle recognizes query endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/query") is True

    def test_can_handle_facts_endpoint(self, knowledge_handler):
        """Test can_handle recognizes facts endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts") is True

    def test_can_handle_facts_with_id(self, knowledge_handler):
        """Test can_handle recognizes facts with ID."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-123") is True

    def test_can_handle_facts_with_action(self, knowledge_handler):
        """Test can_handle recognizes facts with actions."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-1/verify") is True
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-1/contradictions") is True
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-1/relations") is True

    def test_can_handle_search_endpoint(self, knowledge_handler):
        """Test can_handle recognizes search endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/search") is True

    def test_can_handle_stats_endpoint(self, knowledge_handler):
        """Test can_handle recognizes stats endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/stats") is True

    def test_cannot_handle_unrelated_paths(self, knowledge_handler):
        """Test can_handle rejects unrelated paths."""
        assert knowledge_handler.can_handle("/api/v1/debates") is False
        assert knowledge_handler.can_handle("/api/v1/agents") is False
        assert knowledge_handler.can_handle("/api/v1/users") is False
        assert knowledge_handler.can_handle("/") is False

    def test_routes_class_attribute(self, knowledge_handler):
        """Test ROUTES class attribute contains expected endpoints."""
        assert "/api/v1/knowledge/query" in knowledge_handler.ROUTES
        assert "/api/v1/knowledge/facts" in knowledge_handler.ROUTES
        assert "/api/v1/knowledge/search" in knowledge_handler.ROUTES
        assert "/api/v1/knowledge/stats" in knowledge_handler.ROUTES


# =============================================================================
# Tests: Facts Operations (FactsOperationsMixin)
# =============================================================================


class TestFactsListOperation:
    """Test GET /api/knowledge/facts - List facts."""

    def test_list_facts_success(self, knowledge_handler, mock_fact_store):
        """Test listing facts returns expected data structure."""
        handler = create_handler()
        result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "facts" in data
        assert "total" in data
        assert "limit" in data
        assert "offset" in data
        assert len(data["facts"]) == 2

    def test_list_facts_with_workspace_filter(self, knowledge_handler, mock_fact_store):
        """Test listing facts with workspace filter."""
        handler = create_handler()
        params = {"workspace_id": ["test-workspace"]}

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        assert result.status_code == 200
        mock_fact_store.list_facts.assert_called()

    def test_list_facts_with_topic_filter(self, knowledge_handler, mock_fact_store):
        """Test listing facts with topic filter."""
        handler = create_handler()
        params = {"topic": ["science"]}

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        assert result.status_code == 200

    def test_list_facts_with_confidence_filter(self, knowledge_handler, mock_fact_store):
        """Test listing facts with minimum confidence filter."""
        handler = create_handler()
        params = {"min_confidence": ["0.8"]}

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        assert result.status_code == 200

    def test_list_facts_with_pagination(self, knowledge_handler, mock_fact_store):
        """Test listing facts with pagination parameters."""
        handler = create_handler()
        params = {"limit": ["10"], "offset": ["5"]}

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        assert result.status_code == 200
        data = parse_body(result)
        assert data["limit"] == 10
        assert data["offset"] == 5

    def test_list_facts_includes_superseded(self, knowledge_handler, mock_fact_store):
        """Test listing facts with include_superseded parameter."""
        handler = create_handler()
        params = {"include_superseded": ["true"]}

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        assert result.status_code == 200


class TestFactsGetOperation:
    """Test GET /api/knowledge/facts/:id - Get specific fact."""

    def test_get_fact_success(self, knowledge_handler, mock_fact_store):
        """Test getting a specific fact."""
        handler = create_handler()
        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert data["id"] == "fact-1"
        assert data["statement"] == "The sky is blue"

    def test_get_fact_not_found(self, knowledge_handler, mock_fact_store):
        """Test getting a non-existent fact returns 404."""
        mock_fact_store.get_fact.return_value = None
        handler = create_handler()

        result = knowledge_handler.handle("/api/v1/knowledge/facts/nonexistent", {}, handler)

        assert result is not None
        assert result.status_code == 404


class TestFactsCreateOperation:
    """Test POST /api/knowledge/facts - Create fact."""

    @pytest.mark.no_auto_auth
    def test_create_fact_requires_auth(self, knowledge_handler):
        """Test creating a fact requires authentication (403, not a raised denial)."""
        handler = create_handler("POST", {"statement": "Test fact"})

        # Without auth context, the @require_permission denial answers 403
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result.status_code == 403
        assert json.loads(result.body) == {"error": "Permission denied"}

    def test_create_fact_success(self, knowledge_handler, mock_fact_store):
        """Test creating a fact with valid auth."""
        handler = create_handler(
            "POST",
            {
                "statement": "New test fact",
                "workspace_id": "default",
                "confidence": 0.8,
                "topics": ["test"],
            },
        )

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 201
        mock_fact_store.add_fact.assert_called_once()

    def test_create_fact_missing_statement(self, knowledge_handler):
        """Test creating a fact without statement returns 400."""
        handler = create_handler("POST", {"workspace_id": "default"})

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_create_fact_empty_body(self, knowledge_handler):
        """Test creating a fact with empty body returns 400."""
        handler = create_handler("POST")
        handler.headers["Content-Length"] = "0"

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_create_fact_invalid_json(self, knowledge_handler):
        """Test creating a fact with invalid JSON returns 400."""
        handler = create_handler()
        handler.command = "POST"
        handler.headers["Content-Length"] = "10"
        handler.rfile = io.BytesIO(b"not json!!")

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400


class TestFactsUpdateOperation:
    """Test PUT /api/knowledge/facts/:id - Update fact."""

    @pytest.mark.no_auto_auth
    def test_update_fact_requires_auth(self, knowledge_handler):
        """Test updating a fact requires authentication (403, not a raised denial)."""
        handler = create_handler("PUT", {"confidence": 0.95})

        # Without auth context, the @require_permission denial answers 403
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, handler)

        assert result.status_code == 403
        assert json.loads(result.body) == {"error": "Permission denied"}

    def test_update_fact_success(self, knowledge_handler, mock_fact_store):
        """Test updating a fact with valid auth."""
        handler = create_handler(
            "PUT",
            {
                "confidence": 0.95,
                "topics": ["updated", "science"],
            },
        )

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, handler)

        assert result is not None
        assert result.status_code == 200
        mock_fact_store.update_fact.assert_called_once()

    def test_update_fact_not_found(self, knowledge_handler, mock_fact_store):
        """Test updating a non-existent fact returns 404."""
        mock_fact_store.update_fact.return_value = None
        handler = create_handler("PUT", {"confidence": 0.95})

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/nonexistent", {}, handler)

        assert result is not None
        assert result.status_code == 404


class TestFactsDeleteOperation:
    """Test DELETE /api/knowledge/facts/:id - Delete fact."""

    @pytest.mark.no_auto_auth
    def test_delete_fact_requires_auth(self, knowledge_handler):
        """Test deleting a fact requires authentication (403, not a raised denial)."""
        handler = create_handler("DELETE")

        # Without auth context, the @require_permission denial answers 403
        with patch("aragora.server.auth.auth_config") as mock_auth:
            mock_auth.enabled = True
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, handler)

        assert result.status_code == 403
        assert json.loads(result.body) == {"error": "Permission denied"}

    def test_delete_fact_success(self, knowledge_handler, mock_fact_store):
        """Test deleting a fact with valid auth."""
        handler = create_handler("DELETE")

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, handler)

        assert result is not None
        assert result.status_code == 200
        mock_fact_store.delete_fact.assert_called_once_with("fact-1")

    def test_delete_fact_not_found(self, knowledge_handler, mock_fact_store):
        """Test deleting a non-existent fact returns 404."""
        mock_fact_store.delete_fact.return_value = False
        handler = create_handler("DELETE")

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/nonexistent", {}, handler)

        assert result is not None
        assert result.status_code == 404


class TestFactsVerifyOperation:
    """Test POST /api/knowledge/facts/:id/verify - Verify fact."""

    def test_verify_fact_not_found(self, knowledge_handler, mock_fact_store):
        """Test verifying a non-existent fact returns 404."""
        mock_fact_store.get_fact.return_value = None
        handler = create_handler("POST", {})

        result = knowledge_handler.handle("/api/v1/knowledge/facts/nonexistent/verify", {}, handler)

        assert result is not None
        assert result.status_code == 404

    def test_verify_fact_queued_for_simple_engine(self, knowledge_handler, mock_fact_store):
        """Test verifying fact is queued when using SimpleQueryEngine."""
        handler = create_handler("POST", {})

        # Reset query engine to force SimpleQueryEngine
        knowledge_handler._query_engine = None

        with patch(
            "aragora.server.handlers.knowledge_base.handler.FactStore",
            side_effect=RuntimeError("DB unavailable"),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/verify", {}, handler)

        assert result is not None
        assert result.status_code == 200
        data = parse_body(result)
        assert data.get("status") == "queued"


class TestFactsContradictionsOperation:
    """Test GET /api/knowledge/facts/:id/contradictions."""

    def test_get_contradictions_success(self, knowledge_handler, mock_fact_store):
        """Test getting contradictions for a fact."""
        handler = create_handler()

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/fact-1/contradictions", {}, handler
        )

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "fact_id" in data
        assert "contradictions" in data
        assert "count" in data

    def test_get_contradictions_not_found(self, knowledge_handler, mock_fact_store):
        """Test getting contradictions for non-existent fact returns 404."""
        mock_fact_store.get_fact.return_value = None
        handler = create_handler()

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent/contradictions", {}, handler
        )

        assert result is not None
        assert result.status_code == 404


class TestFactsRelationsOperation:
    """Test GET/POST /api/knowledge/facts/:id/relations."""

    def test_get_relations_success(self, knowledge_handler, mock_fact_store):
        """Test getting relations for a fact."""
        handler = create_handler()

        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/relations", {}, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "fact_id" in data
        assert "relations" in data
        assert "count" in data

    def test_get_relations_not_found(self, knowledge_handler, mock_fact_store):
        """Test getting relations for non-existent fact returns 404."""
        mock_fact_store.get_fact.return_value = None
        handler = create_handler()

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent/relations", {}, handler
        )

        assert result is not None
        assert result.status_code == 404

    def test_get_relations_with_type_filter(self, knowledge_handler, mock_fact_store):
        """Test getting relations with type filter."""
        handler = create_handler()
        params = {"type": ["supports"]}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/fact-1/relations", params, handler
        )

        assert result is not None
        assert result.status_code == 200

    def test_add_relation_success(self, knowledge_handler, mock_fact_store):
        """Test adding a relation between facts."""
        handler = create_handler(
            "POST",
            {
                "target_fact_id": "fact-2",
                "relation_type": "supports",
                "confidence": 0.8,
            },
        )

        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/relations", {}, handler)

        assert result is not None
        assert result.status_code == 201

    def test_add_relation_missing_target(self, knowledge_handler, mock_fact_store):
        """Test adding a relation without target_fact_id returns 400."""
        handler = create_handler("POST", {"relation_type": "supports"})

        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/relations", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_add_relation_missing_type(self, knowledge_handler, mock_fact_store):
        """Test adding a relation without relation_type returns 400."""
        handler = create_handler("POST", {"target_fact_id": "fact-2"})

        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/relations", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_add_relation_invalid_type(self, knowledge_handler, mock_fact_store):
        """Test adding a relation with invalid type returns 400."""
        handler = create_handler(
            "POST",
            {
                "target_fact_id": "fact-2",
                "relation_type": "invalid_type",
            },
        )

        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/relations", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_add_relation_source_not_found(self, knowledge_handler, mock_fact_store):
        """Test adding a relation with non-existent source returns 404."""
        mock_fact_store.get_fact.side_effect = lambda fid: (
            MockFact(id="fact-2", statement="test") if fid == "fact-2" else None
        )

        handler = create_handler(
            "POST",
            {
                "target_fact_id": "fact-2",
                "relation_type": "supports",
            },
        )

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent/relations", {}, handler
        )

        assert result is not None
        assert result.status_code == 404


class TestFactsRelationsBulkOperation:
    """Test POST /api/knowledge/facts/relations - Bulk add relation."""

    def test_add_relation_bulk_success(self, knowledge_handler, mock_fact_store):
        """Test adding a relation via bulk endpoint."""
        handler = create_handler(
            "POST",
            {
                "source_fact_id": "fact-1",
                "target_fact_id": "fact-2",
                "relation_type": "supports",
            },
        )

        result = knowledge_handler.handle("/api/v1/knowledge/facts/relations", {}, handler)

        assert result is not None
        assert result.status_code == 201

    def test_add_relation_bulk_missing_source(self, knowledge_handler):
        """Test bulk relation without source_fact_id returns 400."""
        handler = create_handler(
            "POST",
            {
                "target_fact_id": "fact-2",
                "relation_type": "supports",
            },
        )

        result = knowledge_handler.handle("/api/v1/knowledge/facts/relations", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_add_relation_bulk_missing_target(self, knowledge_handler):
        """Test bulk relation without target_fact_id returns 400."""
        handler = create_handler(
            "POST",
            {
                "source_fact_id": "fact-1",
                "relation_type": "supports",
            },
        )

        result = knowledge_handler.handle("/api/v1/knowledge/facts/relations", {}, handler)

        assert result is not None
        assert result.status_code == 400


# =============================================================================
# Tests: Query Operations (QueryOperationsMixin)
# =============================================================================


class TestQueryOperation:
    """Test POST /api/knowledge/query - Natural language query."""

    def test_query_success(self, knowledge_handler, mock_query_engine):
        """Test natural language query returns expected data."""
        handler = create_handler(
            "POST",
            {
                "question": "Why is the sky blue?",
                "workspace_id": "default",
            },
        )

        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=MockQueryResult(answer="Rayleigh scattering"),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "answer" in data

    def test_query_missing_question(self, knowledge_handler):
        """Test query without question returns 400."""
        handler = create_handler("POST", {"workspace_id": "default"})

        result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_query_empty_body(self, knowledge_handler):
        """Test query with empty body returns 400."""
        handler = create_handler("POST", {})

        result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_query_with_options(self, knowledge_handler, mock_query_engine):
        """Test query with custom options."""
        handler = create_handler(
            "POST",
            {
                "question": "What is water?",
                "options": {
                    "max_chunks": 5,
                    "search_alpha": 0.7,
                    "use_agents": True,
                    "extract_facts": True,
                    "include_citations": True,
                },
            },
        )

        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=MockQueryResult(answer="H2O"),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 200

    def test_query_error_handling(self, knowledge_handler, mock_query_engine):
        """Test query handles engine errors gracefully."""
        handler = create_handler(
            "POST",
            {
                "question": "Test question",
            },
        )

        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            side_effect=RuntimeError("Query engine error"),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 500


# =============================================================================
# Tests: Search Operations (SearchOperationsMixin)
# =============================================================================


class TestSearchOperation:
    """Test GET /api/knowledge/search - Search chunks."""

    def test_search_success(self, knowledge_handler, mock_query_engine):
        """Test search returns expected data structure."""
        handler = create_handler()
        params = {"q": ["blue sky"]}

        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async",
            return_value=[
                MockSearchResult(
                    chunk_id="chunk-1",
                    content="Blue sky...",
                    score=0.9,
                    document_id="doc-1",
                )
            ],
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/search", params, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "query" in data
        assert "results" in data
        assert "count" in data

    def test_search_missing_query(self, knowledge_handler):
        """Test search without query returns 400."""
        handler = create_handler()
        params = {}

        result = knowledge_handler.handle("/api/v1/knowledge/search", params, handler)

        assert result is not None
        assert result.status_code == 400

    def test_search_with_workspace(self, knowledge_handler, mock_query_engine):
        """Test search with workspace filter."""
        handler = create_handler()
        params = {"q": ["test"], "workspace_id": ["custom-workspace"]}

        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async",
            return_value=[],
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/search", params, handler)

        assert result is not None
        assert result.status_code == 200

    def test_search_with_limit(self, knowledge_handler, mock_query_engine):
        """Test search with custom limit."""
        handler = create_handler()
        params = {"q": ["test"], "limit": ["5"]}

        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async",
            return_value=[],
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/search", params, handler)

        assert result is not None
        assert result.status_code == 200

    def test_search_error_handling(self, knowledge_handler, mock_query_engine):
        """Test search handles engine errors gracefully."""
        handler = create_handler()
        params = {"q": ["test"]}

        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async",
            side_effect=RuntimeError("Search engine error"),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/search", params, handler)

        assert result is not None
        assert result.status_code == 500


class TestStatsOperation:
    """Test GET /api/knowledge/stats - Statistics."""

    def test_stats_success(self, knowledge_handler, mock_fact_store):
        """Test stats returns expected data structure."""
        handler = create_handler()

        result = knowledge_handler.handle("/api/v1/knowledge/stats", {}, handler)

        assert result is not None
        assert result.status_code == 200

        data = parse_body(result)
        assert "workspace_id" in data

    def test_stats_with_workspace(self, knowledge_handler, mock_fact_store):
        """Test stats with workspace filter."""
        handler = create_handler()
        params = {"workspace_id": ["test-workspace"]}

        result = knowledge_handler.handle("/api/v1/knowledge/stats", params, handler)

        assert result is not None
        assert result.status_code == 200


# =============================================================================
# Tests: Rate Limiting
# =============================================================================


class TestRateLimiting:
    """Test rate limiting for knowledge endpoints."""

    def test_rate_limiter_configuration(self):
        """Test rate limiter has expected configuration."""
        from aragora.server.handlers.knowledge_base.handler import _knowledge_limiter

        assert _knowledge_limiter is not None
        assert _knowledge_limiter.rpm == 60

    def test_rate_limit_enforcement(self, knowledge_handler, mock_fact_store):
        """Test rate limiting is checked on requests."""
        from aragora.server.handlers.knowledge_base.handler import _knowledge_limiter

        # Reset the rate limiter for clean test
        with _knowledge_limiter._lock:
            _knowledge_limiter._buckets.clear()

        handler = create_handler()

        # First request should succeed
        result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)
        assert result is not None
        assert result.status_code == 200


# =============================================================================
# Tests: Error Handling
# =============================================================================


class TestErrorHandling:
    """Test error handling across knowledge handlers."""

    def test_unknown_endpoint_returns_404(self, knowledge_handler):
        """Test unknown endpoint within facts returns 404."""
        handler = create_handler()

        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1/unknown", {}, handler)

        assert result is not None
        assert result.status_code == 404

    def test_invalid_json_returns_400(self, knowledge_handler):
        """Test invalid JSON in request body returns 400."""
        handler = create_handler()
        handler.command = "POST"
        handler.headers["Content-Length"] = "15"
        handler.rfile = io.BytesIO(b"not valid json!")

        mock_user = MagicMock()
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_handles_store_exceptions(self, knowledge_handler, mock_fact_store):
        """Test handler gracefully handles store exceptions."""
        mock_fact_store.list_facts.side_effect = RuntimeError("Database error")
        handler = create_handler()

        result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        # Should return 500 due to @handle_errors decorator
        assert result is not None
        assert result.status_code == 500


# =============================================================================
# Tests: Parameter Validation
# =============================================================================


class TestParameterValidation:
    """Test parameter validation across handlers."""

    def test_bounded_string_param_truncation(self, knowledge_handler, mock_fact_store):
        """Test that string parameters are bounded."""
        handler = create_handler()
        params = {"workspace_id": ["a" * 200]}  # Exceeds max_length of 100

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        # Should still work, parameter gets truncated

    def test_clamped_int_param_bounds(self, knowledge_handler, mock_fact_store):
        """Test that int parameters are clamped."""
        handler = create_handler()
        params = {"limit": ["1000"]}  # Exceeds max_val of 200

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        assert result.status_code == 200
        data = parse_body(result)
        assert data["limit"] <= 200

    def test_bounded_float_param_bounds(self, knowledge_handler, mock_fact_store):
        """Test that float parameters are bounded."""
        handler = create_handler()
        params = {"min_confidence": ["2.0"]}  # Exceeds max_val of 1.0

        result = knowledge_handler.handle("/api/v1/knowledge/facts", params, handler)

        assert result is not None
        # Should still work, parameter gets clamped


# =============================================================================
# Tests: Integration Scenarios
# =============================================================================


class TestIntegrationScenarios:
    """Integration tests for common usage scenarios."""

    def test_full_fact_lifecycle(self, knowledge_handler, mock_fact_store):
        """Test creating, reading, updating, and deleting a fact."""
        mock_user = MagicMock()

        # Create
        create_handler_obj = create_handler(
            "POST",
            {
                "statement": "Integration test fact",
                "workspace_id": "integration",
            },
        )
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, create_handler_obj)
        assert result.status_code == 201

        # Read
        read_handler = create_handler()
        result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, read_handler)
        assert result.status_code == 200

        # Update
        update_handler = create_handler("PUT", {"confidence": 0.99})
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, update_handler)
        assert result.status_code == 200

        # Delete
        delete_handler = create_handler("DELETE")
        with patch.object(
            knowledge_handler, "require_auth_or_error", return_value=(mock_user, None)
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/facts/fact-1", {}, delete_handler)
        assert result.status_code == 200

    def test_query_and_verify_workflow(self, knowledge_handler, mock_fact_store):
        """Test querying knowledge base and verifying facts."""
        # Query
        query_handler = create_handler(
            "POST",
            {
                "question": "What facts do we have?",
            },
        )

        with patch(
            "aragora.server.handlers.knowledge_base.query._run_async",
            return_value=MockQueryResult(answer="Test answer"),
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, query_handler)
        assert result.status_code == 200

        # Get contradictions
        contradictions_handler = create_handler()
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/fact-1/contradictions", {}, contradictions_handler
        )
        assert result.status_code == 200

        # Get relations
        relations_handler = create_handler()
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/fact-1/relations", {}, relations_handler
        )
        assert result.status_code == 200

    def test_search_and_stats_workflow(self, knowledge_handler, mock_fact_store):
        """Test searching and getting statistics."""
        from aragora.server.handlers.knowledge_base.handler import _knowledge_limiter

        # Reset the rate limiter for clean test
        with _knowledge_limiter._lock:
            _knowledge_limiter._buckets.clear()

        # Search
        search_handler = create_handler()
        params = {"q": ["blue sky"]}

        with patch(
            "aragora.server.handlers.knowledge_base.search._run_async",
            return_value=[],
        ):
            result = knowledge_handler.handle("/api/v1/knowledge/search", params, search_handler)
        assert result.status_code == 200

        # Stats
        stats_handler = create_handler()
        result = knowledge_handler.handle("/api/v1/knowledge/stats", {}, stats_handler)
        assert result.status_code == 200
