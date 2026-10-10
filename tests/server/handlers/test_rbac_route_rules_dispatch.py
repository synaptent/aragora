"""Route rules and denial answers for routes the RBAC middleware default-denied.

With auth on, the server runs the RBAC middleware (``_check_rbac``) before modular
dispatch and denies every route that has no rule. A handler's own
``@require_permission`` denial raises ``PermissionDeniedError``, which the
dispatcher must answer as a 403. These tests send callers with real JWTs through
the server's pre-dispatch checks and through the real ``_try_modular_handler``
over the full HANDLER_REGISTRY.
"""

from __future__ import annotations

import io
import itertools
import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.auth.mfa_enforcement import MFAEnforcementMiddleware, MFAStatus
from aragora.billing.jwt_auth import create_access_token
from aragora.connectors.runtime_registry import ConnectorStatus
from aragora.events import cross_subscribers
from aragora.knowledge import mound as knowledge_mound
from aragora.rbac.decorators import PermissionDeniedError
from aragora.rbac.middleware import DEFAULT_ROUTE_PERMISSIONS
from aragora.server import unified_server
from aragora.server.auth import auth_config
from aragora.server.auth_checks import AuthChecksMixin
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.connectors.management import ConnectorManagementHandler
from aragora.server.handlers.features import analytics_platforms as analytics_module
from aragora.server.handlers.features import connectors as connectors_module

CALLERS = ("owner", "admin", "member", "analyst", "viewer", "anon")
ROLES = CALLERS[:-1]

FORBIDDEN = {"error": "Permission denied", "code": "forbidden"}


class _Registry(HandlerRegistryMixin):
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


class _Server(AuthChecksMixin, _Registry):
    """The registry behind the server's pre-dispatch RBAC and auth checks."""


# _Registry's None-valued server attributes shadow UnifiedHandler's typed ones on purpose.
class _Live(_Registry, unified_server.UnifiedHandler):  # type: ignore[misc]
    """The registry behind the real server request path (``do_GET``/``do_POST``)."""


@pytest.fixture(scope="module")
def registry() -> type[_Registry]:
    _Registry._init_handlers()
    assert _Registry._handlers_initialized is True
    return _Registry


@pytest.fixture(autouse=True)
def _auth_on_and_isolated_state(monkeypatch):
    monkeypatch.setattr(auth_config, "enabled", True)
    monkeypatch.setattr(auth_config, "api_token", "route-rules-test-api-token")

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
    known = SimpleNamespace(
        connector_type="github",
        capabilities=["sync"],
        last_health_check="2026-09-30T00:00:00+00:00",
        metadata={"importable": True},
    )
    runtime = SimpleNamespace(
        get=lambda name: known if name == "known_conn" else None,
        health_check=lambda name: ConnectorStatus.HEALTHY,
        get_summary=lambda: {"total": 1},
    )
    monkeypatch.setattr(ConnectorManagementHandler, "_get_registry", lambda self: runtime)
    # Cross-pollination bodies read process-wide singletons; give them empty stand-ins.
    manager = SimpleNamespace(
        _subscribers={},
        _ranking_adapter=SimpleNamespace(get_stats=dict),
        _rlm_adapter=SimpleNamespace(get_stats=dict),
        get_stats=dict,
        get_batch_stats=dict,
    )
    monkeypatch.setattr(cross_subscribers, "get_cross_subscriber_manager", lambda: manager)
    monkeypatch.setattr(knowledge_mound, "get_knowledge_mound", lambda *a, **k: None)
    # Owner and admin callers are admins who have enabled MFA, so the server's separate
    # admin-MFA gate (on by default) admits them and the RBAC rules decide.
    monkeypatch.setattr(
        MFAEnforcementMiddleware,
        "_resolve_mfa_status",
        lambda self, user_id, user_context: MFAStatus(user_id=user_id, mfa_enabled=True),
    )


_client_ips = itertools.count(1)


def _request(cls: type[_Registry], method: str, path: str, caller: str, org: str = "org-1") -> Any:
    instance: Any = cls.__new__(cls)
    instance.path = path
    instance.command = method
    instance.headers = {"Content-Length": "0", "Content-Type": "application/json"}
    if caller != "anon":
        token = create_access_token(
            user_id=f"jwt-{caller}", email=f"{caller}@example.com", org_id=org, role=caller
        )
        instance.headers["Authorization"] = f"Bearer {token}"
    if not isinstance(instance, unified_server.UnifiedHandler):
        instance.rbac = unified_server.UnifiedHandler._get_rbac()
    instance.rfile = io.BytesIO(b"")
    instance.wfile = io.BytesIO()
    instance.send_response = MagicMock()
    instance.send_header = MagicMock()
    instance.end_headers = MagicMock()
    instance._add_cors_headers = MagicMock()
    instance._add_security_headers = MagicMock()
    instance._add_trace_headers = MagicMock()
    instance._send_json = MagicMock()
    instance._auth_context = None
    n = next(_client_ips)
    # A distinct client per request keeps the per-IP limiters out of the way.
    instance.client_address = (f"10.{(n >> 16) & 255}.{(n >> 8) & 255}.{n & 255}", 12345)
    return instance


