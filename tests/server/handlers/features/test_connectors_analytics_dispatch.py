"""Live-dispatch tests for the connector and analytics-platform routes.

ConnectorsHandler and AnalyticsPlatformsHandler serve every route through
``handle_request(request)``, which the modular dispatcher never calls. These
tests build the route index from the full HANDLER_REGISTRY with the real
``_init_handlers`` and send requests through the real ``_try_modular_handler``,
so route ownership, the dispatcher's 500 fallbacks and the handlers' own
permission checks are all exercised.
"""

from __future__ import annotations

import asyncio
import io
import itertools
import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.connectors.runtime_registry import ConnectorStatus
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.connectors.management import ConnectorManagementHandler
from aragora.server.handlers.features import analytics_platforms as analytics_module
from aragora.server.handlers.features import connectors as connectors_module
from aragora.server.handlers.features.connectors import ConnectorsHandler
from aragora.storage.sync_store import ConnectorConfig

CALLERS = ("owner", "admin", "member", "analyst", "viewer", "anon")


class _RegistryMixin(HandlerRegistryMixin):
    _handlers_initialized = False
    _init_lock = threading.Lock()

    storage = None
    stream_emitter = None
    control_plane_stream = None
    nomic_loop_stream = None
    elo_system = None
    nomic_state_file = None
    debate_embeddings = None
    critique_store = None
    document_store = None
    persona_manager = None
    position_ledger = None
    user_store = None
    continuum_memory = None
    cross_debate_memory = None
    knowledge_mound = None


class _FakeConnectorRegistry:
    """Runtime connector registry that knows exactly one connector, ``known_conn``."""

    def __init__(self) -> None:
        self.info = SimpleNamespace(
            connector_type="github",
            capabilities=["sync"],
            last_health_check="2026-09-30T00:00:00+00:00",
            metadata={"importable": True},
        )

    def get(self, name: str) -> Any:
        return self.info if name == "known_conn" else None

    def health_check(self, name: str) -> ConnectorStatus:
        return ConnectorStatus.HEALTHY


_client_ips = itertools.count(1)


@pytest.fixture(scope="module")
def registry_cls() -> type[_RegistryMixin]:
    _RegistryMixin._init_handlers()
    assert _RegistryMixin._handlers_initialized is True
    return _RegistryMixin


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    """In-memory connector/analytics state only, no store, no platform clients."""

    async def _no_store() -> None:
        return None

    async def _no_platform_client(self, platform: str) -> None:
        return None

    monkeypatch.setattr(connectors_module, "_get_store", _no_store)
    monkeypatch.setattr(connectors_module, "_connectors", {})
    monkeypatch.setattr(connectors_module, "_sync_jobs", {})
    monkeypatch.setattr(connectors_module, "_sync_history", [])
    monkeypatch.setattr(analytics_module, "_platform_credentials", {})
    monkeypatch.setattr(analytics_module, "_platform_connectors", {})
    monkeypatch.setattr(
        analytics_module.AnalyticsPlatformsHandler, "_get_connector", _no_platform_client
    )
    fake_registry = _FakeConnectorRegistry()
    monkeypatch.setattr(ConnectorManagementHandler, "_get_registry", lambda self: fake_registry)


def _dispatch(
    registry_cls: type[_RegistryMixin],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    caller: str | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, Any]:
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    if raw_body is not None:
        raw = raw_body
    instance.command = method
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    if caller and caller != "anon":
        token = create_access_token(
            user_id=f"jwt-{caller}", email=f"{caller}@example.com", org_id="org-1", role=caller
        )
        instance.headers["Authorization"] = f"Bearer {token}"
    instance.rfile = io.BytesIO(raw)
    instance.wfile = io.BytesIO()
    instance.send_response = MagicMock()
    instance.send_header = MagicMock()
    instance.end_headers = MagicMock()
    instance._add_cors_headers = MagicMock()
    instance._add_security_headers = MagicMock()
    instance._add_trace_headers = MagicMock()
    instance._auth_context = None
    n = next(_client_ips)
    # A distinct client per request keeps the handlers' per-IP limiters out of the way.
    instance.client_address = (f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}", 12345)
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
        # Keep token validation off whatever revocation database the host points at.
        patch("aragora.billing.auth.blacklist.is_token_revoked_persistent", return_value=False),
    ):
        handled = instance._try_modular_handler(path, {})
    assert handled is True, f"{method} {path} was not handled"
    status = instance.send_response.call_args[0][0]
    return status, json.loads(instance.wfile.getvalue() or b"{}")


