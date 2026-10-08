from __future__ import annotations

import asyncio
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ.setdefault("ARAGORA_USE_SECRETS_MANAGER", "0")

from aragora.server.fastapi.dependencies.pipeline_access import PipelineCaller
from aragora.server.fastapi.routes import canvas_pipeline
from aragora.server.fastapi.routes.canvas_pipeline import (
    SaveCanvasRequest,
    get_pipeline,
    save_canvas_state,
)
from aragora.tenancy.record_scope import OrgScope

_SCOPE = OrgScope(org_id="org-1", user_id="user-1", role="owner")
_CALLER = PipelineCaller(auth=SimpleNamespace(user_id="user-1"), scope=_SCOPE)


class _SlowLoadStore:
    def get(self, pipeline_id: str):
        time.sleep(0.3)
        return {
            "pipeline_id": pipeline_id,
            "stage_status": {"ideas": "complete"},
        }


class _SlowSaveStore:
    def get(self, pipeline_id: str):
        time.sleep(0.2)
        return {"pipeline_id": pipeline_id}

    def save_for_org(self, pipeline_id: str, data: dict, org_id: str, created_by: str) -> bool:
        time.sleep(0.2)
        return True


async def _ticker(duration: float) -> int:
    ticks = 0
    start = time.perf_counter()
    while time.perf_counter() - start < duration:
        await asyncio.sleep(0.01)
        ticks += 1
    return ticks


@pytest.mark.asyncio
async def test_get_pipeline_does_not_block_event_loop_for_sync_store() -> None:
    canvas_pipeline._pipeline_objects.clear()
    task = asyncio.create_task(_ticker(0.4))
    await asyncio.sleep(0)

    with patch.object(canvas_pipeline, "_get_store", return_value=_SlowLoadStore()):
        response = await get_pipeline("pipe-123", caller=_CALLER)
    ticks = await task

    assert response.pipeline_id == "pipe-123"
    assert ticks >= 10


@pytest.mark.asyncio
async def test_save_canvas_state_does_not_block_event_loop_for_sync_store() -> None:
    task = asyncio.create_task(_ticker(0.45))
    await asyncio.sleep(0)

    with patch.object(canvas_pipeline, "_get_store", return_value=_SlowSaveStore()):
        response = await save_canvas_state(
            "pipe-123",
            SaveCanvasRequest(stage="ideas", canvas_data={"nodes": []}),
            caller=_CALLER,
        )
    ticks = await task

    assert response == {"saved": True, "pipeline_id": "pipe-123"}
    assert ticks >= 10


class _SlowOwnerStore:
    def get_owner_org(self, pipeline_id: str):
        time.sleep(0.3)
        return "org-1"


@pytest.mark.asyncio
async def test_owner_lookup_does_not_block_event_loop_for_sync_store() -> None:
    task = asyncio.create_task(_ticker(0.4))
    await asyncio.sleep(0)

    with patch.object(canvas_pipeline, "_get_store", return_value=_SlowOwnerStore()):
        owned = await canvas_pipeline._pipeline_owned("pipe-123", _SCOPE)
    ticks = await task

    assert owned is True
    assert ticks >= 10
