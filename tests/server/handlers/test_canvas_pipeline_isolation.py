"""Org isolation of the canvas pipeline routes (CanvasPipelineHandler dispatch).

Requests go through ``handle`` as the server calls it, with a real
``PipelineResultStore`` and the real RBAC checker. Org A owns ``pipe-a``; B
is a member of another org.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

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
