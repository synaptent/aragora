"""Knowledge routes authorize real JWT callers by their RBAC v2 role.

Every request carries an access token from ``create_access_token``, so
``extract_user_from_request`` builds the ``UserAuthContext`` a real login
produces (a ``role`` string, no ``permissions`` or ``roles`` lists). Requests
go through the real HANDLER_REGISTRY dispatch (``_try_modular_handler``), and
the RBAC v2 checker is not patched (``no_auto_auth``).

RBAC v2 grants ``knowledge.read`` to owner, admin and member (analyst and
viewer have none), and ``knowledge.write`` / ``knowledge.delete`` to owner only.

Every fact route reads and changes only the caller's organization's facts. A
fact of another organization, or one stored without an organization, answers
the same 404 as an id that does not exist; a caller without an organization
gets 403 ``knowledge_org_required``. Chunk search is not organization-scoped
yet: anonymous callers get 401 and every authenticated caller the closure 403.
"""

from __future__ import annotations

import io
import json
import sqlite3
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.knowledge import FactStore, InMemoryFactStore
from aragora.rbac.checker import get_permission_checker
from aragora.server.handler_registry import HandlerRegistryMixin
from aragora.server.handlers.knowledge_base.handler import _knowledge_limiter

pytestmark = pytest.mark.no_auto_auth
EXERCISES_FACT_CLOSURE = True

READERS = ("owner", "admin", "member")
NON_READERS = ("analyst", "viewer", "unknown-role")
ALL_ROLES = READERS + NON_READERS
READERS_WITHOUT_WRITE = ("admin", "member")

CLOSED = {
    "error": {
        "message": "Knowledge fact access is disabled until org scoping is available",
        "code": "knowledge_fact_access_closed",
    }
}

_Request = tuple[str, str, dict[str, Any] | None]

ORG = "org-1"
OTHER_ORG = "org-2"
OWN_STATEMENT = "Org 1 pricing floor is 40 dollars"
OTHER_STATEMENT = "Org 2 acquisition target is Northwind"
OTHER_SECRET = "org-2-deal-room"
PERMISSION_DENIED = {"error": "Permission denied"}

# {own} and {own2} are facts of the caller's organization (org-1).
READ_REQUESTS: list[tuple[str, str, dict[str, Any] | None, int]] = [
    ("GET", "/api/v1/knowledge/facts", None, 200),
    ("GET", "/api/v1/facts", None, 200),
    ("GET", "/api/v1/knowledge/facts/{own}", None, 200),
    ("GET", "/api/v1/facts/{own}", None, 200),
    ("GET", "/api/v1/knowledge/facts/{own}/contradictions", None, 200),
    ("GET", "/api/v1/knowledge/facts/{own}/relations", None, 200),
    ("GET", "/api/v1/knowledge/stats", None, 200),
    ("POST", "/api/v1/knowledge/query", {"question": "pricing floor", "workspace_id": "ws"}, 200),
]
WRITE_REQUESTS: list[tuple[str, str, dict[str, Any] | None, int]] = [
    ("PUT", "/api/v1/knowledge/facts/{own}", {"confidence": 0.7}, 200),
    ("POST", "/api/v1/knowledge/facts/{own}/verify", {}, 200),
    (
        "POST",
        "/api/v1/knowledge/facts/{own}/relations",
        {"target_fact_id": "{own2}", "relation_type": "supports"},
        201,
    ),
    (
        "POST",
        "/api/v1/knowledge/facts/relations",
        {"source_fact_id": "{own}", "target_fact_id": "{own2}", "relation_type": "supports"},
        201,
    ),
    ("DELETE", "/api/v1/knowledge/facts/{own}", None, 200),
]
SCOPED_REQUESTS: list[_Request] = [r[:3] for r in READ_REQUESTS + WRITE_REQUESTS]
# Every route that names one fact; {id} is replaced with the fact under test.
FACT_ID_REQUESTS: list[_Request] = [
    ("GET", "/api/v1/knowledge/facts/{id}", None),
    ("GET", "/api/v1/facts/{id}", None),
    ("GET", "/api/v1/knowledge/facts/{id}/contradictions", None),
    ("GET", "/api/v1/knowledge/facts/{id}/relations", None),
    ("PUT", "/api/v1/knowledge/facts/{id}", {"confidence": 0.99}),
    ("POST", "/api/v1/knowledge/facts/{id}/verify", {}),
    (
        "POST",
        "/api/v1/knowledge/facts/{id}/relations",
        {"target_fact_id": "{own}", "relation_type": "supports"},
    ),
    (
        "POST",
        "/api/v1/knowledge/facts/relations",
        {"source_fact_id": "{own}", "target_fact_id": "{id}", "relation_type": "supports"},
    ),
    ("DELETE", "/api/v1/knowledge/facts/{id}", None),
]
SEARCH_REQUEST: _Request = ("GET", "/api/v1/knowledge/search", None)
CREATE_REQUESTS: list[_Request] = [
    ("POST", "/api/v1/knowledge/facts", {"statement": "A fact", "workspace_id": "ws"}),
    ("POST", "/api/v1/facts", {"statement": "A fact", "workspace_id": "ws"}),
]
# The /api/v1/index family has no route body on this branch, so only the
# cells that answer before the route body are pinned here.
INDEX_REQUESTS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/index", None),
    ("POST", "/api/v1/index", {"name": "idx"}),
    ("POST", "/api/v1/index/search", {"query": "q"}),
    ("POST", "/api/v1/index/embed-batch", {"texts": ["a"]}),
]


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


