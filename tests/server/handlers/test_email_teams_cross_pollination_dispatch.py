"""Live-dispatch tests for the email services, Teams list and conflict-resolve routes.

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
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.rbac import AuthorizationContext, get_role_permissions
from aragora.rbac.checker import get_permission_checker
from aragora.rbac.defaults.helpers import create_custom_role
from aragora.server.handler_registry import HandlerRegistryMixin, get_route_index
from aragora.server.handlers.bots.teams.handler import TeamsHandler
from aragora.server.handlers.email import email_services as email_module
from aragora.server.handlers.email.email_services import EmailServicesHandler
from aragora.server.handlers.evolution.cross_pollination import CrossPollinationStatsHandler
from aragora.server.unified_server import UnifiedHandler
from aragora.services.email_categorizer import EmailCategory
from aragora.services.followup_tracker import FollowUpTracker

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
    user: str | None = None,
    org: str = "org-1",
    query: dict[str, str] | None = None,
) -> tuple[int, Any]:
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    instance.command = method
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    if caller != "anon":
        token = create_access_token(
            user_id=user or f"jwt-{caller}", email=f"{caller}@example.com", org_id=org, role=caller
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
        handled = instance._try_modular_handler(path, {k: [v] for k, v in (query or {}).items()})
    assert handled is True, f"{method} {path} was not handled"
    status = instance.send_response.call_args[0][0]
    return status, json.loads(instance.wfile.getvalue() or b"{}")


SNOOZE_SUGGESTIONS = "/api/v1/email/probe-email/snooze-suggestions"

ROUTES: dict[str, tuple[str, str, dict[str, Any] | None]] = {
    "teams.listTeams": ("GET", "/api/v1/teams", None),
    "teams.createTeam": ("POST", "/api/v1/teams", {"name": "probe-team"}),
    "teams.sendDebate": ("POST", "/api/v1/teams/debates/send", {"debate_id": "d1"}),
    "crossPollination.resolveConflict": (
        "POST",
        "/api/v1/cross-pollination/conflicts/probe-conflict/resolve",
        {"resolution": "keep_a"},
    ),
    "email.categoryFeedback": (
        "POST",
        "/api/v1/email/categories/learn",
        {"email_id": "e1", "predicted_category": "newsletters", "correct_category": "projects"},
    ),
}

EXPECTED: dict[str, dict[str, int]] = {
    "email.categoryFeedback": {
        "owner": 501,
        "admin": 403,
        "member": 403,
        "analyst": 403,
        "viewer": 403,
        "anon": 401,
    },
    **{
        route_id: {
            "owner": 501,
            "admin": 501,
            "member": 501,
            "analyst": 403,
            "viewer": 403,
            "anon": 401,
        }
        for route_id in ("teams.listTeams", "teams.createTeam", "teams.sendDebate")
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


NOT_IMPLEMENTED = {
    "teams.listTeams": "Listing teams is not implemented",
    "teams.createTeam": "Creating teams is not implemented",
    "teams.sendDebate": "Sending debates to Teams is not implemented",
    "crossPollination.resolveConflict": "Resolving cross-pollination conflicts is not implemented",
}


@pytest.mark.parametrize("env", ["development", "production"])
@pytest.mark.parametrize("route_id", sorted(NOT_IMPLEMENTED))
def test_not_implemented_answers_keep_their_message_in_production(
    registry_cls, monkeypatch, caplog, route_id: str, env: str
) -> None:
    monkeypatch.setenv("ARAGORA_ENV", env)
    method, path, body = ROUTES[route_id]
    status, payload = _dispatch(registry_cls, method, path, body, caller="owner")
    error = {"code": "not_implemented", "message": NOT_IMPLEMENTED[route_id]}
    assert (status, payload, "Sanitized" in caplog.text) == (501, {"error": error}, False)


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


# Only owner holds email.*, so the handler's own check answers 403 to every other role.
# Owner's request reaches the module, which repeats the check on the forwarded context;
# the status after that is the module's own answer, so only "not 401/403" is pinned.
EMAIL_ROUTES: dict[str, tuple[str, str, dict[str, Any] | None]] = {
    "getCategories": ("GET", "/api/v1/email/categories", None),
    "getPendingFollowups": ("GET", "/api/v1/email/followups/pending", None),
    "getSnoozedEmails": ("GET", "/api/v1/email/snoozed", None),
    "getSnoozeSuggestions": ("GET", SNOOZE_SUGGESTIONS, None),
    "markFollowup": ("POST", "/api/v1/email/followups/mark", {"email_id": "e1", "thread_id": "t1"}),
    "checkReplies": ("POST", "/api/v1/email/followups/check-replies", {}),
    "autoDetectFollowups": ("POST", "/api/v1/email/followups/auto-detect", {}),
    "resolveFollowup": ("POST", "/api/v1/email/followups/probe-fu/resolve", {}),
    "applySnooze": (
        "POST",
        "/api/v1/email/probe-email/snooze",
        {"snooze_until": "2030-01-01T09:00:00"},
    ),
    "processDueSnoozes": ("POST", "/api/v1/email/snooze/process-due", {}),
    "categoryFeedback": (
        "POST",
        "/api/v1/email/categories/learn",
        {"email_id": "e1", "predicted_category": "a", "correct_category": "b"},
    ),
    "cancelSnooze": ("DELETE", "/api/v1/email/probe-email/snooze", None),
}


@pytest.mark.parametrize("caller", CALLERS)
@pytest.mark.parametrize("route_id", sorted(EMAIL_ROUTES))
def test_email_module_check_sees_the_callers_auth_context(
    registry_cls, route_id: str, caller: str
) -> None:
    method, path, body = EMAIL_ROUTES[route_id]
    real_check = email_module._check_email_permission
    seen: list[tuple[str | None, Any]] = []

    def recording_check(auth_context: Any, permission_key: str) -> Any:
        result = real_check(auth_context, permission_key)
        seen.append((getattr(auth_context, "user_id", None), result))
        return result

    with (
        patch.object(email_module, "_check_email_permission", recording_check),
        patch.dict(email_module._snoozed_emails, clear=True),
    ):
        status, payload = _dispatch(registry_cls, method, path, body, caller=caller)
    if caller == "owner":
        assert seen == [("jwt-owner", None)], (route_id, payload)
        assert status not in (401, 403), (route_id, payload)
    else:
        assert status == (401 if caller == "anon" else 403), (route_id, payload)
        assert seen == [], (route_id, payload)


# Owners of email state: only the built-in owner role holds email.*, so the second
# user and the other organization's user are owners too, with their own identity.
OWNER: dict[str, Any] = {"caller": "owner"}
SAME_ORG_USER: dict[str, Any] = {"caller": "owner", "user": "jwt-owner-2"}
OTHER_ORG_USER: dict[str, Any] = {"caller": "owner", "user": "jwt-owner-x", "org": "org-2"}
MARK = "/api/v1/email/followups/mark"
PENDING = "/api/v1/email/followups/pending"
CHECK_REPLIES = "/api/v1/email/followups/check-replies"
SNOOZE = "/api/v1/email/probe-email/snooze"
SNOOZED = "/api/v1/email/snoozed"
PROCESS_DUE = "/api/v1/email/snooze/process-due"
LEARN = "/api/v1/email/categories/learn"


def _data(payload: Any) -> Any:
    return payload.get("data", payload)


def _utc_z(**delta: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _StubMailbox:
    """Gmail stand-in: t-1 has a reply from bob; sent-1 (thread t-sent) has none."""

    def __init__(self) -> None:
        now = datetime.now()
        self.sent = {
            "sent-1": SimpleNamespace(
                thread_id="t-sent",
                to_addresses=["carol@example.com"],
                subject="Quote",
                date=now - timedelta(days=3),
            )
        }
        self.threads = {
            "t-sent": [
                SimpleNamespace(date=now - timedelta(days=3), from_address="me@example.com")
            ],
            "t-1": [
                SimpleNamespace(date=now - timedelta(days=5), from_address="me@example.com"),
                SimpleNamespace(
                    date=now - timedelta(hours=1), from_address="Bob <bob@example.com>"
                ),
            ],
        }

    async def list_messages(self, **_kwargs: Any) -> tuple[list[str], None]:
        return list(self.sent), None

    async def get_message(self, msg_id: str) -> Any:
        return self.sent[msg_id]

    async def get_thread(self, thread_id: str) -> Any:
        return SimpleNamespace(messages=self.threads.get(thread_id, []))


@pytest.fixture
def services(monkeypatch) -> FollowUpTracker:
    """Real email services with fresh state; the tracker reads the stub mailbox."""
    tracker = FollowUpTracker(gmail_connector=_StubMailbox())  # type: ignore[arg-type]
    for name, value in (
        ("_followup_tracker", tracker),
        ("_snooze_recommender", None),
        ("_email_categorizer", None),
        ("_snoozed_emails", {}),
        ("_followup_owners", {}),
    ):
        monkeypatch.setattr(email_module, name, value, raising=False)
    return tracker


def test_follow_up_routes_work_for_their_owner(registry_cls, services) -> None:
    mark = {"email_id": "e-1", "thread_id": "t-1", "recipient": "bob@example.com"}
    status, body = _dispatch(
        registry_cls,
        "POST",
        MARK,
        mark | {"sent_at": _utc_z(days=-5), "expected_reply_days": 1},
        **OWNER,
    )
    assert status == 200, body
    followup = _data(body)
    assert (followup["status"], followup["days_waiting"]) == ("awaiting", 5)
    status, body = _dispatch(registry_cls, "GET", PENDING, **OWNER)
    assert status == 200 and _data(body)["overdue_count"] == 1, body
    [item] = _data(body)["followups"]
    assert (item["followup_id"], item["status"], item["urgency_score"]) == (
        followup["followup_id"],
        "overdue",
        0.9,
    )
    status, body = _dispatch(
        registry_cls, "POST", "/api/v1/email/followups/auto-detect", {"days_back": "7"}, **OWNER
    )
    assert status == 200, body
    [detected] = _data(body)["detected"]
    assert detected["email_id"] == "sent-1"
    status, body = _dispatch(registry_cls, "POST", CHECK_REPLIES, {}, **OWNER)
    assert status == 200, body
    [reply] = _data(body)["replied"]
    assert reply["followup_id"] == followup["followup_id"] and reply["replied_at"]
    assert _data(body)["still_pending"] == 1
    resolve = f"/api/v1/email/followups/{detected['followup_id']}/resolve"
    before = services._followups[detected["followup_id"]].status
    assert _dispatch(registry_cls, "POST", resolve, {"status": "bogus"}, **OWNER)[0] == 400
    assert services._followups[detected["followup_id"]].status is before
    status, body = _dispatch(registry_cls, "POST", resolve, {"status": "no_longer_needed"}, **OWNER)
    assert status == 200 and _data(body)["status"] == "cancelled" and _data(body)["resolved_at"], (
        body
    )
    assert services._followups[detected["followup_id"]].status.value == "cancelled"
    assert _data(_dispatch(registry_cls, "GET", PENDING, **OWNER)[1])["followups"] == []


def test_snooze_routes_work_for_their_owner(registry_cls, services) -> None:
    query = {"priority": "0.9", "max_suggestions": "2"}
    status, body = _dispatch(registry_cls, "GET", SNOOZE_SUGGESTIONS, query=query, **OWNER)
    assert status == 200, body
    suggestions = _data(body)["suggestions"]
    assert 1 <= len(suggestions) <= 2 and all(s["source"] == s["reason"] for s in suggestions)
    for bad in (
        {"priority": "high"},
        {"priority": "7"},
        {"max_suggestions": "two"},
        {"max_suggestions": "0"},
    ):
        assert _dispatch(registry_cls, "GET", SNOOZE_SUGGESTIONS, query=bad, **OWNER)[0] == 400, bad
    assert (
        _dispatch(registry_cls, "POST", SNOOZE, {"snooze_until": _utc_z(minutes=-5)}, **OWNER)[0]
        == 200
    )
    status, body = _dispatch(registry_cls, "GET", SNOOZED, **OWNER)
    assert status == 200 and (_data(body)["total"], _data(body)["due_now"]) == (1, 1), body
    status, body = _dispatch(registry_cls, "POST", PROCESS_DUE, {}, **OWNER)
    assert (status, _data(body)["processed"]) == (200, ["probe-email"]), body
    assert (
        _dispatch(registry_cls, "POST", SNOOZE, {"snooze_until": _utc_z(days=30)}, **OWNER)[0]
        == 200
    )
    assert _dispatch(registry_cls, "DELETE", SNOOZE, **OWNER)[0] == 200
    assert email_module._snoozed_emails == {}


# field -> (method, path, other body fields or None for a query, highest accepted value)
BOUNDED = {
    "expected_reply_days": ("POST", MARK, {"email_id": "e-1", "thread_id": "t-1"}, 365),
    "days_back": ("POST", "/api/v1/email/followups/auto-detect", {}, 365),
    "max_suggestions": ("GET", SNOOZE_SUGGESTIONS, None, 100),
}


@pytest.mark.parametrize("field", sorted(BOUNDED))
def test_counts_above_their_ceiling_answer_400_not_500(registry_cls, services, field) -> None:
    method, path, body, highest = BOUNDED[field]
    statuses = [
        _dispatch(registry_cls, method, path, query={field: str(value)}, **OWNER)[0]
        if body is None
        else _dispatch(registry_cls, method, path, body | {field: value}, **OWNER)[0]
        for value in (highest, highest + 1, 10**8, 10**12)
    ]
    assert statuses == [200, 400, 400, 400]


# Each instant leaves datetime's range when shifted to UTC or, for the naive last day,
# when the default three-day reply window is added to it.
EXTREME_DATES = [
    (MARK, "sent_at", "9999-12-31T00:00:00", "sent_at is out of range"),
    (MARK, "sent_at", "9999-12-31T23:59:59-12:00", "sent_at is out of range"),
    (MARK, "sent_at", "0001-01-01T00:00:00+14:00", "sent_at is out of range"),
    (SNOOZE, "snooze_until", "9999-12-31T23:59:59-12:00", "Invalid snooze_until format"),
    (SNOOZE, "snooze_until", "0001-01-01T00:00:00+14:00", "Invalid snooze_until format"),
]


@pytest.mark.parametrize(("path", "field", "value", "message"), EXTREME_DATES)
def test_extreme_dates_answer_400_not_500(
    registry_cls, services, path: str, field: str, value: str, message: str
) -> None:
    body = {"email_id": "e-1", "thread_id": "t-1"} if path == MARK else {}
    status, payload = _dispatch(registry_cls, "POST", path, body | {field: value}, **OWNER)
    assert (status, message in json.dumps(payload)) == (400, True), payload
    assert services._followups == {} and email_module._snoozed_emails == {}


@pytest.mark.parametrize("env", ["development", "production"])
def test_category_feedback_is_not_implemented_and_learns_nothing(
    registry_cls, services, monkeypatch, env
) -> None:
    monkeypatch.setenv("ARAGORA_ENV", env)
    status, body = _dispatch(registry_cls, "GET", "/api/v1/email/categories", **OWNER)
    assert status == 200 and {c["id"] for c in _data(body)["categories"]} == {
        c.value for c in EmailCategory
    }
    for learn in ({}, {"email_id": "e-9", "predicted_category": "x", "correct_category": "y"}):
        status, body = _dispatch(registry_cls, "POST", LEARN, learn, **OWNER)
        assert status == 501, body
        assert (body["error"]["code"], body["error"]["message"]) == (
            "not_implemented",
            "Learning from category feedback is not implemented",
        )
    assert email_module._email_categorizer is None


@pytest.mark.parametrize(
    "intruder", [SAME_ORG_USER, OTHER_ORG_USER], ids=["same-org-user", "other-org"]
)
def test_other_users_cannot_read_or_change_the_owners_email_state(
    registry_cls, services, intruder
) -> None:
    def snooze(who: dict[str, Any], label: str, **delta: float) -> int:
        body = {"snooze_until": _utc_z(**delta), "label": label}
        return _dispatch(registry_cls, "POST", SNOOZE, body, **who)[0]

    def labels(who: dict[str, Any]) -> list[str]:
        snoozed = _data(_dispatch(registry_cls, "GET", SNOOZED, **who)[1])["snoozed"]
        return [s["label"] for s in snoozed]

    assert snooze(OWNER, "mine", minutes=-1) == 200
    # To anyone else the owner's snooze answers exactly like an id nobody snoozed.
    unknown = "/api/v1/email/never-snoozed/snooze"
    assert _dispatch(registry_cls, "DELETE", SNOOZE, **intruder) == _dispatch(
        registry_cls, "DELETE", unknown, **intruder
    )
    assert labels(intruder) == []
    assert _data(_dispatch(registry_cls, "POST", PROCESS_DUE, {}, **intruder)[1])["processed"] == []
    assert snooze(intruder, "theirs", days=9) == 200
    assert (labels(OWNER), labels(intruder)) == (["mine"], ["theirs"])
    assert _dispatch(registry_cls, "DELETE", SNOOZE, **intruder)[0] == 200
    assert _data(_dispatch(registry_cls, "POST", PROCESS_DUE, {}, **OWNER)[1])["processed"] == [
        "probe-email"
    ]

    mark = {
        "email_id": "e-1",
        "thread_id": "t-1",
        "recipient": "bob@example.com",
        "sent_at": _utc_z(days=-5),
    }
    mine = _data(_dispatch(registry_cls, "POST", MARK, mark, **OWNER)[1])["followup_id"]
    theirs = _data(
        _dispatch(registry_cls, "POST", MARK, mark | {"email_id": "e-2"}, **intruder)[1]
    )["followup_id"]
    pending = _data(_dispatch(registry_cls, "GET", PENDING, **intruder)[1])["followups"]
    assert [f["followup_id"] for f in pending] == [theirs]
    replied = _data(_dispatch(registry_cls, "POST", CHECK_REPLIES, {}, **intruder)[1])["replied"]
    assert [r["followup_id"] for r in replied] == [theirs]
    resolve = f"/api/v1/email/followups/{mine}/resolve"
    assert (
        _dispatch(registry_cls, "POST", resolve, {"status": "manually_resolved"}, **intruder)[0]
        == 404
    )
    assert services._followups[mine].status.value == "awaiting"


CUSTOM_ROLES = {
    ("email-ru", "org-1"): {"email.read", "email.update"},
    ("email-ru", "org-2"): {"email.read", "email.update"},
    ("email-rd", "org-1"): {"email.read", "email.delete"},
}


@pytest.fixture
def custom_roles(monkeypatch):
    # Fixtures swap the global checker per test; rebuild the middleware on the current one.
    monkeypatch.setattr(UnifiedHandler, "_rbac", None)
    checker = get_permission_checker()
    assert UnifiedHandler._get_rbac()._checker is checker
    for (name, org), permissions in CUSTOM_ROLES.items():
        role = create_custom_role(name, name, "test role", permissions, org)
        checker._custom_roles[role.id] = {"permissions": set(role.permissions)}
    checker.clear_cache()
    yield
    for name, org in CUSTOM_ROLES:
        checker._custom_roles.pop(f"{org}:{name}", None)
    checker.clear_cache()


UPDATE_ROUTES = {
    "cancelSnooze": ("DELETE", SNOOZE, None, 404),
    "checkReplies": ("POST", CHECK_REPLIES, {}, 200),
    "categoryFeedback": (
        "POST",
        LEARN,
        {"email_id": "e1", "predicted_category": "newsletters", "correct_category": "projects"},
        501,
    ),
}


# email-rd is not defined in org-2, so that caller holds no permission at all.
@pytest.mark.parametrize(
    ("role", "org", "allowed"),
    [
        ("email-ru", "org-1", True),
        ("email-ru", "org-2", True),
        ("email-rd", "org-1", False),
        ("email-rd", "org-2", False),
    ],
)
@pytest.mark.parametrize("route_id", sorted(UPDATE_ROUTES))
def test_update_routes_need_email_update_in_middleware_handler_and_module(
    registry_cls, services, custom_roles, route_id: str, role: str, org: str, allowed: bool
) -> None:
    method, path, body, ok_status = UPDATE_ROUTES[route_id]
    user = f"jwt-{role}-{org}"
    context = AuthorizationContext(
        user_id=user,
        org_id=org,
        roles={role},
        permissions=get_role_permissions(role, include_inherited=True),
    )
    passed, _reason, key = UnifiedHandler._get_rbac().check_request(path, method, context)
    status, payload = _dispatch(registry_cls, method, path, body, caller=role, user=user, org=org)
    assert (key, passed, status) == ("email.update", allowed, ok_status if allowed else 403), (
        payload
    )


@pytest.mark.parametrize("caller", ("owner", "member"))
def test_teams_list_answer_applies_to_get_only(registry_cls, caller: str) -> None:
    status, payload = _dispatch(registry_cls, "POST", "/api/v1/teams", {}, caller=caller)
    assert (status, payload["error"]["message"]) == (501, NOT_IMPLEMENTED["teams.createTeam"])


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