def _no_revocation_db() -> Any:
    return patch("aragora.billing.auth.blacklist.is_token_revoked_persistent", return_value=False)


def _sent_json(instance: Any) -> tuple[int, Any]:
    sent = instance._send_json.call_args
    return sent.kwargs["status"], sent.args[0]


def _server_rbac(method: str, path: str, caller: str) -> tuple[int, dict[str, Any]] | None:
    """The server's pre-dispatch RBAC answer, or None when the request passes it."""
    instance = _request(_Server, method, path, caller)
    with _no_revocation_db():
        if instance._check_rbac(path, method):
            return None
    return _sent_json(instance)


def _dispatch(
    cls: type[_Registry], method: str, path: str, caller: str, org: str = "org-1"
) -> tuple[int, Any]:
    instance = _request(cls, method, path, caller, org)
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
        _no_revocation_db(),
    ):
        if cls is _Live:
            getattr(instance, f"do_{method}")()
            if instance._send_json.called:
                return _sent_json(instance)
        elif isinstance(instance, AuthChecksMixin):
            # UnifiedHandler's _do_<METHOD>_internal order; GET alone is rate limited.
            checks = [
                lambda: instance._check_rbac(path, method),
                lambda: instance._check_admin_mfa(path),
            ]
            if method == "GET":
                checks.append(instance._check_rate_limit)
            if not all(check() for check in checks):
                return _sent_json(instance)
        handled = cls is _Live or instance._try_modular_handler(path, {})
    assert handled is True, f"{method} {path} was not handled"
    status = instance.send_response.call_args[0][0]
    raw = instance.wfile.getvalue()
    try:
        return status, json.loads(raw or b"{}")
    except ValueError:  # the Prometheus metrics route answers text/plain
        return status, raw.decode()


_XP = "/api/v1/cross-pollination"
# Cross-pollination routes by what their handler does for a caller holding the key
# (``metrics`` is served too, under ``analytics.read``).
XP_SERVED_GETS = ("stats", "subscribers", "bridge", "km")
XP_UNIMPLEMENTED_GETS = (
    "conflicts",
    "federation",
    "federation/sync",
    "subscribe",
    "sync/status",
    "sync/trigger",
)
MEMORY_UNIMPLEMENTED_GETS = ("context", "cross-debate", "snapshots")

# (method, path) -> key of the first matching middleware rule. Each key is the one the
# route's handler checks (``connectors:configure`` and ``connectors.configure`` name the
# same permission). An empty key admits any signed-in caller.
RULES: dict[tuple[str, str], str] = {
    ("PATCH", "/api/v1/connectors/c1"): "connectors.configure",
    ("PUT", "/api/v1/connectors/c1"): "connectors.configure",
    ("POST", "/api/v1/connectors/c1/sync"): "connectors.configure",
    ("POST", "/api/v1/connectors/sync/s1/cancel"): "connectors.configure",
    ("POST", "/api/v1/connectors/c1/syncs/s1/cancel"): "connectors.configure",
    ("POST", "/api/v1/connectors/test"): "connectors.configure",
    ("GET", "/api/v1/connectors/c1"): "connectors.read",
    ("GET", "/api/v1/connectors/summary"): "connectors.read",
    ("GET", "/api/v1/connectors/stats"): "connectors.read",
    ("GET", "/api/v1/connectors/health"): "connectors.read",
    ("GET", "/api/v1/connectors/sync-history"): "connectors.read",
    ("GET", "/api/v1/connectors/c1/health"): "connectors.read",
    ("POST", "/api/v1/connectors/c1/test"): "connectors.test",
    ("GET", "/api/v1/connectors/types"): "",
    ("DELETE", "/api/v1/analytics/metabase"): "analytics.configure",
    ("GET", "/api/v1/documents/processing/stats"): "documents.read",
    ("GET", "/api/v1/teams"): "bots.read",
    ("POST", "/api/v1/cross-pollination/conflicts/c1/resolve"): "cross_pollination.write",
    ("GET", "/api/v1/batch"): "documents.read",
    ("GET", "/api/v1/batch/queue/status"): "documents.read",
    ("PUT", "/api/v1/memory/k1"): "memory.update",
    **{
        ("GET", f"{_XP}/{route}"): "cross_pollination.read"
        for route in (*XP_SERVED_GETS, *XP_UNIMPLEMENTED_GETS)
    },
    ("GET", f"{_XP}/metrics"): "analytics.read",
    # A create route behind a read key: no write key is registered and the answer is a 501.
    ("POST", "/api/v1/teams"): "bots.read",
    ("POST", "/api/v1/teams/debates/send"): "bots.read",
}