@pytest.fixture(scope="module")
def registry_cls() -> type[_RegistryMixin]:
    _RegistryMixin._init_handlers()
    assert _RegistryMixin._handlers_initialized is True
    return _RegistryMixin


@pytest.fixture(autouse=True, params=[False, True], ids=["auth-disabled", "auth-enabled"])
def _auth_enabled(request, monkeypatch) -> bool:
    """Run every case both ways: RBAC decorators skip a missing context only when auth is off.

    Auth is on in any deployment that sets ARAGORA_API_TOKEN, where a decorator
    that cannot find the request's context denies instead of skipping.
    """
    from aragora.server.auth import auth_config

    monkeypatch.setattr(auth_config, "enabled", request.param)
    return request.param


@pytest.fixture(autouse=True)
def _isolated_knowledge_state(registry_cls, monkeypatch):
    """A fresh in-memory fact store, an empty rate limiter and no cached RBAC decisions."""
    knowledge_handler = registry_cls._knowledge_handler
    monkeypatch.setattr(knowledge_handler, "_fact_store", InMemoryFactStore())
    monkeypatch.setattr(knowledge_handler, "_query_engine", None)
    get_permission_checker().clear_cache()
    _knowledge_limiter.clear()
    yield
    _knowledge_limiter.clear()
    get_permission_checker().clear_cache()


def _token(role: str, org_id: str | None = ORG) -> str:
    return create_access_token(
        user_id=f"jwt-{org_id}-{role}", email=f"{role}@example.com", org_id=org_id, role=role
    )


def _fill(value: Any, ids: dict[str, str]) -> Any:
    if isinstance(value, str):
        for name, fact_id in ids.items():
            value = value.replace("{" + name + "}", fact_id)
        return value
    if isinstance(value, dict):
        return {k: _fill(v, ids) for k, v in value.items()}
    return value


