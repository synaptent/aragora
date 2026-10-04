"""Debate creation requires an authenticated user with an org (inventory D0).

Every request goes through the legacy server's POST dispatch
(``UnifiedHandler._do_POST_internal``: RBAC middleware, then a route index
built by the production handler-registry init, then
``DebatesHandler.handle_post``) with real JWTs. A refused request must leave
no trace: the body is never read, agents are not auto-selected, the controller
never starts a debate, no batch is queued and no debate row is written.
"""

from __future__ import annotations

import http.client
import io
import json
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aragora.server.debate_controller import DebateController
from aragora.server.handlers.debates.handler import DebatesHandler
from aragora.storage.debate_storage import DebateStorage

pytestmark = pytest.mark.no_auto_auth

ORG_A = "org-a-create-auth"
ORG_B = "org-b-create-auth"
STATIC_TOKEN = "create-auth-static-token-0123456789abcdef"
AUTH_REQUIRED_BODY = {"error": "Authentication required", "code": "auth_required"}

# Every POST path that reaches a debate create method. Any /api/v<N>/ prefix
# is stripped before dispatch, so v2 stands in for all other versions.
CREATE_ALIASES: dict[str, str] = {
    "/api/v1/debates": "_create_debate",
    "/api/v1/debate": "_create_debate",
    "/api/debates": "_create_debate",
    "/api/debate": "_create_debate",
    "/api/v2/debates": "_create_debate",
    "/api/v2/debate": "_create_debate",
    "/api/v1/debate-this": "_debate_this",
    "/api/debate-this": "_debate_this",
    "/api/v2/debate-this": "_debate_this",
    "/api/v1/debates/batch": "_submit_batch",
    "/api/v1/debates/batch/": "_submit_batch",
    "/api/debates/batch": "_submit_batch",
    "/api/debates/batch/": "_submit_batch",
    "/api/v2/debates/batch": "_submit_batch",
    "/api/v2/debates/batch/": "_submit_batch",
}
PRIMARY_ROUTES = [
    "/api/v1/debates",
    "/api/v1/debate",
    "/api/v1/debate-this",
    "/api/v1/debates/batch",
]
SPOOF_HEADERS = {"X-Org-Id": ORG_B, "X-Organization-Id": ORG_B, "X-Workspace-ID": ORG_B}


def _body_for(path: str) -> dict[str, Any]:
    """A valid request body that also tries to claim ORG_B as the owner."""
    spoof = {"organization_id": ORG_B, "org_id": ORG_B}
    if CREATE_ALIASES[path] == "_submit_batch":
        item = {"question": "Batch: adopt a four-day week?", "agents": "demo,demo", "rounds": 1}
        return {"items": [{**item, "org_id": ORG_B, "metadata": spoof}]}
    if CREATE_ALIASES[path] == "_debate_this":
        return {"question": "Should we adopt a four-day week?", "metadata": spoof}
    return {
        "question": "Should we adopt a four-day week?",
        "agents": ["demo", "demo"],
        "rounds": 1,
        "org_id": ORG_B,
        "metadata": spoof,
    }


# ---------------------------------------------------------------------------
# Identity and server fixtures
# ---------------------------------------------------------------------------


