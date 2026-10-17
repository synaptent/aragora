"""
Tests for FastAPI knowledge route endpoints.

Covers:
- GET  /api/v2/knowledge/search          - Search knowledge mound
- GET  /api/v2/knowledge/items/{item_id} - Get knowledge item by ID
- POST /api/v2/knowledge/items           - Ingest a new knowledge item
- GET  /api/v2/knowledge/stats           - Knowledge mound statistics
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi import create_app
from aragora.server.fastapi.dependencies.auth import require_authenticated


@pytest.fixture
def app():
    """Create a test FastAPI app whose caller is an org-1 user with knowledge access."""
    app = create_app()
    app.dependency_overrides[require_authenticated] = lambda: AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles={"admin"},
        permissions={"knowledge:read", "knowledge:write"},
    )
    return app


@pytest.fixture
def mock_km():
    """Create a mock Knowledge Mound."""
    km = MagicMock()
    km.search = MagicMock(return_value=[])
    km.get = MagicMock(return_value=None)
    km.ingest = MagicMock()
    km.get_stats = MagicMock(
        return_value={
            "total_items": 42,
            "items_by_type": {"text": 30, "url": 12},
            "items_by_source": {"api": 20, "debate": 22},
            "storage_backend": "sqlite",
        }
    )
    km.list_adapters = MagicMock(return_value=["debate", "consensus", "elo"])
    return km


@pytest.fixture
def client(app, mock_km):
    """Create a test client with mocked context."""
    app.state.context = {
        "storage": MagicMock(),
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
        "knowledge_mound": mock_km,
    }
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def sample_knowledge_item():
    """Sample knowledge item for testing."""
    return {
        "id": "ki_abc123def456",
        "title": "Rate Limiter Best Practices",
        "content": "Token bucket algorithms provide efficient rate limiting...",
        "content_type": "text",
        "source": "debate",
        "confidence": 0.85,
        "created_at": "2026-02-15T10:00:00",
        "updated_at": "2026-02-15T10:05:00",
        "tags": ["architecture", "performance"],
        "metadata": {"debate_id": "debate-001", "org_id": "org-1"},
        "debate_id": "debate-001",
        "adapter": "debate",
    }


# =============================================================================
# GET /api/v2/knowledge/search
# =============================================================================


class TestSearchKnowledge:
    """Tests for GET /api/v2/knowledge/search."""

    def test_search_returns_200_empty(self, client):
        """Search with no results returns 200 with empty list."""
        response = client.get("/api/v2/knowledge/search?query=test")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["query"] == "test"

    def test_search_requires_query(self, client):
        """Search without query param returns 422."""
        response = client.get("/api/v2/knowledge/search")
        assert response.status_code == 422

    def test_search_returns_results(self, client, mock_km, sample_knowledge_item):
        """Search returns matching items."""
        mock_km.search.return_value = [sample_knowledge_item]

        response = client.get("/api/v2/knowledge/search?query=rate+limiter")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "ki_abc123def456"
        assert data["items"][0]["title"] == "Rate Limiter Best Practices"
        assert data["total"] == 1

    def test_search_with_scored_results(self, client, mock_km, sample_knowledge_item):
        """Search handles (item, score) tuple results."""
        mock_km.search.return_value = [(sample_knowledge_item, 0.92)]

        response = client.get("/api/v2/knowledge/search?query=token+bucket")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["relevance_score"] == 0.92

    def test_search_with_limit(self, client, mock_km, sample_knowledge_item):
        """Search reads a fixed candidate window, then trims the org's items to limit."""
        mock_km.search.return_value = [sample_knowledge_item] * 3

        response = client.get("/api/v2/knowledge/search?query=test&limit=2")
        assert response.status_code == 200
        assert len(response.json()["items"]) == 2
        mock_km.search.assert_called_once_with("test", limit=100)

    def test_search_with_content_type_filter(self, client, mock_km):
        """Search passes content_type filter."""
        mock_km.search.return_value = []

        response = client.get("/api/v2/knowledge/search?query=test&content_type=url")
        assert response.status_code == 200
        mock_km.search.assert_called_once_with("test", limit=100, content_type="url")

    def test_search_with_source_filter(self, client, mock_km):
        """Search passes source filter."""
        mock_km.search.return_value = []

        response = client.get("/api/v2/knowledge/search?query=test&source=debate")
        assert response.status_code == 200
        mock_km.search.assert_called_once_with("test", limit=100, source="debate")

    def test_search_limit_validation(self, client):
        """Search limit must be between 1 and 100."""
        response = client.get("/api/v2/knowledge/search?query=test&limit=0")
        assert response.status_code == 422

        response = client.get("/api/v2/knowledge/search?query=test&limit=101")
        assert response.status_code == 422

    def test_search_unavailable_km(self, app):
        """Search returns 503 when KM is not available."""
        from aragora.server.fastapi.routes.knowledge import get_knowledge_mound as _dep

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        app.dependency_overrides[_dep] = lambda: None
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/knowledge/search?query=test")
        app.dependency_overrides.clear()
        assert response.status_code == 503


