"""Static-API-token-only requests on org-scoped routes get 403 org_required.

Requests go through the legacy server's real dispatch methods
(``UnifiedHandler._do_<METHOD>_internal``: RBAC check, MFA, rate limit and
budget gates). Handler dispatch is replaced by a spy, so a request that passes
every gate answers 299 ``{"reached": path}`` and a refused one never reaches it.

"Unchanged" cases compare each response with the one produced when the new
static-token branch is disabled, i.e. the previous behavior.
"""

from __future__ import annotations

import http.client
import io
import json
import threading
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.no_auto_auth

STATIC_TOKEN = "rbac-static-token-org-required-0123456789"
ORG_A = "org-a-static-token"
AUTH_REQUIRED_BODY = {"error": "Authentication required", "code": "auth_required"}
ORG_REQUIRED_BODY = {
    "error": "This resource belongs to an organization; sign in as a member of one",
    "code": "org_required",
}
REACHED = 299

# A1, B1, C1 plus other methods and families on org-scoped routes.
ORG_SCOPED_REQUESTS = [
    ("GET", "/api/v1/plans"),
    ("GET", "/api/v1/documents"),
    ("GET", "/api/v2/receipts"),
    ("GET", "/api/plans/plan-1"),
    ("POST", "/api/v1/plans"),
    ("PUT", "/api/v1/plans/plan-1/approve"),
    ("GET", "/api/v1/decisions/plans"),
    ("GET", "/api/runs"),
    ("DELETE", "/api/v1/documents/doc-1"),
    ("GET", "/api/v1/knowledge/jobs"),
    ("GET", "/api/v2/receipts/rcpt-1"),
    ("POST", "/api/v2/receipts/rcpt-1/share"),
    ("GET", "/api/v1/gauntlet/receipts"),
    ("GET", "/api/v1/debates"),
    ("GET", "/api/v1/debates/deb-1/messages"),
    ("PATCH", "/api/v1/debates/deb-1"),
    ("GET", "/api/v1/search"),
    ("POST", "/api/v1/graph-debates"),
    ("GET", "/api/v1/pipeline/transitions"),
    ("GET", "/api/v1/canvas/pipeline/p-1"),
    ("GET", "/api/v1/workspace/decisions"),
    ("GET", "/api/v1/checkpoints"),
    ("POST", "/api/v1/checkpoints/cp-1/resume"),
]
OUTSIDE_MATCHER_REQUESTS = [
    ("GET", "/api/v1/memory/stats"),
    ("GET", "/api/v1/workspaces"),
    ("POST", "/api/v1/canvas"),
    ("GET", "/api/v1/agents"),
    ("POST", "/api/v1/playground/debate"),
]
# Public-by-design rows and auth-exempt routes inside the matched families.
PUBLIC_REQUESTS = [
    ("GET", "/api/v1/debates/public/deb-1"),
    ("GET", "/api/v1/debates/deb-1/spectate/public"),
    ("GET", "/api/v2/receipts/share/tok-1"),
    ("GET", "/api/v2/receipts/signing-key"),
    ("POST", "/api/v2/receipts/verify"),
    ("GET", "/api/v1/gauntlet/personas"),
    ("GET", "/api/v1/pipeline/plans"),
]


def _install_api_token(monkeypatch: pytest.MonkeyPatch, value: str | None) -> Any:
    from aragora.server import auth as server_auth

    if value is None:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_API_TOKEN", value)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)
    return config