# Methods the routes' handlers do not serve: a rule would turn the default-deny 403 into a
# 500 handler_no_result for every key holder, so they stay without one until they are served.
# The cross-pollination writes act on process-wide state and ``km/culture`` cannot scope its
# workspace to the caller, so an organization-level key must not reach them.
UNSCOPED_XP: list[tuple[str, str]] = [
    ("POST", f"{_XP}/reset"),
    ("POST", f"{_XP}/km/sync"),
    ("POST", f"{_XP}/km/staleness-check"),
    ("GET", f"{_XP}/km/culture"),
]
UNSERVED: list[tuple[str, str]] = [
    ("POST", "/api/v1/batch"),
    ("POST", f"{_XP}/subscribe"),
    *UNSCOPED_XP,
]

# Roles whose RBAC v2 defaults hold each key (measured with the real checker).
HOLDERS: dict[str, set[str]] = {
    "": set(ROLES),
    "connectors.configure": {"owner", "admin"},
    "connectors.read": {"owner", "admin"},
    "connectors.test": {"owner", "admin"},
    "analytics.configure": {"owner", "admin"},
    "analytics.read": {"owner", "admin", "member", "analyst"},
    "documents.read": {"owner", "admin", "analyst"},
    "bots.read": {"owner", "admin", "member"},
    "memory.update": {"owner", "admin"},
    "cross_pollination.read": {"owner", "admin", "member", "analyst"},
    "cross_pollination.write": {"owner", "admin"},
}


def _first_rule(method: str, path: str) -> Any:
    return next((r for r in DEFAULT_ROUTE_PERMISSIONS if r.matches(path, method)[0]), None)


@pytest.mark.parametrize(("method", "path"), sorted(RULES))
def test_first_matching_rule_carries_the_handler_key(method: str, path: str) -> None:
    rule = _first_rule(method, path)
    assert rule is not None, f"no middleware rule matches {method} {path}"
    assert rule.permission_key == RULES[(method, path)], rule.pattern.pattern
    assert rule.allow_unauthenticated is False
    # The handlers check these keys without a resource ID; capturing one would let the
    # checker's ownership fallback admit a resource owner who lacks the key.
    assert rule.matches(path, method) == (True, None)


@pytest.mark.parametrize(("method", "path"), UNSERVED)
def test_unserved_routes_stay_default_denied(method: str, path: str) -> None:
    assert _first_rule(method, path) is None


def test_every_supported_analytics_platform_has_a_disconnect_rule() -> None:
    for platform in analytics_module.SUPPORTED_PLATFORMS:
        rule = _first_rule("DELETE", f"/api/v1/analytics/{platform}")
        assert rule is not None and rule.permission_key == "analytics.configure", platform


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/analytics/dashboards",
        "/api/v1/analytics/metabase/dashboards",
        "/api/analytics/summary",
    ],
)
def test_analytics_delete_outside_a_platform_stays_default_denied(path: str) -> None:
    assert _first_rule("DELETE", path) is None


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", ROLES)
def test_email_rules_and_grants_are_unchanged(caller: str) -> None:
    rule = _first_rule("GET", "/api/v1/email/snoozed")
    assert rule is not None and rule.permission_key == "email.read"
    answer = _server_rbac("GET", "/api/v1/email/snoozed", caller)
    assert (answer is None) == (caller == "owner"), answer


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize(("method", "path"), sorted(RULES))
def test_server_rbac_admits_exactly_the_key_holders(method: str, path: str, caller: str) -> None:
    key = RULES[(method, path)]
    answer = _server_rbac(method, path, caller)
    if caller == "anon":
        assert answer == (401, {"error": "Authentication required", "code": "auth_required"})
    elif caller in HOLDERS[key]:
        assert answer is None, answer
    else:
        assert answer is not None
        status, body = answer
        assert (status, body["required_permission"]) == (403, key), body


def _cells(spec: str) -> dict[str, int]:
    return dict(zip(CALLERS, (int(s) for s in spec.split()), strict=True))


