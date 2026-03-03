"""Tests for FastAPI v2 marketplace routes."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app


def _make_template(template_id: str, stars: int = 0) -> SimpleNamespace:
    """Create a template-like object used by mocked registry methods."""
    payload = {
        "id": template_id,
        "name": f"Template {template_id}",
        "description": "Test template",
        "category": "ops",
        "template_type": "workflow",
        "tags": ["ops"],
        "downloads": 0,
        "stars": stars,
        "average_rating": 4.5,
    }
    return SimpleNamespace(
        to_dict=lambda: payload,
        metadata=SimpleNamespace(stars=stars),
    )


@pytest.fixture
def app():
    """Create a test FastAPI app."""
    return create_app()


@pytest.fixture
def mock_registry():
    """Create a mocked marketplace registry."""
    registry = MagicMock()
    registry.search.return_value = [_make_template("tpl_1")]
    registry.list_categories.return_value = ["ops", "security"]
    registry.get_ratings.return_value = [
        SimpleNamespace(
            user_id="user-1",
            score=5,
            review="Great",
            created_at=datetime(2026, 3, 1, 12, 0, 0),
        )
    ]
    registry.get_average_rating.return_value = 4.5
    registry.export_template.return_value = '{"id":"tpl_1"}'
    registry.get.return_value = _make_template("tpl_1", stars=3)
    registry.import_template.return_value = "tpl_created"
    registry.delete.return_value = True
    return registry


@pytest.fixture
def client(app, mock_registry):
    """Create a test client with mocked app context."""
    app.state.context = {
        "storage": MagicMock(),
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
        "marketplace_registry": mock_registry,
    }
    return TestClient(app, raise_server_exceptions=False)


def _override_auth(client: TestClient, permissions: set[str]):
    """Override auth dependency with the provided permission set."""
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.fastapi.dependencies.auth import require_authenticated

    auth_ctx = AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles={"admin"},
        permissions=permissions,
    )
    client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx


class TestMarketplaceRoutes:
    """FastAPI v2 marketplace route coverage."""

    def test_list_templates_happy_path(self, client, mock_registry):
        response = client.get("/api/v2/marketplace/templates?q=ops&limit=10&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["templates"][0]["id"] == "tpl_1"
        mock_registry.search.assert_called_once()

    def test_create_template_requires_auth(self, client):
        response = client.post(
            "/api/v2/marketplace/templates",
            json={"name": "My Template", "description": "desc"},
        )
        assert response.status_code == 401

    def test_create_template_happy_path(self, client):
        _override_auth(client, {"marketplace:write"})
        response = client.post(
            "/api/v2/marketplace/templates",
            json={"name": "My Template", "description": "desc"},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 201
        data = response.json()
        assert data["success"] is True
        assert data["id"] == "tpl_created"

    def test_delete_template_enforces_permission(self, client):
        _override_auth(client, {"marketplace:write"})
        response = client.delete("/api/v2/marketplace/templates/tpl_1")
        client.app.dependency_overrides.clear()
        assert response.status_code == 403

    def test_rate_template_happy_path(self, client):
        _override_auth(client, {"marketplace:write"})
        response = client.post(
            "/api/v2/marketplace/templates/tpl_1/ratings",
            json={"score": 5, "review": "Great template"},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["average_rating"] == 4.5

    def test_rate_template_validation_failure(self, client):
        _override_auth(client, {"marketplace:write"})
        response = client.post(
            "/api/v2/marketplace/templates/tpl_1/ratings",
            json={"score": 0},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 422

    def test_registry_unavailable_returns_503(self, app):
        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
            "marketplace_registry": None,
        }
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v2/marketplace/templates")
        assert response.status_code == 503

    def test_export_not_found_returns_404(self, client, mock_registry):
        mock_registry.export_template.return_value = None
        response = client.get("/api/v2/marketplace/templates/tpl_missing/export")
        assert response.status_code == 404
