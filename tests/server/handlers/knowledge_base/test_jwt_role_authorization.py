"""Knowledge routes authorize real JWT callers by their RBAC v2 role.

Every request carries an access token from ``create_access_token``, so
``extract_user_from_request`` builds the ``UserAuthContext`` a real login
produces (a ``role`` string, no ``permissions`` or ``roles`` lists). Requests
go through the real HANDLER_REGISTRY dispatch (``_try_modular_handler``), and
the RBAC v2 checker is not patched (``no_auto_auth``).

RBAC v2 grants ``knowledge.read`` to owner, admin and member (analyst and
viewer have none), and ``knowledge.write`` / ``knowledge.delete`` to owner only.

Until facts are scoped to an organization, every route that returns data derived
from stored facts or touches an existing fact is closed: anonymous callers get
401 and every authenticated caller, owner included, gets the closure 403.
Creating a fact and the routes that never touch stored facts follow RBAC v2.
"""

from __future__ import annotations

import io
import json
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.knowledge import InMemoryFactStore
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

CLOSED_REQUESTS: list[_Request] = [
    ("GET", "/api/v1/knowledge/facts", None),
    ("GET", "/api/v1/facts", None),
    ("GET", "/api/v1/knowledge/facts/missing-fact", None),
    ("GET", "/api/v1/facts/missing-fact", None),
    ("GET", "/api/v1/knowledge/facts/missing-fact/contradictions", None),
    ("GET", "/api/v1/knowledge/facts/missing-fact/relations", None),
    ("GET", "/api/v1/knowledge/search", None),
    ("GET", "/api/v1/knowledge/stats", None),
    ("GET", "/api/v1/facts/stats", None),
    ("POST", "/api/v1/knowledge/query", {}),
    ("PUT", "/api/v1/knowledge/facts/missing-fact", {"confidence": 0.5}),
    ("DELETE", "/api/v1/knowledge/facts/missing-fact", None),
    ("POST", "/api/v1/knowledge/facts/missing-fact/verify", {}),
    ("POST", "/api/v1/knowledge/facts/missing-fact/relations", {}),
    ("POST", "/api/v1/knowledge/facts/relations", {}),
    ("POST", "/api/v1/facts/batch", {}),
]
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


def _token(role: str) -> str:
    return create_access_token(
        user_id=f"jwt-{role}", email=f"{role}@example.com", org_id="org-1", role=role
    )


def _dispatch(
    registry_cls: type[_RegistryMixin],
    method: str,
    path: str,
    body: dict[str, Any] | None,
    role: str | None,
    *,
    bearer: str | None = None,
) -> tuple[int, dict[str, Any]]:
    instance: Any = registry_cls()
    raw = json.dumps(body).encode("utf-8") if body is not None else b""
    instance.command = method
    instance.path = path
    instance.headers = {"Content-Length": str(len(raw)), "Content-Type": "application/json"}
    if role is not None:
        bearer = _token(role)
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


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.parametrize(("method", "path", "body"), CLOSED_REQUESTS)
def test_closed_fact_routes_answer_closure_403_to_every_role(
    registry_cls, role, method, path, body
) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, role)
    assert status == 403, payload
    assert payload == CLOSED


@pytest.mark.parametrize(("method", "path", "body"), CLOSED_REQUESTS)
def test_closed_fact_routes_answer_401_to_a_non_jwt_bearer(
    registry_cls, method, path, body
) -> None:
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


def test_owner_created_fact_stays_unreadable_to_owner_and_member(registry_cls) -> None:
    status, created = _dispatch(
        registry_cls,
        "POST",
        "/api/v1/knowledge/facts",
        {"statement": "Owners write, nobody reads yet", "workspace_id": "ws"},
        "owner",
    )
    assert status == 201, created
    for role in ("owner", "member"):
        for path in ("/api/v1/knowledge/facts", f"/api/v1/knowledge/facts/{created['id']}"):
            status, payload = _dispatch(registry_cls, "GET", path, None, role)
            assert (status, payload) == (403, CLOSED)


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


@pytest.mark.parametrize(("method", "path", "body"), CLOSED_REQUESTS + CREATE_REQUESTS)
def test_anonymous_requests_get_401(registry_cls, method, path, body) -> None:
    status, payload = _dispatch(registry_cls, method, path, body, None)
    assert status == 401, payload
    assert payload == {"error": "Authentication required"}
