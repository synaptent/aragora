"""Org isolation of pipeline execute (E1) and pipeline transitions (E4).

Requests go through ``handle`` / ``handle_post`` with real graph and pipeline
stores and the real RBAC checker. Org A owns the graph ``pipe-a`` (with one
orchestration node) and the saved pipeline ``saved-a``; B is a member of
another org.
"""

from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.canvas.stages import PipelineStage
from aragora.pipeline.execution_ownership import ExecutionNotAuthorizedError
from aragora.pipeline.graph_store import GraphStore
from aragora.pipeline.universal_node import UniversalGraph, UniversalNode
from aragora.server.handlers.pipeline import execute as execute_module
from aragora.server.handlers.pipeline import transitions as transitions_module
from aragora.server.handlers.pipeline.execute import PipelineExecuteHandler
from aragora.server.handlers.pipeline.transitions import PipelineTransitionsHandler
from aragora.storage.pipeline_store import PipelineResultStore

pytestmark = pytest.mark.no_auto_auth

USER_A = SimpleNamespace(is_authenticated=True, user_id="user-a", org_id="org-a", role="owner")
USER_B = SimpleNamespace(is_authenticated=True, user_id="user-b", org_id="org-b", role="owner")
ANONYMOUS = SimpleNamespace(is_authenticated=False, user_id=None, org_id=None, role=None)

PA = "pipe-a"
SAVED_A = "saved-a"
MISSING = "pipe-missing"
NOT_FOUND = {"error": "Pipeline not found", "code": "not_found"}

TRANSITION_POSTS = {
    "ideas-to-goals": {"ideas": [{"id": "idea-b", "label": "B idea"}]},
    "goals-to-tasks": {"goals": [{"id": "goal-b", "label": "B goal"}]},
    "tasks-to-workflow": {"tasks": [{"id": "task-b", "label": "B task"}]},
    "execute": {"nodes": [{"id": "orch-b"}]},
}


class _Request:
    def __init__(self, caller: Any, body: dict[str, Any] | None = None) -> None:
        self.caller = caller
        self.client_address = ("127.0.0.1", 12345)
        raw = json.dumps(body or {}).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = MagicMock()
        self.rfile.read.return_value = raw


def _json(result: Any) -> Any:
    return json.loads(result.body)


@pytest.fixture(autouse=True)
def _identity():
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request",
        side_effect=lambda handler, user_store=None: handler.caller,
    ):
        yield


@pytest.fixture(autouse=True)
def _clear_memory():
    execute_module._executions.clear()
    execute_module._execution_tasks.clear()
    execute_module._execute_limiter._buckets.clear()
    transitions_module._transition_limiter._buckets.clear()
    with (
        patch.object(transitions_module, "_org_node_stores", {}, create=True),
        patch.dict(transitions_module._node_store, clear=True),
    ):
        yield
    execute_module._executions.clear()
    execute_module._execution_tasks.clear()


@pytest.fixture
def stores(tmp_path):
    graphs = GraphStore(db_path=str(tmp_path / "graphs.db"))
    graph = UniversalGraph(id=PA, name="A graph")
    graph.nodes["orch-1"] = UniversalNode(
        id="orch-1",
        stage=PipelineStage.ORCHESTRATION,
        node_subtype="agent_task",
        label="Ship it",
        data={"stage": "orchestration", "label": "Ship it", "orch_type": "agent_task"},
    )
    graphs.create(graph, org_id="org-a", created_by="user-a")
    pipelines = PipelineResultStore(str(tmp_path / "pipelines.db"))
    pipelines.save(
        SAVED_A,
        {"pipeline_id": SAVED_A, "stage_status": {"ideas": "complete", "goals": "pending"}},
        org_id="org-a",
        created_by="user-a",
    )
    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=graphs),
        patch("aragora.storage.pipeline_store.get_pipeline_store", return_value=pipelines),
    ):
        yield SimpleNamespace(graphs=graphs, pipelines=pipelines)


@pytest.fixture
def queue():
    launch = {
        "plan_id": "plan-1",
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
        "status": "queued",
    }
    with (
        patch(
            "aragora.pipeline.canonical_execution.queue_plan_execution", return_value=launch
        ) as queued,
        patch.object(PipelineExecuteHandler, "_execute_pipeline", new_callable=AsyncMock),
    ):
        yield queued


def _execute_path(pipeline_id: str) -> str:
    return f"/api/v1/pipeline/{pipeline_id}/execute"


async def _start(caller: Any, pipeline_id: str) -> Any:
    handler = PipelineExecuteHandler()
    return await handler.handle_post(_execute_path(pipeline_id), {}, _Request(caller))


def _status(caller: Any, pipeline_id: str) -> Any:
    return PipelineExecuteHandler().handle(_execute_path(pipeline_id), {}, _Request(caller))


# ---------------------------------------------------------------------------
# Pipeline execute (E1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_other_org_execute_is_the_missing_pipeline_404_and_starts_nothing(
    stores, queue
) -> None:
    other = await _start(USER_B, PA)
    missing = await _start(USER_B, MISSING)

    assert other.status_code == missing.status_code == 404
    assert other.body == missing.body
    assert _json(other) == NOT_FOUND
    queue.assert_not_called()
    assert execute_module._executions == {}
    assert _json(_status(USER_A, PA))["status"] == "not_started"


@pytest.mark.parametrize("pipeline_id", [PA, SAVED_A])
def test_other_org_status_is_the_missing_pipeline_404(stores, pipeline_id) -> None:
    other = _status(USER_B, pipeline_id)
    missing = _status(USER_B, MISSING)

    assert other.status_code == missing.status_code == 404
    assert other.body == missing.body