def _install_api_token(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    from aragora.server import auth as server_auth

    if value is None:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_API_TOKEN", value)
    config = server_auth.AuthConfig()
    config.configure_from_env()
    monkeypatch.setattr(server_auth, "auth_config", config, raising=False)


@pytest.fixture(autouse=True)
def _isolated_auth(monkeypatch):
    """Real JWTs, the stock (unset) API token, a fresh RBAC checker, open limits."""
    import aragora.billing.auth.config as jwt_config
    import aragora.storage.token_blacklist_store as blacklist_store
    from aragora.rbac.checker import PermissionChecker
    from aragora.server.middleware.rate_limit import decorators as rl_decorators
    from aragora.server.middleware.rate_limit.limiter import RateLimitResult
    from aragora.server.middleware.rate_limit.registry import reset_rate_limiters

    for name in ("ARAGORA_ENV", "ARAGORA_ENVIRONMENT", "ARAGORA_SECRETS_STRICT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")
    monkeypatch.setenv("ARAGORA_JWT_SECRET", "debate-create-auth-secret-" + "s" * 32)
    monkeypatch.setattr(jwt_config, "_jwt_secret_cache", None)
    monkeypatch.setattr(jwt_config, "_jwt_secret_previous_cache", None)
    monkeypatch.setattr(blacklist_store, "_blacklist_backend", blacklist_store.InMemoryBlacklist())
    _install_api_token(monkeypatch, None)

    checker = PermissionChecker(enable_cache=False)
    monkeypatch.setattr("aragora.rbac.decorators.get_permission_checker", lambda: checker)
    monkeypatch.setattr(
        rl_decorators,
        "check_user_rate_limit",
        lambda *a, **k: RateLimitResult(allowed=True, remaining=99, limit=100, key="test"),
    )
    reset_rate_limiters()
    from aragora.server.state import get_state_manager

    state = get_state_manager()
    before = set(state.get_active_debates())
    yield checker
    reset_rate_limiters()
    for debate_id in set(state.get_active_debates()) - before:
        state.unregister_debate(debate_id)


def _jwt(org_id: str | None, role: str = "member", user_id: str = "user-a") -> str:
    from aragora.billing.auth.tokens import create_access_token

    token = create_access_token(user_id, f"{user_id}@example.test", org_id, role)
    return f"Bearer {token}"


@pytest.fixture(scope="module")
def server():
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
        "_DispatchServer",
        (UnifiedHandler,),
        {"_handlers_initialized": False, "_init_lock": threading.Lock(), **resources},
    )
    with patch("aragora.server.handler_registry.get_route_index", return_value=index):
        server_cls._init_handlers()
    return SimpleNamespace(cls=server_cls, index=index)


@pytest.fixture
def storage(tmp_path) -> DebateStorage:
    return DebateStorage(str(tmp_path / "debates.db"))


class _InlineExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return Mock()


@pytest.fixture
def probes(storage):
    """A real controller on a temp store plus spies for every create side effect."""
    result = Mock(
        final_answer="Pilot it",
        consensus_reached=True,
        confidence=0.8,
        grounded_verdict=None,
        status="consensus_reached",
        agent_failures={},
        participants=["demo_1", "demo_2"],
        messages=[],
        explanation=None,
        total_cost_usd=0.0,
        per_agent_cost={},
        plan=None,
    )

    async def _run():
        return result

    factory = Mock()
    factory.create_arena.return_value = MagicMock(run=_run)
    auto_select = Mock(return_value="demo,demo")
    controller = DebateController(
        factory=factory, emitter=Mock(), storage=storage, auto_select_fn=auto_select
    )
    controller._preflight_agents = Mock(return_value=None)  # type: ignore[method-assign]
    controller._get_executor = Mock(return_value=_InlineExecutor())  # type: ignore[method-assign]
    controller._emit_leaderboard_update = Mock()  # type: ignore[method-assign]
    controller._generate_debate_receipt = Mock()  # type: ignore[method-assign]
    controller._quick_classify = Mock()  # type: ignore[method-assign]
    start = Mock(wraps=controller.start_debate)
    controller.start_debate = start  # type: ignore[method-assign]

    queue = MagicMock(debate_executor=MagicMock())
    queue.submit_batch = AsyncMock(return_value="batch_create_auth")
    get_queue = AsyncMock(return_value=queue)
    spam = MagicMock(enabled=False, _initialized=True)
    read_body = Mock(wraps=DebatesHandler.read_json_body)

    def _read_json_body(self, handler, max_size=None):
        return read_body(self, handler, max_size)

    with (
        patch("aragora.server.debate_queue.get_debate_queue", get_queue),
        patch("aragora.moderation.get_spam_moderation", return_value=spam),
        patch.object(DebatesHandler, "read_json_body", _read_json_body),
        patch.object(DebatesHandler, "_check_spam_content", return_value=None),
    ):
        yield SimpleNamespace(
            controller=controller,
            start=start,
            auto_select=auto_select,
            factory=factory,
            get_queue=get_queue,
            queue=queue,
            read_body=read_body,
            storage=storage,
        )


