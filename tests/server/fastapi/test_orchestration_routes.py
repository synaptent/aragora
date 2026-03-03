"""Tests for FastAPI v2 orchestration routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app


@pytest.fixture
def app():
    """Create a test FastAPI app."""
    return create_app()


@pytest.fixture
def client(app):
    """Create a test client with mocked app context."""
    app.state.context = {
        "storage": MagicMock(),
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
        "orchestration_handler": MagicMock(_execute_deliberation=AsyncMock()),
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


class TestOrchestrationRoutes:
    """FastAPI v2 orchestration route coverage."""

    def test_deliberate_requires_auth(self, client):
        response = client.post("/api/v2/orchestration/deliberate", json={"question": "Ship?"})
        assert response.status_code == 401

    def test_deliberate_dry_run_happy_path(self, client):
        _override_auth(client, {"orchestration:execute"})
        response = client.post(
            "/api/v2/orchestration/deliberate",
            json={"question": "Ship?", "dry_run": True},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 202
        data = response.json()
        assert data["dry_run"] is True
        assert "request_id" in data

    def test_deliberate_sync_dry_run_happy_path(self, client):
        _override_auth(client, {"orchestration:execute"})
        response = client.post(
            "/api/v2/orchestration/deliberate/sync",
            json={"question": "Rollback?", "dry_run": True},
        )
        client.app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["dry_run"] is True
        assert "request_id" in data

    def test_status_happy_path_completed(self, client):
        _override_auth(client, {"orchestration:read"})
        result_obj = MagicMock()
        result_obj.to_dict.return_value = {
            "request_id": "req_1",
            "success": True,
            "consensus_reached": True,
            "final_answer": "Ship it",
        }
        with patch(
            "aragora.server.fastapi.routes.orchestration._get_orchestration_stores",
            return_value=({}, {"req_1": result_obj}),
        ):
            response = client.get("/api/v2/orchestration/status/req_1")
        client.app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"]["final_answer"] == "Ship it"

    def test_status_not_found_failure(self, client):
        _override_auth(client, {"orchestration:read"})
        with patch(
            "aragora.server.fastapi.routes.orchestration._get_orchestration_stores",
            return_value=({}, {}),
        ):
            response = client.get("/api/v2/orchestration/status/req_missing")
        client.app.dependency_overrides.clear()
        assert response.status_code == 404

    def test_templates_requires_auth(self, client):
        response = client.get("/api/v2/orchestration/templates")
        assert response.status_code == 401

    def test_templates_happy_path(self, client):
        _override_auth(client, {"orchestration:read"})
        response = client.get("/api/v2/orchestration/templates")
        client.app.dependency_overrides.clear()
        assert response.status_code == 200
        data = response.json()
        assert "templates" in data
        assert "count" in data

    def test_deliberate_returns_503_when_handler_unavailable(self, app):
        app.state.context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
        }
        client = TestClient(app, raise_server_exceptions=False)
        _override_auth(client, {"orchestration:execute"})
        with patch(
            "aragora.server.fastapi.routes.orchestration._get_orchestration_handler",
            return_value=None,
        ):
            response = client.post(
                "/api/v2/orchestration/deliberate",
                json={"question": "Service check"},
            )
        client.app.dependency_overrides.clear()
        assert response.status_code == 503
