"""Live-dispatch tests for the email snooze, Teams list and conflict-resolve routes.

The requests go through the real ``_try_modular_handler`` over the route index built
from the full HANDLER_REGISTRY by ``_init_handlers``. Every authenticated caller
carries a real HS256 access token, so handlers see the ``UserAuthContext`` that
``extract_user_from_request`` builds (a role, no permission lists).
"""

from __future__ import annotations

import io
import itertools
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.bots.teams.handler import TeamsHandler
from aragora.server.handlers.email.email_services import EmailServicesHandler
from aragora.server.handlers.evolution.cross_pollination import CrossPollinationStatsHandler

pytestmark = pytest.mark.no_auto_auth

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


_client_ips = itertools.count(1)


@pytest.fixture(scope="module")
def registry_cls() -> type[_RegistryMixin]:
    _RegistryMixin._init_handlers()
    assert _RegistryMixin._handlers_initialized is True
    return _RegistryMixin


def _dispatch(
    registry_cls: type[_RegistryMixin],
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    caller: str,
) -> tuple[int, Any]:
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    instance.command = method
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    if caller != "anon":
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


SNOOZE_SUGGESTIONS = "/api/v1/email/probe-email/snooze-suggestions"

ROUTES: dict[str, tuple[str, str, dict[str, Any] | None]] = {
    "emailServices.getSnoozeSuggestions": ("GET", SNOOZE_SUGGESTIONS, None),
    "teams.listTeams": ("GET", "/api/v1/teams", None),
    "crossPollination.resolveConflict": (
        "POST",
        "/api/v1/cross-pollination/conflicts/probe-conflict/resolve",
        {"resolution": "keep_a"},
    ),
}

# Email: the handler's own check denies every role but owner (403), and the email
# module functions answer 401 because the handler never passes them an auth context,
# so nobody gets suggestions yet. The handler's other routes answer the same way.
EXPECTED: dict[str, dict[str, int]] = {
    "emailServices.getSnoozeSuggestions": {
        "owner": 401,
        "admin": 403,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "teams.listTeams": {
        "owner": 501,
        "admin": 501,
        "member": 501,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    "crossPollination.resolveConflict": {
        "owner": 501,
        "admin": 501,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
}


@pytest.mark.parametrize(
    ("path", "owner_cls"),
    [
        (SNOOZE_SUGGESTIONS, EmailServicesHandler),
        ("/api/v1/teams", TeamsHandler),
    ],
)
def test_routes_resolve_to_the_handler_that_lists_them(
    registry_cls, path: str, owner_cls: type
) -> None:
    match = get_route_index().get_handler(path)
    assert match is not None
    assert type(match[1]) is owner_cls


def test_conflict_resolve_is_answered_by_the_cross_pollination_handler(registry_cls) -> None:
    # The route index has no entry for this path; the dispatcher's can_handle scan finds it.
    assert get_route_index().get_handler(ROUTES["crossPollination.resolveConflict"][1]) is None
    method, path, body = ROUTES["crossPollination.resolveConflict"]
    status, payload = _dispatch(registry_cls, method, path, body, caller="owner")
    assert status == 501, payload
    assert payload["error"]["message"] == (
        "Resolving cross-pollination conflicts is not implemented"
    )


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


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/email/followups/pending", None),
        ("GET", "/api/v1/email/snoozed", None),
        ("POST", "/api/v1/email/followups/mark", {"email_id": "e1", "thread_id": "t1"}),
    ],
)
def test_snooze_suggestions_answer_like_the_other_email_routes(
    registry_cls, method: str, path: str, body: dict[str, Any] | None, caller: str
) -> None:
    snooze_status, _ = _dispatch(registry_cls, "GET", SNOOZE_SUGGESTIONS, caller=caller)
    status, payload = _dispatch(registry_cls, method, path, body, caller=caller)
    assert status == snooze_status, (path, caller, payload)


@pytest.mark.parametrize("caller", ("owner", "member", "anon"))
def test_teams_list_answer_applies_to_get_only(registry_cls, caller: str) -> None:
    status, payload = _dispatch(registry_cls, "POST", "/api/v1/teams", {}, caller=caller)
    assert status != 501, payload


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/cross-pollination/conflicts",
        "/api/v1/cross-pollination/conflicts/probe-conflict",
        "/api/v1/cross-pollination/conflicts/a/b/resolve",
        "/api/v1/cross-pollination/conflicts/probe-conflict/resolve/extra",
        "/api/v1/cross-pollination/stats",
    ],
)
def test_only_the_resolve_path_gets_the_conflict_answer(path: str) -> None:
    handler = CrossPollinationStatsHandler({})
    assert handler.handle_post(path, {}, MagicMock()) is None
