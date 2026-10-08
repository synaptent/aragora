from __future__ import annotations

import asyncio
import os
import time

import pytest

os.environ.setdefault("ARAGORA_USE_SECRETS_MANAGER", "0")

import aragora.server.debate_controller as debate_controller_mod
from aragora.server.fastapi.routes.debates import CreateDebateRequest, create_debate, list_debates
from aragora.tenancy.record_scope import OrgScope

_SCOPE = OrgScope(org_id="org-1", user_id="user-1", role="member")


class _SlowSyncStorage:
    def list_recent(self, **kwargs):
        time.sleep(0.2)
        return []

    def count_debates(self, org_id: str | None = None) -> int:
        time.sleep(0.2)
        return 0


class _SlowStartResponse:
    debate_id = "debate-123"
    success = True

    def to_dict(self) -> dict[str, str]:
        return {"debate_id": self.debate_id, "status": "started"}


class _SlowSyncController:
    def start_debate(self, request):
        time.sleep(0.2)
        return _SlowStartResponse()


class _RecordingController:
    def __init__(self) -> None:
        self.request = None

    def start_debate(self, request):
        self.request = request
        return _SlowStartResponse()


@pytest.mark.asyncio
async def test_list_debates_does_not_block_event_loop_for_sync_storage() -> None:
    async def ticker() -> int:
        ticks = 0
        start = time.perf_counter()
        while time.perf_counter() - start < 0.35:
            await asyncio.sleep(0.01)
            ticks += 1
        return ticks

    task = asyncio.create_task(ticker())
    await asyncio.sleep(0)

    response = await list_debates(
        request=None,
        limit=10,
        offset=0,
        status=None,
        scope=_SCOPE,
        storage=_SlowSyncStorage(),
    )
    ticks = await task

    assert response.total == 0
    assert response.debates == []
    assert ticks >= 10


@pytest.mark.asyncio
async def test_create_debate_does_not_block_event_loop_for_sync_controller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ticker(done: asyncio.Event) -> int:
        ticks = 0
        while not done.is_set():
            await asyncio.sleep(0.01)
            ticks += 1
        return ticks

    monkeypatch.setattr(
        debate_controller_mod,
        "get_debate_controller",
        lambda: _SlowSyncController(),
        raising=False,
    )

    done = asyncio.Event()
    tick_task = asyncio.create_task(ticker(done))
    await asyncio.sleep(0)

    response = await create_debate(
        body=CreateDebateRequest(question="Should we cache debate summaries?"),
        request=None,
        auth=None,
        scope=_SCOPE,
        storage=object(),
    )
    done.set()
    ticks = await tick_task

    assert response.debate_id == "debate-123"
    assert response.status == "started"
    assert ticks >= 5


@pytest.mark.asyncio
async def test_create_debate_forwards_model_combinations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _RecordingController()
    monkeypatch.setattr(
        debate_controller_mod,
        "get_debate_controller",
        lambda: controller,
        raising=False,
    )

    response = await create_debate(
        body=CreateDebateRequest(
            question="Which lineup produces the best implementation plan?",
            model_combinations=[
                [
                    {"provider": "openai-api", "model": "gpt-4.1"},
                    {"provider": "anthropic-api", "model": "claude-opus-4-7"},
                ],
                [
                    {"provider": "openai-api", "model": "gpt-4.1-mini"},
                    {"provider": "anthropic-api", "model": "claude-sonnet-4-5"},
                ],
            ],
        ),
        request=None,
        auth=None,
        scope=_SCOPE,
        storage=object(),
    )

    assert response.debate_id == "debate-123"
    assert controller.request is not None
    assert controller.request.comparison_config is not None
    assert controller.request.comparison_config["agent_combinations"][0][0]["model"] == "gpt-4.1"
    assert (
        controller.request.model_combinations
        == controller.request.comparison_config["agent_combinations"]
    )