# (method, path, body) for each batch-5 id this change makes reachable.
ROUTES: dict[str, tuple[str, str, dict[str, Any] | None]] = {
    "connectors.create": ("POST", "/api/v1/connectors", {"type": "github", "name": "probe"}),
    "connectors.delete": ("DELETE", "/api/v1/connectors/probe-conn", None),
    "connectors.update": ("PATCH", "/api/v1/connectors/probe-conn", {"name": "renamed"}),
    "connectors.triggerSync": ("POST", "/api/v1/connectors/probe-conn/sync", None),
    "connectors.cancelSync": (
        "POST",
        "/api/v1/connectors/probe-conn/syncs/probe-sync/cancel",
        None,
    ),
    "connectors.listSyncs": ("GET", "/api/v1/connectors/probe-conn/syncs", None),
    "connectors.getSyncStatus": ("GET", "/api/v1/connectors/probe-conn/syncs/probe-sync", None),
    "connectors.getHealth": ("GET", "/api/v1/connectors/unknown_conn/health", None),
    "connectors.testConnection": ("POST", "/api/v1/connectors/unknown_conn/test", None),
    "analytics.connectPlatform": (
        "POST",
        "/api/v1/analytics/connect",
        {"platform": "metabase", "credentials": {"base_url": "https://mb.example"}},
    ),
    "analytics.disconnectPlatform": ("DELETE", "/api/v1/analytics/metabase", None),
    "analytics.executeQuery": (
        "POST",
        "/api/v1/analytics/query",
        {"platform": "metabase", "query": "select 1"},
    ),
    "analytics.generateReport": ("POST", "/api/v1/analytics/reports/generate", {"days": 7}),
    "analytics.getWorkspaceUsage": ("GET", "/api/v1/analytics/workspace/ws-1/usage", None),
}

_ALL_403 = {"owner": 403, "admin": 403, "member": 403, "analyst": 403, "viewer": 403, "anon": 401}

