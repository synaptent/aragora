"""The v2 knowledge-base fact routes stay closed until organization scoping lands for them.

Requests go through the real FastAPI app (``create_app``) with access tokens from
``create_access_token``, so ``require_authenticated`` and ``require_permission`` see the
context a real login produces. One organization's fact is seeded; every caller below
belongs to another organization.

Every route that reads or changes stored facts answers 401 to anonymous callers and the
closure 403 to every authenticated role, before the fact store or the query engine is
touched. Creating a fact stays open to ``knowledge:write`` and never hands back a fact
that another organization stored.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.knowledge import InMemoryEmbeddingService, InMemoryFactStore, SimpleQueryEngine
from aragora.rbac.models import AuthorizationContext
from aragora.server.fastapi.routes import knowledge_base

PREFIX = "/api/v2/knowledge-base"
ROLES = ("owner", "admin", "member", "analyst", "viewer")
ORG_A = "org-a"
ORG_B = "org-b"
ORG_C = "org-c"
ORG_A_STATEMENT = "Org A acquisition target is Northwind, closing 2026-11-30"
ORG_A_WORKSPACE = "ws-org-a"
ORG_A_METADATA = {"deal_room": "org-a-only"}
API_KEY = "ara_" + "k" * 40

CLOSED = {
    "error": "Knowledge fact access is disabled until org scoping is available",
    "code": "knowledge_fact_access_closed",
}

FACT_ID = "{fact_id}"
CLOSED_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/facts", None),
    ("GET", "/facts/{fact_id}", None),
    ("PUT", "/facts/{fact_id}", {"confidence": 0.9}),
    ("DELETE", "/facts/{fact_id}", None),
    ("POST", "/facts/{fact_id}/verify", None),
    ("GET", "/facts/{fact_id}/contradictions", None),
    ("GET", "/facts/{fact_id}/relations", None),
    (
        "POST",
        "/facts/{fact_id}/relations",
        {"target_fact_id": FACT_ID, "relation_type": "supports"},
    ),
    (
        "POST",
        "/facts/relations",
        {"source_fact_id": FACT_ID, "target_fact_id": FACT_ID, "relation_type": "supports"},
    ),
    ("POST", "/query", {"question": "What is the acquisition target?", "workspace_id": "default"}),
    ("GET", "/search?q=Northwind", None),
    ("GET", "/stats", None),
    ("GET", "/export", None),
    (
        "POST",
        "/import",
        {"facts": [{"id": FACT_ID, "statement": "probe"}], "merge_strategy": "skip_existing"},
    ),
]
ROUTE_IDS = [f"{method} {path}" for method, path, _ in CLOSED_ROUTES]


class _Recording:
    """Delegates to a real store or engine and records every method called on it."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def _call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return attr(*args, **kwargs)

        return _call


class _ApiKeyUser:
    id = "key-user"
    email = "key@org-b.example"
    org_id = "org-b"
    role = "owner"
    is_active = True


class _ApiKeyUserStore:
    """Accepts ``API_KEY`` for an org-B owner if anything looks it up."""

    def get_user_by_api_key(self, key: str) -> _ApiKeyUser | None:
        return _ApiKeyUser() if key == API_KEY else None


@pytest.fixture
def seeded(fastapi_app) -> dict[str, Any]:
    inner = InMemoryFactStore()
    fact_a = inner.add_fact(
        statement=ORG_A_STATEMENT,
        workspace_id=ORG_A_WORKSPACE,
        metadata=ORG_A_METADATA,
        org_id=ORG_A,
    )
    default_fact_a = inner.add_fact(statement=ORG_A_STATEMENT, workspace_id="default", org_id=ORG_A)
    store = _Recording(inner)
    engine = _Recording(
        SimpleQueryEngine(fact_store=inner, embedding_service=InMemoryEmbeddingService())
    )
    user_store = _ApiKeyUserStore()
    fastapi_app.state.context = {
        "fact_store": store,
        "query_engine": engine,
        "user_store": user_store,
    }
    return {
        "inner": inner,
        "store": store,
        "engine": engine,
        "user_store": user_store,
        "fact_a": fact_a,
        "org_a_ids": {fact_a.id, default_fact_a.id},
    }


def _bearer(role: str, org_id: str = "org-b") -> dict[str, str]:
    token = create_access_token(f"user-{org_id}-{role}", f"{role}@{org_id}.example", org_id, role)
    return {"Authorization": f"Bearer {token}"}


def _fill(value: Any, fact_id: str) -> Any:
    if isinstance(value, str):
        return value.replace(FACT_ID, fact_id)
    if isinstance(value, dict):
        return {k: _fill(v, fact_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, fact_id) for v in value]
    return value


def _send(client, seeded, method: str, path: str, body: Any, headers: dict[str, str]):
    fact_id = seeded["fact_a"].id
    return client.request(
        method, PREFIX + _fill(path, fact_id), json=_fill(body, fact_id), headers=headers
    )


def _assert_no_org_a_data(seeded, response) -> None:
    for fact_id in seeded["org_a_ids"]:
        assert fact_id not in response.text
    assert ORG_A_STATEMENT not in response.text
    assert ORG_A_METADATA["deal_room"] not in response.text


def _assert_untouched(seeded) -> None:
    assert seeded["store"].calls == []
    assert seeded["engine"].calls == []
    assert seeded["inner"].get_fact(seeded["fact_a"].id, org_id=ORG_A).confidence == 0.5