# (method, path) -> (handler-layer answers, server answers) per caller. Owner and admin
# probe empty in-memory state, so a connector or platform they may touch is not found
# (404). A 501 is the answer of a served route that has no implementation, given after
# the handler's permission check.
DISPATCH: dict[tuple[str, str], tuple[str, str]] = {
    ("PATCH", "/api/v1/connectors/c1"): ("404 404 403 403 403 401",) * 2,
    ("PUT", "/api/v1/connectors/c1"): ("404 404 403 403 403 401",) * 2,
    ("POST", "/api/v1/connectors/c1/sync"): ("404 404 403 403 403 401",) * 2,
    ("POST", "/api/v1/connectors/sync/s1/cancel"): ("404 404 403 403 403 401",) * 2,
    ("POST", "/api/v1/connectors/c1/syncs/s1/cancel"): ("404 404 403 403 403 401",) * 2,
    ("POST", "/api/v1/connectors/test"): ("501 501 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/c1"): ("404 404 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/summary"): ("200 200 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/stats"): ("200 200 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/health"): ("200 200 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/sync-history"): ("200 200 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/known_conn/health"): ("200 200 403 403 403 401",) * 2,
    ("POST", "/api/v1/connectors/known_conn/test"): ("200 200 403 403 403 401",) * 2,
    ("GET", "/api/v1/connectors/types"): ("200 200 200 200 200 200", "200 200 200 200 200 401"),
    ("DELETE", "/api/v1/analytics/metabase"): ("404 404 403 403 403 401",) * 2,
    ("GET", "/api/v1/documents/processing/stats"): (
        "200 200 403 200 403 403",
        "200 200 403 200 403 401",
    ),
    ("GET", "/api/v1/teams"): ("501 501 501 403 403 401",) * 2,
    ("POST", f"{_XP}/conflicts/c1/resolve"): ("501 501 403 403 403 401",) * 2,
    ("GET", "/api/v1/batch"): ("501 501 403 501 403 403", "501 501 403 501 403 401"),
    ("GET", "/api/v1/batch/queue/status"): ("501 501 403 501 403 403", "501 501 403 501 403 401"),
    ("PUT", "/api/v1/memory/k1"): ("501 501 403 403 403 403", "501 501 403 403 403 401"),
    **{
        ("GET", f"/api/v1/memory/{route}"): ("501 501 501 501 403 403", "501 501 501 501 403 401")
        for route in MEMORY_UNIMPLEMENTED_GETS
    },
    **{
        ("GET", f"{_XP}/{route}"): ("200 200 200 200 403 403", "200 200 200 200 403 401")
        for route in (*XP_SERVED_GETS, "metrics")
    },
    **{
        ("GET", f"{_XP}/{route}"): ("501 501 501 501 403 403", "501 501 501 501 403 401")
        for route in XP_UNIMPLEMENTED_GETS
    },
    ("POST", "/api/v1/teams"): ("501 501 501 403 403 401",) * 2,
    ("POST", "/api/v1/teams/debates/send"): ("501 501 501 403 403 401",) * 2,
    # Continuum memory is not initialized here, so a caller holding memory.read gets 503.
    ("GET", "/api/v1/memory/tier-stats"): ("503 503 503 503 403 403", "503 503 503 503 403 401"),
    # The middleware's knowledge.read rule admits member; the handler's documents:read does not.
    ("GET", "/api/v1/knowledge/jobs"): ("200 200 403 200 403 403", "200 200 403 403 403 401"),
}


def _memory_handler() -> Any:
    route = get_route_index().get_handler("/api/v1/memory/tier-stats")
    assert route is not None
    return route[1]


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("layer", ["handler", "server", "live"])
@pytest.mark.parametrize(("method", "path"), sorted(DISPATCH))
def test_real_jwt_callers_get_the_same_rule_at_every_layer(
    registry, method: str, path: str, layer: str, caller: str
) -> None:
    handler_spec, server_spec = DISPATCH[(method, path)]
    expected = _cells(handler_spec if layer == "handler" else server_spec)[caller]
    cls = {"handler": registry, "server": _Server, "live": _Live}[layer]
    status, body = _dispatch(cls, method, path, caller)
    assert status == expected, (layer, caller, body)


