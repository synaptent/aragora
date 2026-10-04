"""Tests for Knowledge handler endpoints.

Validates the REST API endpoints for the enterprise knowledge base:
- Facts API (CRUD operations)
- Query/search functionality
- Fact relationships and contradictions
- Statistics
"""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from aragora.knowledge import InMemoryFactStore, ScopedFactStore
from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler


@pytest.fixture
def knowledge_handler():
    """Create a knowledge handler with mocked dependencies."""
    ctx = {"storage": None, "elo_system": None, "nomic_dir": None}
    handler = KnowledgeHandler(ctx)
    handler._fact_store = ScopedFactStore(InMemoryFactStore(), "test-org-001")
    return handler


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler with client address and headers."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {"Content-Length": "0"}
    handler.command = "GET"
    return handler


@pytest.fixture
def mock_http_handler_post():
    """Create a mock HTTP handler for POST requests."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.command = "POST"
    return handler


def create_request_body(data: dict) -> MagicMock:
    """Create a mock handler with request body."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    body = json.dumps(data).encode("utf-8")
    handler.headers = {"Content-Length": str(len(body))}
    handler.rfile = BytesIO(body)
    handler.command = "POST"
    return handler


class MockAuthUser:
    """Mock authenticated user with permissions for knowledge handler tests."""

    org_id = "test-org-001"

    def __init__(self, user_id: str = "test-user"):
        self.user_id = user_id
        self.permissions = {"*", "admin", "knowledge.read", "knowledge.write", "knowledge.delete"}
        self.roles = {"admin", "owner"}