@pytest.mark.asyncio
async def test_anonymous_execute_and_status_are_401(stores, queue) -> None:
    started = await _start(ANONYMOUS, PA)
    status = _status(ANONYMOUS, PA)

    assert started.status_code == 401
    assert status.status_code == 401
    queue.assert_not_called()


@pytest.mark.asyncio
async def test_owner_starts_execution_owned_by_its_org(stores, queue) -> None:
    started = await _start(USER_A, PA)

    assert started.status_code == 202
    assert queue.call_args.kwargs["org_id"] == "org-a"
    assert queue.call_args.kwargs["created_by"] == "user-a"
    assert execute_module._executions[PA]["org_id"] == "org-a"

    status = _status(USER_A, PA)
    assert status.status_code == 200
    assert _json(status)["status"] == "started"
    assert _status(USER_B, PA).status_code == 404


def test_owner_reads_status_of_saved_pipeline_without_graph(stores) -> None:
    result = _status(USER_A, SAVED_A)

    assert result.status_code == 200
    assert _json(result) == {"pipeline_id": SAVED_A, "status": "not_started"}


def test_execution_state_of_another_org_reads_as_not_started(stores) -> None:
    execute_module._executions[PA] = {"pipeline_id": PA, "status": "running", "org_id": "org-b"}

    result = _status(USER_A, PA)

    assert result.status_code == 200
    assert _json(result) == {"pipeline_id": PA, "status": "not_started"}


@pytest.mark.asyncio
async def test_graph_owner_decides_over_a_saved_pipeline_of_the_same_id(stores, queue) -> None:
    stores.graphs.create(UniversalGraph(id="shared-id"), org_id="org-b", created_by="user-b")
    stores.pipelines.save("shared-id", {"pipeline_id": "shared-id"}, org_id="org-a")

    result = await _start(USER_A, "shared-id")

    assert result.status_code == 404
    queue.assert_not_called()


@pytest.mark.asyncio
async def test_refused_execution_is_404_and_leaves_no_state(stores, queue) -> None:
    queue.side_effect = ExecutionNotAuthorizedError("plan_org_mismatch", "refused")

    result = await _start(USER_A, PA)

    assert result.status_code == 404
    assert _json(result) == NOT_FOUND
    assert PA not in execute_module._executions


def test_owner_lookup_failure_hides_the_pipeline(stores) -> None:
    with patch.object(stores.graphs, "get", side_effect=sqlite3.OperationalError("locked")):
        result = _status(USER_A, PA)

    assert result.status_code == 404


# ---------------------------------------------------------------------------
# Pipeline transitions (E4)
# ---------------------------------------------------------------------------


def _transition(caller: Any, route: str, body: dict[str, Any]) -> Any:
    handler = PipelineTransitionsHandler()
    path = f"/api/v1/pipeline/transitions/{route}"
    return handler.handle_post(path, {"mode": "heuristic"}, _Request(caller, body))


def _provenance(caller: Any, node_id: str) -> Any:
    path = f"/api/v1/pipeline/transitions/{node_id}/provenance"
    return PipelineTransitionsHandler().handle(path, {}, _Request(caller))


@pytest.mark.parametrize("route", sorted(TRANSITION_POSTS))
def test_anonymous_transitions_are_401(stores, route) -> None:
    assert _transition(ANONYMOUS, route, TRANSITION_POSTS[route]).status_code == 401


def test_anonymous_provenance_is_401(stores) -> None:
    assert _provenance(ANONYMOUS, "idea-a").status_code == 401


@pytest.mark.parametrize("route", sorted(TRANSITION_POSTS))
@pytest.mark.parametrize(
    ("reference", "owned_id"), [("pipeline_id", PA), ("pipeline_id", SAVED_A), ("graph_id", PA)]
)
def test_other_org_reference_is_404_with_no_side_effect(stores, route, reference, owned_id) -> None:
    before = stores.pipelines.get(SAVED_A)

    other = _transition(USER_B, route, {**TRANSITION_POSTS[route], reference: owned_id})
    missing = _transition(USER_B, route, {**TRANSITION_POSTS[route], reference: MISSING})

    assert other.status_code == missing.status_code == 404
    assert other.body == missing.body
    assert _json(other) == NOT_FOUND
    assert transitions_module.get_node_store("org-b") == {}
    assert stores.pipelines.get(SAVED_A) == before


@pytest.mark.parametrize("route", sorted(TRANSITION_POSTS))
def test_owner_reference_is_accepted(stores, route) -> None:
    result = _transition(USER_A, route, {**TRANSITION_POSTS[route], "pipeline_id": PA})

    assert result.status_code == 200


def test_nodes_are_kept_per_org(stores) -> None:
    created = _transition(
        USER_A, "ideas-to-goals", {"ideas": [{"id": "idea-a", "label": "A secret idea"}]}
    )
    assert created.status_code == 200

    other = _provenance(USER_B, "idea-a")
    missing = _provenance(USER_B, "idea-missing")
    assert other.status_code == missing.status_code == 404
    assert _json(other)["error"] == "Node 'idea-a' not found"

    overwrite = _transition(USER_B, "ideas-to-goals", {"ideas": [{"id": "idea-a", "label": "B"}]})
    assert overwrite.status_code == 200

    own = _provenance(USER_A, "idea-a")
    assert own.status_code == 200
    assert _json(own)["chain"][0]["label"] == "A secret idea"
    assert transitions_module._node_store == {}