def _dispatch(
    registry_cls: type[_RegistryMixin],
    method: str,
    path: str,
    body: dict[str, Any] | None,
    role: str | None,
    *,
    org_id: str | None = ORG,
    bearer: str | None = None,
    ids: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    path, body = _fill(path, ids or {}), _fill(body, ids or {})
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    instance.command = method
    instance.path = path
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    if role is not None:
        bearer = _token(role, org_id)
    if bearer is not None:
        instance.headers["Authorization"] = f"Bearer {bearer}"
    instance.rfile = io.BytesIO(raw)
    instance.wfile = io.BytesIO()
    instance.send_response = MagicMock()
    instance.send_header = MagicMock()
    instance.end_headers = MagicMock()
    instance._add_cors_headers = MagicMock()
    instance._add_security_headers = MagicMock()
    instance._add_trace_headers = MagicMock()
    instance._auth_context = None
    instance.client_address = ("127.0.0.1", 12345)
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


@pytest.fixture
def facts(fact_store) -> dict[str, Any]:
    own = fact_store.add_fact(OWN_STATEMENT, "ws", topics=["pricing"], org_id=ORG)
    own2 = fact_store.add_fact("Org 1 discount cap is 15 percent", "ws", org_id=ORG)
    other = fact_store.add_fact(
        OTHER_STATEMENT, "ws", metadata={"secret": OTHER_SECRET}, org_id=OTHER_ORG
    )
    return {"own": own.id, "own2": own2.id, "other": other.id}


def _assert_other_org_untouched(fact_store, facts) -> None:
    other = fact_store.get_fact(facts["other"], org_id=OTHER_ORG)
    assert other is not None
    assert (other.statement, other.confidence, other.metadata) == (
        OTHER_STATEMENT,
        0.5,
        {"secret": OTHER_SECRET},
    )
    assert fact_store.get_relations(facts["other"], org_id=OTHER_ORG) == []


def _assert_no_other_org_data(payload: dict[str, Any], facts) -> None:
    text = json.dumps(payload)
    assert facts["other"] not in text
    assert OTHER_STATEMENT not in text
    assert OTHER_SECRET not in text


@pytest.mark.parametrize("role", READERS)
@pytest.mark.parametrize(("method", "path", "body", "expected"), READ_REQUESTS)
def test_readers_read_their_orgs_facts(
    registry_cls, fact_store, facts, role, method, path, body, expected
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role, ids=facts)
    assert status == expected, payload
    _assert_no_other_org_data(payload, facts)
    _assert_other_org_untouched(fact_store, facts)


def test_reads_return_the_callers_facts(registry_cls, facts) -> None:
    _status, listed = _dispatch(registry_cls, "GET", "/api/v1/knowledge/facts", None, "member")
    assert sorted(f["id"] for f in listed["facts"]) == sorted([facts["own"], facts["own2"]])
    _status, fact = _dispatch(registry_cls, "GET", "/api/v1/facts/{own}", None, "admin", ids=facts)
    assert (fact["id"], fact["statement"]) == (facts["own"], OWN_STATEMENT)
    _status, stats = _dispatch(registry_cls, "GET", "/api/v1/knowledge/stats", None, "member")
    assert (stats["total_facts"], stats["total_relations"]) == (2, 0)


@pytest.mark.parametrize(("method", "path", "body", "expected"), WRITE_REQUESTS)
def test_owner_changes_their_orgs_facts(
    registry_cls, fact_store, facts, method, path, body, expected
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, "owner", ids=facts)
    assert status == expected, payload
    _assert_no_other_org_data(payload, facts)
    _assert_other_org_untouched(fact_store, facts)


@pytest.mark.parametrize("role", READERS_WITHOUT_WRITE)
@pytest.mark.parametrize(("method", "path", "body", "expected"), WRITE_REQUESTS)
def test_readers_without_write_cannot_change_facts(
    registry_cls, fact_store, facts, role, method, path, body, expected
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role, ids=facts)
    assert (status, payload) == (403, PERMISSION_DENIED)
    assert fact_store.get_fact(facts["own"], org_id=ORG).confidence == 0.5


@pytest.mark.parametrize("role", NON_READERS)
@pytest.mark.parametrize(("method", "path", "body"), SCOPED_REQUESTS)
def test_roles_without_knowledge_read_are_denied(
    registry_cls, facts, role, method, path, body
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role, ids=facts)
    assert (status, payload) == (403, PERMISSION_DENIED)


# Only the SQLite store can hold a fact stored before org scoping (NULL org_id),
# so the unassigned case is never generated for the in-memory store.
@pytest.mark.parametrize(
    ("target", "fact_store"),
    [
        ("other-org", "in-memory-store"),
        ("other-org", "sqlite-store"),
        ("unassigned", "sqlite-store"),
    ],
    indirect=["fact_store"],
)
@pytest.mark.parametrize(("method", "path", "body"), FACT_ID_REQUESTS)
def test_a_fact_outside_the_callers_org_answers_the_missing_404(
    registry_cls, fact_store, facts, target, method, path, body
) -> None:
    """Another org's fact and a fact without an org look exactly like an id that does not exist."""
    if target == "unassigned":
        legacy = fact_store.add_fact("Unassigned legacy fact", "ws", org_id=ORG)
        with sqlite3.connect(fact_store.db_path) as conn:
            conn.execute("UPDATE facts SET org_id = NULL WHERE id = ?", (legacy.id,))
        target_id = legacy.id
    else:
        target_id = facts["other"]
    missing_id = "fact-that-does-not-exist"

    status, payload = _dispatch(
        registry_cls, method, path, body, "owner", ids={**facts, "id": target_id}
    )
    missing_status, missing_payload = _dispatch(
        registry_cls, method, path, body, "owner", ids={**facts, "id": missing_id}
    )

    assert status == missing_status == 404, payload
    # The 404 echoes only the id the caller sent.
    assert json.dumps(payload).replace(target_id, missing_id) == json.dumps(missing_payload)
    assert OTHER_STATEMENT not in json.dumps(payload)
    assert OTHER_SECRET not in json.dumps(payload)
    _assert_other_org_untouched(fact_store, facts)
    assert fact_store.get_relations(facts["own"], org_id=ORG) == []


@pytest.mark.parametrize(("method", "path", "body"), SCOPED_REQUESTS + CREATE_REQUESTS)
def test_callers_without_an_org_get_knowledge_org_required(
    registry_cls, fact_store, facts, method, path, body
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, "owner", org_id=None, ids=facts)
    assert status == 403, payload
    assert payload["error"]["code"] == "knowledge_org_required"
    _assert_no_other_org_data(payload, facts)
    assert fact_store.get_fact(facts["own"], org_id=ORG).confidence == 0.5


def test_listing_and_stats_are_never_served_from_another_orgs_response(registry_cls, facts) -> None:
    """Back-to-back identical requests from two orgs, then a write, each read fresh."""
    path, stats_path = "/api/v1/knowledge/facts", "/api/v1/knowledge/stats"
    _s, org1 = _dispatch(registry_cls, "GET", path, None, "owner")
    _s, org2 = _dispatch(registry_cls, "GET", path, None, "owner", org_id=OTHER_ORG)
    assert {f["statement"] for f in org2["facts"]} == {OTHER_STATEMENT}
    assert OTHER_STATEMENT not in json.dumps(org1)

    _s, before = _dispatch(registry_cls, "GET", stats_path, None, "owner")
    body = {"statement": "New", "workspace_id": "ws"}
    status, created = _dispatch(registry_cls, "POST", path, body, "owner")
    assert status == 201, created
    _s, after = _dispatch(registry_cls, "GET", stats_path, None, "owner")
    _s, listed = _dispatch(registry_cls, "GET", path, None, "owner")
    _s, other = _dispatch(registry_cls, "GET", stats_path, None, "owner", org_id=OTHER_ORG)
    assert (before["total_facts"], after["total_facts"], other["total_facts"]) == (2, 3, 1)
    assert created["id"] in {f["id"] for f in listed["facts"]}


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize(("method", "path", "body"), [SEARCH_REQUEST])
def test_search_answers_closure_403_to_every_role(registry_cls, role, method, path, body) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role)
    assert status == 403, payload
    assert payload == CLOSED


