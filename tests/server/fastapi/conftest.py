"""Shared fixtures for FastAPI route tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi import create_app
from aragora.server.fastapi.dependencies.auth import require_authenticated


@pytest.fixture(autouse=True)
def reset_health_probe_cache():
    """Prevent stale admin health state from leaking into FastAPI routes."""
    from aragora.server.degraded_mode import clear_degraded
    from aragora.server.handlers.admin.health import _HEALTH_CACHE, _HEALTH_CACHE_TIMESTAMPS

    clear_degraded()
    _HEALTH_CACHE.clear()
    _HEALTH_CACHE_TIMESTAMPS.clear()
    yield
    clear_degraded()
    _HEALTH_CACHE.clear()
    _HEALTH_CACHE_TIMESTAMPS.clear()


@pytest.fixture
def fastapi_context_builder():
    """Build common FastAPI app context dictionaries for route tests."""

    def _build(**overrides: Any) -> dict[str, Any]:
        context = {
            "storage": MagicMock(),
            "elo_system": MagicMock(),
            "user_store": None,
            "rbac_checker": MagicMock(),
            "decision_service": MagicMock(),
        }
        context.update(overrides)
        return context

    return _build


@pytest.fixture
def fastapi_context(fastapi_context_builder):
    """Default FastAPI app context used by shared client/request fixtures."""
    return fastapi_context_builder()


@pytest.fixture
def fastapi_app(fastapi_context):
    """Create a FastAPI app with a lightweight mocked context."""
    app = create_app()
    app.state.context = fastapi_context
    return app


@pytest.fixture
def app(fastapi_app):
    """Compatibility alias for tests that expect an ``app`` fixture."""
    return fastapi_app


@pytest.fixture
def fastapi_client(fastapi_app):
    """Create a test client that always clears dependency overrides on teardown."""
    client = TestClient(fastapi_app, raise_server_exceptions=False)
    try:
        yield client
    finally:
        fastapi_app.dependency_overrides.clear()
        client.close()


@pytest.fixture
def client(fastapi_client):
    """Compatibility alias for tests that expect a ``client`` fixture."""
    return fastapi_client


@pytest.fixture
def mock_app_client(fastapi_client):
    """Explicit alias used by route tests that want a mocked app client."""
    return fastapi_client


@pytest.fixture
def fastapi_request_factory(fastapi_context_builder):
    """Create lightweight request mocks for calling route functions directly."""

    def _build(
        *,
        context: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        path: str = "/",
        body: bytes = b"",
    ) -> MagicMock:
        request = MagicMock()
        request.app.state.context = context if context is not None else fastapi_context_builder()
        request.headers = headers or {}
        request.method = method
        request.url = SimpleNamespace(path=path)
        request.state = SimpleNamespace()
        request.body = AsyncMock(return_value=body)
        return request

    return _build


@pytest.fixture
def route_request_factory(fastapi_request_factory):
    """Short alias for direct route-request helper creation."""
    return fastapi_request_factory


@pytest.fixture
def fastapi_route_auth_factory():
    """Build lightweight auth objects for direct route-function tests."""

    def _build(
        *,
        user_id: str = "user-1",
        email: str = "user@example.com",
        org_id: str = "org-1",
        workspace_id: str = "ws-1",
        roles: set[str] | None = None,
        permissions: set[str] | None = None,
        **extra: Any,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            user_id=user_id,
            email=email,
            org_id=org_id,
            workspace_id=workspace_id,
            roles=set(roles or {"admin"}),
            permissions=set(permissions or {"*"}),
            **extra,
        )

    return _build


@pytest.fixture
def route_auth_factory(fastapi_route_auth_factory):
    """Short alias for direct route-auth helper creation."""
    return fastapi_route_auth_factory


@pytest.fixture
def override_fastapi_auth():
    """Override ``require_authenticated`` with a configurable auth context."""

    def _override(
        client: TestClient,
        *,
        user_id: str = "user-1",
        org_id: str = "org-1",
        workspace_id: str = "ws-1",
        roles: set[str] | None = None,
        permissions: set[str] | None = None,
    ) -> AuthorizationContext:
        auth_ctx = AuthorizationContext(
            user_id=user_id,
            org_id=org_id,
            workspace_id=workspace_id,
            roles=set(roles or {"admin"}),
            permissions=set(permissions or {"*"}),
        )
        client.app.dependency_overrides[require_authenticated] = lambda: auth_ctx
        return auth_ctx

    return _override


@pytest.fixture
def override_auth(override_fastapi_auth):
    """Short alias for common auth override helper usage."""
    return override_fastapi_auth


@pytest.fixture
def fastapi_bearer(monkeypatch):
    """Sign real JWTs: returns ``bearer(user_id, org_id, role="owner")`` -> headers.

    For routes whose org scope comes from ``require_org_scope_fastapi`` or
    ``authorize_debate_read_fastapi``, which read the token itself and so are
    not reached by dependency overrides.
    """
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.billing.auth.tokens import create_access_token
    from aragora.server import auth as server_auth

    for name in (
        "ARAGORA_ENV",
        "ARAGORA_ENVIRONMENT",
        "ARAGORA_SECRETS_STRICT",
        "ARAGORA_API_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "fastapi-route-test-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)

    def _bearer(user_id: str, org_id: str | None, role: str = "owner") -> dict[str, str]:
        token = create_access_token(user_id, f"{user_id}@example.test", org_id, role)
        return {"Authorization": f"Bearer {token}"}

    return _bearer
