"""Org isolation of the FastAPI v2 pipeline run routes (``/api/v2/pipeline/runs``).

Two orgs (real JWTs), an org-less user and an anonymous caller exercise every
run route against the in-memory run store:

* another org's run, a run with no recorded org and a missing one answer the
  same 404 body, before any permission check, and writes to them have no effect;
* the run list only shows the caller org's runs;
* anonymous callers get 401 everywhere (create included) and org-less users
  403 ``org_required``;
* the owner keeps access, and a run it starts belongs to its org.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app

ORG_A = "org-a"
ORG_B = "org-b"

RA = "pipe-run-a"
RA_DONE = "pipe-run-a-done"
RB = "pipe-run-b"
RN = "pipe-run-null"
RX = "pipe-run-missing"

RUN_NOT_FOUND = {"error": "Pipeline run not found", "code": "not_found"}
ORG_REQUIRED = "org_required"
RUNS = "/api/v2/pipeline/runs"

RUN_READS: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", RUNS + "/{id}", None),
    ("GET", RUNS + "/{id}/stages", None),
]
RUN_WRITES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("POST", RUNS + "/{id}/approve", {"stage": "goals"}),
    ("DELETE", RUNS + "/{id}", None),
    ("POST", RUNS + "/{id}/execute-workflow", None),
]


def _stage(name: str, status: str) -> dict[str, Any]:
    return {
        "stage_name": name,
        "status": status,
        "output": None,
        "started_at": None,
        "completed_at": None,
        "duration": 0.0,
        "error": None,
    }


def _run(run_id: str, org_id: str | None, status: str = "running") -> dict[str, Any]:
    run: dict[str, Any] = {
        "id": run_id,
        "idea": f"{run_id} private idea",
        "status": status,
        "stages": [_stage("ideation", "completed"), _stage("goals", "pending")],
        "created_at": "2026-10-08T10:00:00",
        "updated_at": "2026-10-08T10:00:00",
        "config": {},
        "result": {
            "pipeline_id": run_id,
            "goals": {
                "id": f"gg-{run_id}",
                "goals": [{"id": "goal-1", "title": "Ship it", "type": "goal"}],
                "metadata": {},
            },
        },
    }
    if org_id:
        run["org_id"] = org_id
        run["created_by"] = f"user-{org_id}"
    return run


@pytest.fixture
def runs() -> dict[str, dict[str, Any]]:
    return {
        RA: _run(RA, ORG_A),
        RA_DONE: _run(RA_DONE, ORG_A, status="completed"),
        RB: _run(RB, ORG_B),
        RN: _run(RN, None),
    }


@pytest.fixture
def client(runs, fastapi_context_builder):
    application = create_app()
    application.state.context = fastapi_context_builder(pipeline_store=runs)
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


def _call(client: TestClient, route: tuple[str, str, Any], run_id: str, headers: dict):
    method, template, body = route
    return client.request(method, template.replace("{id}", run_id), headers=headers, json=body)


class TestNoScope:
    def test_anonymous_gets_401_on_every_route(self, client, runs):
        before = copy.deepcopy(runs)

        responses = [client.get(RUNS), client.post(RUNS, json={"idea": "anonymous idea"})]
        for route in RUN_READS + RUN_WRITES:
            responses += [_call(client, route, run_id, {}) for run_id in (RA, RX)]

        assert [r.status_code for r in responses] == [401] * len(responses)
        assert runs == before

    def test_org_less_user_gets_org_required(self, client, runs, fastapi_bearer):
        no_org = fastapi_bearer("user-solo", None)
        before = copy.deepcopy(runs)

        responses = [
            client.get(RUNS, headers=no_org),
            client.post(RUNS, headers=no_org, json={"idea": "no org"}),
            client.get(f"{RUNS}/{RA}", headers=no_org),
            client.delete(f"{RUNS}/{RA}", headers=no_org),
        ]

        assert [r.status_code for r in responses] == [403] * len(responses)
        assert {r.json()["code"] for r in responses} == {ORG_REQUIRED}
        assert runs == before


class TestOtherOrg:
    @pytest.mark.parametrize("route", RUN_READS + RUN_WRITES, ids=lambda r: f"{r[0]} {r[1]}")
    def test_other_org_run_answers_like_a_missing_one(self, client, runs, as_b, route):
        before = copy.deepcopy(runs)

        answers = [_call(client, route, run_id, as_b) for run_id in (RA, RN, RX)]

        for response in answers:
            assert response.status_code == 404
            assert response.json() == RUN_NOT_FOUND
        assert runs == before

    def test_other_org_viewer_gets_404_not_403(self, client, runs, fastapi_bearer):
        """Ownership is checked before the permission, so the answer never depends on the role."""
        viewer_b = fastapi_bearer("viewer-b", ORG_B, role="viewer")
        before = copy.deepcopy(runs)

        responses = [_call(client, route, RA, viewer_b) for route in RUN_READS + RUN_WRITES]

        assert [r.status_code for r in responses] == [404] * len(responses)
        assert runs == before

    def test_list_shows_only_the_callers_org(self, client, as_a, as_b):
        listed_a = client.get(RUNS, headers=as_a).json()
        listed_b = client.get(RUNS, headers=as_b).json()

        assert {r["id"] for r in listed_a["runs"]} == {RA, RA_DONE}
        assert listed_a["total"] == 2
        assert {r["id"] for r in listed_b["runs"]} == {RB}
        assert listed_b["total"] == 1


class TestOwner:
    def test_owner_reads_its_run(self, client, as_a):
        detail = client.get(f"{RUNS}/{RA}", headers=as_a)
        stages = client.get(f"{RUNS}/{RA}/stages", headers=as_a)

        assert detail.status_code == 200
        assert detail.json()["idea"] == f"{RA} private idea"
        assert "org_id" not in detail.json()
        assert stages.status_code == 200
        assert stages.json()["total"] == 2

    def test_owner_approves_and_cancels_its_run(self, client, runs, as_a):
        approved = client.post(f"{RUNS}/{RA}/approve", headers=as_a, json={"stage": "goals"})
        assert approved.status_code == 200
        assert runs[RA]["stages"][1]["status"] == "completed"

        runs[RA]["status"] = "running"
        cancelled = client.delete(f"{RUNS}/{RA}", headers=as_a)
        assert cancelled.status_code == 200
        assert runs[RA]["status"] == "cancelled"

    def test_created_run_belongs_to_the_creators_org(self, client, runs, as_a, as_b):
        with patch(
            "aragora.server.fastapi.routes.pipeline._execute_pipeline",
            side_effect=ImportError("pipeline backend unavailable"),
        ):
            created = client.post(RUNS, headers=as_a, json={"idea": "Org A new idea"})

        assert created.status_code == 201
        run_id = created.json()["id"]
        assert runs[run_id]["org_id"] == ORG_A
        assert runs[run_id]["created_by"] == "user-a"
        assert client.get(f"{RUNS}/{run_id}", headers=as_a).status_code == 200
        hidden = client.get(f"{RUNS}/{run_id}", headers=as_b)
        assert (hidden.status_code, hidden.json()) == (404, RUN_NOT_FOUND)

    def test_owner_without_the_permission_gets_403(self, client, runs, fastapi_bearer):
        """A viewer of org A reaches its org's run and is then refused by RBAC."""
        viewer_a = fastapi_bearer("viewer-a", ORG_A, role="viewer")
        before = copy.deepcopy(runs)

        read = client.get(f"{RUNS}/{RA}", headers=viewer_a)
        cancel = client.delete(f"{RUNS}/{RA}", headers=viewer_a)

        assert read.status_code == 403
        assert cancel.status_code == 403
        assert runs == before

    def test_member_cannot_cancel_without_canvas_delete(self, client, runs, fastapi_bearer):
        member_a = fastapi_bearer("member-a", ORG_A, role="member")

        read = client.get(f"{RUNS}/{RA}", headers=member_a)
        cancel = client.delete(f"{RUNS}/{RA}", headers=member_a)

        assert read.status_code == 200
        assert cancel.status_code == 403
        assert runs[RA]["status"] == "running"


