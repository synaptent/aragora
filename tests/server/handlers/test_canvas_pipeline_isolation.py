"""Org isolation of the canvas pipeline routes (CanvasPipelineHandler dispatch).

Requests go through ``handle`` / ``handle_post`` / ``handle_put`` as the
server calls them, with a real ``PipelineResultStore`` and the real RBAC
checker. Org A owns ``pipe-a``; B is a member of another org.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.handlers.canvas import canvas_pipeline as module
from aragora.server.handlers.canvas.canvas_pipeline import CanvasPipelineHandler
from aragora.storage.pipeline_store import PipelineResultStore

pytestmark = pytest.mark.no_auto_auth

USER_A = SimpleNamespace(is_authenticated=True, user_id="user-a", org_id="org-a", role="owner")
USER_B = SimpleNamespace(is_authenticated=True, user_id="user-b", org_id="org-b", role="owner")
ANONYMOUS = SimpleNamespace(is_authenticated=False, user_id=None, org_id=None, role=None)

PA = "pipe-a"
MISSING = "pipe-missing"
BASE = "/api/v1/canvas/pipeline"

READ_SUFFIXES = [
    "",
    "/status",
    "/stage/ideas",
    "/graph",
    "/receipt",
    "/intelligence",
    "/beliefs",
    "/explanations",
    "/precedents",
]


class _Request:
    def __init__(self, caller: Any, body: dict[str, Any] | None = None) -> None:
        self.caller = caller
        self.headers: dict[str, str] = {}
        self._body = json.dumps(body or {}).encode()


async def _resolve(result: Any) -> Any:
    if hasattr(result, "__await__"):
        return await result
    return result


def _json(result: Any) -> Any:
    return json.loads(result.body)


@pytest.fixture(autouse=True)
def _identity():
    with patch(
        "aragora.billing.jwt_auth.extract_user_from_request",
        side_effect=lambda handler, user_store=None: handler.caller,
    ):
        yield


@pytest.fixture
def store(tmp_path):
    store = PipelineResultStore(str(tmp_path / "pipelines.db"))
    store.save(
        PA,
        {
            "pipeline_id": PA,
            "stage_status": {"ideas": "complete", "goals": "pending"},
            "ideas": {"nodes": [{"id": "idea-1", "data": {"label": "A secret idea"}}]},
            "transitions": [{"from_stage": "ideas", "to_stage": "goals", "status": "pending"}],
        },
        org_id="org-a",
        created_by="user-a",
    )
    with patch.object(module, "_get_store", return_value=store):
        yield store


@pytest.fixture(autouse=True)
def _clear_memory():
    module._pipeline_objects.clear()
    module._pipeline_tasks.clear()
    yield
    module._pipeline_objects.clear()
    module._pipeline_tasks.clear()


@pytest.fixture
def handler() -> CanvasPipelineHandler:
    return CanvasPipelineHandler()


async def _get(handler: CanvasPipelineHandler, caller: Any, path: str, query=None) -> Any:
    return await _resolve(handler.handle(path, query or {}, _Request(caller)))


async def _post(handler: CanvasPipelineHandler, caller: Any, path: str, body=None) -> Any:
    request = _Request(caller, body)
    result = await _resolve(handler.handle_post(path, {}, request))
    if result is None:
        result = await _resolve(handler.handle(path, {}, request))
    return result


async def _put(handler: CanvasPipelineHandler, caller: Any, path: str, body=None) -> Any:
    return await _resolve(handler.handle_put(path, {}, _Request(caller, body)))


# ---------------------------------------------------------------------------
# Reads (E2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", READ_SUFFIXES)
async def test_other_org_read_is_the_missing_pipeline_404(handler, store, suffix) -> None:
    other = await _get(handler, USER_B, f"{BASE}/{PA}{suffix}")
    missing = await _get(handler, USER_B, f"{BASE}/{MISSING}{suffix}")

    assert other.status_code == missing.status_code == 404
    assert other.body == missing.body
    assert _json(other) == {"error": "Pipeline not found", "code": "not_found"}


@pytest.mark.asyncio
async def test_other_org_agents_read_is_404(handler, store) -> None:
    other = await _get(handler, USER_B, f"/api/v1/pipeline/{PA}/agents")
    missing = await _get(handler, USER_B, f"/api/v1/pipeline/{MISSING}/agents")

    assert other.status_code == 404
    assert other.body == missing.body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [BASE, f"{BASE}/templates", f"/api/v1/pipeline/{PA}/agents"]
    + [f"{BASE}/{PA}{suffix}" for suffix in READ_SUFFIXES],
)
async def test_anonymous_reads_are_401(handler, store, path) -> None:
    result = await _get(handler, ANONYMOUS, path)

    assert result.status_code == 401
    assert _json(result)["code"] == "auth_required"


@pytest.mark.asyncio
async def test_list_and_latest_only_show_the_callers_org(handler, store) -> None:
    store.save("pipe-b", {"stage_status": {}}, org_id="org-b", created_by="user-b")
    store.save("pipe-legacy", {"stage_status": {}})

    listed_b = _json(await _get(handler, USER_B, BASE, {"list": "true"}))
    listed_a = _json(await _get(handler, USER_A, BASE, {"list": "true"}))
    latest_b = _json(await _get(handler, USER_B, BASE))

    assert [p["id"] for p in listed_b["pipelines"]] == ["pipe-b"]
    assert [p["id"] for p in listed_a["pipelines"]] == [PA]
    assert latest_b["pipeline_id"] == "pipe-b"


@pytest.mark.asyncio
@pytest.mark.parametrize(("caller", "listed"), [(USER_A, [PA]), (USER_B, [])])
async def test_list_mode_passes_the_server_query_allowlist(handler, store, caller, listed) -> None:
    from aragora.server.http_utils import validate_query_params

    assert validate_query_params({"list": ["true"], "limit": ["500"]}) == (True, "")
    assert validate_query_params({"list": ["t" * 11]})[0] is False
    result = await _get(handler, caller, BASE, {"list": "true", "limit": "500"})
    assert [p["id"] for p in _json(result)["pipelines"]] == listed


@pytest.mark.asyncio
async def test_owner_reads_own_pipeline(handler, store) -> None:
    listed = await _get(handler, USER_A, BASE, {"list": "true"})
    pipeline = await _get(handler, USER_A, f"{BASE}/{PA}")
    status = await _get(handler, USER_A, f"{BASE}/{PA}/status")
    stage = await _get(handler, USER_A, f"{BASE}/{PA}/stage/ideas")
    templates = await _get(handler, USER_A, f"{BASE}/templates")
    agents = await _get(handler, USER_A, f"/api/v1/pipeline/{PA}/agents")

    assert [p["id"] for p in _json(listed)["pipelines"]] == [PA]
    assert pipeline.status_code == 200 and _json(pipeline)["pipeline_id"] == PA
    assert status.status_code == 200 and _json(status)["stage_status"]["ideas"] == "complete"
    assert stage.status_code == 200
    assert templates.status_code == 200 and _json(templates)["count"] >= 1
    assert agents.status_code == 200


@pytest.mark.asyncio
async def test_unversioned_alias_is_scoped_too(handler, store) -> None:
    assert (await _get(handler, USER_B, f"/api/canvas/pipeline/{PA}")).status_code == 404
    assert (await _get(handler, USER_A, f"/api/canvas/pipeline/{PA}")).status_code == 200


@pytest.mark.asyncio
async def test_pipeline_without_known_owner_is_hidden_from_every_org(handler, store) -> None:
    store.save("pipe-legacy", {"stage_status": {"ideas": "complete"}})

    assert (await _get(handler, USER_A, f"{BASE}/pipe-legacy")).status_code == 404
    assert (await _get(handler, USER_B, f"{BASE}/pipe-legacy/status")).status_code == 404


@pytest.mark.asyncio
async def test_member_without_org_is_403(handler, store) -> None:
    no_org = SimpleNamespace(is_authenticated=True, user_id="user-x", org_id=None, role="owner")

    result = await _get(handler, no_org, f"{BASE}/{PA}")

    assert result.status_code == 403
    assert _json(result)["code"] == "org_required"


# ---------------------------------------------------------------------------
# Writes (E3)
# ---------------------------------------------------------------------------

B_WRITES = [
    (f"{BASE}/{PA}/execute", {}),
    (f"{BASE}/{PA}/approve-transition", {"from_stage": "ideas", "to_stage": "goals"}),
    (f"{BASE}/approve-transition", {"pipeline_id": PA, "from_stage": "ideas", "to_stage": "goals"}),
    (f"{BASE}/advance", {"pipeline_id": PA, "target_stage": "goals"}),
    (f"{BASE}/{PA}/self-improve", {"budget_limit": 1.0}),
    (f"/api/v1/pipeline/{PA}/agents/agent-1/approve", {"notes": "ok"}),
    (f"/api/v1/pipeline/{PA}/agents/agent-1/reject", {"feedback": "no"}),
    (f"{BASE}/{PA}/run", {"input_text": "x"}),
    (f"{BASE}/{PA}/advance", {"target_stage": "goals"}),
]

CREATE_ROUTES = [
    "from-debate",
    "from-ideas",
    "from-braindump",
    "from-template",
    "demo",
    "run",
    "auto-run",
    "from-system-metrics",
    "extract-goals",
    "extract-principles",
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("path", "body"), B_WRITES)
async def test_other_org_writes_are_404_without_side_effect(handler, store, path, body) -> None:
    before = store.get(PA)
    count_before = len(store.list_pipelines(limit=100))
    spies = {
        name: patch.object(CanvasPipelineHandler, name, side_effect=AssertionError(name))
        for name in (
            "handle_execute",
            "handle_approve_transition",
            "handle_advance",
            "handle_self_improve",
            "handle_approve_agent",
            "handle_reject_agent",
        )
    }
    for spy in spies.values():
        spy.start()
    try:
        result = await _post(handler, USER_B, path, body)
    finally:
        for spy in spies.values():
            spy.stop()

    assert result.status_code == 404
    assert _json(result) == {"error": "Pipeline not found", "code": "not_found"}
    assert store.get(PA) == before
    assert len(store.list_pipelines(limit=100)) == count_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [path for path, _body in B_WRITES]
    + [f"{BASE}/{name}" for name in CREATE_ROUTES]
    + ["/api/v1/canvas/convert/debate", "/api/v1/canvas/convert/workflow"],
)
async def test_anonymous_writes_are_401(handler, store, path) -> None:
    before = store.get(PA)

    result = await _post(handler, ANONYMOUS, path, {"pipeline_id": PA, "ideas": ["x"]})

    assert result.status_code == 401
    assert store.get(PA) == before
    assert {p["id"] for p in store.list_pipelines(limit=100)} == {PA}


@pytest.mark.asyncio
async def test_owner_approves_own_transition(handler, store) -> None:
    result = await _post(
        handler,
        USER_A,
        f"{BASE}/{PA}/approve-transition",
        {"from_stage": "ideas", "to_stage": "goals"},
    )

    assert result.status_code == 200
    assert store.get(PA)["transitions"][0]["status"] == "approved"


@pytest.mark.asyncio
async def test_self_improve_record_belongs_to_the_owner(handler, store) -> None:
    store.save(
        PA,
        {"stage_status": {}, "goals": {"goals": [{"title": "Ship it"}]}},
        org_id="org-a",
    )

    result = await _post(handler, USER_A, f"{BASE}/{PA}/self-improve", {})

    assert result.status_code == 201
    run_id = _json(result)["data"]["run_id"]
    assert store.get_owner_org(f"self-improve-{run_id}") == "org-a"


@pytest.mark.asyncio
async def test_put_other_orgs_pipeline_is_404_and_unchanged(handler, store) -> None:
    before = store.get(PA)
    stages = {"stages": {"ideas": {"nodes": [{"id": "evil"}], "edges": []}}}

    other = await _put(handler, USER_B, f"{BASE}/{PA}", stages)
    anonymous = await _put(handler, ANONYMOUS, f"{BASE}/{PA}", stages)

    assert other.status_code == 404
    assert anonymous.status_code == 401
    assert store.get(PA) == before


@pytest.mark.asyncio
async def test_put_saves_own_and_creates_for_the_callers_org(handler, store) -> None:
    stages = {"stages": {"goals": {"nodes": [{"id": "g1"}], "edges": []}}}

    own = await _put(handler, USER_A, f"{BASE}/{PA}", stages)
    new = await _put(handler, USER_B, f"{BASE}/pipe-new", stages)

    assert own.status_code == 200
    assert store.get(PA)["goals"]["nodes"] == [{"id": "g1"}]
    assert new.status_code == 200
    assert store.get_owner_org("pipe-new") == "org-b"
    assert store.get_owner_org(PA) == "org-a"


@pytest.mark.asyncio
async def test_put_create_loses_to_a_pipeline_created_after_admission(
    handler, store, monkeypatch
) -> None:
    """B's create-via-PUT is admitted for a free id, then A creates that id
    before B's save: B gets the shared 404 and A's pipeline is unchanged."""
    raced = "pipe-raced"
    a_content = {
        "pipeline_id": raced,
        "stage_status": {"ideas": "complete"},
        "ideas": {"nodes": [{"id": "idea-1", "data": {"label": "A raced idea"}}]},
    }
    read_body = CanvasPipelineHandler._get_request_body

    def body_read_after_a_creates(request: Any) -> dict[str, Any]:
        store.save(raced, a_content, org_id="org-a", created_by="user-a")
        return read_body(request)

    monkeypatch.setattr(
        CanvasPipelineHandler, "_get_request_body", staticmethod(body_read_after_a_creates)
    )
    stages = {"stages": {"ideas": {"nodes": [{"id": "evil", "label": "B"}], "edges": []}}}
    before = store.get(PA)

    raced_put = await _put(handler, USER_B, f"{BASE}/{raced}", stages)
    foreign_put = await _put(handler, USER_B, f"{BASE}/{PA}", stages)

    assert raced_put.status_code == 404
    assert _json(raced_put) == _json(foreign_put)
    assert "A raced idea" not in raced_put.body.decode()
    assert store.get(raced)["ideas"] == a_content["ideas"]
    assert store.get(raced)["stage_status"] == {"ideas": "complete"}
    assert store.get_owner_org(raced) == "org-a"
    assert store.get(PA) == before


@pytest.mark.asyncio
async def test_put_save_refuses_a_pipeline_that_changed_hands(handler, store) -> None:
    """The save itself checks the owner, whatever the caller saw before."""
    scope_b = SimpleNamespace(org_id="org-b", user_id="user-b")
    stages = {"stages": {"goals": {"nodes": [{"id": "g-evil"}], "edges": []}}}
    before = store.get(PA)

    result = await handler.handle_save_pipeline(PA, stages, scope=scope_b)

    assert result.status_code == 404
    assert "A secret idea" not in result.body.decode()
    assert store.get(PA) == before
    assert store.get_owner_org(PA) == "org-a"


# ---------------------------------------------------------------------------
# Records created through the routes carry the creator's org
# ---------------------------------------------------------------------------


def _fake_result(pipeline_id: str = "pipe-fake") -> SimpleNamespace:
    return SimpleNamespace(
        pipeline_id=pipeline_id,
        stage_status={"ideas": "complete"},
        goal_graph=None,
        universal_graph=None,
        ideas_canvas=None,
        actions_canvas=None,
        orchestration_canvas=None,
        to_dict=lambda: {"pipeline_id": pipeline_id, "stage_status": {"ideas": "complete"}},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("from-ideas", {"ideas": ["Rate limit the API"], "auto_advance": False}),
        ("from-template", {"template_name": "product_launch"}),
        ("demo", {}),
    ],
)
async def test_created_pipelines_carry_the_creator_org(handler, store, route, body) -> None:
    with patch.object(module, "_persist_pipeline_to_km"):
        result = await _post(handler, USER_B, f"{BASE}/{route}", body)

    assert result.status_code == 201, _json(result)
    pipeline_id = _json(result)["pipeline_id"]
    assert store.get_owner_org(pipeline_id) == "org-b"
    assert (await _get(handler, USER_B, f"{BASE}/{pipeline_id}")).status_code == 200
    assert (await _get(handler, USER_A, f"{BASE}/{pipeline_id}")).status_code == 404


@pytest.mark.asyncio
async def test_run_records_the_creator_org(handler, store) -> None:
    from aragora.pipeline import idea_to_execution

    with (
        patch.object(
            idea_to_execution.IdeaToExecutionPipeline,
            "run",
            new=AsyncMock(return_value=_fake_result()),
        ),
        patch.object(module, "_persist_pipeline_to_km"),
    ):
        result = await _post(handler, USER_B, f"{BASE}/run", {"input_text": "Plan the launch"})
        pipeline_id = _json(result)["pipeline_id"]
        placeholder_owner = store.get_owner_org(pipeline_id)
        await module._pipeline_tasks[pipeline_id]

    assert result.status_code == 202
    assert placeholder_owner == "org-b"
    assert store.get_owner_org(pipeline_id) == "org-b"


@pytest.mark.asyncio
async def test_auto_run_and_system_metrics_record_the_creator_org(handler, store) -> None:
    from aragora.pipeline import idea_to_execution

    pipeline_cls = idea_to_execution.IdeaToExecutionPipeline
    with (
        patch.object(pipeline_cls, "from_brain_dump", new=AsyncMock(return_value=None)),
        patch.object(
            pipeline_cls, "from_system_metrics", new=AsyncMock(return_value=_fake_result())
        ),
    ):
        auto = await _post(handler, USER_B, f"{BASE}/auto-run", {"text": "Ideas"})
        metrics = await _post(handler, USER_B, f"{BASE}/from-system-metrics", {})
        await module._pipeline_tasks[_json(auto)["pipeline_id"]]

    for result in (auto, metrics):
        pipeline_id = _json(result)["pipeline_id"]
        assert store.get_owner_org(pipeline_id) == "org-b"
        assert (await _get(handler, USER_B, f"{BASE}/{pipeline_id}/status")).status_code == 200
        assert (
            await _get(handler, USER_A, f"{BASE}/{pipeline_id}/intelligence")
        ).status_code == 404


def _save_executable(store: PipelineResultStore) -> None:
    complete = dict.fromkeys(("ideas", "goals", "actions", "orchestration"), "complete")
    task = {"id": "t1", "data": {"orch_type": "agent_task", "label": "Build cache"}}
    store.save(
        PA,
        {"stage_status": complete, "orchestration": {"nodes": [task], "edges": []}},
        org_id="org-a",
    )


@pytest.mark.asyncio
async def test_execute_queues_the_plan_for_the_owner_org(handler, store) -> None:
    _save_executable(store)
    graph_store = MagicMock()
    graph_store.list.return_value = []
    launch = {
        "execution_id": "exec-1",
        "correlation_id": "corr-1",
        "execution_mode": "workflow",
        "run_id": "run-1",
    }

    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=graph_store),
        patch(
            "aragora.pipeline.canonical_execution.queue_plan_execution", return_value=launch
        ) as queue,
        patch(
            "aragora.pipeline.canonical_execution.execute_queued_plan",
            new=AsyncMock(side_effect=RuntimeError("stop")),
        ),
    ):
        result = await _post(handler, USER_A, f"{BASE}/{PA}/execute", {})
        await module._pipeline_tasks["exec-1"]

    assert result.status_code == 202
    assert queue.call_args.kwargs["org_id"] == "org-a"
    assert queue.call_args.kwargs["created_by"] == "user-a"
    assert graph_store.list.call_args.kwargs["org_id"] == "org-a"


@pytest.mark.asyncio
async def test_execute_reads_receipt_provenance_for_the_owner_org(handler, store) -> None:
    _save_executable(store)
    graph_store = MagicMock()
    graph_store.list.return_value = []
    launch = {
        "execution_id": "exec-2",
        "correlation_id": "corr-2",
        "execution_mode": "workflow",
        "run_id": "run-2",
    }
    outcome = MagicMock(success=True, receipt_id="rcpt-2")
    outcome.to_dict.return_value = {"success": True}

    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=graph_store),
        patch("aragora.pipeline.canonical_execution.queue_plan_execution", return_value=launch),
        patch(
            "aragora.pipeline.canonical_execution.execute_queued_plan",
            new=AsyncMock(return_value=(outcome, {}, {})),
        ),
        patch(
            "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
            new=AsyncMock(return_value={"receipt_id": "pipe-rcpt"}),
        ) as receipt,
    ):
        result = await _post(handler, USER_A, f"{BASE}/{PA}/execute", {})
        await module._pipeline_tasks["exec-2"]

    assert result.status_code == 202
    assert receipt.call_args.args[0] == PA
    assert receipt.call_args.kwargs["org_id"] == "org-a"


def _emitter() -> MagicMock:
    emitter = MagicMock()
    emitter.emit_stage_started = AsyncMock()
    emitter.emit_completed = AsyncMock()
    emitter.emit_failed = AsyncMock()
    return emitter


async def _execute_in_background(
    handler: CanvasPipelineHandler,
    store: PipelineResultStore,
    emitter: MagicMock,
    execute_queued_plan: AsyncMock,
    execution_id: str,
) -> Any:
    graph_store = MagicMock()
    graph_store.list.return_value = []
    launch = {
        "execution_id": execution_id,
        "correlation_id": f"corr-{execution_id}",
        "execution_mode": "workflow",
        "run_id": f"run-{execution_id}",
    }
    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=graph_store),
        patch("aragora.pipeline.canonical_execution.queue_plan_execution", return_value=launch),
        patch("aragora.pipeline.canonical_execution.execute_queued_plan", new=execute_queued_plan),
        patch(
            "aragora.pipeline.receipt_generator.generate_pipeline_receipt",
            new=AsyncMock(return_value={"receipt_id": "pipe-rcpt", "label": "A receipt"}),
        ),
        patch("aragora.server.stream.pipeline_stream.get_pipeline_emitter", return_value=emitter),
    ):
        result = await _post(handler, USER_A, f"{BASE}/{PA}/execute", {})
        await module._pipeline_tasks[execution_id]
    return result


def _outcome() -> MagicMock:
    outcome = MagicMock(success=True, receipt_id="rcpt-a")
    outcome.to_dict.return_value = {"success": True}
    return outcome


B_CONTENT = {
    "pipeline_id": PA,
    "stage_status": {"ideas": "complete"},
    "ideas": {"nodes": [{"id": "b-idea", "data": {"label": "B idea"}}]},
}


def _hand_pa_to_b(store: PipelineResultStore) -> None:
    assert store.delete(PA)
    store.save(PA, B_CONTENT, org_id="org-b", created_by="user-b")


@pytest.mark.asyncio
async def test_execute_saves_its_result_while_the_owner_keeps_the_pipeline(handler, store) -> None:
    _save_executable(store)
    emitter = _emitter()

    result = await _execute_in_background(
        handler, store, emitter, AsyncMock(return_value=(_outcome(), {}, {})), "exec-own"
    )

    assert result.status_code == 202
    saved = store.get(PA)
    assert saved["execution"]["status"] == "completed"
    assert saved["receipt"]["execution_id"] == "exec-own"
    assert store.get_owner_org(PA) == "org-a"
    emitter.emit_completed.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes_hands", "succeeds"), [("execution", True), ("execution", False), ("start", True)]
)
async def test_execute_never_saves_over_a_pipeline_that_changed_hands(
    handler, store, changes_hands, succeeds
) -> None:
    """A's pipeline is deleted and B creates the same id while A's execution
    runs: the background saves leave B's row as B wrote it."""
    _save_executable(store)
    emitter = _emitter()
    if changes_hands == "start":
        emitter.emit_stage_started.side_effect = lambda *args, **kwargs: _hand_pa_to_b(store)

    async def run(*args: Any, **kwargs: Any) -> Any:
        if changes_hands == "execution":
            _hand_pa_to_b(store)
        if not succeeds:
            raise RuntimeError("A execution failed")
        return _outcome(), {"record": "A execution record"}, {}

    result = await _execute_in_background(
        handler, store, emitter, AsyncMock(side_effect=run), f"exec-{changes_hands}-{succeeds}"
    )

    assert result.status_code == 202
    saved = store.get(PA)
    assert store.get_owner_org(PA) == "org-b"
    assert saved["ideas"] == B_CONTENT["ideas"]
    assert saved["stage_status"] == B_CONTENT["stage_status"]
    assert "execution" not in saved
    assert "receipt" not in saved
    for a_content in ("Build cache", "A execution record", "A receipt"):
        assert a_content not in json.dumps(saved)
    emitter.emit_completed.assert_not_awaited()
    emitter.emit_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_refused_by_plan_ownership_is_404(handler, store) -> None:
    from aragora.pipeline.execution_ownership import ExecutionNotAuthorizedError

    _save_executable(store)

    with (
        patch("aragora.pipeline.graph_store.get_graph_store", return_value=MagicMock()),
        patch(
            "aragora.pipeline.canonical_execution.queue_plan_execution",
            side_effect=ExecutionNotAuthorizedError("plan_owned_by_other_org", "refused"),
        ),
    ):
        result = await _post(handler, USER_A, f"{BASE}/{PA}/execute", {})

    assert result.status_code == 404
    assert "execution" not in store.get(PA)


