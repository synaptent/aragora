"""Knowledge fact HTTP routes bind the authenticated organization or fail closed (v2 and v1)."""

from __future__ import annotations

import asyncio
import io
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from aragora.billing.jwt_auth import create_access_token
from aragora.knowledge import FactFilters, FactStore, ScopedFactStore
from aragora.knowledge.fact_store import OrgScopeRequiredError

V2 = "/api/v2/knowledge-base"


@pytest.fixture(params=["api-token-unset", "api-token-set"])
def world(request, tmp_path, monkeypatch):
    if request.param == "api-token-set":
        monkeypatch.setenv("ARAGORA_API_TOKEN", "static-token-" + "x" * 32)
    else:
        monkeypatch.delenv("ARAGORA_API_TOKEN", raising=False)
    from aragora.storage.user_store import UserStore

    users = UserStore(tmp_path / "users.db")
    callers = {}
    for name in ("acme", "beta"):
        owner = users.create_user(f"owner@{name}.example", "x" * 64, "s" * 32, role="owner")
        org = users.create_organization(name.title(), owner.id, slug=name)
        users.update_user(owner.id, org_id=org.id, role="owner")
        callers[name] = SimpleNamespace(user_id=owner.id, email=owner.email, org_id=org.id)
    loner = users.create_user("loner@example.com", "x" * 64, "s" * 32, role="owner")
    callers["no-org"] = SimpleNamespace(user_id=loner.id, email=loner.email, org_id=None)
    fresh = users.get_user_by_id(callers["beta"].user_id)
    api_key = fresh.generate_api_key(expires_days=30)
    users.update_user(
        fresh.id,
        api_key_hash=fresh.api_key_hash,
        api_key_prefix=fresh.api_key_prefix,
        api_key_created_at=fresh.api_key_created_at,
        api_key_expires_at=fresh.api_key_expires_at,
    )
    store = FactStore(db_path=tmp_path / "knowledge.db")
    acme_fact = ScopedFactStore(store, callers["acme"].org_id).add_fact(
        "Acme acquires Northwind", "acme-research"
    )
    return SimpleNamespace(
        users=users, store=store, callers=callers, acme_fact=acme_fact, key=api_key
    )


def _token(world, who: str) -> str:
    c = world.callers[who]
    return create_access_token(c.user_id, c.email, c.org_id, "owner")


def _rows(store: FactStore) -> tuple[int, int]:
    with sqlite3.connect(store.db_path) as conn:
        return (
            conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0],
        )


def _acme_view(world) -> list[tuple[str, str, str]]:
    acme = ScopedFactStore(world.store, world.callers["acme"].org_id)
    facts = acme.list_facts(FactFilters(include_superseded=True, limit=1000))
    return sorted((f.id, f.statement, f.workspace_id) for f in facts)


def _v2(world) -> TestClient:
    from aragora.knowledge import InMemoryEmbeddingService, SimpleQueryEngine
    from aragora.server.fastapi import create_app

    app = create_app()
    engine = SimpleQueryEngine(fact_store=world.store, embedding_service=InMemoryEmbeddingService())
    app.state.context = {
        "fact_store": world.store,
        "query_engine": engine,
        "user_store": world.users,
    }
    app.state.user_store = world.users
    return TestClient(app, raise_server_exceptions=False)


class _Request:
    def __init__(self, world, bearer: str, body: dict | None = None) -> None:
        self.user_store = world.users
        raw = json.dumps(body or {}).encode()
        self.headers = {
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Content-Length": str(len(raw) if body is not None else 0),
        }
        self.rfile = io.BytesIO(raw)
        self.client_address = ("127.0.0.1", 50000)
        self.command, self.path = "POST", "/api/v1/knowledge/facts"


def _v1(world, org_id: str | None = None):
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.handlers.knowledge_base.handler import KnowledgeHandler

    handler = KnowledgeHandler({"user_store": world.users, "fact_store": world.store})
    handler._fact_store = world.store
    handler._auth_context = AuthorizationContext(  # type: ignore[attr-defined]
        user_id="u", org_id=org_id, roles={"owner"}, permissions={"*"}
    )
    return handler


def _body(result) -> dict:
    return json.loads(result.body)


def _v1_code(payload: dict) -> str | None:
    error = payload.get("error")
    return (
        payload.get("error_code")
        or payload.get("code")
        or (error.get("code") if isinstance(error, dict) else None)
    )


