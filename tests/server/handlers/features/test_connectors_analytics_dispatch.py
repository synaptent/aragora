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
import copy
import io
import itertools
import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.connectors.runtime_registry import ConnectorStatus
from aragora.server import unified_server
from aragora.server.auth import auth_config
from aragora.server.auth_checks import AuthChecksMixin
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.connectors.management import ConnectorManagementHandler
from aragora.server.handlers.features import analytics_platforms as analytics_module
from aragora.server.handlers.features import connectors as connectors_module
from aragora.server.handlers.features.connectors import ConnectorsHandler
from aragora.storage.sync_store import ConnectorConfig, SyncStore
from aragora.utils.async_utils import get_pool_event_loop

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


class _ServerChecks(AuthChecksMixin, _RegistryMixin):
    """The registry behind the server's pre-dispatch RBAC and auth checks."""

    @property
    def rbac(self) -> Any:
        return unified_server.UnifiedHandler._get_rbac()


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

    def get_summary(self) -> dict[str, Any]:
        return {"total": 1, "by_type": {"github": 1}, "by_status": {"healthy": 1}}


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
    instance.path = path
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
    send_json = instance._send_json = MagicMock()
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
        if isinstance(instance, AuthChecksMixin):
            # UnifiedHandler runs both checks before modular dispatch and stops on False.
            if not (instance._check_rbac(path, method) and instance._check_rate_limit()):
                sent = send_json.call_args
                return sent.kwargs["status"], sent.args[0]
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
# connectors:configure, analytics:configure and analytics:query are registered RBAC
# permissions held by owner and admin; analyst holds analytics:query only. A caller
# holding the guarding key reaches the handler and gets its answer to the probe request.
# Per-connector health and test follow the RBAC v2 role grants: connectors.read
# and connectors.test are both held by owner and admin.
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
    "connectors.update": {**_ALL_403, "owner": 404, "admin": 404},
    "connectors.triggerSync": {**_ALL_403, "owner": 404, "admin": 404},
    "connectors.cancelSync": {**_ALL_403, "owner": 404, "admin": 404},
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
        "admin": 404,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "analytics.connectPlatform": {**_ALL_403, "owner": 400, "admin": 400},
    "analytics.disconnectPlatform": {**_ALL_403, "owner": 404, "admin": 404},
    "analytics.executeQuery": {**_ALL_403, "owner": 400, "admin": 400, "analyst": 400},
    "analytics.generateReport": {**_ALL_403, "owner": 200, "admin": 200, "analyst": 200},
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
        ("/api/v1/connectors/summary", ConnectorManagementHandler),
        ("/api/v1/connectors", ConnectorsHandler),
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
        "admin": 200,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    ("POST", f"/api/v1/connectors/{_STORE_ID}/test"): {
        "owner": 501,
        "admin": 501,
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


@pytest.fixture
def open_sqlite_store(monkeypatch, tmp_path) -> Iterator[Callable[[], SyncStore]]:
    """Open a real SQLite SyncStore; each call reopens the same file, as after a restart."""
    url = f"sqlite:///{tmp_path / 'connectors.db'}"
    stores: list[SyncStore] = []

    def _open() -> SyncStore:
        store = SyncStore(database_url=url, use_encryption=False)
        asyncio.run(store.initialize())
        stores.append(store)
        return store

    async def _latest() -> SyncStore:
        return stores[-1]

    monkeypatch.setattr(connectors_module, "_get_store", _latest)
    yield _open
    for store in stores:
        asyncio.run(store.close())


# Real JWTs get 403 on PATCH and PUT (connectors:configure is not a registered
# permission), so these run under the handler suite's default admin context.
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
def test_config_update_status_survives_get_and_restart(
    registry_cls, open_sqlite_store, method: str
) -> None:
    store = open_sqlite_store()
    asyncio.run(store.save_connector("stored-1", "github", "Stored", {"org": "a"}))
    asyncio.run(store.update_connector_status("stored-1", "connected", "last sync failed"))

    status, updated = _dispatch(
        registry_cls, method, "/api/v1/connectors/stored-1", {"config": {"repo": "b"}}
    )
    assert (status, updated["status"]) == (200, "configuring"), updated

    status, fetched = _dispatch(registry_cls, "GET", "/api/v1/connectors/stored-1")
    assert (status, fetched["status"]) == (200, "configuring"), fetched

    open_sqlite_store()
    status, fetched = _dispatch(registry_cls, "GET", "/api/v1/connectors/stored-1")
    assert status == 200, fetched
    assert (fetched["status"], fetched["config"]) == ("configuring", {"org": "a", "repo": "b"})
    assert fetched["error_message"] == "last sync failed"


def test_config_update_does_not_share_the_handler_dict_with_the_store(
    registry_cls, open_sqlite_store
) -> None:
    store = open_sqlite_store()
    asyncio.run(store.save_connector("stored-1", "github", "Stored", {"org": {"name": "a"}}))

    status, updated = _dispatch(
        registry_cls, "PATCH", "/api/v1/connectors/stored-1", {"config": {"repo": "b"}}
    )
    assert status == 200, updated

    in_memory = connectors_module._connectors["stored-1"]["config"]
    in_memory["repo"] = "changed in memory"
    in_memory["org"]["name"] = "changed in memory"
    cached = asyncio.run(store.get_connector("stored-1"))
    assert cached is not None
    assert cached.config == {"org": {"name": "a"}, "repo": "b"}


_MASK = "********"
_SECRET_CONFIG: dict[str, Any] = {
    "org": "a",
    "api_key": "sk-live-1",
    "auth": {"user": "u", "client_secret": "cs-1"},
    "credentials": {"password": "pw-1"},
    "accounts": [{"name": "n", "token": "t-1"}],
}
_MASKED_CONFIG: dict[str, Any] = {
    "org": "a",
    "api_key": _MASK,
    "auth": {"user": "u", "client_secret": _MASK},
    "credentials": _MASK,
    "accounts": [{"name": "n", "token": _MASK}],
}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", ["owner", "admin"])
@pytest.mark.parametrize("backend", ["sqlite", "memory"])
def test_list_and_detail_mask_secret_config_values(
    registry_cls, request, backend: str, caller: str
) -> None:
    if backend == "sqlite":
        store = request.getfixturevalue("open_sqlite_store")()
        asyncio.run(store.save_connector("c1", "github", "C1", copy.deepcopy(_SECRET_CONFIG)))
    else:
        connectors_module._connectors["c1"] = {
            "id": "c1",
            "type": "github",
            "name": "C1",
            "status": "configured",
            "config": copy.deepcopy(_SECRET_CONFIG),
        }

    status, listed = _dispatch(registry_cls, "GET", "/api/v1/connectors", caller=caller)
    assert status == 200, listed
    assert [c["config"] for c in listed["connectors"]] == [_MASKED_CONFIG]

    status, detail = _dispatch(registry_cls, "GET", "/api/v1/connectors/c1", caller=caller)
    assert (status, detail["config"]) == (200, _MASKED_CONFIG), detail

    if backend == "sqlite":
        stored = asyncio.run(store.get_connector("c1"))
        assert stored is not None
        assert stored.config == _SECRET_CONFIG
    else:
        assert connectors_module._connectors["c1"]["config"] == _SECRET_CONFIG


# Real JWTs get 403 on PATCH and PUT (see above), so this uses the default admin context.
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
def test_create_and_update_mask_secrets_and_never_store_the_mask(
    registry_cls, open_sqlite_store, method: str
) -> None:
    open_sqlite_store()
    status, created = _dispatch(
        registry_cls,
        "POST",
        "/api/v1/connectors",
        {"type": "github", "name": "Repo", "config": copy.deepcopy(_SECRET_CONFIG)},
    )
    assert (status, created["config"]) == (201, _MASKED_CONFIG), created
    path = f"/api/v1/connectors/{created['id']}"

    # The masked "accounts" list cannot say which stored entry each mask stands for.
    status, rejected = _dispatch(
        registry_cls, method, path, {"config": {**created["config"], "org": "b"}}
    )
    assert status == 400, rejected

    # The rest of the masked config sent straight back with one real edit keeps every secret.
    resent = {k: v for k, v in created["config"].items() if k != "accounts"}
    status, updated = _dispatch(registry_cls, method, path, {"config": {**resent, "org": "b"}})
    assert (status, updated["config"]) == (200, {**_MASKED_CONFIG, "org": "b"}), updated
    stored = asyncio.run(open_sqlite_store().get_connector(created["id"]))
    assert stored is not None
    assert stored.config == {**_SECRET_CONFIG, "org": "b"}

    new_values = {"api_key": "sk-live-2", "auth": {"user": "u", "client_secret": "cs-2"}}
    status, updated = _dispatch(registry_cls, method, path, {"config": new_values})
    assert (status, updated["config"]["api_key"]) == (200, _MASK), updated
    stored = asyncio.run(open_sqlite_store().get_connector(created["id"]))
    assert stored is not None
    assert stored.config == {**_SECRET_CONFIG, "org": "b", **new_values}


_LIST_CONFIG: dict[str, Any] = {
    "org": "a",
    "api_key": "sk-1",
    "accounts": [{"name": "A", "token": "t-A"}, {"name": "B", "token": "t-B"}],
}


@pytest.mark.parametrize("method", ["PATCH", "PUT"])
@pytest.mark.parametrize(
    "accounts",
    [
        pytest.param([{"name": "B", "token": _MASK}], id="delete"),
        pytest.param([{"name": "B", "token": _MASK}, {"name": "A", "token": _MASK}], id="reorder"),
        pytest.param(
            [{"name": "A", "token": _MASK}, {"name": "A", "token": _MASK}], id="duplicate"
        ),
        pytest.param([{"name": "A", "token": _MASK}, {"name": "B", "token": _MASK}], id="same"),
        pytest.param([{"name": "C", "token": "t-C"}, _MASK], id="bare-mask"),
        pytest.param([[{"token": _MASK}]], id="nested-list"),
    ],
)
def test_mask_inside_a_list_is_refused_and_nothing_is_stored(
    registry_cls, open_sqlite_store, method: str, accounts: list[Any]
) -> None:
    store = open_sqlite_store()
    asyncio.run(store.save_connector("stored-1", "github", "Stored", copy.deepcopy(_LIST_CONFIG)))

    status, body = _dispatch(
        registry_cls,
        method,
        "/api/v1/connectors/stored-1",
        {"name": "Renamed", "config": {"org": "b", "api_key": _MASK, "accounts": accounts}},
    )
    assert status == 400, body
    assert "inside a list" in json.dumps(body)

    assert connectors_module._connectors["stored-1"]["config"] == _LIST_CONFIG
    for reader in (store, open_sqlite_store()):
        stored = asyncio.run(reader.get_connector("stored-1"))
        assert stored is not None
        assert (stored.name, stored.config) == ("Stored", _LIST_CONFIG)


def test_list_without_the_mask_replaces_and_dict_masks_still_restore(
    registry_cls, open_sqlite_store
) -> None:
    store = open_sqlite_store()
    asyncio.run(store.save_connector("stored-1", "github", "Stored", copy.deepcopy(_SECRET_CONFIG)))
    accounts = [{"name": "m", "token": "t-2"}]

    status, updated = _dispatch(
        registry_cls,
        "PATCH",
        "/api/v1/connectors/stored-1",
        {"config": {**_MASKED_CONFIG, "org": "b", "accounts": accounts}},
    )
    assert status == 200, updated
    masked_accounts = [{"name": "m", "token": _MASK}]
    assert updated["config"] == {**_MASKED_CONFIG, "org": "b", "accounts": masked_accounts}

    stored = asyncio.run(open_sqlite_store().get_connector("stored-1"))
    assert stored is not None
    assert stored.config == {**_SECRET_CONFIG, "org": "b", "accounts": accounts}


def _wait_until(predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.01)
    return True


def _sync_awaits_io(monkeypatch) -> list[asyncio.AbstractEventLoop]:
    """Make the sync job await once before finishing, as a real connector's I/O would."""
    loops: list[asyncio.AbstractEventLoop] = []
    stub = ConnectorsHandler._run_sync

    async def _run_sync_after_io(self, sync_id: str, connector_id: str) -> None:
        loops.append(asyncio.get_running_loop())
        await asyncio.sleep(0.05)
        await stub(self, sync_id, connector_id)

    monkeypatch.setattr(ConnectorsHandler, "_run_sync", _run_sync_after_io)
    return loops


@contextmanager
def _server_main_loop(monkeypatch, running: bool) -> Iterator[asyncio.AbstractEventLoop | None]:
    if not running:
        yield None
        return
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(unified_server, "_main_event_loop", loop)
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


def _assert_two_syncs_finish(registry_cls, connector_id: str) -> None:
    """Each 202 job must reach its terminal state after its request's event loop is gone."""
    for _ in range(2):
        status, started = _dispatch(registry_cls, "POST", f"/api/v1/connectors/{connector_id}/sync")
        assert status == 202, started
        job = connectors_module._sync_jobs[started["sync_id"]]
        assert _wait_until(lambda: job["status"] != "running"), job
        assert job["status"] == "failed", job
        assert job["error_message"].startswith("Real connector sync required"), job
        assert connectors_module._connectors[connector_id]["status"] == "error"


@pytest.mark.parametrize("job", ["stub", "awaits-io"])
@pytest.mark.parametrize("server_loop", [False, True], ids=["no-server-loop", "server-loop"])
def test_sync_job_finishes_after_the_request_loop_is_gone(
    registry_cls, open_sqlite_store, monkeypatch, job: str, server_loop: bool
) -> None:
    # SQLite only: with no PostgreSQL pool each request runs on its own short-lived loop.
    assert get_pool_event_loop() is None
    open_sqlite_store()
    loops = _sync_awaits_io(monkeypatch) if job == "awaits-io" else []
    status, created = _dispatch(
        registry_cls, "POST", "/api/v1/connectors", {"type": "github", "name": "Repo"}
    )
    assert status == 201, created

    with _server_main_loop(monkeypatch, server_loop) as main_loop:
        _assert_two_syncs_finish(registry_cls, created["id"])
    if main_loop is not None and job == "awaits-io":
        assert loops == [main_loop, main_loop]


@pytest.mark.parametrize("job", ["stub", "awaits-io"])
def test_stored_connector_syncs_after_a_restart(
    registry_cls, open_sqlite_store, monkeypatch, job: str
) -> None:
    store = open_sqlite_store()
    asyncio.run(store.save_connector("stored-1", "github", "Stored", {"org": "a"}))
    open_sqlite_store()
    assert connectors_module._connectors == {}
    assert (connectors_module._sync_jobs, connectors_module._sync_history) == ({}, [])
    if job == "awaits-io":
        _sync_awaits_io(monkeypatch)

    _assert_two_syncs_finish(registry_cls, "stored-1")


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


@pytest.fixture
def auth_on(monkeypatch) -> None:
    monkeypatch.setattr(auth_config, "enabled", True)
    monkeypatch.setattr(auth_config, "api_token", "dispatch-test-api-token")


_PLATFORM_LIST = "/api/v1/analytics/platforms"
# RBAC v2 grants analytics.read to owner, admin, member and analyst, not to viewer.
_PLATFORM_LIST_CELLS = {
    "owner": 200,
    "admin": 200,
    "member": 200,
    "analyst": 200,
    "viewer": 403,
    "anon": 401,
}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("server_checks", [False, True], ids=["handler", "server"])
def test_platform_list_requires_analytics_read(
    registry_cls, auth_on, server_checks: bool, caller: str
) -> None:
    analytics_module._platform_credentials["metabase"] = {"connected_at": "2026-10-01T00:00:00Z"}
    # The server skips its own RBAC and auth checks for this GET, so the handler's
    # check is the only one that can refuse the caller.
    assert _ServerChecks()._is_path_exempt_for_get(_PLATFORM_LIST)
    dispatcher = _ServerChecks if server_checks else registry_cls
    status, body = _dispatch(dispatcher, "GET", _PLATFORM_LIST, caller=caller)
    assert status == _PLATFORM_LIST_CELLS[caller], (caller, body)
    if status == 200:
        assert body["connected_count"] == 1, body
    else:
        assert "platforms" not in body, body


def test_workspace_usage_answers_501_not_implemented(registry_cls) -> None:
    status, body = _dispatch(registry_cls, "GET", "/api/v1/analytics/workspace/ws-1/usage")
    assert status == 501, body
    assert body["error"]["code"] == "not_implemented"


def test_invalid_json_body_is_a_client_error(registry_cls) -> None:
    status, body = _dispatch(registry_cls, "POST", "/api/v1/connectors", raw_body=b"{not json")
    assert status == 400, body


# RBAC v2 grants connectors.read, connectors.create and connectors.configure to owner
# and admin only; the server's route rules and both handlers' own checks agree.
_OWNER_ADMIN_CELLS = {
    "owner": 200,
    "admin": 200,
    "member": 403,
    "analyst": 403,
    "viewer": 403,
    "anon": 401,
}
_READ_PATHS = {
    "list": "/api/v1/connectors",
    "detail": "/api/v1/connectors/c1",
    "summary": "/api/v1/connectors/summary",
}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("server_checks", [False, True], ids=["handler", "server"])
@pytest.mark.parametrize("route", sorted(_READ_PATHS))
def test_list_and_detail_stay_configured_connectors_and_summary_is_the_runtime_registry(
    registry_cls, auth_on, route: str, server_checks: bool, caller: str
) -> None:
    connectors_module._connectors["c1"] = {
        "id": "c1",
        "type": "github",
        "name": "C1",
        "status": "configured",
        "config": {},
    }
    dispatcher = _ServerChecks if server_checks else registry_cls
    status, body = _dispatch(dispatcher, "GET", _READ_PATHS[route], caller=caller)
    assert status == _OWNER_ADMIN_CELLS[caller], (route, caller, body)
    if status != 200:
        return
    if route == "list":
        assert [c["id"] for c in body["connectors"]] == ["c1"], body
    elif route == "detail":
        assert (body["id"], body["name"]) == ("c1", "C1"), body
    else:
        assert body == _FakeConnectorRegistry().get_summary()


_MASKED_CREATE_CELLS = {**_OWNER_ADMIN_CELLS, "owner": 400, "admin": 400}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("server_checks", [False, True], ids=["handler", "server"])
def test_create_with_a_masked_config_value_is_refused_for_every_caller(
    registry_cls, auth_on, memory_store, server_checks: bool, caller: str
) -> None:
    dispatcher = _ServerChecks if server_checks else registry_cls
    status, body = _dispatch(
        dispatcher,
        "POST",
        "/api/v1/connectors",
        {"type": "github", "name": "Repo", "config": {"org": "a", "api_key": _MASK}},
        caller=caller,
    )
    assert status == _MASKED_CREATE_CELLS[caller], (caller, body)
    assert (connectors_module._connectors, memory_store.rows) == ({}, {})


@pytest.mark.parametrize(
    "config",
    [
        pytest.param({"org": "a", "api_key": _MASK}, id="secret-key"),
        pytest.param({"auth": {"user": "u", "client_secret": _MASK}}, id="nested"),
        pytest.param({"accounts": [{"name": "n", "token": _MASK}]}, id="in-a-list"),
        pytest.param({"org": _MASK}, id="plain-key"),
        pytest.param(_MASK, id="whole-config"),
    ],
)
def test_create_refuses_the_mask_anywhere_in_the_config(
    registry_cls, memory_store, config: Any
) -> None:
    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/connectors", {"type": "github", "config": config}
    )
    assert status == 400, body
    assert _MASK in body["error"], body
    assert (connectors_module._connectors, memory_store.rows) == ({}, {})


_MALFORMED_UPDATE_CELLS = {**_OWNER_ADMIN_CELLS, "owner": 400, "admin": 400}


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("server_checks", [False, True], ids=["handler", "server"])
@pytest.mark.parametrize("method", ["PATCH", "PUT"])
def test_malformed_json_update_is_a_client_error_and_changes_nothing(
    registry_cls, auth_on, memory_store, method: str, server_checks: bool, caller: str
) -> None:
    asyncio.run(memory_store.save_connector("stored-1", "github", "Stored", {"org": "a"}))
    dispatcher = _ServerChecks if server_checks else registry_cls
    status, body = _dispatch(
        dispatcher,
        method,
        "/api/v1/connectors/stored-1",
        caller=caller,
        raw_body=b'{"name": "Renamed", "config": {"org": "b"}',
    )
    assert status == _MALFORMED_UPDATE_CELLS[caller], (caller, body)
    if status == 400:
        assert body == {"error": "Invalid JSON body"}
    stored = memory_store.rows["stored-1"]
    assert (stored.name, stored.config) == ("Stored", {"org": "a"})
    in_memory = connectors_module._connectors.get("stored-1")
    assert in_memory is None or (in_memory["name"], in_memory["config"]) == ("Stored", {"org": "a"})