@pytest.mark.parametrize(("method", "path", "body"), SCOPED_REQUESTS + [SEARCH_REQUEST])
def test_fact_routes_answer_401_to_a_non_jwt_bearer(registry_cls, method, path, body) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, None, bearer="static-api-token")
    assert status == 401, payload
    assert payload == {"error": "Authentication required"}


@pytest.mark.parametrize(("method", "path", "body"), CREATE_REQUESTS)
def test_owner_creates_facts(registry_cls, method, path, body) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, "owner")
    assert status == 201, payload
    assert payload["statement"] == "A fact"


@pytest.mark.parametrize("role", READERS_WITHOUT_WRITE + NON_READERS)
@pytest.mark.parametrize(("method", "path", "body"), CREATE_REQUESTS)
def test_roles_without_knowledge_write_cannot_create_facts(
    registry_cls, role, method, path, body
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role)
    assert status == 403, payload
    assert payload == {"error": "Permission denied"}


def _org_owner_token(org_id: str) -> str:
    return create_access_token(
        user_id=f"owner-{org_id}", email=f"owner@{org_id}.example.com", org_id=org_id, role="owner"
    )


@pytest.fixture(params=["in-memory-store", "sqlite-store"])
def fact_store(request, registry_cls, monkeypatch, tmp_path):
    if request.param == "in-memory-store":
        store: Any = InMemoryFactStore()
    else:
        store = FactStore(db_path=tmp_path / "knowledge.db")
    monkeypatch.setattr(registry_cls._knowledge_handler, "_fact_store", store)
    return store


