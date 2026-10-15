"""The knowledge pipeline cache is bounded and stops only pipelines no caller holds."""

from __future__ import annotations

import asyncio
import time
import weakref
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.exceptions import CacheCapacityError
from aragora.knowledge import integration
from aragora.knowledge.embeddings import InMemoryEmbeddingService
from aragora.knowledge.pipeline import PipelineConfig


class _FakePipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.running = False

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False


async def _use_pipeline(workspace_id: str, org_id: str) -> Any:
    async with integration._borrowed_pipeline(workspace_id, org_id=org_id) as pipeline:
        return pipeline


def _fresh_cache(monkeypatch: pytest.MonkeyPatch, pipeline_cls: type) -> None:
    # A fresh lock too: the module-level one can be left bound to another test's event loop.
    for name, value in (("_pipelines", {}), ("_borrowers", {}), ("_evicted_in_use", {})):
        monkeypatch.setattr(integration, name, value)
    monkeypatch.setattr(integration, "_handed_out", weakref.WeakSet())
    monkeypatch.setattr(integration, "_pipeline_lock", asyncio.Lock())
    monkeypatch.setattr(integration, "_MAX_PIPELINES", 1)
    monkeypatch.setattr(integration, "KnowledgePipeline", pipeline_cls)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)


async def test_pipeline_cache_is_bounded_and_stops_the_least_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_cache(monkeypatch, _FakePipeline)
    monkeypatch.setattr(integration, "_MAX_PIPELINES", 2)

    first = await _use_pipeline("ws-1", "acme")
    second = await _use_pipeline("ws-2", "acme")
    assert await _use_pipeline("ws-1", "acme") is first
    third = await _use_pipeline("ws-1", "beta")

    assert list(integration._pipelines) == [("acme", "ws-1"), ("beta", "ws-1")]
    assert integration._pipelines[("beta", "ws-1")] is third
    assert isinstance(second, _FakePipeline) and second.running is False
    assert isinstance(first, _FakePipeline) and first.running is True


async def test_a_pipeline_returned_by_get_pipeline_is_never_stopped_by_eviction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_cache(monkeypatch, _FakePipeline)

    held = await integration.get_pipeline("ws-1", org_id="acme")
    await _use_pipeline("ws-2", "acme")

    assert list(integration._pipelines) == [("acme", "ws-2")]
    assert isinstance(held, _FakePipeline) and held.running is True


async def test_a_pipeline_evicted_while_processing_is_stopped_only_afterwards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    busy: list[_FakePipeline] = []
    running_during_processing: list[bool] = []

    class _BusyPipeline(_FakePipeline):
        async def process_document(self, **_kwargs: Any) -> Any:
            busy.append(self)
            # Another request evicts this pipeline while it is still in use.
            await integration.get_pipeline("ws-2", org_id="acme")
            running_during_processing.append(self.running)
            return SimpleNamespace(success=True)

    _fresh_cache(monkeypatch, _BusyPipeline)

    await integration.process_document_async(b"x", "a.txt", "ws-1", org_id="acme")

    assert running_during_processing == [True]
    assert busy[0].running is False
    assert list(integration._pipelines) == [("acme", "ws-2")]


async def test_a_failing_stop_of_an_evicted_pipeline_leaves_no_borrow(monkeypatch):
    class _BrokenStop(_FakePipeline):
        async def stop(self) -> None:
            raise ValueError("close failed")

    _fresh_cache(monkeypatch, _BrokenStop)
    await _use_pipeline("ws-1", "acme")

    assert (await _use_pipeline("ws-2", "acme")).config.workspace_id == "ws-2"
    assert integration._borrowers == {}


async def test_a_cancelled_checkout_leaves_no_borrow(monkeypatch):
    stopping = asyncio.Event()

    class _SlowStop(_FakePipeline):
        async def stop(self) -> None:
            stopping.set()
            await asyncio.Event().wait()

    _fresh_cache(monkeypatch, _SlowStop)
    await _use_pipeline("ws-1", "acme")
    task = asyncio.create_task(_use_pipeline("ws-2", "acme"))
    await stopping.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert integration._borrowers == {}


async def test_a_new_key_gets_a_capacity_error_instead_of_dropping_an_index(monkeypatch):
    class _IndexedPipeline(_FakePipeline):
        async def start(self) -> None:
            await super().start()
            self._embedding_service = InMemoryEmbeddingService()

    _fresh_cache(monkeypatch, _IndexedPipeline)
    async with integration._borrowed_pipeline("ws-1", org_id="acme") as indexed:
        await indexed._embedding_service.embed_chunks([{"chunk_id": "c1", "content": "x"}], "ws-1")

    with pytest.raises(CacheCapacityError):
        await _use_pipeline("ws-2", "acme")

    assert integration._pipelines == {("acme", "ws-1"): indexed} and indexed.running
    assert await _use_pipeline("ws-1", "acme") is indexed


async def test_an_idle_empty_in_memory_pipeline_is_still_evicted(monkeypatch):
    class _EmptyPipeline(_FakePipeline):
        async def start(self) -> None:
            await super().start()
            self._embedding_service = InMemoryEmbeddingService()

    _fresh_cache(monkeypatch, _EmptyPipeline)
    first = await _use_pipeline("ws-1", "acme")
    await _use_pipeline("ws-2", "acme")

    assert list(integration._pipelines) == [("acme", "ws-2")] and first.running is False


def test_a_queued_job_reports_the_capacity_error(monkeypatch):
    def _full(**_kwargs: Any) -> Any:
        raise CacheCapacityError(1, 1)

    monkeypatch.setattr(integration, "process_text_sync", _full)
    job_id = integration.queue_text_processing("text", workspace_id="ws-1", org_id="acme")
    for _ in range(200):
        if integration.get_job_status(job_id)["status"] == "failed":
            break
        time.sleep(0.01)

    assert integration.get_job_status(job_id)["error"] == "Processing failed: CacheCapacityError"
