"""The v2 knowledge routes require the v1 permission and confine Mound items to the caller's org."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from aragora.billing.jwt_auth import create_access_token

ITEM = "/api/v2/knowledge/items"
SEARCHES = [
    ("GET", "/api/v2/knowledge/search?query=roadmap", None),
    ("POST", "/api/v2/knowledge/search", {"query": "roadmap"}),
    ("POST", "/api/v2/knowledge/query", {"query": "roadmap"}),
]
READS = [
    *SEARCHES,
    ("GET", "/api/v2/knowledge/stats", None),
    ("GET", "/api/v2/knowledge/gaps", None),
    ("GET", "/api/v2/knowledge/adapters", None),
    ("GET", "/api/v2/knowledge/staleness", None),
    ("GET", f"{ITEM}/kn_missing", None),
]
WRITES = [
    ("POST", ITEM, {"title": "t", "content": "c"}),
    ("DELETE", "/api/v2/knowledge/kn_missing", None),
]
ROUTES = READS + WRITES


@pytest.fixture
def world(tmp_path, monkeypatch):
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "VOYAGE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    from aragora.knowledge.mound import KnowledgeMound, MoundBackend, MoundConfig
    from aragora.server.fastapi import create_app
    from aragora.storage.user_store import UserStore

    users = UserStore(tmp_path / "users.db")
    callers: dict[str, SimpleNamespace] = {}
    for name in ("acme", "beta"):
        owner = users.create_user(f"owner@{name}.example", "x" * 64, "s" * 32, role="owner")
        org = users.create_organization(name.title(), owner.id, slug=name)
        users.update_user(owner.id, org_id=org.id, role="owner")
        callers[name] = SimpleNamespace(id=owner.id, email=owner.email, org=org.id, role="owner")
    viewer = users.create_user("viewer@acme.example", "x" * 64, "s" * 32, role="viewer")
    users.update_user(viewer.id, org_id=callers["acme"].org, role="viewer")
    callers["viewer"] = SimpleNamespace(
        id=viewer.id, email=viewer.email, org=callers["acme"].org, role="viewer"
    )
    loner = users.create_user("loner@example.com", "x" * 64, "s" * 32, role="owner")
    callers["no-org"] = SimpleNamespace(id=loner.id, email=loner.email, org=None, role="owner")

    km = KnowledgeMound(
        config=MoundConfig(backend=MoundBackend.SQLITE, sqlite_path=tmp_path / "mound.db"),
        workspace_id="default",
    )
    stamps = {
        "acme": {"org_id": callers["acme"].org},
        "beta": {"org_id": callers["beta"].org},
        "unstamped": {},
    }

    async def seed() -> dict[str, str]:
        await km.initialize()
        return {who: await km.add(f"roadmap note {who}", metadata=m) for who, m in stamps.items()}

    ids = asyncio.run(seed())
    app = create_app()
    app.state.context = {"knowledge_mound": km, "user_store": users}
    app.state.user_store = users
    client = TestClient(app, raise_server_exceptions=False)
    return SimpleNamespace(app=app, client=client, callers=callers, ids=ids)


def _call(world, who: str | None, method: str, path: str, body: dict | None = None):
    headers = {}
    if who is not None:
        c = world.callers[who]
        headers["Authorization"] = f"Bearer {create_access_token(c.id, c.email, c.org, c.role)}"
    return world.client.request(method, path, json=body, headers=headers)


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_every_route_rejects_anonymous_callers(world, method, path, body) -> None:
    assert _call(world, None, method, path, body).status_code == 401


@pytest.mark.parametrize(
    ("method", "path", "body", "permission"),
    [(*r, "knowledge:read") for r in READS] + [(*w, "knowledge:write") for w in WRITES],
)
def test_every_route_requires_the_v1_permission(world, method, path, body, permission) -> None:
    response = _call(world, "viewer", method, path, body)
    assert response.status_code == 403
    assert f"Permission denied: {permission}" in response.text


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_callers_without_an_org_fail_closed(world, method, path, body) -> None:
    response = _call(world, "no-org", method, path, body)
    assert response.status_code == 403
    assert response.json()["code"] == "knowledge_org_required"


@pytest.mark.parametrize(("method", "path", "body"), SEARCHES)
def test_searches_return_only_the_callers_stamped_items(world, method, path, body) -> None:
    for who in ("acme", "beta"):
        response = _call(world, who, method, path, body)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == [world.ids[who]]
        assert response.json()["total"] == 1


def test_item_reads_and_deletes_never_reach_another_orgs_or_an_unstamped_item(world) -> None:
    own = _call(world, "acme", "GET", f"{ITEM}/{world.ids['acme']}")
    assert own.status_code == 200, own.text
    assert own.json()["metadata"]["org_id"] == world.callers["acme"].org
    for victim in ("beta", "unstamped"):
        assert _call(world, "acme", "GET", f"{ITEM}/{world.ids[victim]}").status_code == 404
        assert (
            _call(world, "acme", "DELETE", f"/api/v2/knowledge/{world.ids[victim]}").status_code
            == 404
        )
    assert _call(world, "beta", "GET", f"{ITEM}/{world.ids['beta']}").status_code == 200
    deleted = _call(world, "acme", "DELETE", f"/api/v2/knowledge/{world.ids['acme']}")
    assert deleted.status_code == 200, deleted.text


def test_ingest_stamps_the_callers_org_over_a_body_org(world) -> None:
    recorder = MagicMock(spec=["ingest"])
    world.app.state.context["knowledge_mound"] = recorder
    body = {"title": "t", "content": "c", "metadata": {"org_id": world.callers["beta"].org, "k": 1}}
    response = _call(world, "acme", "POST", ITEM, body)
    assert response.status_code == 201, response.text
    (written,), _ = recorder.ingest.call_args
    assert written["metadata"] == {"org_id": world.callers["acme"].org, "k": 1}
    assert response.json()["item"]["metadata"]["org_id"] == world.callers["acme"].org


def test_staleness_withholds_items_without_the_callers_stamp(world) -> None:
    acme, beta = world.callers["acme"].org, world.callers["beta"].org
    entries = [
        {"id": "own", "metadata": {"org_id": acme}},
        {"id": "other", "metadata": {"org_id": beta}},
        {"id": "unstamped"},
    ]
    stale_km = MagicMock(spec=["get_staleness"])
    stale_km.get_staleness.return_value = {"total_items": 3, "stale_items": 3, "items": entries}
    world.app.state.context["knowledge_mound"] = stale_km
    response = _call(world, "acme", "GET", "/api/v2/knowledge/staleness")
    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == ["own"]


def test_gaps_attribute_detector_records_through_the_items_they_name(world, monkeypatch) -> None:
    from aragora.knowledge.gap_detector import Contradiction, StaleKnowledge

    ids = world.ids

    def stale(who: str) -> StaleKnowledge:
        return StaleKnowledge(ids[who], f"note {who}", "d", 120.0, 0.5, None, 0.9)

    def clash(a: str, b: str) -> Contradiction:
        return Contradiction(ids[a], ids[b], a, b, "d", 0.8)

    class _Detector:
        def __init__(self, mound, workspace_id) -> None:
            pass

        async def detect_staleness(self, max_age_days):
            return [stale(who) for who in ("acme", "beta", "unstamped")]

        async def detect_contradictions(self):
            return [clash("acme", "acme"), clash("acme", "beta"), clash("unstamped", "acme")]

    monkeypatch.setattr("aragora.knowledge.gap_detector.KnowledgeGapDetector", _Detector)
    for who in ("acme", "beta"):
        gaps = _call(world, who, "GET", "/api/v2/knowledge/gaps")
        assert gaps.status_code == 200, gaps.text
        assert [entry["id"] for entry in gaps.json()["stale_entries"]] == [ids[who]]
    pairs = [(c["item_a_id"], c["item_b_id"]) for c in gaps.json()["contradictions"]]
    assert pairs == []
    acme = _call(world, "acme", "GET", "/api/v2/knowledge/gaps").json()
    pairs = [(c["item_a_id"], c["item_b_id"]) for c in acme["contradictions"]]
    assert pairs == [(ids["acme"], ids["acme"])]