@pytest.mark.asyncio
async def test_extract_goals_ignores_another_orgs_canvas(handler, store) -> None:
    canvas = SimpleNamespace(
        workspace_id="org-a",
        nodes={"n1": MagicMock(to_dict=lambda: {"id": "n1", "label": "Secret"})},
        edges={},
    )
    manager = MagicMock()
    manager.get_canvas = AsyncMock(return_value=canvas)

    with patch("aragora.canvas.get_canvas_manager", return_value=manager):
        other = await _post(
            handler, USER_B, f"{BASE}/extract-goals", {"ideas_canvas_id": "canvas-a"}
        )
        manager.get_canvas = AsyncMock(return_value=None)
        missing = await _post(
            handler, USER_B, f"{BASE}/extract-goals", {"ideas_canvas_id": "canvas-x"}
        )

    assert other.status_code == missing.status_code == 400
    assert other.body == missing.body


@pytest.mark.asyncio
async def test_debate_to_pipeline_needs_the_debate_owner(handler, store) -> None:
    storage = MagicMock()
    storage.get_access_info.return_value = ("debate-a", "org-a", True)
    handler = CanvasPipelineHandler({"storage": storage})

    with patch.object(CanvasPipelineHandler, "handle_debate_to_pipeline") as convert:
        other = await _post(handler, USER_B, "/api/v1/debates/debate-a/to-pipeline", {})
        anonymous = await _post(handler, ANONYMOUS, "/api/v1/debates/debate-a/to-pipeline", {})

    assert other.status_code == 404
    assert anonymous.status_code == 401
    convert.assert_not_called()