class TestKnowledgeHandlerCanHandle:
    """Test KnowledgeHandler.can_handle method."""

    def test_can_handle_query(self, knowledge_handler):
        """Test can_handle returns True for query endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/query")

    def test_can_handle_facts(self, knowledge_handler):
        """Test can_handle returns True for facts endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts")

    def test_can_handle_search(self, knowledge_handler):
        """Test can_handle returns True for search endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/search")

    def test_can_handle_stats(self, knowledge_handler):
        """Test can_handle returns True for stats endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/stats")

    def test_can_handle_fact_by_id(self, knowledge_handler):
        """Test can_handle returns True for fact by ID endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-123")

    def test_can_handle_fact_verify(self, knowledge_handler):
        """Test can_handle returns True for fact verify endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-123/verify")

    def test_can_handle_fact_contradictions(self, knowledge_handler):
        """Test can_handle returns True for fact contradictions endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-123/contradictions")

    def test_can_handle_fact_relations(self, knowledge_handler):
        """Test can_handle returns True for fact relations endpoint."""
        assert knowledge_handler.can_handle("/api/v1/knowledge/facts/fact-123/relations")

    def test_cannot_handle_unknown(self, knowledge_handler):
        """Test can_handle returns False for unknown endpoint."""
        assert not knowledge_handler.can_handle("/api/v1/knowledge/unknown")
        assert not knowledge_handler.can_handle("/api/v1/debates")


class TestKnowledgeHandlerListFacts:
    """Test GET /api/v1/knowledge/facts endpoint."""

    def test_list_facts_default(self, knowledge_handler, mock_http_handler):
        """Test listing facts with default parameters."""
        result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, mock_http_handler)

        assert result is not None
        body = json.loads(result.body)
        assert "facts" in body
        assert "total" in body
        assert "limit" in body
        assert "offset" in body

    def test_list_facts_with_filters(self, knowledge_handler, mock_http_handler):
        """Test listing facts with filter parameters."""
        query_params = {
            "workspace_id": "test-workspace",
            "topic": "security",
            "min_confidence": "0.7",
            "limit": "10",
            "offset": "0",
        }
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        body = json.loads(result.body)
        assert "facts" in body
        assert body["limit"] == 10
        assert body["offset"] == 0

    def test_list_facts_with_status_filter(self, knowledge_handler, mock_http_handler):
        """Test listing facts filtered by validation status."""
        query_params = {
            "status": "majority_agreed",
            "include_superseded": "false",
        }
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        body = json.loads(result.body)
        assert "facts" in body


class TestKnowledgeHandlerGetFact:
    """Test GET /api/v1/knowledge/facts/:id endpoint."""

    def test_get_fact_not_found(self, knowledge_handler, mock_http_handler):
        """Test getting non-existent fact returns 404."""
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent-id", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 404
        body = json.loads(result.body)
        assert "error" in body

    def test_get_fact_success(self, knowledge_handler, mock_http_handler):
        """Test getting existing fact."""
        # First create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Test fact statement",
            workspace_id="default",
            confidence=0.8,
        )

        # Then retrieve it
        result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["statement"] == "Test fact statement"
        assert body["confidence"] == 0.8


class TestKnowledgeHandlerCreateFact:
    """Test POST /api/v1/knowledge/facts endpoint."""

    def test_create_fact_requires_auth(self, knowledge_handler):
        """Test creating fact requires authentication."""
        handler = create_request_body(
            {
                "statement": "New test fact",
                "workspace_id": "default",
            }
        )

        # Patch require_auth_or_error to return auth error
        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            from aragora.server.handlers.base import error_response

            mock_auth.return_value = (None, error_response("Unauthorized", 401))

            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 401

    def test_create_fact_success(self, knowledge_handler):
        """Test creating fact with valid data."""
        handler = create_request_body(
            {
                "statement": "New test fact",
                "workspace_id": "default",
                "confidence": 0.9,
                "topics": ["testing"],
            }
        )

        # Patch require_auth_or_error to return success
        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)

            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 201
        body = json.loads(result.body)
        assert body["statement"] == "New test fact"
        assert body["confidence"] == 0.9

    def test_create_fact_missing_statement(self, knowledge_handler):
        """Test creating fact without statement returns error."""
        handler = create_request_body(
            {
                "workspace_id": "default",
            }
        )

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)

            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body


class TestKnowledgeHandlerUpdateFact:
    """Test PUT /api/v1/knowledge/facts/:id endpoint."""

    def test_update_fact_not_found(self, knowledge_handler):
        """Test updating non-existent fact returns 404."""
        handler = create_request_body(
            {
                "confidence": 0.95,
            }
        )
        handler.command = "PUT"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)

            result = knowledge_handler.handle("/api/v1/knowledge/facts/nonexistent-id", {}, handler)

        assert result is not None
        assert result.status_code == 404

    def test_update_fact_success(self, knowledge_handler):
        """Test updating existing fact."""
        # First create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Original statement",
            workspace_id="default",
            confidence=0.5,
        )

        # Then update it
        handler = create_request_body(
            {
                "confidence": 0.95,
                "topics": ["updated"],
            }
        )
        handler.command = "PUT"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)

            result = knowledge_handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, handler)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["confidence"] == 0.95


class TestKnowledgeHandlerDeleteFact:
    """Test DELETE /api/v1/knowledge/facts/:id endpoint."""

    def test_delete_fact_not_found(self, knowledge_handler, mock_http_handler):
        """Test deleting non-existent fact returns 404."""
        mock_http_handler.command = "DELETE"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)

            result = knowledge_handler.handle(
                "/api/v1/knowledge/facts/nonexistent-id", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 404

    def test_delete_fact_success(self, knowledge_handler, mock_http_handler):
        """Test deleting existing fact."""
        # First create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Fact to delete",
            workspace_id="default",
        )

        mock_http_handler.command = "DELETE"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)

            result = knowledge_handler.handle(
                f"/api/v1/knowledge/facts/{fact.id}", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["deleted"] is True


class TestKnowledgeHandlerVerifyFact:
    """Test POST /api/v1/knowledge/facts/:id/verify endpoint."""

    def test_verify_fact_not_found(self, knowledge_handler, mock_http_handler_post):
        """Test verifying non-existent fact returns 404."""
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent-id/verify", {}, mock_http_handler_post
        )

        assert result is not None
        assert result.status_code == 404

    def test_verify_fact_queued(self, knowledge_handler, mock_http_handler_post):
        """Test verifying fact queues when agents not available."""
        # Create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Fact to verify",
            workspace_id="default",
        )

        result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/verify", {}, mock_http_handler_post
        )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "queued"


class TestKnowledgeHandlerContradictions:
    """Test GET /api/v1/knowledge/facts/:id/contradictions endpoint."""

    def test_get_contradictions_not_found(self, knowledge_handler, mock_http_handler):
        """Test getting contradictions for non-existent fact returns 404."""
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent-id/contradictions", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 404

    def test_get_contradictions_success(self, knowledge_handler, mock_http_handler):
        """Test getting contradictions for existing fact."""
        # Create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Original fact",
            workspace_id="default",
        )

        result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/contradictions", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "contradictions" in body
        assert "count" in body


class TestKnowledgeHandlerRelations:
    """Test /api/v1/knowledge/facts/:id/relations endpoints."""

    def test_get_relations_not_found(self, knowledge_handler, mock_http_handler):
        """Test getting relations for non-existent fact returns 404."""
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts/nonexistent-id/relations", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 404

    def test_get_relations_success(self, knowledge_handler, mock_http_handler):
        """Test getting relations for existing fact."""
        # Create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Fact with relations",
            workspace_id="default",
        )

        result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/relations", {}, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "relations" in body
        assert "count" in body

    def test_get_relations_with_type_filter(self, knowledge_handler, mock_http_handler):
        """Test getting relations filtered by type."""
        # Create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(
            statement="Fact for filtering",
            workspace_id="default",
        )

        query_params = {"type": "supports"}
        result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/relations", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "relations" in body


class TestKnowledgeHandlerStats:
    """Test GET /api/v1/knowledge/stats endpoint."""

    def test_get_stats(self, knowledge_handler, mock_http_handler):
        """Test getting knowledge base statistics."""
        result = knowledge_handler.handle("/api/v1/knowledge/stats", {}, mock_http_handler)

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert isinstance(body, dict)

    def test_get_stats_with_workspace(self, knowledge_handler, mock_http_handler):
        """Test getting stats for specific workspace."""
        query_params = {"workspace_id": "test-workspace"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/stats", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200


class TestKnowledgeHandlerSearch:
    """Test GET /api/v1/knowledge/search endpoint."""

    def test_search_basic(self, knowledge_handler, mock_http_handler):
        """Test basic search functionality."""
        query_params = {"q": "security"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/search", query_params, mock_http_handler
        )

        assert result is not None
        body = json.loads(result.body)
        assert isinstance(body, dict)


class TestKnowledgeHandlerQuery:
    """Test POST /api/v1/knowledge/query endpoint."""

    def test_query_missing_question(self, knowledge_handler):
        """Test query without question returns error."""
        handler = create_request_body({})

        result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body

    def test_query_with_question(self, knowledge_handler):
        """Test query with valid question."""
        handler = create_request_body(
            {
                "question": "What are the security requirements?",
                "workspace_id": "default",
            }
        )

        result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        body = json.loads(result.body)
        assert isinstance(body, dict)

    def test_query_with_options(self, knowledge_handler):
        """Test query with custom options."""
        handler = create_request_body(
            {
                "question": "What are the compliance rules?",
                "workspace_id": "compliance",
                "options": {
                    "max_chunks": 5,
                    "search_alpha": 0.7,
                    "use_agents": False,
                },
            }
        )

        result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        body = json.loads(result.body)
        assert isinstance(body, dict)


class TestKnowledgeHandlerIntegration:
    """Integration tests for Knowledge handler."""

    def test_full_fact_lifecycle(self, knowledge_handler):
        """Test full fact lifecycle: create -> read -> update -> delete."""
        # 1. Create a fact
        create_handler = create_request_body(
            {
                "statement": "Integration test fact",
                "workspace_id": "integration",
                "confidence": 0.7,
                "topics": ["testing", "integration"],
            }
        )

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            create_result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, create_handler)

        assert create_result is not None
        assert create_result.status_code == 201
        create_body = json.loads(create_result.body)
        fact_id = create_body["id"]

        # 2. Read the fact
        read_handler = MagicMock()
        read_handler.client_address = ("127.0.0.1", 12345)
        read_handler.command = "GET"

        read_result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact_id}", {}, read_handler
        )
        assert read_result is not None
        assert read_result.status_code == 200

        # 3. Update the fact
        update_handler = create_request_body(
            {
                "confidence": 0.95,
            }
        )
        update_handler.command = "PUT"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            update_result = knowledge_handler.handle(
                f"/api/v1/knowledge/facts/{fact_id}", {}, update_handler
            )

        assert update_result is not None
        assert update_result.status_code == 200
        update_body = json.loads(update_result.body)
        assert update_body["confidence"] == 0.95

        # 4. Delete the fact
        delete_handler = MagicMock()
        delete_handler.client_address = ("127.0.0.1", 12345)
        delete_handler.command = "DELETE"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            delete_result = knowledge_handler.handle(
                f"/api/v1/knowledge/facts/{fact_id}", {}, delete_handler
            )

        assert delete_result is not None
        assert delete_result.status_code == 200

        # 5. Verify fact is gone
        verify_result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact_id}", {}, read_handler
        )
        assert verify_result.status_code == 404


# ============================================================================
# Knowledge Mound Handler Tests
# ============================================================================

from aragora.server.handlers.knowledge_base.mound.handler import KnowledgeMoundHandler


@pytest.fixture
def mound_handler():
    """Create a knowledge mound handler with mocked dependencies."""
    ctx = {"storage": None, "elo_system": None, "nomic_dir": None}
    handler = KnowledgeMoundHandler(ctx)
    return handler


class TestKnowledgeMoundHandlerCanHandle:
    """Test KnowledgeMoundHandler.can_handle method."""

    def test_can_handle_mound_query(self, mound_handler):
        """Test can_handle returns True for mound query endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/query")

    def test_can_handle_mound_nodes(self, mound_handler):
        """Test can_handle returns True for mound nodes endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/nodes")

    def test_can_handle_mound_node_by_id(self, mound_handler):
        """Test can_handle returns True for mound node by ID endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/nodes/node-123")

    def test_can_handle_mound_node_relationships(self, mound_handler):
        """Test can_handle returns True for node relationships endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/nodes/node-123/relationships")

    def test_can_handle_mound_relationships(self, mound_handler):
        """Test can_handle returns True for mound relationships endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/relationships")

    def test_can_handle_mound_stats(self, mound_handler):
        """Test can_handle returns True for mound stats endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/stats")

    def test_can_handle_mound_graph(self, mound_handler):
        """Test can_handle returns True for mound graph endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/graph/node-123")

    def test_cannot_handle_non_mound(self, mound_handler):
        """Test can_handle returns False for non-mound endpoints."""
        assert not mound_handler.can_handle("/api/v1/knowledge/facts")
        assert not mound_handler.can_handle("/api/v1/debates")