# Status per caller with a real JWT (role only, as production tokens carry).
# connectors:configure, analytics:configure and analytics:query are not registered
# RBAC permissions, so every authenticated caller gets 403 on the routes they guard.
# Per-connector health and test follow the RBAC v2 role grants: connectors.read is
# held by owner and admin, connectors.test by owner only.
EXPECTED: dict[str, dict[str, int]] = {
    "connectors.create": {
        "owner": 201,
        "admin": 201,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "connectors.delete": {
        "owner": 404,
        "admin": 404,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "connectors.update": _ALL_403,
    "connectors.triggerSync": _ALL_403,
    "connectors.cancelSync": _ALL_403,
    "connectors.listSyncs": {
        "owner": 501,
        "admin": 501,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "connectors.getSyncStatus": {
        "owner": 501,
        "admin": 501,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "connectors.getHealth": {
        "owner": 404,
        "admin": 404,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "connectors.testConnection": {
        "owner": 404,
        "admin": 403,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "analytics.connectPlatform": _ALL_403,
    "analytics.disconnectPlatform": _ALL_403,
    "analytics.executeQuery": _ALL_403,
    "analytics.generateReport": _ALL_403,
    "analytics.getWorkspaceUsage": {
        "owner": 501,
        "admin": 501,
        "member": 501,
        "analyst": 501,
        "viewer": 403,
        "anon": 401,
    },
}


@pytest.mark.parametrize(
    ("path", "owner_cls"),
    [
        ("/api/v1/connectors/probe_conn/health", ConnectorManagementHandler),
        ("/api/v1/connectors/probe_conn/test", ConnectorManagementHandler),
        ("/api/v1/connectors/health", ConnectorsHandler),
        ("/api/v1/connectors/test", ConnectorsHandler),
        ("/api/v1/connectors/probe-conn", ConnectorsHandler),
        ("/api/v1/connectors/probe-conn/syncs", ConnectorsHandler),
        ("/api/v1/connectors/probe-conn/syncs/probe-sync/cancel", ConnectorsHandler),
    ],
)
def test_connector_routes_resolve_to_the_handler_with_the_logic(
    registry_cls, path: str, owner_cls: type
) -> None:
    match = get_route_index().get_handler(path)
    assert match is not None
    assert type(match[1]) is owner_cls


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("route_id", sorted(ROUTES))
def test_real_jwt_callers_get_the_route_permission_answer(
    registry_cls, route_id: str, caller: str
) -> None:
    method, path, body = ROUTES[route_id]
    status, payload = _dispatch(registry_cls, method, path, body, caller=caller)
    assert status == EXPECTED[route_id][caller], (route_id, caller, payload)
    if status == 501:
        assert payload["error"]["code"] == "not_implemented"


# POST /api/v1/connectors gives stored connectors hyphenated UUID ids, which the
# runtime registry's name rule rejects.
_STORE_ID = "0b6f3c2e-8d1a-4e5b-9f7c-3a2d1e0f9b8c"

PER_CONNECTOR_CELLS: dict[tuple[str, str], dict[str, int]] = {
    ("GET", "/api/v1/connectors/known_conn/health"): {
        "owner": 200,
        "admin": 200,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    ("GET", f"/api/v1/connectors/{_STORE_ID}/health"): {
        "owner": 501,
        "admin": 501,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    ("POST", "/api/v1/connectors/known_conn/test"): {
        "owner": 200,
        "admin": 403,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    ("POST", f"/api/v1/connectors/{_STORE_ID}/test"): {
        "owner": 501,
        "admin": 403,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize(("method", "path"), sorted(PER_CONNECTOR_CELLS))
def test_per_connector_health_and_test_check_rbac_before_the_connector_name(
    registry_cls, method: str, path: str, caller: str
) -> None:
    status, payload = _dispatch(registry_cls, method, path, caller=caller)
    assert status == PER_CONNECTOR_CELLS[(method, path)][caller], (path, caller, payload)
    if status == 501:
        assert payload["error"]["code"] == "not_implemented"


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(
    ("caller", "name", "expected"),
    [("member", "unknown_conn", 404), ("member", _STORE_ID, 400), ("viewer", "unknown_conn", 403)],
)
def test_connector_detail_keeps_its_own_permission_and_name_checks(
    caller: str, name: str, expected: int
) -> None:
    # The route index gives GET /api/v1/connectors/{id} to ConnectorsHandler, so the
    # management handler's detail route is only reachable by calling it directly.
    token = create_access_token(
        user_id=f"jwt-{caller}", email=f"{caller}@example.com", org_id="org-1", role=caller
    )
    request = SimpleNamespace(
        command="GET",
        headers={"Authorization": f"Bearer {token}"},
        client_address=("10.255.0.1", 12345),
    )
    with patch("aragora.billing.auth.blacklist.is_token_revoked_persistent", return_value=False):
        result = ConnectorManagementHandler().handle(f"/api/v1/connectors/{name}", {}, request)
    assert result is not None
    assert result.status_code == expected, result.body


def test_connector_lifecycle_through_the_sdk_paths(registry_cls) -> None:
    status, created = _dispatch(
        registry_cls, "POST", "/api/v1/connectors", {"type": "github", "name": "Repo sync"}
    )
    assert status == 201, created
    connector_id = created["id"]

    status, updated = _dispatch(
        registry_cls, "PATCH", f"/api/v1/connectors/{connector_id}", {"name": "Renamed"}
    )
    assert status == 200, updated
    assert updated["name"] == "Renamed"

    status, started = _dispatch(registry_cls, "POST", f"/api/v1/connectors/{connector_id}/sync")
    assert status == 202, started
    assert started["connector_id"] == connector_id

    status, deleted = _dispatch(registry_cls, "DELETE", f"/api/v1/connectors/{connector_id}")
    assert status == 200, deleted
    assert connector_id not in connectors_module._connectors


class _MemorySyncStore:
    """The SyncStore connector methods the connectors handler calls, kept in a dict."""

    def __init__(self) -> None:
        self.rows: dict[str, ConnectorConfig] = {}

    async def save_connector(
        self, connector_id: str, connector_type: str, name: str, config: dict[str, Any]
    ) -> ConnectorConfig:
        row = ConnectorConfig(
            id=connector_id, connector_type=connector_type, name=name, config=dict(config)
        )
        self.rows[connector_id] = row
        return row

    async def get_connector(self, connector_id: str) -> ConnectorConfig | None:
        return self.rows.get(connector_id)

    async def list_connectors(self, status=None, connector_type=None) -> list[ConnectorConfig]:
        return list(self.rows.values())

    async def delete_connector(self, connector_id: str) -> bool:
        return self.rows.pop(connector_id, None) is not None

    async def get_sync_history(self, connector_id=None, limit: int = 50) -> list[Any]:
        return []


@pytest.fixture
def memory_store(monkeypatch) -> _MemorySyncStore:
    store = _MemorySyncStore()

    async def _store() -> _MemorySyncStore:
        return store

    monkeypatch.setattr(connectors_module, "_get_store", _store)
    return store


def test_update_and_delete_reach_the_persistent_store(registry_cls, memory_store) -> None:
    status, created = _dispatch(
        registry_cls, "POST", "/api/v1/connectors", {"type": "github", "name": "Repo sync"}
    )
    assert status == 201, created
    connector_id = created["id"]

    status, updated = _dispatch(
        registry_cls, "PATCH", f"/api/v1/connectors/{connector_id}", {"name": "Renamed"}
    )
    assert status == 200, updated
    assert memory_store.rows[connector_id].name == "Renamed"

    status, deleted = _dispatch(registry_cls, "DELETE", f"/api/v1/connectors/{connector_id}")
    assert status == 200, deleted
    assert connector_id not in memory_store.rows

    status, listed = _dispatch(registry_cls, "GET", "/api/v1/connectors")
    assert status == 200, listed
    assert [c["id"] for c in listed["connectors"]] == []


def test_stored_connector_can_be_updated_and_deleted_after_a_restart(
    registry_cls, memory_store
) -> None:
    asyncio.run(memory_store.save_connector("stored-1", "github", "Stored", {"org": "a"}))
    assert "stored-1" not in connectors_module._connectors

    status, updated = _dispatch(
        registry_cls, "PATCH", "/api/v1/connectors/stored-1", {"config": {"repo": "b"}}
    )
    assert status == 200, updated
    assert memory_store.rows["stored-1"].config == {"org": "a", "repo": "b"}

    status, deleted = _dispatch(registry_cls, "DELETE", "/api/v1/connectors/stored-1")
    assert status == 200, deleted
    assert memory_store.rows == {}

    status, missing = _dispatch(registry_cls, "DELETE", "/api/v1/connectors/stored-1")
    assert status == 404, missing


def test_cancel_sync_accepts_the_sdk_path_and_checks_the_connector(registry_cls) -> None:
    connectors_module._connectors["c1"] = {"id": "c1", "type": "github", "status": "syncing"}
    connectors_module._sync_jobs["s1"] = {"id": "s1", "connector_id": "c1", "status": "running"}

    status, body = _dispatch(registry_cls, "POST", "/api/v1/connectors/other/syncs/s1/cancel")
    assert status == 404, body
    assert connectors_module._sync_jobs["s1"]["status"] == "running"

    status, body = _dispatch(registry_cls, "POST", "/api/v1/connectors/c1/syncs/s1/cancel")
    assert status == 200, body
    assert connectors_module._sync_jobs["s1"]["status"] == "cancelled"


@pytest.mark.parametrize("path", ["/api/v1/connectors/c1/syncs", "/api/v1/connectors/c1/syncs/s1"])
def test_sync_listing_routes_answer_501_not_implemented(registry_cls, path: str) -> None:
    connectors_module._connectors["c1"] = {"id": "c1", "type": "github", "status": "configured"}
    status, body = _dispatch(registry_cls, "GET", path)
    assert status == 501, body
    assert body["error"]["code"] == "not_implemented"


def test_per_connector_health_and_test_reach_connector_management(registry_cls) -> None:
    status, health = _dispatch(registry_cls, "GET", "/api/v1/connectors/known_conn/health")
    assert status == 200, health
    assert health == {
        "name": "known_conn",
        "status": "healthy",
        "last_health_check": "2026-09-30T00:00:00+00:00",
        "metadata": {"importable": True},
    }

    status, tested = _dispatch(registry_cls, "POST", "/api/v1/connectors/known_conn/test")
    assert status == 200, tested
    assert tested["connector_type"] == "github"
    assert tested["status"] == "healthy"


def test_global_connector_health_stays_with_connectors_handler(registry_cls) -> None:
    status, body = _dispatch(registry_cls, "GET", "/api/v1/connectors/health")
    assert status == 200, body
    assert body["summary"]["total"] == 0


def test_analytics_platform_routes_run_their_logic(registry_cls) -> None:
    credentials = {"base_url": "https://mb.example", "username": "u", "password": "p"}
    status, body = _dispatch(
        registry_cls,
        "POST",
        "/api/v1/analytics/connect",
        {"platform": "metabase", "credentials": credentials},
    )
    assert status == 200, body
    assert body["platform"] == "metabase"

    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/analytics/query", {"platform": "mixpanel", "query": "q"}
    )
    assert status == 400, body
    assert body == {"error": "Valid connected platform is required"}

    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/analytics/reports/generate", {"platforms": [], "days": 7}
    )
    assert status == 200, body
    assert body["platforms"] == {}

    status, body = _dispatch(registry_cls, "DELETE", "/api/v1/analytics/metabase")
    assert status == 200, body
    status, body = _dispatch(registry_cls, "DELETE", "/api/v1/analytics/metabase")
    assert status == 404, body


def test_workspace_usage_answers_501_not_implemented(registry_cls) -> None:
    status, body = _dispatch(registry_cls, "GET", "/api/v1/analytics/workspace/ws-1/usage")
    assert status == 501, body
    assert body["error"]["code"] == "not_implemented"


def test_invalid_json_body_is_a_client_error(registry_cls) -> None:
    status, body = _dispatch(registry_cls, "POST", "/api/v1/connectors", raw_body=b"{not json")
    assert status == 400, body