def _post(
    server: SimpleNamespace,
    probes: SimpleNamespace,
    path: str,
    body: dict[str, Any],
    authorization: str | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Send one POST through UnifiedHandler._do_POST_internal; return (status, body)."""
    raw = json.dumps(body).encode()
    request_cls = type(
        "_Request",
        (server.cls,),
        {"_debate_controller": probes.controller, "stream_emitter": MagicMock()},
    )
    request = request_cls.__new__(request_cls)
    request.command = "POST"
    request.path = path
    request.request_version = "HTTP/1.1"
    request.headers = http.client.HTTPMessage()
    request.headers["Content-Type"] = "application/json"
    request.headers["Content-Length"] = str(len(raw))
    request.headers["Host"] = "localhost"
    for name, value in (headers or {}).items():
        request.headers[name] = value
    if authorization is not None:
        request.headers["Authorization"] = authorization
    request.rfile = io.BytesIO(raw)
    request.wfile = io.BytesIO()
    request.client_address = ("127.0.0.1", 50123)
    for name in ("send_response", "send_header", "end_headers"):
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
        request._do_POST_internal(path)

    assert request.send_response.call_args is not None, f"no response for POST {path}"
    status = request.send_response.call_args.args[0]
    payload = request.wfile.getvalue()
    return status, json.loads(payload) if payload else {}


def _debate_rows(storage: DebateStorage) -> list[tuple[Any, ...]]:
    with storage.connection() as conn:
        return [tuple(r) for r in conn.execute("SELECT id, org_id, is_public FROM debates")]


def _assert_no_side_effect(probes: SimpleNamespace) -> None:
    assert probes.read_body.call_count == 0, "request body was read"
    probes.auto_select.assert_not_called()
    probes.start.assert_not_called()
    probes.factory.create_arena.assert_not_called()
    probes.get_queue.assert_not_called()
    probes.queue.submit_batch.assert_not_called()
    assert _debate_rows(probes.storage) == []


# ---------------------------------------------------------------------------
# Route inventory
# ---------------------------------------------------------------------------


class TestCreateAliases:
    @pytest.mark.parametrize("path", sorted(CREATE_ALIASES))
    def test_alias_resolves_to_debates_handler_in_full_registry(self, server, path):
        match = server.index.get_handler(path)

        assert match is not None
        assert match[0] == "_debates_handler"

    @pytest.mark.parametrize("path", sorted(CREATE_ALIASES))
    def test_alias_reaches_its_create_method(self, server, probes, path):
        reached: list[str] = []

        def _spy(name):
            def _method(self, handler):
                reached.append(name)
                from aragora.server.handlers.base import json_response

                return json_response({"reached": name}, status=299)

            return _method

        with (
            patch.object(DebatesHandler, "_create_debate", _spy("_create_debate")),
            patch.object(DebatesHandler, "_debate_this", _spy("_debate_this")),
            patch.object(DebatesHandler, "_submit_batch", _spy("_submit_batch")),
        ):
            status, _ = _post(server, probes, path, _body_for(path))

        assert (status, reached) == (299, [CREATE_ALIASES[path]])


# ---------------------------------------------------------------------------
# Refused callers (VAL-DEB-029 / VAL-DEB-030)
# ---------------------------------------------------------------------------


class TestRefusedCallers:
    @pytest.mark.parametrize("path", sorted(CREATE_ALIASES))
    def test_anonymous_gets_401_and_nothing_happens(self, server, probes, path):
        status, body = _post(server, probes, path, _body_for(path))

        assert (status, body) == (401, AUTH_REQUIRED_BODY)
        _assert_no_side_effect(probes)

    @pytest.mark.parametrize("path", sorted(CREATE_ALIASES))
    def test_jwt_user_without_org_gets_403_org_required(self, server, probes, path):
        status, body = _post(
            server, probes, path, _body_for(path), _jwt(None), headers=SPOOF_HEADERS
        )

        assert status == 403
        assert body["code"] == "org_required"
        _assert_no_side_effect(probes)

    @pytest.mark.parametrize("path", PRIMARY_ROUTES)
    def test_invalid_bearer_gets_401(self, server, probes, path):
        status, body = _post(server, probes, path, _body_for(path), "Bearer not-a-real-token")

        assert (status, body) == (401, AUTH_REQUIRED_BODY)
        _assert_no_side_effect(probes)

    @pytest.mark.parametrize("path", PRIMARY_ROUTES)
    def test_viewer_role_is_still_refused_by_rbac(self, server, probes, path):
        status, _ = _post(server, probes, path, _body_for(path), _jwt(ORG_A, role="viewer"))

        assert status == 403
        _assert_no_side_effect(probes)

    def test_unknown_custom_role_gets_no_debate_permission(self, server, probes):
        path = "/api/v1/debates"
        status, _ = _post(server, probes, path, _body_for(path), _jwt(ORG_A, role="auditor-x"))

        assert status == 403
        _assert_no_side_effect(probes)

    def test_with_api_token_set_anonymous_and_static_token_are_refused(
        self, server, probes, monkeypatch
    ):
        """With ARAGORA_API_TOKEN set the RBAC middleware answers before any handler.

        A static-token-only request has no user, so the middleware's own
        ``auth_required`` 401 is what reaches the caller (not ``org_required``);
        either way nothing is created.
        """
        _install_api_token(monkeypatch, STATIC_TOKEN)
        for path in PRIMARY_ROUTES:
            for authorization in (None, f"Bearer {STATIC_TOKEN}"):
                status, body = _post(server, probes, path, _body_for(path), authorization)
                assert (status, body) == (401, AUTH_REQUIRED_BODY), (path, authorization)
        _assert_no_side_effect(probes)

    def test_with_api_token_set_org_less_jwt_gets_403_org_required(
        self, server, probes, monkeypatch
    ):
        _install_api_token(monkeypatch, STATIC_TOKEN)
        path = "/api/v1/debates"

        status, body = _post(server, probes, path, _body_for(path), _jwt(None))

        assert status == 403
        assert body["code"] == "org_required"
        _assert_no_side_effect(probes)


# ---------------------------------------------------------------------------
# Accepted callers keep working, with the org from the token only
# ---------------------------------------------------------------------------


class TestOrgUserCreates:
    @pytest.mark.parametrize("role", ["member", "admin", "owner"])
    @pytest.mark.parametrize("path", ["/api/v1/debates", "/api/v1/debate", "/api/debates"])
    def test_create_stores_token_org_private_with_explicit_agents(self, server, probes, path, role):
        status, body = _post(
            server, probes, path, _body_for(path), _jwt(ORG_A, role=role), headers=SPOOF_HEADERS
        )

        assert status == 200, body
        request = probes.start.call_args.args[0]
        assert request.org_id == ORG_A
        assert request.agents_str == ["demo", "demo"]
        probes.auto_select.assert_not_called()
        assert _debate_rows(probes.storage) == [(body["debate_id"], ORG_A, 0)]

    @pytest.mark.parametrize("path", ["/api/v1/debate-this", "/api/debate-this"])
    def test_debate_this_stores_token_org_private(self, server, probes, path):
        status, body = _post(
            server, probes, path, _body_for(path), _jwt(ORG_A), headers=SPOOF_HEADERS
        )

        assert status == 200, body
        probes.auto_select.assert_called_once()
        assert _debate_rows(probes.storage) == [(body["debate_id"], ORG_A, 0)]

    @pytest.mark.parametrize("path", ["/api/v1/debates/batch", "/api/debates/batch/"])
    def test_batch_items_carry_token_org(self, server, probes, path):
        status, body = _post(
            server, probes, path, _body_for(path), _jwt(ORG_A), headers=SPOOF_HEADERS
        )

        assert status == 200, body
        batch = probes.queue.submit_batch.call_args.args[0]
        assert [item.org_id for item in batch.items] == [ORG_A]

    def test_custom_role_granted_debate_create_succeeds(self, server, probes, _isolated_auth):
        _isolated_auth._custom_roles[f"{ORG_A}:debate-runner"] = {"permissions": {"debates.create"}}
        path = "/api/v1/debates"

        status, body = _post(server, probes, path, _body_for(path), _jwt(ORG_A, "debate-runner"))

        assert status == 200, body
        assert _debate_rows(probes.storage) == [(body["debate_id"], ORG_A, 0)]