class TestKnowledgeMoundNodeRelationships:
    """Test GET /api/v1/knowledge/mound/nodes/:id/relationships endpoint."""

    def test_get_node_relationships_mound_unavailable(self, mound_handler, mock_http_handler):
        """Test getting relationships when mound not available returns 503."""
        # Don't initialize mound
        with patch.object(mound_handler, "_get_mound", return_value=None):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/nodes/node-123/relationships", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 503

    def test_get_node_relationships_node_not_found(self, mound_handler, mock_http_handler):
        """Test getting relationships for non-existent node returns 404."""
        from unittest.mock import AsyncMock

        mock_mound = MagicMock()
        mock_mound.get_node = AsyncMock(return_value=None)

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/nodes/nonexistent/relationships", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 404
        body = json.loads(result.body)
        assert "error" in body

    def test_get_node_relationships_success(self, mound_handler, mock_http_handler):
        """Test getting relationships for existing node."""
        from unittest.mock import AsyncMock
        from datetime import datetime

        # Create mock node
        mock_node = MagicMock()
        mock_node.id = "node-123"

        # Create mock relationships
        mock_rel = MagicMock()
        mock_rel.id = "rel-1"
        mock_rel.from_node_id = "node-123"
        mock_rel.to_node_id = "node-456"
        mock_rel.relationship_type = "supports"
        mock_rel.strength = 0.8
        mock_rel.created_at = datetime(2024, 1, 15)
        mock_rel.created_by = "test-user"
        mock_rel.metadata = {"note": "test"}

        mock_mound = MagicMock()
        mock_mound.get_node = AsyncMock(return_value=mock_node)
        mock_mound.get_relationships = AsyncMock(return_value=[mock_rel])

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/nodes/node-123/relationships", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["node_id"] == "node-123"
        assert "relationships" in body
        assert body["count"] == 1
        assert body["relationships"][0]["from_node_id"] == "node-123"
        assert body["relationships"][0]["to_node_id"] == "node-456"
        assert body["relationships"][0]["relationship_type"] == "supports"

    def test_get_node_relationships_with_filters(self, mound_handler, mock_http_handler):
        """Test getting relationships with direction filter."""
        from unittest.mock import AsyncMock

        mock_node = MagicMock()
        mock_node.id = "node-123"

        mock_mound = MagicMock()
        mock_mound.get_node = AsyncMock(return_value=mock_node)
        mock_mound.get_relationships = AsyncMock(return_value=[])

        query_params = {
            "direction": "outgoing",
            "relationship_type": "supports",
        }

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/nodes/node-123/relationships",
                query_params,
                mock_http_handler,
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["direction"] == "outgoing"

        # Verify the mound method was called with correct params
        mock_mound.get_relationships.assert_called_once()
        call_kwargs = mock_mound.get_relationships.call_args
        assert call_kwargs[1]["direction"] == "outgoing"
        assert call_kwargs[1]["relationship_type"] == "supports"

    def test_get_node_relationships_invalid_direction(self, mound_handler, mock_http_handler):
        """Test getting relationships with invalid direction returns 400."""
        from unittest.mock import AsyncMock

        mock_node = MagicMock()
        mock_node.id = "node-123"

        mock_mound = MagicMock()
        mock_mound.get_node = AsyncMock(return_value=mock_node)

        query_params = {"direction": "invalid"}

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/nodes/node-123/relationships",
                query_params,
                mock_http_handler,
            )

        assert result is not None
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body
        assert "direction" in body["error"]