# =============================================================================
# GET /api/v2/knowledge/stats
# =============================================================================


class TestKnowledgeStats:
    """Tests for GET /api/v2/knowledge/stats."""

    def test_stats_returns_200(self, client):
        """Stats returns aggregate information."""
        response = client.get("/api/v2/knowledge/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 42
        assert data["items_by_type"]["text"] == 30
        assert data["storage_backend"] == "sqlite"
        assert "debate" in data["adapters"]

    def test_stats_when_km_unavailable(self, app):
        """Stats returns defaults when KM is not initialized."""
        from aragora.server.fastapi.routes.knowledge import get_knowledge_mound as _dep

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        app.dependency_overrides[_dep] = lambda: None
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/knowledge/stats")
        app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 0
        assert data["storage_backend"] == "not_initialized"


# =============================================================================
# GET /api/v2/knowledge/items/{item_id}
# =============================================================================


class TestGetKnowledgeItem:
    """Tests for GET /api/v2/knowledge/items/{item_id}."""

    def test_get_item_not_found(self, client):
        """Get nonexistent item returns 404."""
        response = client.get("/api/v2/knowledge/items/nonexistent-id")
        assert response.status_code == 404

    def test_get_item_found(self, client, mock_km, sample_knowledge_item):
        """Get existing item returns full details."""
        mock_km.get.return_value = sample_knowledge_item

        response = client.get("/api/v2/knowledge/items/ki_abc123def456")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "ki_abc123def456"
        assert data["title"] == "Rate Limiter Best Practices"
        assert data["content_type"] == "text"
        assert data["source"] == "debate"
        assert data["confidence"] == 0.85
        assert "architecture" in data["tags"]
        assert data["debate_id"] == "debate-001"

    def test_get_item_unavailable_km(self, app):
        """Get item returns 503 when KM is not available."""
        from aragora.server.fastapi.routes.knowledge import get_knowledge_mound as _dep

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        app.dependency_overrides[_dep] = lambda: None
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/knowledge/items/some-id")
        app.dependency_overrides.clear()
        assert response.status_code == 503


# =============================================================================
# POST /api/v2/knowledge/items
# =============================================================================


class TestIngestKnowledgeItem:
    """Tests for POST /api/v2/knowledge/items."""

    def _override_auth(self, client):
        """Override auth for write operations."""
        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"knowledge:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx
        return auth_ctx

    def test_ingest_item_returns_201(self, client, mock_km):
        """Ingest creates a new knowledge item."""
        self._override_auth(client)

        response = client.post(
            "/api/v2/knowledge/items",
            json={
                "title": "New Knowledge",
                "content": "Important information about security best practices.",
                "content_type": "text",
                "source": "api",
                "tags": ["security"],
            },
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["item_id"].startswith("ki_")
        assert data["item"]["title"] == "New Knowledge"
        assert data["item"]["content_type"] == "text"

    def test_ingest_calls_km_ingest(self, client, mock_km):
        """Ingest calls the knowledge mound ingest method."""
        self._override_auth(client)

        response = client.post(
            "/api/v2/knowledge/items",
            json={
                "title": "Test Item",
                "content": "Test content.",
            },
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 201
        mock_km.ingest.assert_called_once()

    def test_ingest_requires_title(self, client):
        """Ingest without title returns 422."""
        self._override_auth(client)

        response = client.post(
            "/api/v2/knowledge/items",
            json={
                "content": "Content without title.",
            },
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_ingest_requires_content(self, client):
        """Ingest without content returns 422."""
        self._override_auth(client)

        response = client.post(
            "/api/v2/knowledge/items",
            json={
                "title": "Title without content",
            },
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 422

    def test_ingest_requires_auth(self, client):
        """Ingest without auth returns 401."""
        client.app.dependency_overrides.clear()
        response = client.post(
            "/api/v2/knowledge/items",
            json={
                "title": "Unauthorized",
                "content": "Should fail",
            },
        )
        assert response.status_code == 401

    def test_ingest_unavailable_km(self, app):
        """Ingest returns 503 when KM is not available."""
        from aragora.server.fastapi.routes.knowledge import get_knowledge_mound as _dep

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        client = TestClient(app, raise_server_exceptions=False)

        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"knowledge:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx
        client.app.dependency_overrides[_dep] = lambda: None

        response = client.post(
            "/api/v2/knowledge/items",
            json={"title": "Test", "content": "Content"},
        )
        client.app.dependency_overrides.clear()

        assert response.status_code == 503


# =============================================================================
# GET /api/v2/knowledge/adapters
# =============================================================================


class TestListAdapters:
    """Tests for GET /api/v2/knowledge/adapters."""

    def test_list_returns_200(self, client, mock_km):
        """List returns adapters from KM."""
        response = client.get("/api/v2/knowledge/adapters")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["adapters"][0]["name"] == "debate"
        assert data["adapters"][1]["name"] == "consensus"
        assert data["adapters"][2]["name"] == "elo"

    def test_list_returns_empty_when_km_unavailable(self, app):
        """List returns empty when KM is not available."""
        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/knowledge/adapters")
        assert response.status_code == 200
        data = response.json()
        assert data["adapters"] == []
        assert data["total"] == 0

    def test_list_handles_dict_adapters(self, client, mock_km):
        """List handles dict adapter entries."""
        mock_km.list_adapters.return_value = [
            {"name": "debate", "description": "Debate adapter", "status": "active"},
            {"name": "elo", "description": "ELO adapter", "status": "active"},
        ]

        response = client.get("/api/v2/knowledge/adapters")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 2
        assert data["adapters"][0]["description"] == "Debate adapter"


# =============================================================================
# POST /api/v2/knowledge/query
# =============================================================================


class TestStructuredQuery:
    """Tests for POST /api/v2/knowledge/query."""

    def _override_auth(self, client):
        """Override auth for operations."""
        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"knowledge:read"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx

    def test_query_returns_200(self, client, mock_km):
        """Structured query returns results."""
        mock_km.query = MagicMock(return_value=[])

        response = client.post(
            "/api/v2/knowledge/query",
            json={"query": "security best practices"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "security best practices"
        assert data["items"] == []
        assert data["total"] == 0

    def test_query_with_filters(self, client, mock_km):
        """Structured query passes filters."""
        mock_km.query = MagicMock(return_value=[])

        response = client.post(
            "/api/v2/knowledge/query",
            json={
                "query": "test",
                "content_type": "text",
                "source": "debate",
                "adapter": "consensus",
                "tags": ["security"],
                "min_confidence": 0.5,
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["filters_applied"]["content_type"] == "text"
        assert data["filters_applied"]["source"] == "debate"
        assert data["filters_applied"]["adapter"] == "consensus"
        assert data["filters_applied"]["tags"] == ["security"]
        assert data["filters_applied"]["min_confidence"] == 0.5

    def test_query_requires_query_field(self, client):
        """Structured query without query string returns 422."""
        response = client.post(
            "/api/v2/knowledge/query",
            json={},
        )
        assert response.status_code == 422

    def test_query_with_results(self, client, mock_km, sample_knowledge_item):
        """Structured query returns matching items."""
        mock_km.query = MagicMock(return_value=[sample_knowledge_item])

        response = client.post(
            "/api/v2/knowledge/query",
            json={"query": "rate limiter"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["id"] == "ki_abc123def456"

    def test_query_unavailable_km(self, app):
        """Query returns 503 when KM is not available."""
        from aragora.server.fastapi.routes.knowledge import get_knowledge_mound as _dep

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        app.dependency_overrides[_dep] = lambda: None
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post(
            "/api/v2/knowledge/query",
            json={"query": "test"},
        )
        app.dependency_overrides.clear()
        assert response.status_code == 503


# =============================================================================
# GET /api/v2/knowledge/staleness
# =============================================================================


class TestStalenessAnalysis:
    """Tests for GET /api/v2/knowledge/staleness."""

    def test_staleness_returns_200(self, client, mock_km):
        """Staleness returns analysis based on KM stats."""
        response = client.get("/api/v2/knowledge/staleness")
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 42
        assert data["threshold_days"] == 30.0

    def test_staleness_with_custom_threshold(self, client, mock_km):
        """Staleness accepts custom threshold_days."""
        response = client.get("/api/v2/knowledge/staleness?threshold_days=7")
        assert response.status_code == 200
        data = response.json()
        assert data["threshold_days"] == 7.0

    def test_staleness_with_dedicated_method(self, client, mock_km):
        """Staleness uses dedicated get_staleness when available."""
        mock_km.get_staleness = MagicMock(
            return_value={
                "total_items": 100,
                "stale_items": 15,
                "stale_percent": 15.0,
                "items": [
                    {
                        "id": "ki_stale1",
                        "title": "Old item",
                        "stale": True,
                        "age_days": 45.0,
                        "metadata": {"org_id": "org-1"},
                    },
                ],
            }
        )

        response = client.get("/api/v2/knowledge/staleness")
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 100
        assert data["stale_items"] == 15
        assert data["stale_percent"] == 15.0
        assert len(data["items"]) == 1
        assert data["items"][0]["stale"] is True

    def test_staleness_when_km_unavailable(self, app):
        """Staleness returns defaults when KM unavailable."""
        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v2/knowledge/staleness")
        assert response.status_code == 200
        data = response.json()
        assert data["total_items"] == 0

    def test_staleness_threshold_validation(self, client):
        """Staleness threshold_days must be between 1 and 365."""
        response = client.get("/api/v2/knowledge/staleness?threshold_days=0.5")
        assert response.status_code == 422

        response = client.get("/api/v2/knowledge/staleness?threshold_days=400")
        assert response.status_code == 422


# =============================================================================
# DELETE /api/v2/knowledge/{item_id}
# =============================================================================


class TestDeleteKnowledgeItem:
    """Tests for DELETE /api/v2/knowledge/{item_id}."""

    def _override_auth(self, client):
        """Override auth for write operations."""
        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"knowledge:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx
        return auth_ctx

    def test_delete_returns_200(self, client, mock_km, sample_knowledge_item):
        """Delete existing item returns success."""
        self._override_auth(client)
        mock_km.get.return_value = sample_knowledge_item
        mock_km.delete = MagicMock(return_value=True)

        response = client.delete("/api/v2/knowledge/ki_abc123def456")
        client.app.dependency_overrides.clear()

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["item_id"] == "ki_abc123def456"

    def test_delete_not_found(self, client, mock_km):
        """Delete nonexistent item returns 404."""
        self._override_auth(client)
        mock_km.get.return_value = None

        response = client.delete("/api/v2/knowledge/nonexistent-id")
        client.app.dependency_overrides.clear()

        assert response.status_code == 404

    def test_delete_requires_auth(self, client):
        """Delete without auth returns 401."""
        client.app.dependency_overrides.clear()
        response = client.delete("/api/v2/knowledge/ki_abc123def456")
        assert response.status_code == 401

    def test_delete_unavailable_km(self, app):
        """Delete returns 503 when KM is not available."""
        from aragora.server.fastapi.routes.knowledge import get_knowledge_mound as _dep
        from aragora.server.fastapi.dependencies.auth import require_authenticated
        from aragora.rbac.models import AuthorizationContext

        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "knowledge_mound": None,
        }
        client = TestClient(app, raise_server_exceptions=False)

        auth_ctx = AuthorizationContext(
            user_id="user-1",
            org_id="org-1",
            workspace_id="ws-1",
            roles={"admin"},
            permissions={"knowledge:write"},
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx
        client.app.dependency_overrides[_dep] = lambda: None

        response = client.delete("/api/v2/knowledge/ki_abc123def456")
        client.app.dependency_overrides.clear()

        assert response.status_code == 503
