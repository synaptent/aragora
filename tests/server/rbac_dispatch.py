"""Send requests through ``UnifiedHandler._do_<METHOD>_internal`` for RBAC route tests.

That covers the RBAC route rules, the admin MFA gate and the rate limits, then
the handler resolved by a route index built by the production registry init.
"""

from __future__ import annotations

import http.client
import io
import itertools
import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

STATIC_TOKEN = "rbac-route-rules-static-token-0123456789"
AUTH_REQUIRED_BODY = {"error": "Authentication required", "code": "auth_required"}
ORG_REQUIRED_BODY = {
    "error": "This resource belongs to an organization; sign in as a member of one",
    "code": "org_required",
}

_client_ips = (f"10.77.{n // 250}.{n % 250 + 1}" for n in itertools.count())


class MFAEnrolledUsers:
    """User store in which every user has MFA enabled (owner/admin pass the MFA gate)."""

    def get_user_by_id(self, user_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=user_id, mfa_enabled=True)


def install_api_token(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    from aragora.server import auth as server_auth

    if value is None:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_API_TOKEN", value)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)


def isolate_auth(monkeypatch: pytest.MonkeyPatch, api_token: str | None = STATIC_TOKEN) -> Any:
    """Real JWTs, the given API token, a fresh uncached RBAC checker, reset limiters."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.rbac.checker import PermissionChecker
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "rbac-route-rules-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    install_api_token(monkeypatch, api_token)
    checker = PermissionChecker(enable_cache=False)
    monkeypatch.setattr("aragora.rbac.decorators.get_permission_checker", lambda: checker)
    reset_rate_limiters()
    return checker


def jwt(user_id: str, org_id: str | None, role: str) -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token(user_id, f"{user_id}@example.test", org_id, role)


def build_server() -> SimpleNamespace:
    """UnifiedHandler subclass initialised by the production registry init."""
    from aragora.server.handler_registry.core import RouteIndex
    from aragora.server.unified_server import UnifiedHandler

    index = RouteIndex()
    resources = dict.fromkeys(
        "storage stream_emitter control_plane_stream nomic_loop_stream elo_system "
        "nomic_state_file debate_embeddings critique_store document_store persona_manager "
        "position_ledger user_store continuum_memory cross_debate_memory knowledge_mound".split()
    )
    server_cls = type(
        "_RouteRuleServer",
        (UnifiedHandler,),
        {"_handlers_initialized": False, "_init_lock": threading.Lock(), **resources},
    )
    with patch("aragora.server.handler_registry.get_route_index", return_value=index):
        server_cls._init_handlers()
    return SimpleNamespace(cls=server_cls, index=index)


def handler_for(server: SimpleNamespace, path: str) -> Any:
    match = server.index.get_handler(path)
    assert match is not None, path
    return match[1]


def dispatch(
    server: SimpleNamespace,
    method: str,
    path: str,
    authorization: str | None = None,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    raw_body: bytes | None = None,
    content_type: str = "application/json",
    content_length: int | None = None,
) -> tuple[int, dict[str, Any]]:
    """Send one request through ``_do_<METHOD>_internal``; return (status, JSON body)."""
    status, _, payload = dispatch_raw(
        server,
        method,
        path,
        authorization,
        body=body,
        query=query,
        raw_body=raw_body,
        content_type=content_type,
        content_length=content_length,
    )
    return status, json.loads(payload) if payload else {}


def dispatch_raw(
    server: SimpleNamespace,
    method: str,
    path: str,
    authorization: str | None = None,
    *,
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    raw_body: bytes | None = None,
    content_type: str = "application/json",
    content_length: int | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """Like ``dispatch``, but return (status, response headers, raw body).

    ``raw_body`` replaces the JSON ``body`` (for multipart uploads), and
    ``content_length`` overrides the announced length.
    """
    raw = (
        raw_body if raw_body is not None else json.dumps(body if body is not None else {}).encode()
    )
    request_cls = type("_Request", (server.cls,), {"user_store": MFAEnrolledUsers()})
    request = request_cls.__new__(request_cls)
    request.command = method
    request.path = path
    request.request_version = "HTTP/1.1"
    request.headers = http.client.HTTPMessage()
    request.headers["Host"] = "localhost"
    request.headers["Content-Type"] = content_type
    request.headers["Content-Length"] = str(len(raw) if content_length is None else content_length)
    if authorization is not None:
        request.headers["Authorization"] = authorization
    request.rfile = io.BytesIO(raw)
    request.wfile = io.BytesIO()
    request.client_address = (next(_client_ips), 50125)
    for name in ("send_response", "send_header", "end_headers", "send_error"):
        setattr(request, name, MagicMock())
    for name in ("_add_cors_headers", "_add_security_headers", "_add_trace_headers"):
        setattr(request, name, MagicMock())

    with (
        patch("aragora.server.handler_registry.get_route_index", return_value=server.index),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        if method == "GET":
            request._do_GET_internal(path, {k: [v] for k, v in (query or {}).items()})
        else:
            getattr(request, f"_do_{method}_internal")(path)

    if request.send_response.call_args is None:
        assert request.send_error.call_args is not None, f"no response for {method} {path}"
        return request.send_error.call_args.args[0], {}, b""
    headers = {call.args[0]: call.args[1] for call in request.send_header.call_args_list}
    return request.send_response.call_args.args[0], headers, request.wfile.getvalue()