@pytest.fixture(autouse=True)
def auth_config(monkeypatch):
    """Real JWTs, ARAGORA_API_TOKEN set, a fresh RBAC checker, open limits."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.rbac.checker import PermissionChecker
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "rbac-static-token-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    checker = PermissionChecker(enable_cache=False)
    monkeypatch.setattr("aragora.rbac.decorators.get_permission_checker", lambda: checker)
    reset_rate_limiters()
    yield _install_api_token(monkeypatch, STATIC_TOKEN)
    reset_rate_limiters()


def _jwt(org_id: str | None, role: str = "member") -> str:
    from aragora.billing.auth.tokens import create_access_token

    return "Bearer " + create_access_token("user-a", "user-a@example.test", org_id, role)


def _request_class() -> type:
    from aragora.server.unified_server import UnifiedHandler

    resources = dict.fromkeys("storage user_store stream_emitter document_store".split())
    return type(
        "_GateProbe",
        (UnifiedHandler,),
        {"_handlers_initialized": True, "_init_lock": threading.Lock(), **resources},
    )


def _dispatch(
    method: str, path: str, authorization: str | None = None, *, legacy: bool = False
) -> tuple[int, dict[str, Any], list[str]]:
    """Run one request through ``_do_<METHOD>_internal``; return (status, body, reached)."""
    request_cls = _request_class()
    request = request_cls.__new__(request_cls)
    request.command = method
    request.path = path
    request.request_version = "HTTP/1.1"
    request.headers = http.client.HTTPMessage()
    request.headers["Host"] = "localhost"
    request.headers["Content-Type"] = "application/json"
    request.headers["Content-Length"] = "2"
    if authorization is not None:
        request.headers["Authorization"] = authorization
    request.rfile = io.BytesIO(b"{}")
    request.wfile = io.BytesIO()
    request.client_address = ("127.0.0.1", 50124)
    for name in ("send_response", "send_header", "end_headers", "send_error"):
        setattr(request, name, MagicMock())
    for name in ("_add_cors_headers", "_add_security_headers", "_add_trace_headers"):
        setattr(request, name, MagicMock())

    reached: list[str] = []

    def _handler_spy(handler_path: str, query: dict[str, Any]) -> bool:
        reached.append(handler_path)
        request._send_json({"reached": handler_path}, status=REACHED)
        return True

    request._try_modular_handler = _handler_spy
    previous = (
        patch("aragora.tenancy.record_scope.static_token_denial", return_value=None)
        if legacy
        else nullcontext()
    )
    with (
        previous,
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        if method == "GET":
            request._do_GET_internal(path, {})
        else:
            getattr(request, f"_do_{method}_internal")(path)

    assert request.send_response.call_args is not None, f"no response for {method} {path}"
    status = request.send_response.call_args.args[0]
    payload = request.wfile.getvalue()
    return status, json.loads(payload) if payload else {}, reached


def _ids(requests: list[tuple[str, str]]) -> list[str]:
    return [f"{method} {path}" for method, path in requests]


class TestStaticTokenOnOrgScopedRoutes:
    @pytest.mark.parametrize(("method", "path"), ORG_SCOPED_REQUESTS, ids=_ids(ORG_SCOPED_REQUESTS))
    def test_static_token_gets_403_org_required_before_any_handler(self, method, path):
        status, body, reached = _dispatch(method, path, f"Bearer {STATIC_TOKEN}")

        assert (status, body, reached) == (403, ORG_REQUIRED_BODY, [])

    @pytest.mark.parametrize(("method", "path"), ORG_SCOPED_REQUESTS, ids=_ids(ORG_SCOPED_REQUESTS))
    def test_it_was_401_auth_required_before(self, method, path):
        assert _dispatch(method, path, f"Bearer {STATIC_TOKEN}", legacy=True) == (
            401,
            AUTH_REQUIRED_BODY,
            [],
        )

    def test_token_signed_with_static_token_gets_403_org_required(self, auth_config):
        signed = auth_config.generate_token("loop-1", expires_in=600)

        status, body, reached = _dispatch("GET", "/api/v1/plans", f"Bearer {signed}")

        assert (status, body, reached) == (403, ORG_REQUIRED_BODY, [])

    @pytest.mark.parametrize(
        "authorization",
        [None, "Bearer not-the-token", STATIC_TOKEN, f"Basic {STATIC_TOKEN}"],
        ids=["none", "invalid", "no-bearer-scheme", "basic-scheme"],
    )
    @pytest.mark.parametrize(("method", "path"), ORG_SCOPED_REQUESTS, ids=_ids(ORG_SCOPED_REQUESTS))
    def test_missing_or_invalid_credential_still_gets_401(self, method, path, authorization):
        status, body, reached = _dispatch(method, path, authorization)

        assert (status, body, reached) == (401, AUTH_REQUIRED_BODY, [])


class TestUnchangedBehavior:
    @pytest.mark.parametrize("role", ["member", "owner"])
    @pytest.mark.parametrize("org_id", [ORG_A, None], ids=["with-org", "without-org"])
    @pytest.mark.parametrize(("method", "path"), ORG_SCOPED_REQUESTS, ids=_ids(ORG_SCOPED_REQUESTS))
    def test_jwt_users_get_exactly_the_previous_response(self, method, path, org_id, role):
        authorization = _jwt(org_id, role)

        current = _dispatch(method, path, authorization)

        assert current == _dispatch(method, path, authorization, legacy=True)
        assert current[1].get("code") != "org_required"

    @pytest.mark.parametrize("org_id", [ORG_A, None], ids=["with-org", "without-org"])
    def test_jwt_member_still_reaches_the_plans_handler(self, org_id):
        status, _, reached = _dispatch("GET", "/api/v1/plans", _jwt(org_id))

        assert (status, reached) == (REACHED, ["/api/v1/plans"])

    @pytest.mark.parametrize(
        "authorization", [None, f"Bearer {STATIC_TOKEN}"], ids=["anonymous", "static-token"]
    )
    @pytest.mark.parametrize(
        ("method", "path"),
        OUTSIDE_MATCHER_REQUESTS + PUBLIC_REQUESTS,
        ids=_ids(OUTSIDE_MATCHER_REQUESTS + PUBLIC_REQUESTS),
    )
    def test_paths_outside_the_matcher_and_public_paths_are_unchanged(
        self, method, path, authorization
    ):
        current = _dispatch(method, path, authorization)

        assert current == _dispatch(method, path, authorization, legacy=True)
        assert current[1].get("code") != "org_required"

    @pytest.mark.parametrize(
        ("method", "path"),
        [("GET", "/api/v2/receipts/signing-key"), ("GET", "/api/v1/debates/public/deb-1")],
    )
    def test_public_paths_still_reach_their_handler_with_the_static_token(self, method, path):
        status, _, reached = _dispatch(method, path, f"Bearer {STATIC_TOKEN}")

        assert (status, reached) == (REACHED, [path])

    def test_receipt_export_refuses_the_static_token_before_the_rate_limit(self):
        # The receipt export route rule admits unauthenticated requests, so
        # the static-token denial has to come before the route rules.
        from aragora.server.unified_server import UnifiedHandler

        path = "/api/v2/receipts/rcpt-1/export"
        with patch.object(UnifiedHandler, "_check_rate_limit") as rate_limit:
            assert _dispatch("GET", path, f"Bearer {STATIC_TOKEN}") == (403, ORG_REQUIRED_BODY, [])
        rate_limit.assert_not_called()
        assert _dispatch("GET", path)[::2] == (401, [])
        assert _dispatch("GET", path, _jwt(ORG_A))[::2] == (REACHED, [path])

    @pytest.mark.parametrize(
        "authorization", [None, f"Bearer {STATIC_TOKEN}"], ids=["anonymous", "static-token"]
    )
    @pytest.mark.parametrize(("method", "path"), ORG_SCOPED_REQUESTS, ids=_ids(ORG_SCOPED_REQUESTS))
    def test_without_api_token_configured_rbac_gate_is_open_as_before(
        self, monkeypatch, method, path, authorization
    ):
        _install_api_token(monkeypatch, None)

        status, _, reached = _dispatch(method, path, authorization)

        assert (status, reached) == (REACHED, [path])