def test_v2_cross_org_name_creates_into_the_callers_own_org(world) -> None:
    before = _acme_view(world)
    body = {"statement": "Acme acquires Northwind", "workspace_id": "acme-research"}
    r = _v2(world).post(
        V2 + "/facts", json=body, headers={"Authorization": f"Bearer {_token(world, 'beta')}"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["id"] != world.acme_fact.id
    stored = ScopedFactStore(world.store, world.callers["beta"].org_id).get_fact(r.json()["id"])
    assert stored is not None and stored.workspace_id == "acme-research"
    assert _acme_view(world) == before


def test_v1_cross_org_name_creates_into_the_callers_own_org(world) -> None:
    before = _acme_view(world)
    body = {"statement": "Acme acquires Northwind", "workspace_id": "acme-research"}
    result = _v1(world)._handle_create_fact(_Request(world, _token(world, "beta"), body))
    assert result.status_code == 201, result.body
    created = _body(result)
    created = created.get("data", created)
    assert created["id"] != world.acme_fact.id
    stored = ScopedFactStore(world.store, world.callers["beta"].org_id).get_fact(created["id"])
    assert stored is not None and stored.workspace_id == "acme-research"
    assert _acme_view(world) == before


def test_callers_without_an_org_get_403_and_no_row(world) -> None:
    before = _rows(world.store)
    client, bearer = _v2(world), _token(world, "no-org")
    hdr = {"Authorization": f"Bearer {bearer}"}
    r = client.post(
        V2 + "/facts", json={"statement": "Orphan", "workspace_id": "default"}, headers=hdr
    )
    assert r.status_code == 403 and r.json()["code"] == "knowledge_org_required"
    items = [{"statement": "Orphan import", "workspace_id": "default"}]
    r = client.post(V2 + "/import", json={"facts": items}, headers=hdr)
    assert r.status_code == 403 and r.json()["code"] == "knowledge_fact_access_closed"
    result = _v1(world)._handle_create_fact(_Request(world, bearer, {"statement": "Orphan v1"}))
    assert result.status_code == 403 and _v1_code(_body(result)) == "knowledge_org_required"
    assert _rows(world.store) == before


def test_v2_import_is_closed_and_its_body_binds_the_org_and_scopes_skip_existing(world) -> None:
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.fastapi.routes import knowledge_base as routes

    beta = world.callers["beta"].org_id
    items = [
        {
            "id": world.acme_fact.id,
            "statement": "Acme acquires Northwind",
            "workspace_id": "acme-research",
        },
        {"statement": "Beta pilot starts in December", "workspace_id": "acme-research"},
    ]
    hdr = {"Authorization": f"Bearer {_token(world, 'beta')}"}
    before, rows = _acme_view(world), _rows(world.store)
    r = _v2(world).post(
        V2 + "/import", json={"facts": items, "merge_strategy": "skip_existing"}, headers=hdr
    )
    assert r.status_code == 403 and r.json()["code"] == "knowledge_fact_access_closed"
    assert _rows(world.store) == rows

    result = asyncio.run(
        routes.import_knowledge_base(
            body=routes.ImportRequest(
                facts=items, workspace_id="default", merge_strategy="skip_existing"
            ),
            auth=AuthorizationContext(user_id=world.callers["beta"].user_id, org_id=beta),
            store=world.store,
        )
    )
    assert (result.imported, result.skipped, result.errors) == (2, 0, 0)
    beta_facts = ScopedFactStore(world.store, beta).list_facts(
        FactFilters(workspace_id="acme-research")
    )
    assert len(beta_facts) == 2 and all(f.org_id == beta for f in beta_facts)
    assert _acme_view(world) == before


def test_v2_retries_reuse_the_callers_fact_and_never_another_orgs(world) -> None:
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.fastapi.routes import knowledge_base as routes

    beta = world.callers["beta"].org_id
    before = _acme_view(world)
    body = {"statement": "Acme acquires Northwind", "workspace_id": "acme-research"}
    client, hdr = _v2(world), {"Authorization": f"Bearer {_token(world, 'beta')}"}
    created = [client.post(V2 + "/facts", json=body, headers=hdr) for _ in range(2)]
    assert [r.status_code for r in created] == [201, 201], created[-1].text
    fact_id = created[0].json()["id"]
    assert created[1].json()["id"] == fact_id != world.acme_fact.id

    auth = AuthorizationContext(user_id=world.callers["beta"].user_id, org_id=beta)
    request = routes.ImportRequest(
        facts=[body], workspace_id="default", merge_strategy="skip_existing"
    )
    for _ in range(2):
        result = asyncio.run(
            routes.import_knowledge_base(body=request, auth=auth, store=world.store)
        )
        assert result.errors == 0
    beta_facts = ScopedFactStore(world.store, beta).list_facts(
        FactFilters(include_superseded=True, limit=1000)
    )
    assert [f.id for f in beta_facts] == [fact_id]
    assert _acme_view(world) == before


def test_v2_import_body_requires_an_org(world) -> None:
    from aragora.rbac.models import AuthorizationContext
    from aragora.server.fastapi.middleware.error_handling import APIError
    from aragora.server.fastapi.routes import knowledge_base as routes

    before = _rows(world.store)
    request = routes.ImportRequest(
        facts=[{"statement": "Orphan import"}],
        workspace_id="default",
        merge_strategy="skip_existing",
    )
    with pytest.raises(APIError) as raised:
        asyncio.run(
            routes.import_knowledge_base(
                body=request,
                auth=AuthorizationContext(user_id=world.callers["no-org"].user_id, org_id=None),
                store=world.store,
            )
        )
    assert (raised.value.status_code, raised.value.code) == (403, "knowledge_org_required")
    assert _rows(world.store) == before


V2_CLOSED = [
    ("GET", "/facts", None),
    ("GET", "/facts?workspace_id=acme-research", None),
    ("GET", "/facts/{fid}", None),
    ("PUT", "/facts/{fid}", {"confidence": 0.9}),
    ("DELETE", "/facts/{fid}", None),
    ("POST", "/facts/{fid}/verify", None),
    ("GET", "/facts/{fid}/contradictions", None),
    ("GET", "/facts/{fid}/relations", None),
    ("POST", "/facts/{fid}/relations", {"target_fact_id": "{fid}", "relation_type": "supports"}),
    (
        "POST",
        "/facts/relations",
        {"source_fact_id": "{fid}", "target_fact_id": "{fid}", "relation_type": "supports"},
    ),
    ("POST", "/query", {"question": "Who buys Northwind?", "workspace_id": "acme-research"}),
    ("GET", "/stats", None),
    ("GET", "/export", None),
]


@pytest.mark.parametrize(("method", "path", "body"), V2_CLOSED)
def test_v2_fact_reads_and_edits_are_closed_for_an_owner_with_an_org(
    world, method, path, body
) -> None:
    fid = world.acme_fact.id
    payload = json.loads(json.dumps(body).replace("{fid}", fid)) if body else None
    hdr = {"Authorization": f"Bearer {_token(world, 'acme')}"}
    before = _acme_view(world)
    r = _v2(world).request(method, V2 + path.replace("{fid}", fid), json=payload, headers=hdr)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "knowledge_fact_access_closed"
    assert "Northwind" not in r.text
    assert _acme_view(world) == before


def _v1_closed_calls(handler, fid: str, req):
    rel = {"source_fact_id": fid, "target_fact_id": fid, "relation_type": "supports"}
    return {
        "list": lambda: handler._handle_list_facts({}),
        "get": lambda: handler._handle_get_fact(fid),
        "update": lambda: handler._handle_update_fact(fid, req({"confidence": 0.9})),
        "delete": lambda: handler._handle_delete_fact(fid, req(None)),
        "contradictions": lambda: handler._handle_get_contradictions(fid),
        "relations": lambda: handler._handle_get_relations(fid, {}),
        "add_relation": lambda: handler._handle_add_relation(fid, req(rel)),
        "add_relation_bulk": lambda: handler._handle_add_relation_bulk(req(rel)),
        "stats": lambda: handler._handle_stats(None),
    }


@pytest.mark.parametrize(
    "route",
    [
        "list",
        "get",
        "update",
        "delete",
        "contradictions",
        "relations",
        "add_relation",
        "add_relation_bulk",
        "stats",
    ],
)
def test_v1_fact_routes_are_closed_at_handler_level(world, route) -> None:
    acme = world.callers["acme"]
    handler = _v1(world, org_id=acme.org_id)
    bearer = _token(world, "acme")
    before = _acme_view(world)
    result = _v1_closed_calls(handler, world.acme_fact.id, lambda b: _Request(world, bearer, b))[
        route
    ]()
    assert result.status_code == 403, result.body
    assert _v1_code(_body(result)) == "knowledge_fact_access_closed"
    assert b"Northwind" not in result.body
    assert _acme_view(world) == before


def test_mound_fact_sync_route_is_closed_and_writes_no_node(world) -> None:
    from aragora.server.handlers.knowledge_base.mound.sync import SyncOperationsMixin

    mound = MagicMock()
    host = SimpleNamespace(_get_mound=lambda: mound, _auth_context=_v1(world)._auth_context)
    result = SyncOperationsMixin._handle_sync_facts(
        host, _Request(world, _token(world, "acme"), {})
    )
    assert result.status_code == 403
    assert _v1_code(_body(result)) == "knowledge_fact_access_closed"
    assert mound.mock_calls == []


def test_ara_api_keys_keep_todays_reachability(world) -> None:
    body = {"statement": "Key-authenticated create", "workspace_id": "default"}
    r = _v2(world).post(V2 + "/facts", json=body, headers={"Authorization": f"Bearer {world.key}"})
    assert r.status_code == 401
    result = _v1(world)._handle_create_fact(_Request(world, world.key, body))
    assert result.status_code == 201, result.body


def _world_store(world) -> FactStore:
    return FactStore(db_path=world.store.db_path)


def _assert_unscoped_world_store(store, world) -> None:
    assert isinstance(store, FactStore) and not isinstance(store, ScopedFactStore)
    assert store.db_path == world.store.db_path


def _assert_only_operator_sees(world, fid: str, rows: tuple[int, int]) -> None:
    acme = world.callers["acme"].org_id
    stored = ScopedFactStore(world.store, acme).get_fact(fid)
    assert stored is not None and stored.org_id == acme
    assert ScopedFactStore(world.store, world.callers["beta"].org_id).get_fact(fid) is None
    with pytest.raises(OrgScopeRequiredError):
        world.store.get_fact(fid)
    assert _rows(world.store) == rows


def test_v2_default_provider_closes_reads_and_creates_cannot_be_read_back(
    world, monkeypatch
) -> None:
    from aragora.server.fastapi.routes import knowledge_base as routes

    monkeypatch.setattr(routes, "_fact_store_instance", None)
    monkeypatch.setattr(routes, "FactStore", lambda: _world_store(world))
    client = _v2(world)
    client.app.state.context.pop("fact_store")  # type: ignore[attr-defined]
    hdr = {"Authorization": f"Bearer {_token(world, 'acme')}"}
    r = client.get(V2 + "/facts", headers=hdr)
    assert r.status_code == 403 and r.json()["code"] == "knowledge_fact_access_closed"
    before = _rows(world.store)
    body = {"statement": "Acme renews Contoso", "workspace_id": "acme-research"}
    r = client.post(V2 + "/facts", json=body, headers=hdr)
    assert r.status_code == 201, r.text
    _assert_unscoped_world_store(routes._fact_store_instance, world)
    fid, after = r.json()["id"], _rows(world.store)
    assert after[0] == before[0] + 1
    for method in ("GET", "DELETE"):
        r = client.request(method, f"{V2}/facts/{fid}", headers=hdr)
        assert r.status_code == 403 and r.json()["code"] == "knowledge_fact_access_closed"
    _assert_only_operator_sees(world, fid, after)


def test_v1_default_provider_closes_reads_and_creates_cannot_be_read_back(
    world, monkeypatch
) -> None:
    from aragora.server.handlers.knowledge_base import handler as handler_module

    monkeypatch.setattr(handler_module, "FactStore", lambda: _world_store(world))
    handler = _v1(world, org_id=world.callers["acme"].org_id)
    handler._fact_store = None
    bearer = _token(world, "acme")
    result = handler._handle_list_facts({})
    assert result.status_code == 403
    assert _v1_code(_body(result)) == "knowledge_fact_access_closed"
    before = _rows(world.store)
    body = {"statement": "Acme renews Contoso", "workspace_id": "acme-research"}
    result = handler._handle_create_fact(_Request(world, bearer, body))
    assert result.status_code == 201, result.body
    _assert_unscoped_world_store(handler._fact_store, world)
    created = _body(result)
    fid, after = created.get("data", created)["id"], _rows(world.store)
    assert after[0] == before[0] + 1
    for result in (
        handler._handle_get_fact(fid),
        handler._handle_delete_fact(fid, _Request(world, bearer, None)),
    ):
        assert result.status_code == 403
        assert _v1_code(_body(result)) == "knowledge_fact_access_closed"
    _assert_only_operator_sees(world, fid, after)