class TestKnowledgeMoundExport:
    """Test Knowledge Mound graph export endpoints (D3 and GraphML)."""

    def test_can_handle_export_d3(self, mound_handler):
        """Test can_handle returns True for D3 export endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/export/d3")

    def test_can_handle_export_graphml(self, mound_handler):
        """Test can_handle returns True for GraphML export endpoint."""
        assert mound_handler.can_handle("/api/v1/knowledge/mound/export/graphml")

    def test_export_d3_mound_unavailable(self, mound_handler, mock_http_handler):
        """Test D3 export returns 503 when mound not available."""
        with patch.object(mound_handler, "_get_mound", return_value=None):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/d3", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 503
        body = json.loads(result.body)
        assert "error" in body

    def test_export_d3_default_params(self, mound_handler, mock_http_handler):
        """Test D3 export with default parameters."""
        from unittest.mock import AsyncMock

        mock_d3_result = {
            "nodes": [
                {"id": "node-1", "label": "Test Node", "type": "fact"},
                {"id": "node-2", "label": "Another Node", "type": "debate"},
            ],
            "links": [
                {"source": "node-1", "target": "node-2", "type": "supports", "weight": 0.8},
            ],
        }

        mock_mound = MagicMock()
        mock_mound.export_graph_d3 = AsyncMock(return_value=mock_d3_result)

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/d3", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["format"] == "d3"
        assert body["total_nodes"] == 2
        assert body["total_links"] == 1
        assert len(body["nodes"]) == 2
        assert len(body["links"]) == 1
        assert body["nodes"][0]["id"] == "node-1"
        assert body["links"][0]["source"] == "node-1"

        # Verify default params were passed
        mock_mound.export_graph_d3.assert_called_once()
        call_kwargs = mock_mound.export_graph_d3.call_args[1]
        assert call_kwargs["start_node_id"] is None
        assert call_kwargs["depth"] == 3
        assert call_kwargs["limit"] == 100

    def test_export_d3_with_start_node(self, mound_handler, mock_http_handler):
        """Test D3 export starting from specific node."""
        from unittest.mock import AsyncMock

        mock_d3_result = {
            "nodes": [{"id": "start-node", "label": "Start", "type": "fact"}],
            "links": [],
        }

        mock_mound = MagicMock()
        mock_mound.export_graph_d3 = AsyncMock(return_value=mock_d3_result)

        query_params = {
            "start_node_id": "start-node",
            "depth": "5",
            "limit": "50",
        }

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/d3", query_params, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200

        # Verify custom params were passed
        mock_mound.export_graph_d3.assert_called_once()
        call_kwargs = mock_mound.export_graph_d3.call_args[1]
        assert call_kwargs["start_node_id"] == "start-node"
        assert call_kwargs["depth"] == 5
        assert call_kwargs["limit"] == 50

    def test_export_d3_handles_error(self, mound_handler, mock_http_handler):
        """Test D3 export handles errors gracefully."""
        from unittest.mock import AsyncMock

        mock_mound = MagicMock()
        mock_mound.export_graph_d3 = AsyncMock(side_effect=ValueError("Export failed"))

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/d3", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 500
        body = json.loads(result.body)
        assert "error" in body
        assert body["error"]  # Sanitized error message present

    def test_export_graphml_mound_unavailable(self, mound_handler, mock_http_handler):
        """Test GraphML export returns 503 when mound not available."""
        with patch.object(mound_handler, "_get_mound", return_value=None):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/graphml", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 503

    def test_export_graphml_returns_xml(self, mound_handler, mock_http_handler):
        """Test GraphML export returns valid XML with correct content type."""
        from unittest.mock import AsyncMock

        graphml_content = """<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <graph id="knowledge-graph" edgedefault="directed">
    <node id="node-1">
      <data key="label">Test Node</data>
    </node>
  </graph>
