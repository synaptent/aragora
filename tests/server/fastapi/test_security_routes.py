from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Route

from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.dependencies.auth import require_authenticated
from aragora.server.fastapi.routes import security


def test_security_routes_require_auth(fastapi_client):
    response = fastapi_client.get("/api/v2/security/rbac-coverage")
    assert response.status_code == 401


def test_security_routes_reject_unexpected_query_params(fastapi_client, override_auth):
    override_auth(fastapi_client)
    response = fastapi_client.get("/api/v2/security/encryption-status?scope=invalid")
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid query"}


def test_rbac_coverage_returns_summary_shape(fastapi_client, fastapi_context, override_auth):
    checker = MagicMock()
    checker.list_assignments.return_value = ["one", "two"]
    fastapi_context["rbac_checker"] = checker

    override_auth(fastapi_client)
    response = fastapi_client.get("/api/v2/security/rbac-coverage")

    assert response.status_code == 200
    data = response.json()["data"]
    assert {
        "roles_defined",
        "permissions_defined",
        "assignments_active",
        "unprotected_endpoints",
        "total_endpoints",
        "coverage_percent",
    } <= data.keys()
    assert data["assignments_active"] == 2


def test_rbac_coverage_maps_assignment_failures_to_safe_summary(
    fastapi_client, fastapi_context, override_auth
):
    checker = MagicMock()
    checker.list_assignments.side_effect = OSError("backend unavailable")
    fastapi_context["rbac_checker"] = checker

    override_auth(fastapi_client)
    response = fastapi_client.get("/api/v2/security/rbac-coverage")

    assert response.status_code == 200
    assert response.json()["data"]["assignments_active"] == 0


def test_rbac_coverage_counts_openapi_operations_for_included_router_tree():
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    parent = APIRouter(prefix="/api/v2")
    nested = APIRouter(prefix="/protected")

    @nested.get("/covered")
    async def covered_route() -> dict[str, bool]:
        return {"ok": True}

    parent.include_router(nested)
    app.include_router(parent)
    app.include_router(security.router)
    checker = MagicMock()
    checker.list_assignments.return_value = []
    app.state.context = {"rbac_checker": checker}
    app.dependency_overrides[require_authenticated] = lambda: AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles={"admin"},
        permissions={"*"},
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v2/security/rbac-coverage")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_endpoints"] == 3
    assert data["unprotected_endpoints"] == 0
    assert data["coverage_percent"] == 100.0


def test_rbac_coverage_counts_schema_hidden_registered_operations():
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    hidden_router = APIRouter(prefix="/api/v2")

    @hidden_router.get("/health", include_in_schema=False)
    async def hidden_health_route() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(hidden_router)
    app.include_router(security.router)
    app.state.context = {"rbac_checker": MagicMock(list_assignments=lambda: [])}
    app.dependency_overrides[require_authenticated] = lambda: AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles={"admin"},
        permissions={"*"},
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v2/security/rbac-coverage")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_endpoints"] == 3
    assert data["unprotected_endpoints"] == 1
    assert data["coverage_percent"] == 66.7


def test_schema_hidden_operations_omit_implicit_head_for_get_route():
    async def hidden_get(request):
        return None

    route = Route(
        "/api/v2/hidden-get",
        hidden_get,
        methods=["GET"],
        include_in_schema=False,
    )

    assert security._schema_hidden_operations(SimpleNamespace(routes=[route])) == {
        ("get", "/api/v2/hidden-get")
    }


def test_schema_hidden_operations_preserve_head_only_route():
    async def hidden_head(request):
        return None

    route = Route(
        "/api/v2/hidden-head",
        hidden_head,
        methods=["HEAD"],
        include_in_schema=False,
    )

    assert security._schema_hidden_operations(SimpleNamespace(routes=[route])) == {
        ("head", "/api/v2/hidden-head")
    }


def test_rbac_coverage_deduplicates_schema_and_registered_operations(monkeypatch):
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.get("/api/v2/hidden", include_in_schema=False)
    async def hidden_route() -> dict[str, bool]:
        return {"ok": True}

    monkeypatch.setattr(
        app,
        "openapi",
        lambda: {"paths": {"/api/v2/hidden": {"get": {"responses": {}}}}},
    )

    assert security._rbac_coverage_route_paths(app) == ["/api/v2/hidden"]


def test_rbac_coverage_retains_legacy_flat_route_fallback():
    app = SimpleNamespace(routes=[SimpleNamespace(path="/api/v2/legacy", methods={"GET"})])

    assert security._rbac_coverage_route_paths(app) == ["/api/v2/legacy"]


def test_rbac_coverage_fails_closed_when_openapi_generation_raises():
    app = SimpleNamespace(
        openapi=MagicMock(side_effect=RuntimeError("generation failed")),
        routes=[SimpleNamespace(path="/api/v2/legacy", methods={"GET"})],
    )

    with pytest.raises(RuntimeError, match="generation failed"):
        security._rbac_coverage_route_paths(app)


def test_rbac_coverage_fails_closed_when_openapi_schema_is_malformed():
    app = SimpleNamespace(
        openapi=lambda: [],
        routes=[SimpleNamespace(path="/api/v2/legacy", methods={"GET"})],
    )

    with pytest.raises(RuntimeError, match="malformed schema"):
        security._rbac_coverage_route_paths(app)


def test_rbac_coverage_endpoint_maps_openapi_failure_to_unavailable():
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.include_router(security.router)
    app.state.context = {"rbac_checker": MagicMock(list_assignments=lambda: [])}
    app.dependency_overrides[require_authenticated] = lambda: AuthorizationContext(
        user_id="user-1",
        org_id="org-1",
        workspace_id="ws-1",
        roles={"admin"},
        permissions={"*"},
    )
    app.openapi = MagicMock(side_effect=RuntimeError("generation failed"))

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v2/security/rbac-coverage")

    assert response.status_code == 503
    assert response.json() == {"detail": "RBAC coverage unavailable"}


def test_encryption_status_maps_tls_failures_to_degraded(
    fastapi_client, override_auth, monkeypatch
):
    override_auth(fastapi_client)
    monkeypatch.setenv("ARAGORA_TLS_CERT_PATH", "/tmp/missing-cert.pem")

    response = fastapi_client.get("/api/v2/security/encryption-status")

    assert response.status_code == 200
    data = response.json()["data"]
    assert {"at_rest", "in_transit"} <= data.keys()
    assert data["in_transit"]["status"] == "degraded"