NOT_IMPLEMENTED_ROUTES = [
    ("GET", "/api/v1/batch"),
    ("GET", "/api/v1/batch/queue/status"),
    ("PUT", "/api/v1/memory/k1"),
    *(("GET", f"/api/v1/memory/{route}") for route in MEMORY_UNIMPLEMENTED_GETS),
    *(("GET", f"{_XP}/{route}") for route in XP_UNIMPLEMENTED_GETS),
    ("POST", "/api/v1/teams"),
    ("POST", "/api/v1/teams/debates/send"),
]


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(("method", "path"), NOT_IMPLEMENTED_ROUTES)
def test_not_implemented_answers_keep_their_envelope_in_production(
    registry, monkeypatch, method: str, path: str
) -> None:
    monkeypatch.setenv("ARAGORA_ENV", "production")
    status, body = _dispatch(registry, method, path, "owner")
    assert (status, set(body), set(body["error"])) == (501, {"error"}, {"code", "message"})
    assert body["error"]["code"] == "not_implemented"
    assert body["error"]["message"].endswith("is not implemented"), body


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize(("method", "path"), UNSERVED)
def test_unserved_routes_are_denied_before_dispatch(
    registry, method: str, path: str, caller: str
) -> None:
    status, body = _dispatch(_Server, method, path, caller)
    expected = (401, "auth_required") if caller == "anon" else (403, "permission_denied")
    assert (status, body["code"]) == expected, body


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(("method", "path"), UNSCOPED_XP)
def test_unscoped_cross_pollination_routes_are_not_dispatched(
    registry, method: str, path: str
) -> None:
    found = get_route_index().get_handler(path)
    assert found is not None
    request = _request(registry, method, path, "owner")
    serve = found[1].handle_post if method == "POST" else found[1].handle
    assert serve(path, {}, request) is None


@pytest.mark.no_auto_auth
def test_memory_get_as_viewer_answers_403_not_500(registry) -> None:
    status, body = _dispatch(registry, "GET", "/api/v1/memory/tier-stats", "viewer")
    assert (status, body) == (403, FORBIDDEN)


# Each caller signs in to its own organization, which is the tenant its memory reads use.
MIXED_SEQUENCE = (
    ("viewer", "org-v"),
    ("owner", "org-o"),
    ("viewer", "org-v"),
    ("anon", "-"),
    ("member", "org-m"),
    ("owner", "org-o"),
)


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(("layer", "anon_status"), [("handler", 403), ("live", 401)])
def test_memory_handler_judges_and_scopes_each_request_by_its_own_caller(
    registry, monkeypatch, layer: str, anon_status: int
) -> None:
    tenants: list[str | None] = []

    def retrieve(**kwargs: Any) -> list[Any]:
        tenants.append(kwargs["tenant_id"])
        return []

    monkeypatch.setitem(
        _memory_handler().ctx, "continuum_memory", SimpleNamespace(retrieve=retrieve)
    )
    cls = {"handler": registry, "live": _Live}[layer]
    statuses = [
        _dispatch(cls, "GET", "/api/v1/memory/continuum/retrieve", caller, org)[0]
        for caller, org in MIXED_SEQUENCE
    ]
    assert statuses == [403, 200, 403, anon_status, 200, 200]
    assert tenants == ["org-o", "org-m", "org-o"]


@pytest.mark.no_auto_auth
@pytest.mark.parametrize("caller", ["member", "viewer", "anon"])
def test_documents_read_denial_answers_403_with_the_dispatcher_envelope(
    registry, caller: str
) -> None:
    status, body = _dispatch(registry, "GET", "/api/v1/documents/processing/stats", caller)
    assert (status, body) == (403, FORBIDDEN)


@pytest.mark.no_auto_auth
def test_member_denied_by_the_handler_behind_the_server_rule_gets_403(registry) -> None:
    status, body = _dispatch(_Server, "GET", "/api/v1/knowledge/jobs", "member")
    assert (status, body) == (403, FORBIDDEN)


@pytest.mark.no_auto_auth
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PermissionDeniedError("Resource policy denied access to m1"), (403, FORBIDDEN)),
        (
            PermissionDeniedError("Can only modify own data or requires admin role"),
            (403, FORBIDDEN),
        ),
        (RuntimeError("store unavailable"), (500, None)),
    ],
    ids=["resource-policy", "own-data", "runtime-error"],
)
def test_every_permission_denial_maps_to_403_and_other_errors_stay_500(
    registry, monkeypatch, error: Exception, expected: tuple[int, Any]
) -> None:
    def _raise(*args: Any, **kwargs: Any) -> None:
        raise error

    monkeypatch.setattr(_memory_handler(), "handle", _raise)
    status, body = _dispatch(registry, "GET", "/api/v1/memory/tier-stats", "owner")
    assert status == expected[0], body
    if expected[1] is not None:
        assert body == expected[1]
    else:
        assert body["code"] == "handler_error"
