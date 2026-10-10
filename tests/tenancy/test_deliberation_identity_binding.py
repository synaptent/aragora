"""Deliberations are routed under the caller's org, so the shared decision cache
never hands one org's result to another.

The real DecisionRouter and a fresh DecisionCache run; only the debate execution
is replaced. The n-th execution answers ``answer-<n>``, so a result served from
another org's cache entry or in-flight run is visible as a missing execution.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import aragora.core.decision_results as decision_results
import aragora.core.decision_router as decision_router
from aragora.control_plane.deliberation import (
    DeliberationManager,
    DeliberationTask,
    run_deliberation,
)
from aragora.core.decision import DecisionRequest, DecisionResult, DecisionType
from aragora.core.decision_cache import DecisionCache
from aragora.core.decision_router import DecisionRouter
from aragora.storage.decision_result_store import DecisionResultStore

ORG_A, ORG_B = "org-a-binding", "org-b-binding"
OWNER_A = {"org_id": ORG_A, "created_by": "user-a"}
OWNER_B = {"org_id": ORG_B, "created_by": "user-b"}
QUESTION = "Should we ship the release this week?"


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = DecisionResultStore(db_path=tmp_path / "decision_results.db", ttl_seconds=3600)
    monkeypatch.setattr(decision_results, "_decision_result_store", store)
    monkeypatch.setattr(decision_results, "_decision_results_fallback", {})
    return store


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(decision_router, "_decision_cache", DecisionCache())
    monkeypatch.setattr(decision_router, "_cache_imported", True)
    calls: list[tuple[str | None, str | None]] = []

    async def debate(self, request):
        calls.append((request.context.workspace_id, request.context.user_id))
        answer = f"answer-{len(calls)}"
        await asyncio.sleep(0.05)
        return DecisionResult(request.request_id, DecisionType.DEBATE, answer, 0.9, True)

    monkeypatch.setattr(DecisionRouter, "_route_to_debate", debate)
    return SimpleNamespace(router=DecisionRouter(enable_voice_responses=False), calls=calls)


def _answer(store, request_id: str) -> str:
    return store.get(request_id)["result"]["answer"]


@pytest.mark.asyncio
async def test_spoofed_workspace_never_gets_another_orgs_cached_result(engine, store):
    first, spoofed = DecisionRequest(content=QUESTION), DecisionRequest(content=QUESTION)
    for request in (first, spoofed):
        request.context.workspace_id, request.context.user_id = ORG_A, "user-a"
    await run_deliberation(first, engine.router, **OWNER_A)

    result = await run_deliberation(spoofed, engine.router, **OWNER_B)

    assert result.answer == _answer(store, spoofed.request_id) == "answer-2"
    assert _answer(store, first.request_id) == "answer-1"
    assert store.get(spoofed.request_id)["org_id"] == ORG_B
    assert engine.calls == [(ORG_A, "user-a"), (ORG_B, "user-b")]


@pytest.mark.asyncio
async def test_requests_without_a_workspace_are_cached_per_org(engine, store):
    requests = [DecisionRequest(content=QUESTION) for _ in range(2)]
    for request, owner in zip(requests, (OWNER_A, OWNER_B)):
        await run_deliberation(request, engine.router, **owner)

    assert [_answer(store, r.request_id) for r in requests] == ["answer-1", "answer-2"]
    assert [org for org, _user in engine.calls] == [ORG_A, ORG_B]


@pytest.mark.asyncio
async def test_concurrent_orgs_do_not_share_an_in_flight_run(engine, store):
    requests = [DecisionRequest(content=QUESTION) for _ in range(2)]

    results = await asyncio.gather(
        *(run_deliberation(r, engine.router, **o) for r, o in zip(requests, (OWNER_A, OWNER_B)))
    )

    assert [r.answer for r in results] == ["answer-1", "answer-2"]
    assert [org for org, _user in engine.calls] == [ORG_A, ORG_B]


@pytest.mark.asyncio
async def test_worker_runs_each_task_under_its_owner(engine, store):
    tasks = [DeliberationTask(question=QUESTION, metadata=dict(o)) for o in (OWNER_A, OWNER_B)]
    for task in tasks:
        await DeliberationManager().execute_deliberation(task, engine.router)

    assert [_answer(store, t.request_id) for t in tasks] == ["answer-1", "answer-2"]
    assert engine.calls == [(ORG_A, "user-a"), (ORG_B, "user-b")]


@pytest.mark.asyncio
async def test_same_org_repeat_is_still_served_from_the_cache(engine, store):
    requests = [DecisionRequest(content=QUESTION) for _ in range(2)]
    for request in requests:
        await run_deliberation(request, engine.router, **OWNER_A)

    assert len(engine.calls) == 1
    assert [_answer(store, r.request_id) for r in requests] == ["answer-1", "answer-1"]