# ---------------------------------------------------------------------------
# VAL-PIPE-005: the permission check fails closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [ImportError, AttributeError, ValueError])
async def test_checker_failure_denies_and_skips_the_operation(handler, store, exc) -> None:
    request = _Request(USER_A, {"ideas": ["x"]})

    with (
        patch("aragora.rbac.checker.get_permission_checker", side_effect=exc("checker down")),
        patch.object(CanvasPipelineHandler, "handle_from_ideas") as operation,
        patch.object(CanvasPipelineHandler, "handle_approve_transition") as approve,
    ):
        denial = handler._check_permission(request, "canvas:create")
        create = await _resolve(handler.handle_post(f"{BASE}/from-ideas", {}, request))
        write = await _resolve(handler.handle_post(f"{BASE}/{PA}/approve-transition", {}, request))

    assert denial is not None and denial.status_code == 403
    assert create.status_code == 403
    assert write.status_code == 403
    operation.assert_not_called()
    approve.assert_not_called()
    assert {p["id"] for p in store.list_pipelines(limit=100)} == {PA}


@pytest.mark.asyncio
async def test_checker_call_failure_denies(handler, store) -> None:
    checker = MagicMock()
    checker.check_permission.side_effect = ValueError("bad context")

    with (
        patch("aragora.rbac.checker.get_permission_checker", return_value=checker),
        patch.object(CanvasPipelineHandler, "handle_save_pipeline") as save,
    ):
        result = await _put(handler, USER_A, f"{BASE}/{PA}", {"stages": {"ideas": {}}})

    assert result.status_code == 403
    save.assert_not_called()