class _CompletedEngine:
    async def execute(self, workflow, inputs, execution_id, **_options):
        return SimpleNamespace(
            success=True, final_output={}, steps=[], error=None, total_duration_ms=1.0
        )


class TestExecuteWorkflowTenant:
    @pytest.fixture
    def workflows(self, tmp_path, monkeypatch) -> SimpleNamespace:
        """A real workflow store, an engine that completes at once, recorded audit events."""
        from aragora.server.handlers import workflows as workflows_package
        from aragora.workflow.persistent_store import PersistentWorkflowStore

        store = PersistentWorkflowStore(db_path=tmp_path / "workflows.db")
        audits: list[dict[str, Any]] = []
        monkeypatch.setattr(workflows_package, "_get_store", lambda: store)
        monkeypatch.setattr(workflows_package, "_engine", _CompletedEngine(), raising=False)
        monkeypatch.setattr(workflows_package, "audit_data", lambda **event: audits.append(event))
        return SimpleNamespace(store=store, audits=audits)

    @pytest.mark.parametrize("header", ["X-Workspace-ID", "X-Tenant-ID"])
    def test_tenant_headers_cannot_move_the_rows_to_another_org(
        self, client, runs, as_b, workflows, header
    ):
        response = client.post(
            f"{RUNS}/{RB}/execute-workflow", headers={**as_b, header: ORG_A}, json=None
        )

        assert response.status_code == 201, response.text[:300]
        workflow_id = response.json()["workflow_id"]
        execution_id = response.json()["execution_id"]
        assert workflows.store.list_workflows(tenant_id=ORG_A) == ([], 0)
        assert workflows.store.list_executions(tenant_id=ORG_A) == ([], 0)
        created, _total = workflows.store.list_workflows(tenant_id=ORG_B)
        executed, _total = workflows.store.list_executions(tenant_id=ORG_B)
        assert [w.id for w in created] == [workflow_id]
        assert [e["id"] for e in executed] == [execution_id]
        assert {event["tenant_id"] for event in workflows.audits} == {ORG_B}
        assert runs[RB]["workflow_id"] == workflow_id