@pytest.mark.parametrize(("method", "path", "body"), CLOSED_ROUTES, ids=ROUTE_IDS)
@pytest.mark.parametrize("role", ROLES)
def test_closed_route_answers_closure_to_every_role(
    fastapi_client, seeded, role, method, path, body
) -> None:
    response = _send(fastapi_client, seeded, method, path, body, _bearer(role))

    assert response.status_code == 403
    assert response.json() == CLOSED
    _assert_no_org_a_data(seeded, response)
    _assert_untouched(seeded)


@pytest.mark.parametrize(("method", "path", "body"), CLOSED_ROUTES, ids=ROUTE_IDS)
def test_closed_route_answers_401_to_anonymous(fastapi_client, seeded, method, path, body) -> None:
    response = _send(fastapi_client, seeded, method, path, body, {})

    assert response.status_code == 401
    _assert_no_org_a_data(seeded, response)
    _assert_untouched(seeded)


@pytest.mark.parametrize(("method", "path", "body"), CLOSED_ROUTES, ids=ROUTE_IDS)
def test_closed_route_never_serves_an_api_key_caller(
    fastapi_client, seeded, method, path, body
) -> None:
    """Whether or not the key resolves to a user, a closed route never reaches the store:
    an unresolved key is anonymous (401) and a resolved one gets the closure (403)."""
    headers = {"Authorization": f"Bearer {API_KEY}"}
    response = _send(fastapi_client, seeded, method, path, body, headers)

    if response.status_code == 401:
        assert response.json() != CLOSED
    else:
        assert response.status_code == 403
        assert response.json() == CLOSED
    _assert_no_org_a_data(seeded, response)
    _assert_untouched(seeded)


@pytest.mark.parametrize("workspace_id", [ORG_A_WORKSPACE, "default"])
def test_create_with_another_orgs_statement_stores_a_new_fact(
    fastapi_client, seeded, workspace_id
) -> None:
    response = fastapi_client.post(
        f"{PREFIX}/facts",
        json={"statement": ORG_A_STATEMENT, "workspace_id": workspace_id},
        headers=_bearer("owner"),
    )

    assert response.status_code == 201
    created = response.json()
    assert created["id"] not in seeded["org_a_ids"]
    assert created["workspace_id"] == workspace_id
    assert created["metadata"] == {}
    assert ORG_A_METADATA["deal_room"] not in response.text
    assert seeded["inner"].get_fact(created["id"], org_id=ORG_B) is not None
    assert seeded["inner"].get_statistics(org_id=ORG_A)["total_facts"] == 2
    assert seeded["inner"].get_statistics(org_id=ORG_B)["total_facts"] == 1


@pytest.mark.parametrize("role", ("admin", "member", "analyst", "viewer"))
def test_create_still_requires_knowledge_write(fastapi_client, seeded, role) -> None:
    response = fastapi_client.post(
        f"{PREFIX}/facts",
        json={"statement": ORG_A_STATEMENT, "workspace_id": ORG_A_WORKSPACE},
        headers=_bearer(role),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Permission denied: knowledge:write"}
    _assert_untouched(seeded)


def test_create_answers_401_to_anonymous(fastapi_client, seeded) -> None:
    response = fastapi_client.post(
        f"{PREFIX}/facts",
        json={"statement": ORG_A_STATEMENT, "workspace_id": ORG_A_WORKSPACE},
    )

    assert response.status_code == 401
    _assert_untouched(seeded)


@pytest.mark.parametrize("role", ROLES)
def test_sync_status_stays_open(fastapi_client, seeded, role) -> None:
    response = fastapi_client.get(f"{PREFIX}/sync-status", headers=_bearer(role))

    assert response.status_code == 200
    assert response.json() == {
        "synced": True,
        "last_sync_at": None,
        "pending_changes": 0,
        "status": "ok",
    }


def test_retried_create_returns_the_same_fact_and_never_another_orgs(
    fastapi_client, seeded
) -> None:
    body = {"statement": ORG_A_STATEMENT, "workspace_id": ORG_A_WORKSPACE}

    def create(org_id: str):
        return fastapi_client.post(f"{PREFIX}/facts", json=body, headers=_bearer("owner", org_id))

    first, retry, other_org = create(ORG_B), create(ORG_B), create(ORG_C)

    assert (first.status_code, retry.status_code, other_org.status_code) == (201, 201, 201)
    assert retry.json()["id"] == first.json()["id"]
    assert first.json()["id"] not in seeded["org_a_ids"]
    assert other_org.json()["id"] not in {first.json()["id"], *seeded["org_a_ids"]}
    assert seeded["inner"].get_statistics(org_id=ORG_A)["total_facts"] == 2
    assert seeded["inner"].get_statistics(org_id=ORG_B)["total_facts"] == 1
    assert seeded["inner"].get_statistics(org_id=ORG_C)["total_facts"] == 1


async def test_retried_import_stores_each_statement_once_per_org() -> None:
    store = InMemoryFactStore()
    body = knowledge_base.ImportRequest(
        facts=[{"statement": ORG_A_STATEMENT}],
        workspace_id="default",
        merge_strategy="skip_existing",
    )

    for org_id in (ORG_B, ORG_B, ORG_C):
        result = await knowledge_base.import_knowledge_base(
            body=body,
            auth=AuthorizationContext(user_id=f"user-{org_id}-owner", org_id=org_id),
            store=store,
        )
        assert result.errors == 0

    def ids(org_id: str) -> set[str]:
        filters = knowledge_base.FactFilters(limit=10, org_id=org_id)
        return {fact.id for fact in store.list_facts(filters)}

    assert len(ids(ORG_B)) == 1
    assert len(ids(ORG_C)) == 1
    assert ids(ORG_B) != ids(ORG_C)
