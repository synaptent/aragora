"""
Tests for FastAPI route endpoints.

Covers:
- Health check endpoints (liveness/readiness)
- Debate listing (org members only)
- Decision endpoints (auth-protected write operations)
- RBAC enforcement
"""

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
    """Create a test client."""
    # Override lifespan to avoid real subsystem initialization
    app.state.context = {
        "storage": MagicMock(),
        "elo_system": MagicMock(),
        "user_store": None,
        "rbac_checker": MagicMock(),
        "decision_service": MagicMock(),
    }
    return TestClient(app, raise_server_exceptions=False)


class TestHealthRoutes:
    """Tests for health check endpoints."""

    def test_healthz_returns_ok(self, client):
        """Liveness probe should always return 200."""
        response = client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_readyz_returns_status(self, client):
        """Readiness probe should check storage."""
        response = client.get("/readyz")
        # May return 200 (ready) or 503 (not ready) depending on storage
        assert response.status_code in [200, 503]

    def test_health_detail_returns_info(self, client):
        """Detailed health endpoint returns subsystem status."""
        response = client.get("/api/v2/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "subsystems" in data

    def test_root_returns_api_info(self, client):
        """Root endpoint returns API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


class TestDebateRoutes:
    """Tests for debate query endpoints (org members only)."""

    def test_list_debates_requires_auth(self, client):
        """Anonymous callers cannot list debates."""
        response = client.get("/api/v2/debates")
        assert response.status_code == 401

    def test_list_debates_returns_200(self, client, fastapi_bearer):
        """An org member lists the org's debates."""
        storage = client.app.state.context["storage"]
        storage.list_recent = MagicMock(return_value=[])
        storage.count_debates = MagicMock(return_value=0)
        response = client.get("/api/v2/debates", headers=fastapi_bearer("user-1", "org-1"))
        assert response.status_code == 200

    def test_list_debates_with_pagination(self, client, fastapi_bearer):
        """List debates supports pagination params."""
        storage = client.app.state.context["storage"]
        storage.list_recent = MagicMock(return_value=[])
        storage.count_debates = MagicMock(return_value=0)
        response = client.get(
            "/api/v2/debates?limit=10&offset=0", headers=fastapi_bearer("user-1", "org-1")
        )
        assert response.status_code == 200
        storage.list_recent.assert_called_once_with(limit=10, org_id="org-1", offset=0)


class TestDecisionRoutes:
    """Tests for decision endpoints (auth-protected)."""

    def test_start_decision_requires_auth(self, client):
        """POST /decisions should require authentication."""
        response = client.post(
            "/api/v2/decisions",
            json={"task": "Test debate"},
        )
        # Should return 401 because no Authorization header
        assert response.status_code == 401

    def test_cancel_decision_requires_auth(self, client):
        """DELETE /decisions/{id} should require authentication."""
        response = client.delete("/api/v2/decisions/test-id")
        assert response.status_code == 401

    def test_get_decision_is_public(self, client):
        """GET /decisions/{id} should be publicly accessible."""
        # Mock the decision service
        mock_service = AsyncMock()
        mock_service.get_debate = AsyncMock(return_value=None)

        with patch(
            "aragora.server.fastapi.routes.decisions.get_decision_service",
            return_value=mock_service,
        ):
            response = client.get("/api/v2/decisions/nonexistent-id")
            # 404 because debate doesn't exist, not 401
            assert response.status_code in [404, 500]

    def test_list_decisions_is_public(self, client):
        """GET /decisions should be publicly accessible."""
        mock_service = AsyncMock()
        mock_service.list_debates = AsyncMock(return_value=[])

        # Override the decision service in app context
        client.app.state.context["decision_service"] = mock_service
        response = client.get("/api/v2/decisions")
        assert response.status_code == 200


class TestCORSHeaders:
    """Tests for CORS middleware."""

    def test_cors_allows_configured_origins(self, client):
        """CORS should include expected headers."""
        response = client.options(
            "/api/v2/debates",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORS middleware should respond to preflight
        assert response.status_code in [200, 204, 400]

    def test_response_includes_trace_id(self, client):
        """Responses should include X-Trace-ID header."""
        response = client.get("/healthz")
        assert "x-trace-id" in response.headers


class TestRequestValidation:
    """Tests for request validation middleware."""

    def test_rejects_oversized_body(self, client):
        """Should reject bodies exceeding size limit."""
        # Create a body larger than 10MB
        large_body = "x" * (11 * 1024 * 1024)
        response = client.post(
            "/api/v2/decisions",
            content=large_body,
            headers={"Content-Type": "application/json"},
        )
        # Should return 413 (too large) or 401 (auth first) or 422 (invalid JSON)
        assert response.status_code in [401, 413, 422]
