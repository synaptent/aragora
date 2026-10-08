"""Org isolation of the FastAPI v2 canvas pipeline routes.

Two orgs (real JWTs), an org-less user and an anonymous caller exercise every
``/api/v2/canvas/pipeline`` route that reads or acts on one pipeline (and the
``/api/v2/pipeline/{id}/agents`` routes) against a real SQLite
``PipelineResultStore``:

* another org's pipeline, an unowned one and a missing one answer the same 404
  body, before any permission check, and writes to them have no effect;
* anonymous callers get 401 everywhere (create routes included) and org-less
  users 403 ``org_required``;
* the owner keeps access, and what it creates belongs to its org.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.execution_ownership import ExecutionNotAuthorizedError
from aragora.pipeline.graph_store import GraphStore
from aragora.pipeline.universal_node import UniversalGraph, UniversalNode
from aragora.server.fastapi import create_app
from aragora.server.fastapi.routes import canvas_pipeline as canvas_routes
from aragora.storage.debate_storage import DebateStorage
from aragora.storage.pipeline_store import PipelineResultStore

ORG_A = "org-a"
ORG_B = "org-b"

PA = "pipe-canvas-a"
PB = "pipe-canvas-b"
PN = "pipe-canvas-null"
PX = "pipe-canvas-missing"
DA = "debate-pipe-a"

PIPELINE_NOT_FOUND = {"error": "Pipeline not found", "code": "not_found"}
DEBATE_NOT_FOUND = {"error": "Debate not found", "code": "not_found"}
CANVAS = "/api/v2/canvas/pipeline"

READS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", CANVAS + "/{id}", None),
    ("GET", CANVAS + "/{id}/status", None),
    ("GET", CANVAS + "/{id}/stage/ideas", None),
    ("GET", CANVAS + "/{id}/graph", None),
    ("GET", CANVAS + "/{id}/receipt", None),
    ("GET", CANVAS + "/{id}/intelligence", None),
    ("GET", CANVAS + "/{id}/beliefs", None),
    ("GET", CANVAS + "/{id}/explanations", None),
    ("GET", CANVAS + "/{id}/precedents", None),
    ("GET", "/api/v2/pipeline/{id}/agents", None),
]
WRITES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", CANVAS + "/{id}/execute", {}),
    ("POST", CANVAS + "/{id}/self-improve", {"dry_run": True}),
    ("POST", CANVAS + "/{id}/approve-transition", {"approved": True}),
    ("POST", "/api/v2/pipeline/{id}/agents/agent-1/approve", None),
    ("POST", "/api/v2/pipeline/{id}/agents/agent-1/reject", None),
    ("PUT", CANVAS + "/{id}", {"canvas_data": {"name": "hijacked"}}),
    ("POST", CANVAS + "/advance", {"pipeline_id": "{id}"}),
]
CREATES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", CANVAS + "/from-debate", {"cartographer_data": {}}),
    ("POST", CANVAS + "/from-ideas", {"ideas": ["anonymous idea"]}),
    ("POST", CANVAS + "/from-braindump", {"text": "anonymous idea"}),
    ("POST", CANVAS + "/from-template", {"template_id": "any"}),
    ("POST", CANVAS + "/from-system-metrics", {}),
    ("POST", CANVAS + "/demo", None),
    ("POST", CANVAS + "/run", {"ideas": ["anonymous idea"]}),
    ("POST", CANVAS + "/auto-run", {"ideas": ["anonymous idea"]}),
    ("POST", CANVAS + "/extract-goals", {"ideas_canvas": {}}),
    ("POST", CANVAS + "/extract-principles", {"ideas": ["x"]}),
    ("POST", "/api/v2/canvas/convert/debate", {"debate_data": {}}),
    ("POST", "/api/v2/canvas/convert/workflow", {"workflow_data": {}}),
    ("POST", f"/api/v2/debates/{DA}/to-pipeline", {}),
]


def _pipeline(pipeline_id: str) -> dict[str, Any]:
    return {
        "pipeline_id": pipeline_id,
        "stage_status": {"ideas": "complete", "goals": "pending"},
        "ideas": {"nodes": [{"id": "idea-1", "data": {"label": f"{pipeline_id} secret idea"}}]},
        "transitions": [{"from_stage": "ideas", "to_stage": "goals", "status": "pending"}],
    }


@pytest.fixture
def store(tmp_path: Path, monkeypatch) -> PipelineResultStore:
    pipeline_store = PipelineResultStore(str(tmp_path / "pipelines.db"))
    pipeline_store.save(PA, _pipeline(PA), org_id=ORG_A, created_by="user-a")
    pipeline_store.save(PB, _pipeline(PB), org_id=ORG_B, created_by="user-b")
    pipeline_store.save(PN, _pipeline(PN))
    monkeypatch.setattr(canvas_routes, "_get_store", lambda: pipeline_store)
    return pipeline_store


@pytest.fixture
def graphs(tmp_path: Path):
    graph_store = GraphStore(db_path=str(tmp_path / "graphs.db"))
    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=graph_store),
        patch("aragora.knowledge.mound.adapters.receipt_adapter.ReceiptAdapter"),
    ):
        yield graph_store


@pytest.fixture(autouse=True)
def _no_live_pipelines(monkeypatch):
    canvas_routes._pipeline_objects.clear()
    # Keep creates away from the Knowledge Mound.
    monkeypatch.setattr(canvas_routes, "_persist_pipeline_to_km", lambda result: None)
    yield
    canvas_routes._pipeline_objects.clear()


@pytest.fixture
def client(store, tmp_path: Path, fastapi_context_builder):
    debates = DebateStorage(str(tmp_path / "debates.db"))
    debates.save_dict(
        {
            "id": DA,
            "task": "Org A debate",
            "agents": ["claude"],
            "rounds": [],
            "consensus_reached": True,
            "confidence": 0.9,
            "final_answer": "answer",
        },
        org_id=ORG_A,
    )
    application = create_app()
    application.state.context = fastapi_context_builder(storage=debates)
    # Not entered as a context manager: the app's startup would replace this context.
    test_client = TestClient(application, raise_server_exceptions=False)
    yield test_client
    application.dependency_overrides.clear()
    test_client.close()


@pytest.fixture
def as_a(fastapi_bearer) -> dict[str, str]:
    return fastapi_bearer("user-a", ORG_A)


@pytest.fixture
def as_b(fastapi_bearer) -> dict[str, str]:
    return fastapi_bearer("user-b", ORG_B)


def _fill(value: Any, pipeline_id: str) -> Any:
    if isinstance(value, str):
        return value.replace("{id}", pipeline_id)
    if isinstance(value, dict):
        return {key: _fill(item, pipeline_id) for key, item in value.items()}
    return value


def _call(client: TestClient, route: tuple[str, str, Any], pipeline_id: str, headers: dict):
    method, template, body = route
    return client.request(
        method, _fill(template, pipeline_id), headers=headers, json=_fill(body, pipeline_id)
    )


def _snapshot(store: PipelineResultStore) -> dict[str, Any]:
    ids = sorted(row.get("pipeline_id") or row["id"] for row in store.list_pipelines(limit=100))
    return {
        "rows": {pid: store.get(pid) for pid in ids},
        "owners": {pid: store.get_owner_org(pid) for pid in ids},
        "live": sorted(canvas_routes._pipeline_objects),
    }


class TestNoScope:
    def test_anonymous_gets_401_on_every_route(self, client, store):
        before = _snapshot(store)

        responses = [_call(client, route, "", {}) for route in CREATES]
        for route in READS + WRITES:
            responses += [_call(client, route, pipeline_id, {}) for pipeline_id in (PA, PX)]

        assert [r.status_code for r in responses] == [401] * len(responses)
        assert _snapshot(store) == before

    def test_org_less_user_gets_org_required(self, client, store, fastapi_bearer):
        no_org = fastapi_bearer("user-solo", None)
        before = _snapshot(store)

        responses = [
            client.get(f"{CANVAS}/{PA}", headers=no_org),
            client.put(f"{CANVAS}/{PA}", headers=no_org, json={"canvas_data": {"x": 1}}),
            client.post(f"{CANVAS}/from-ideas", headers=no_org, json={"ideas": ["x"]}),
            client.get(f"/api/v2/pipeline/{PA}/agents", headers=no_org),
        ]

        assert [r.status_code for r in responses] == [403] * len(responses)
        assert {r.json()["code"] for r in responses} == {"org_required"}
        assert _snapshot(store) == before


class TestOtherOrg:
    @pytest.mark.parametrize("route", READS + WRITES, ids=lambda r: f"{r[0]} {r[1]}")
    def test_other_org_pipeline_answers_like_a_missing_one(self, client, store, as_b, route):
        before = _snapshot(store)

        answers = [_call(client, route, pipeline_id, as_b) for pipeline_id in (PA, PN, PX)]

        for response in answers:
            assert response.status_code == 404
            assert response.json() == PIPELINE_NOT_FOUND
        assert _snapshot(store) == before

    def test_live_pipeline_object_does_not_bypass_the_stored_owner(self, client, as_b):
        canvas_routes._pipeline_objects[PA] = MagicMock(pipeline_id=PA)

        read = client.get(f"{CANVAS}/{PA}", headers=as_b)
        advance = client.post(f"{CANVAS}/advance", headers=as_b, json={"pipeline_id": PA})

        assert (read.status_code, read.json()) == (404, PIPELINE_NOT_FOUND)
        assert (advance.status_code, advance.json()) == (404, PIPELINE_NOT_FOUND)

    def test_other_org_viewer_gets_404_not_403(self, client, store, fastapi_bearer):
        """Ownership is checked before the permission, so the answer never depends on the role."""
        viewer_b = fastapi_bearer("viewer-b", ORG_B, role="viewer")
        before = _snapshot(store)

        responses = [_call(client, route, PA, viewer_b) for route in READS + WRITES]

        assert [r.status_code for r in responses] == [404] * len(responses)
        assert _snapshot(store) == before

    def test_debate_to_pipeline_needs_the_debates_org(self, client, store, as_b):
        before = _snapshot(store)

        foreign = client.post(f"/api/v2/debates/{DA}/to-pipeline", headers=as_b, json={})
        missing = client.post("/api/v2/debates/debate-missing/to-pipeline", headers=as_b, json={})

        assert (foreign.status_code, foreign.json()) == (404, DEBATE_NOT_FOUND)
        assert (missing.status_code, missing.json()) == (404, DEBATE_NOT_FOUND)
        assert _snapshot(store) == before


class TestOwner:
    @pytest.mark.parametrize("route", READS, ids=lambda r: r[1])
    def test_owner_reads_its_stored_pipeline(self, client, as_a, route):
        response = _call(client, route, PA, as_a)

        assert response.status_code == 200
        assert response.json()["pipeline_id"] == PA

    def test_owner_reads_pipeline_content(self, client, as_a):
        detail = client.get(f"{CANVAS}/{PA}", headers=as_a)

        assert detail.status_code == 200
        assert f"{PA} secret idea" in detail.text

    def test_owner_saves_canvas_state_but_put_creates_nothing(self, client, store, as_a):
        saved = client.put(
            f"{CANVAS}/{PA}",
            headers=as_a,
            json={"canvas_data": {"stage_status": {"ideas": "complete", "goals": "complete"}}},
        )
        missing = client.put(f"{CANVAS}/{PX}", headers=as_a, json={"canvas_data": {"x": 1}})

        assert saved.status_code == 200
        assert store.get(PA)["stage_status"]["goals"] == "complete"
        assert store.get_owner_org(PA) == ORG_A
        assert (missing.status_code, missing.json()) == (404, PIPELINE_NOT_FOUND)
        assert store.get(PX) is None

    def test_created_pipeline_belongs_to_the_creators_org(self, client, store, as_a, as_b):
        created = client.post(f"{CANVAS}/from-ideas", headers=as_a, json={"ideas": ["Org A idea"]})

        assert created.status_code == 201
        pipeline_id = created.json()["pipeline_id"]
        assert store.get_owner_org(pipeline_id) == ORG_A
        assert client.get(f"{CANVAS}/{pipeline_id}/status", headers=as_a).status_code == 200
        hidden = client.get(f"{CANVAS}/{pipeline_id}/status", headers=as_b)
        assert (hidden.status_code, hidden.json()) == (404, PIPELINE_NOT_FOUND)

    def test_debate_to_pipeline_belongs_to_the_debates_org(self, client, store, as_a):
        created = client.post(f"/api/v2/debates/{DA}/to-pipeline", headers=as_a, json={})

        assert created.status_code == 201
        assert store.get_owner_org(created.json()["pipeline_id"]) == ORG_A

    def test_execute_queues_the_plan_for_the_callers_org(self, client, store, as_a):
        complete = dict.fromkeys(("ideas", "goals", "actions", "orchestration"), "complete")
        store.save(PA, {**_pipeline(PA), "stage_status": complete})
        with (
            patch(
                "aragora.pipeline.canonical_execution.build_decision_plan_from_orchestration",
                return_value=(MagicMock(id="plan-a"), []),
            ),
            patch(
                "aragora.pipeline.canonical_execution.queue_plan_execution",
                side_effect=ExecutionNotAuthorizedError("plan_owner_mismatch", "refused"),
            ) as queue,
        ):
            response = client.post(f"{CANVAS}/{PA}/execute", headers=as_a, json={})

        assert (response.status_code, response.json()) == (404, PIPELINE_NOT_FOUND)
        assert queue.call_args.kwargs["org_id"] == ORG_A
        assert queue.call_args.kwargs["created_by"] == "user-a"
        assert "execution" not in store.get(PA)

    def test_orgs_creating_from_ideas_keep_their_own_graph_nodes(
        self, client, store, graphs, as_a, as_b
    ):
        """Every from-ideas graph has a ``raw-idea-0``; one org's never replaces another's."""
        created = {}
        for org, headers, idea in ((ORG_A, as_a, "Org A secret idea"), (ORG_B, as_b, "B idea")):
            response = client.post(
                f"{CANVAS}/from-ideas",
                headers=headers,
                json={"ideas": [idea, f"{idea} two"], "use_universal": True},
            )
            assert response.status_code == 201
            created[org] = response.json()["pipeline_id"]

        for org, idea in ((ORG_A, "Org A secret idea"), (ORG_B, "B idea")):
            graph_id = f"ugraph-{created[org]}"
            graph = graphs.get(graph_id)
            assert graph is not None
            assert graphs.get_owner_org(graph_id) == org
            assert graph.nodes["raw-idea-0"].label == idea
            assert graph.nodes["raw-idea-1"].label == f"{idea} two"

    def test_receipt_reads_graph_nodes_only_for_the_graphs_org(self, client, graphs, as_a, as_b):
        """B's pipeline named like A's graph gets a receipt without A's nodes."""
        for graph_id, node_id, label in (
            (PB, "idea-x", "A graph secret"),
            (PA, "idea-1", "A own idea"),
        ):
            graph = UniversalGraph(id=graph_id, name="A graph")
            graph.nodes[node_id] = UniversalNode(
                id=node_id, stage=PipelineStage.IDEAS, node_subtype="concept", label=label
            )
            graphs.create(graph, org_id=ORG_A, created_by="user-a")

        foreign = client.get(f"{CANVAS}/{PB}/receipt", headers=as_b)
        own = client.get(f"{CANVAS}/{PA}/receipt", headers=as_a)

        assert foreign.status_code == 200
        assert "A graph secret" not in foreign.text
        assert foreign.json()["receipt"]["provenance"]["ideas"] == []
        assert own.status_code == 200
        assert own.json()["receipt"]["provenance"]["ideas"] == [
            {"id": "idea-1", "label": "A own idea", "type": "concept"}
        ]

    def test_viewer_of_the_owning_org_gets_403(self, client, store, fastapi_bearer):
        viewer_a = fastapi_bearer("viewer-a", ORG_A, role="viewer")
        before = _snapshot(store)

        read = client.get(f"{CANVAS}/{PA}", headers=viewer_a)
        save = client.put(f"{CANVAS}/{PA}", headers=viewer_a, json={"canvas_data": {"x": 1}})

        assert read.status_code == 403
        assert save.status_code == 403
        assert _snapshot(store) == before
