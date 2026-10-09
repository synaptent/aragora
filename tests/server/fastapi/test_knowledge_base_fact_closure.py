"""The v2 knowledge-base fact routes stay closed until organization scoping lands for them.

Requests go through the real FastAPI app (``create_app``) with access tokens from
``create_access_token``, so ``require_authenticated`` and ``require_permission`` see the
context a real login produces. One organization's fact is seeded; every caller below
belongs to another organization.

Every route that reads or changes stored facts without organization scoping answers 401 to
anonymous callers and the closure 403 to every authenticated role, before the fact store or
the query engine is touched. Creating and importing facts stay open to ``knowledge:write``:
both write only into the caller's organization and never match, return or change a fact
that another organization stored.
"""

from __future__ import annotations

from typing import Any

import pytest

from aragora.billing.jwt_auth import create_access_token
from aragora.knowledge import (
    FactFilters,
    InMemoryEmbeddingService,
    InMemoryFactStore,
    SimpleQueryEngine,
)

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


def _bearer(role: str, org_id: str | None = "org-b") -> dict[str, str]:
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


def _import(
    client,
    facts: list[dict[str, Any]],
    headers: dict[str, str],
    merge_strategy: str | None = "skip_existing",
):
    body: dict[str, Any] = {"facts": facts, "workspace_id": "default"}
    if merge_strategy is not None:
        body["merge_strategy"] = merge_strategy
    return client.post(f"{PREFIX}/import", json=body, headers=headers)


def _org_facts(seeded, org_id: str) -> list[Any]:
    return seeded["inner"].list_facts(FactFilters(limit=100, org_id=org_id))


def test_import_binds_the_callers_org_and_never_matches_another_orgs_fact(
    fastapi_client, seeded
) -> None:
    facts = [
        {"id": seeded["fact_a"].id, "statement": ORG_A_STATEMENT, "workspace_id": ORG_A_WORKSPACE},
        {"statement": ORG_A_STATEMENT},
    ]

    response = _import(fastapi_client, facts, _bearer("owner"))

    assert response.status_code == 201, response.text
    assert response.json() == {"imported": 2, "skipped": 0, "errors": 0, "total": 2, "details": []}
    org_b = _org_facts(seeded, ORG_B)
    assert sorted((f.workspace_id, f.org_id) for f in org_b) == [
        ("default", ORG_B),
        (ORG_A_WORKSPACE, ORG_B),
    ]
    assert not {f.id for f in org_b} & seeded["org_a_ids"]
    assert seeded["inner"].get_statistics(org_id=ORG_A)["total_facts"] == 2
    assert seeded["inner"].get_fact(seeded["fact_a"].id, org_id=ORG_A).confidence == 0.5


@pytest.mark.parametrize("role", ("admin", "member", "analyst", "viewer"))
def test_import_requires_knowledge_write(fastapi_client, seeded, role) -> None:
    response = _import(fastapi_client, [{"statement": ORG_A_STATEMENT}], _bearer(role))

    assert response.status_code == 403
    assert response.json() == {"detail": "Permission denied: knowledge:write"}
    _assert_untouched(seeded)


def test_import_answers_401_to_anonymous(fastapi_client, seeded) -> None:
    response = _import(fastapi_client, [{"statement": ORG_A_STATEMENT}], {})

    assert response.status_code == 401
    _assert_untouched(seeded)


def test_import_without_an_org_answers_knowledge_org_required(fastapi_client, seeded) -> None:
    response = _import(fastapi_client, [{"statement": ORG_A_STATEMENT}], _bearer("owner", None))

    assert response.status_code == 403
    assert response.json()["code"] == "knowledge_org_required"
    _assert_untouched(seeded)


def test_retried_import_counts_only_new_facts_and_never_another_orgs(
    fastapi_client, seeded
) -> None:
    facts = [
        {"statement": ORG_A_STATEMENT},
        {"statement": "Org renewal is due in March"},
        {"statement": ORG_A_STATEMENT},
    ]

    responses = [
        _import(fastapi_client, facts, _bearer("owner", org_id)) for org_id in (ORG_B, ORG_B, ORG_C)
    ]

    counts = [(r.status_code, r.json()["imported"], r.json()["skipped"]) for r in responses]
    assert counts == [(201, 2, 1), (201, 0, 3), (201, 2, 1)]
    ids_b = {f.id for f in _org_facts(seeded, ORG_B)}
    ids_c = {f.id for f in _org_facts(seeded, ORG_C)}
    assert len(ids_b) == len(ids_c) == 2
    assert not ids_b & ids_c and not (ids_b | ids_c) & seeded["org_a_ids"]
    assert seeded["inner"].get_statistics(org_id=ORG_A)["total_facts"] == 2


@pytest.mark.parametrize("strategy", ("overwrite", "merge"))
def test_import_rejects_merge_strategies_it_does_not_implement(
    fastapi_client, seeded, strategy
) -> None:
    facts = [
        {"id": seeded["fact_a"].id, "statement": ORG_A_STATEMENT},
        {"statement": "Org renewal is due in March"},
    ]

    response = _import(fastapi_client, facts, _bearer("owner"), merge_strategy=strategy)

    assert response.status_code == 422, response.text
    assert "skip_existing" in response.json()["detail"][0]["msg"]
    _assert_untouched(seeded)
    assert _org_facts(seeded, ORG_B) == []


def test_import_without_a_merge_strategy_skips_existing_facts(fastapi_client, seeded) -> None:
    facts = [
        {"statement": ORG_A_STATEMENT},
        {"statement": "Org renewal is due in March"},
        {"statement": ORG_A_STATEMENT},
    ]

    responses = [
        _import(fastapi_client, facts, _bearer("owner"), merge_strategy=None) for _ in range(2)
    ]

    counts = [(r.status_code, r.json()["imported"], r.json()["skipped"]) for r in responses]
    assert counts == [(201, 2, 1), (201, 0, 3)]
    assert len(_org_facts(seeded, ORG_B)) == 2


@pytest.mark.parametrize(
    "workspace_id", (7, None, ["ws"], "w" * 101), ids=("int", "null", "list", "101-chars")
)
def test_import_rejects_an_entry_workspace_that_is_not_a_short_string(
    fastapi_client, seeded, workspace_id
) -> None:
    facts = [
        {"statement": "Org renewal is due in March"},
        {"statement": "Org renewal is due in April", "workspace_id": workspace_id},
    ]

    response = _import(fastapi_client, facts, _bearer("owner"))

    assert response.status_code == 422, response.text
    assert "facts[1].workspace_id" in response.json()["detail"][0]["msg"]
    _assert_untouched(seeded)
    assert _org_facts(seeded, ORG_B) == []


def test_import_accepts_an_entry_workspace_of_100_characters(fastapi_client, seeded) -> None:
    facts = [{"statement": "Org renewal is due in March", "workspace_id": "w" * 100}]

    response = _import(fastapi_client, facts, _bearer("owner"))

    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 1
    assert [f.workspace_id for f in _org_facts(seeded, ORG_B)] == ["w" * 100]