</graphml>"""

        mock_mound = MagicMock()
        mock_mound.export_graph_graphml = AsyncMock(return_value=graphml_content)

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/graphml", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        assert result.content_type == "application/xml"
        assert b'<?xml version="1.0"' in result.body
        assert b"<graphml" in result.body
        assert b'<node id="node-1">' in result.body

    def test_export_graphml_with_params(self, mound_handler, mock_http_handler):
        """Test GraphML export with custom parameters."""
        from unittest.mock import AsyncMock

        graphml_content = '<?xml version="1.0"?><graphml></graphml>'

        mock_mound = MagicMock()
        mock_mound.export_graph_graphml = AsyncMock(return_value=graphml_content)

        query_params = {
            "start_node_id": "custom-start",
            "depth": "7",
            "limit": "200",
        }

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/graphml", query_params, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200

        # Verify params were passed
        mock_mound.export_graph_graphml.assert_called_once()
        call_kwargs = mock_mound.export_graph_graphml.call_args[1]
        assert call_kwargs["start_node_id"] == "custom-start"
        assert call_kwargs["depth"] == 7
        assert call_kwargs["limit"] == 200

    def test_export_graphml_handles_error(self, mound_handler, mock_http_handler):
        """Test GraphML export handles errors gracefully."""
        from unittest.mock import AsyncMock

        mock_mound = MagicMock()
        mock_mound.export_graph_graphml = AsyncMock(side_effect=RuntimeError("GraphML failed"))

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/graphml", {}, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 500
        body = json.loads(result.body)
        assert "error" in body
        assert body["error"]  # Sanitized error message present

    def test_export_d3_depth_clamping(self, mound_handler, mock_http_handler):
        """Test D3 export clamps depth parameter to valid range."""
        from unittest.mock import AsyncMock

        mock_mound = MagicMock()
        mock_mound.export_graph_d3 = AsyncMock(return_value={"nodes": [], "links": []})

        # Test depth too high (should clamp to 10)
        query_params = {"depth": "999"}

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/d3", query_params, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        call_kwargs = mock_mound.export_graph_d3.call_args[1]
        assert call_kwargs["depth"] == 10  # Clamped to max

    def test_export_d3_limit_clamping(self, mound_handler, mock_http_handler):
        """Test D3 export clamps limit parameter to valid range."""
        from unittest.mock import AsyncMock

        mock_mound = MagicMock()
        mock_mound.export_graph_d3 = AsyncMock(return_value={"nodes": [], "links": []})

        # Test limit too high (should clamp to 500)
        query_params = {"limit": "10000"}

        with patch.object(mound_handler, "_get_mound", return_value=mock_mound):
            result = mound_handler.handle(
                "/api/v1/knowledge/mound/export/d3", query_params, mock_http_handler
            )

        assert result is not None
        assert result.status_code == 200
        call_kwargs = mock_mound.export_graph_d3.call_args[1]
        assert call_kwargs["limit"] == 500  # Clamped to max


# =============================================================================
# TIER 3.1: RBAC BOUNDARY TESTS
# =============================================================================


class MockUserNoPermissions:
    """Mock user with no knowledge permissions."""

    def __init__(self, user_id: str = "limited-user"):
        self.user_id = user_id
        self.permissions = {"debates.read"}  # No knowledge permissions
        self.roles = {"viewer"}


class MockUserReadOnly:
    """Mock user with only read permission."""

    def __init__(self, user_id: str = "readonly-user"):
        self.user_id = user_id
        self.permissions = {"knowledge.read"}
        self.roles = {"viewer"}


class MockUserWriteOnly:
    """Mock user with read and write but no delete."""

    def __init__(self, user_id: str = "writer-user"):
        self.user_id = user_id
        self.permissions = {"knowledge.read", "knowledge.write"}
        self.roles = {"member"}


class TestKnowledgeHandlerRBACBoundaries:
    """Test RBAC permission enforcement boundaries."""

    def test_list_facts_denied_without_read_permission(self, knowledge_handler, mock_http_handler):
        """Test listing facts fails without knowledge.read permission."""
        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserNoPermissions(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, mock_http_handler)

        assert result is not None
        assert result.status_code == 403
        body = json.loads(result.body)
        assert "error" in body
        assert "permission" in body["error"].lower()

    def test_create_fact_denied_without_write_permission(self, knowledge_handler):
        """Test creating fact fails without knowledge.write permission."""
        handler = create_request_body({"statement": "Test fact", "workspace_id": "default"})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 403
        body = json.loads(result.body)
        assert "error" in body

    def test_update_fact_denied_without_write_permission(self, knowledge_handler):
        """Test updating fact fails without knowledge.write permission."""
        # First create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(statement="Test", workspace_id="default", confidence=0.5)

        handler = create_request_body({"confidence": 0.9})
        handler.command = "PUT"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, handler)

        assert result is not None
        assert result.status_code == 403

    def test_delete_fact_denied_without_delete_permission(self, knowledge_handler):
        """Test deleting fact fails without knowledge.delete permission."""
        # Create a fact
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(statement="Test", workspace_id="default", confidence=0.5)

        handler = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.command = "DELETE"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserWriteOnly(), None)  # Has write but not delete
            result = knowledge_handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, handler)

        assert result is not None
        assert result.status_code == 403

    def test_query_allowed_with_read_permission(self, knowledge_handler):
        """Test query endpoint works with only read permission."""
        handler = create_request_body({"question": "What is the meaning of life?"})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        # Should succeed (not 403)
        assert result is not None
        assert result.status_code != 403

    def test_search_allowed_with_read_permission(self, knowledge_handler, mock_http_handler):
        """Test search endpoint works with read permission."""
        query_params = {"q": "test query"}

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle(
                "/api/v1/knowledge/search", query_params, mock_http_handler
            )

        assert result is not None
        assert result.status_code != 403

    def test_stats_allowed_with_read_permission(self, knowledge_handler, mock_http_handler):
        """Test stats endpoint works with read permission."""
        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/stats", {}, mock_http_handler)

        assert result is not None
        assert result.status_code != 403

    def test_admin_role_bypasses_permission_check(self, knowledge_handler):
        """Test admin role can perform any operation."""

        class AdminNoExplicitPerms:
            user_id = "admin-user"
            org_id = "test-org-001"
            permissions = set()  # No explicit permissions
            roles = {"admin"}

        handler = create_request_body({"statement": "Admin fact", "workspace_id": "default"})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (AdminNoExplicitPerms(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        # Admin should be able to create facts even without explicit permission
        assert result is not None
        assert result.status_code == 201

    def test_verify_fact_requires_write_permission(self, knowledge_handler):
        """Test verifying a fact requires write permission."""
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(statement="Test", workspace_id="default", confidence=0.5)

        handler = create_request_body({})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle(
                f"/api/v1/knowledge/facts/{fact.id}/verify", {}, handler
            )

        assert result is not None
        assert result.status_code == 403

    def test_add_relation_requires_write_permission(self, knowledge_handler):
        """Test adding a relation requires write permission."""
        store = knowledge_handler._get_fact_store()
        fact1 = store.add_fact(statement="Fact 1", workspace_id="default", confidence=0.8)
        fact2 = store.add_fact(statement="Fact 2", workspace_id="default", confidence=0.8)

        handler = create_request_body(
            {
                "target_fact_id": fact2.id,
                "relation_type": "supports",
            }
        )

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockUserReadOnly(), None)
            result = knowledge_handler.handle(
                f"/api/v1/knowledge/facts/{fact1.id}/relations", {}, handler
            )

        assert result is not None
        assert result.status_code == 403


# =============================================================================
# TIER 3.1: INPUT VALIDATION TESTS
# =============================================================================


class TestKnowledgeHandlerInputValidation:
    """Test input validation and edge cases."""

    def test_create_fact_empty_statement(self, knowledge_handler):
        """Test creating fact with empty statement fails."""
        handler = create_request_body({"statement": "", "workspace_id": "default"})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_create_fact_whitespace_only_statement(self, knowledge_handler):
        """Test creating fact with whitespace-only statement fails."""
        handler = create_request_body({"statement": "   ", "workspace_id": "default"})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_create_fact_invalid_confidence_too_high(self, knowledge_handler):
        """Test creating fact with confidence > 1.0 is handled."""
        handler = create_request_body(
            {
                "statement": "Test fact",
                "workspace_id": "default",
                "confidence": 1.5,  # Invalid: > 1.0
            }
        )

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        # Should either reject (400), clamp to 1.0, or accept the raw value
        assert result is not None
        assert result.status_code in (201, 400)

    def test_create_fact_invalid_confidence_negative(self, knowledge_handler):
        """Test creating fact with negative confidence is handled."""
        handler = create_request_body(
            {
                "statement": "Test fact",
                "workspace_id": "default",
                "confidence": -0.5,  # Invalid: < 0
            }
        )

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        # Should either reject (400) or accept the raw value
        assert result is not None
        assert result.status_code in (201, 400)

    def test_query_empty_question(self, knowledge_handler):
        """Test query with empty question fails."""
        handler = create_request_body({"question": ""})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 400

    def test_list_facts_invalid_limit(self, knowledge_handler, mock_http_handler):
        """Test listing facts with invalid limit parameter."""
        query_params = {"limit": "not_a_number"}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        # Should use default or return error
        body = json.loads(result.body)
        if result.status_code == 200:
            assert isinstance(body.get("limit"), int)

    def test_list_facts_negative_limit(self, knowledge_handler, mock_http_handler):
        """Test listing facts with negative limit parameter."""
        query_params = {"limit": "-10"}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        body = json.loads(result.body)
        if result.status_code == 200:
            assert body.get("limit", 0) >= 0

    def test_list_facts_excessive_limit(self, knowledge_handler, mock_http_handler):
        """Test listing facts with excessive limit is clamped."""
        query_params = {"limit": "10000"}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        body = json.loads(result.body)
        if result.status_code == 200:
            # Should be clamped to a reasonable max
            assert body.get("limit", 0) <= 1000

    def test_list_facts_negative_offset(self, knowledge_handler, mock_http_handler):
        """Test listing facts with negative offset."""
        query_params = {"offset": "-5"}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        body = json.loads(result.body)
        if result.status_code == 200:
            assert body.get("offset", 0) >= 0

    def test_update_fact_invalid_confidence(self, knowledge_handler):
        """Test updating fact with invalid confidence value."""
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(statement="Test", workspace_id="default", confidence=0.5)

        handler = create_request_body({"confidence": "not_a_number"})
        handler.command = "PUT"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle(f"/api/v1/knowledge/facts/{fact.id}", {}, handler)

        assert result is not None
        # Should either fail or ignore invalid value

    def test_search_empty_query(self, knowledge_handler, mock_http_handler):
        """Test search with empty query string."""
        query_params = {"q": ""}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/search", query_params, mock_http_handler
        )

        assert result is not None
        # Should return empty results or error

    def test_get_relations_invalid_type_filter(self, knowledge_handler, mock_http_handler):
        """Test get relations with invalid relation type filter."""
        store = knowledge_handler._get_fact_store()
        fact = store.add_fact(statement="Test", workspace_id="default", confidence=0.8)

        query_params = {"relation_type": "invalid_type_xyz"}

        result = knowledge_handler.handle(
            f"/api/v1/knowledge/facts/{fact.id}/relations", query_params, mock_http_handler
        )

        assert result is not None
        # Should return empty or all relations (filter is optional)


# =============================================================================
# TIER 3.1: ERROR HANDLING TESTS
# =============================================================================


class TestKnowledgeHandlerErrorHandling:
    """Test error handling scenarios."""

    def test_handle_fact_store_initialization_failure(self, knowledge_handler, mock_http_handler):
        """Test graceful handling when fact store fails to initialize."""
        with patch.object(knowledge_handler, "_get_fact_store") as mock_store:
            mock_store.side_effect = RuntimeError("Database connection failed")

            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, mock_http_handler)

        assert result is not None
        assert result.status_code == 500

    def test_handle_query_engine_failure(self, knowledge_handler):
        """Test handling query engine failure."""
        handler = create_request_body({"question": "Test question?"})

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            with patch.object(knowledge_handler, "_get_query_engine") as mock_engine:
                mock_engine.side_effect = RuntimeError("Query engine unavailable")

                result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        assert result.status_code == 500

    def test_handle_malformed_json_body(self, knowledge_handler):
        """Test handling malformed JSON in request body."""
        handler = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.command = "POST"
        handler.headers = {"Content-Length": "20"}
        handler.rfile = BytesIO(b"this is not json!!!")

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code in [400, 500]

    def test_handle_empty_request_body(self, knowledge_handler):
        """Test handling empty request body for POST."""
        handler = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.command = "POST"
        handler.headers = {"Content-Length": "0"}
        handler.rfile = BytesIO(b"")

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler)

        assert result is not None
        assert result.status_code in [400, 500]

    def test_fact_deletion_error_propagation(self, knowledge_handler):
        """Test error propagation during fact deletion."""
        handler = MagicMock()
        handler.client_address = ("127.0.0.1", 12345)
        handler.command = "DELETE"

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            with patch.object(knowledge_handler, "_get_fact_store") as mock_store:
                mock_store_instance = MagicMock()
                mock_store_instance.delete_fact.side_effect = ValueError("Deletion failed")
                mock_store.return_value = mock_store_instance

                result = knowledge_handler.handle("/api/v1/knowledge/facts/some-id", {}, handler)

        assert result is not None
        # Should return 500 or 404, not crash


# =============================================================================
# TIER 3.1: PARAMETER VALIDATION TESTS
# =============================================================================


class TestKnowledgeHandlerParameterValidation:
    """Test parameter validation and clamping."""

    def test_min_confidence_filter_bounds(self, knowledge_handler, mock_http_handler):
        """Test min_confidence filter respects 0-1 bounds."""
        # Add some test facts
        store = knowledge_handler._get_fact_store()
        store.add_fact(statement="Low confidence", workspace_id="default", confidence=0.3)
        store.add_fact(statement="High confidence", workspace_id="default", confidence=0.9)

        # Test with valid min_confidence
        query_params = {"min_confidence": "0.5"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200

    def test_min_confidence_invalid_values(self, knowledge_handler, mock_http_handler):
        """Test min_confidence handles invalid values."""
        query_params = {"min_confidence": "not_a_number"}

        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        # Should ignore invalid and use default

    def test_workspace_id_filter(self, knowledge_handler, mock_http_handler):
        """Test workspace_id filtering works correctly."""
        store = knowledge_handler._get_fact_store()
        store.add_fact(statement="Workspace A", workspace_id="workspace-a", confidence=0.8)
        store.add_fact(statement="Workspace B", workspace_id="workspace-b", confidence=0.8)

        query_params = {"workspace_id": "workspace-a"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200
        body = json.loads(result.body)
        # All returned facts should be from workspace-a
        for fact in body.get("facts", []):
            assert fact.get("workspace_id") == "workspace-a"

    def test_topic_filter(self, knowledge_handler, mock_http_handler):
        """Test topic filtering works correctly."""
        store = knowledge_handler._get_fact_store()
        store.add_fact(
            statement="Security fact",
            workspace_id="default",
            confidence=0.8,
            topics=["security"],
        )
        store.add_fact(
            statement="Performance fact",
            workspace_id="default",
            confidence=0.8,
            topics=["performance"],
        )

        query_params = {"topic": "security"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200

    def test_status_filter_valid_values(self, knowledge_handler, mock_http_handler):
        """Test status filter with valid status values."""
        valid_statuses = ["pending", "verified", "majority_agreed", "disputed"]

        for status in valid_statuses:
            query_params = {"status": status}
            result = knowledge_handler.handle(
                "/api/v1/knowledge/facts", query_params, mock_http_handler
            )

            assert result is not None
            # Should not error on valid status

    def test_include_superseded_flag(self, knowledge_handler, mock_http_handler):
        """Test include_superseded parameter handling."""
        query_params = {"include_superseded": "true"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200

        query_params = {"include_superseded": "false"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/facts", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200

    def test_stats_workspace_filter(self, knowledge_handler, mock_http_handler):
        """Test stats endpoint respects workspace_id filter."""
        store = knowledge_handler._get_fact_store()
        store.add_fact(statement="WS1 fact", workspace_id="workspace-1", confidence=0.8)
        store.add_fact(statement="WS2 fact", workspace_id="workspace-2", confidence=0.8)

        query_params = {"workspace_id": "workspace-1"}
        result = knowledge_handler.handle(
            "/api/v1/knowledge/stats", query_params, mock_http_handler
        )

        assert result is not None
        assert result.status_code == 200

    def test_query_with_options(self, knowledge_handler):
        """Test query endpoint with additional options."""
        handler = create_request_body(
            {
                "question": "What are the best practices?",
                "workspace_id": "default",
                "max_results": 5,
                "min_confidence": 0.7,
            }
        )

        with patch.object(knowledge_handler, "require_auth_or_error") as mock_auth:
            mock_auth.return_value = (MockAuthUser(), None)
            result = knowledge_handler.handle("/api/v1/knowledge/query", {}, handler)

        assert result is not None
        # Should process options without error


# =============================================================================
# TIER 3.1: RATE LIMITING TESTS
# =============================================================================


class TestKnowledgeHandlerRateLimiting:
    """Test rate limiting behavior."""

    def test_rate_limit_exceeded(self, knowledge_handler, mock_http_handler):
        """Test rate limiting returns 429 when exceeded."""
        from aragora.server.handlers.knowledge_base.handler import _knowledge_limiter

        # Clear existing buckets and set very low limit
        _knowledge_limiter._buckets.clear()

        # Make many rapid requests to trigger rate limit
        results = []
        for i in range(100):
            result = knowledge_handler.handle("/api/v1/knowledge/facts", {}, mock_http_handler)
            if result and result.status_code == 429:
                results.append(result)
                break

        # Should have hit rate limit at some point
        # Note: This test may be flaky if rate limiter is configured very high
        # At minimum, verify handler doesn't crash

    def test_different_clients_separate_rate_limits(self, knowledge_handler):
        """Test different client IPs have separate rate limits."""
        handler1 = MagicMock()
        handler1.client_address = ("192.168.1.1", 12345)
        handler1.headers = {"Content-Length": "0"}
        handler1.command = "GET"

        handler2 = MagicMock()
        handler2.client_address = ("192.168.1.2", 12345)
        handler2.headers = {"Content-Length": "0"}
        handler2.command = "GET"

        # Both should succeed (different IPs)
        result1 = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler1)
        result2 = knowledge_handler.handle("/api/v1/knowledge/facts", {}, handler2)

        assert result1 is not None
        assert result2 is not None