# The org B statement normalizes to org A's (case and whitespace), so a store
# that deduplicates by statement and workspace would hand back org A's row.
@pytest.mark.parametrize(
    ("org_a_workspace", "org_b_workspace"),
    [("ws-org-a", "ws-org-a"), ("ws-org-a", "ws-org-b"), (None, None)],
    ids=["org-b-names-org-a-workspace", "org-b-own-workspace", "both-default-workspace"],
)
def test_create_never_returns_another_orgs_existing_fact(
    registry_cls, fact_store, org_a_workspace, org_b_workspace
) -> None:
    org_a_body: dict[str, Any] = {
        "statement": "Org A Pricing Floor Is 40 Dollars",
        "confidence": 0.91,
        "evidence_ids": ["ev-org-a"],
        "source_documents": ["doc-org-a"],
        "topics": ["org-a-pricing"],
        "metadata": {"owner": "org-a", "secret": "org-a-only"},
    }
    org_b_body: dict[str, Any] = {
        "statement": "  org a pricing floor   is 40 dollars ",
        "confidence": 0.3,
    }
    if org_a_workspace is not None:
        org_a_body["workspace_id"] = org_a_workspace
    if org_b_workspace is not None:
        org_b_body["workspace_id"] = org_b_workspace

    path = "/api/v1/knowledge/facts"
    status, org_a_fact = _dispatch(
        registry_cls, "POST", path, org_a_body, None, bearer=_org_owner_token("org-a")
    )
    assert status == 201, org_a_fact
    status, created = _dispatch(
        registry_cls, "POST", path, org_b_body, None, bearer=_org_owner_token("org-b")
    )
    assert status == 201, created

    assert created["id"] != org_a_fact["id"]
    assert created["statement"] == org_b_body["statement"]
    assert created["confidence"] == 0.3
    assert created["evidence_ids"] == []
    assert created["source_documents"] == []
    assert created["topics"] == []
    assert created["metadata"] == {}
    assert created["created_at"] != org_a_fact["created_at"]
    assert created["updated_at"] != org_a_fact["updated_at"]
    assert "org-a-only" not in json.dumps(created)


def test_retried_create_returns_the_callers_existing_fact(registry_cls, fact_store) -> None:
    body = {"statement": "Retried fact", "workspace_id": "ws"}
    path = "/api/v1/knowledge/facts"
    first = _dispatch(registry_cls, "POST", path, body, "owner")
    retry = _dispatch(registry_cls, "POST", path, body, "owner")
    other_org = _dispatch(registry_cls, "POST", path, body, "owner", org_id=OTHER_ORG)
    assert (first[0], retry[0], other_org[0]) == (201, 201, 201)
    assert retry[1]["id"] == first[1]["id"] != other_org[1]["id"]


def test_owner_created_fact_is_readable_by_the_owners_org_only(registry_cls) -> None:
    status, created = _dispatch(
        registry_cls,
        "POST",
        "/api/v1/knowledge/facts",
        {"statement": "Owners write, their org reads", "workspace_id": "ws"},
        "owner",
    )
    assert status == 201, created
    path = f"/api/v1/knowledge/facts/{created['id']}"
    for role in ("owner", "member"):
        status, payload = _dispatch(registry_cls, "GET", path, None, role)
        assert (status, payload["id"]) == (200, created["id"])
    status, _payload = _dispatch(registry_cls, "GET", path, None, "member", org_id=OTHER_ORG)
    assert status == 404


@pytest.mark.parametrize("role", READERS)
@pytest.mark.parametrize(("method", "path", "body"), INDEX_REQUESTS)
def test_index_routes_are_not_closed(registry_cls, role, method, path, body) -> None:
    _status, payload = _dispatch(registry_cls, method, path, body, role)
    assert payload != CLOSED


@pytest.mark.parametrize("role", NON_READERS)
@pytest.mark.parametrize(("method", "path", "body"), INDEX_REQUESTS)
def test_index_routes_answer_403_to_roles_without_knowledge_read(
    registry_cls, role, method, path, body
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role)
    assert status == 403, payload
    assert payload == {"error": "Permission denied"}


@pytest.mark.parametrize(
    ("method", "path", "body"), SCOPED_REQUESTS + CREATE_REQUESTS + [SEARCH_REQUEST]
)
def test_anonymous_requests_get_401(registry_cls, method, path, body) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, None)
    assert status == 401, payload
    assert payload == {"error": "Authentication required"}
