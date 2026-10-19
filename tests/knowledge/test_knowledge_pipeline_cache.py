"""The knowledge pipeline cache is bounded per organization and stops only pipelines no caller holds."""

from __future__ import annotations

import asyncio
import gc
import importlib
import threading
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


class _MemoryPipeline(_FakePipeline):
    async def start(self) -> None:
        await super().start()
        self._embedding_service = InMemoryEmbeddingService()


async def _use_pipeline(workspace_id: str, org_id: str) -> Any:
    async with integration._borrowed_pipeline(workspace_id, org_id=org_id) as pipeline:
        return pipeline


async def _index(pipeline: Any) -> None:
    await pipeline._embedding_service.embed_chunks([{"chunk_id": "c1", "content": "x"}], "ws")


def _fresh_cache(
    monkeypatch: pytest.MonkeyPatch, pipeline_cls: type, max_pipelines: int = 1, per_org: int = 8
) -> None:
    for name in ("_pipelines", "_borrowers", "_evicted_in_use"):
        monkeypatch.setattr(integration, name, {})
    monkeypatch.setattr(integration, "_handed_out", weakref.WeakSet())
    monkeypatch.setattr(integration, "_orphans", weakref.WeakValueDictionary(), raising=False)
    monkeypatch.setattr(integration, "_MAX_PIPELINES", max_pipelines)
    monkeypatch.setattr(integration, "_MAX_PIPELINES_PER_ORG", per_org, raising=False)
    monkeypatch.setattr(integration, "KnowledgePipeline", pipeline_cls)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)


def _in_thread(use: Any) -> tuple[threading.Thread, dict[str, Any]]:
    out: dict[str, Any] = {}

    def run() -> None:
        out["pipeline"] = asyncio.run(use())  # each thread on its own event loop

    # Daemon: on a lock that cannot exclude threads, a waiter can be left asleep for good.
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, out


async def test_pipeline_cache_is_bounded_and_stops_the_least_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_cache(monkeypatch, _FakePipeline, max_pipelines=2)

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
    _fresh_cache(monkeypatch, _MemoryPipeline)
    async with integration._borrowed_pipeline("ws-1", org_id="acme") as indexed:
        await _index(indexed)

    with pytest.raises(CacheCapacityError):
        await _use_pipeline("ws-2", "acme")

    assert integration._pipelines == {("acme", "ws-1"): indexed} and indexed.running
    assert await _use_pipeline("ws-1", "acme") is indexed


async def test_an_idle_empty_in_memory_pipeline_is_still_evicted(monkeypatch):
    _fresh_cache(monkeypatch, _MemoryPipeline)
    first = await _use_pipeline("ws-1", "acme")
    await _use_pipeline("ws-2", "acme")

    assert list(integration._pipelines) == [("acme", "ws-2")] and first.running is False


async def test_a_borrowed_pipeline_holds_its_slot_only_until_it_is_returned(monkeypatch):
    _fresh_cache(monkeypatch, _MemoryPipeline)
    async with integration._borrowed_pipeline("ws-1", org_id="acme") as busy:
        with pytest.raises(CacheCapacityError):
            await _use_pipeline("ws-2", "acme")
        assert busy.running

    assert (await _use_pipeline("ws-2", "acme")).running and busy.running is False


async def test_one_org_cannot_take_another_orgs_slots(monkeypatch):
    _fresh_cache(monkeypatch, _MemoryPipeline, max_pipelines=3, per_org=2)
    for workspace_id in ("ws-1", "ws-2"):
        async with integration._borrowed_pipeline(workspace_id, org_id="acme") as pipeline:
            await _index(pipeline)

    with pytest.raises(CacheCapacityError):
        await _use_pipeline("ws-3", "acme")
    beta = await _use_pipeline("ws-1", "beta")

    assert list(integration._pipelines) == [("acme", "ws-1"), ("acme", "ws-2"), ("beta", "ws-1")]
    assert beta.running


async def test_an_org_at_its_share_drops_its_own_idle_pipeline_first(monkeypatch):
    _fresh_cache(monkeypatch, _FakePipeline, max_pipelines=3, per_org=2)
    beta = await _use_pipeline("ws-1", "beta")
    oldest = await _use_pipeline("ws-1", "acme")
    await _use_pipeline("ws-2", "acme")
    await _use_pipeline("ws-3", "acme")

    assert list(integration._pipelines) == [("beta", "ws-1"), ("acme", "ws-2"), ("acme", "ws-3")]
    assert beta.running and oldest.running is False


async def test_a_handed_out_pipeline_stops_pinning_and_is_tracked_only_while_held(monkeypatch):
    _fresh_cache(monkeypatch, _MemoryPipeline, max_pipelines=2)
    held = await integration.get_pipeline("ws-1", org_id="acme")
    await _use_pipeline("ws-2", "acme")
    await _use_pipeline("ws-3", "acme")  # drops the empty held pipeline without stopping it
    assert list(integration._pipelines) == [("acme", "ws-2"), ("acme", "ws-3")] and held.running

    await _index(held)  # its holder keeps writing after the drop
    assert await _use_pipeline("ws-1", "acme") is held  # re-adopted: the index is not split
    await _use_pipeline("ws-3", "acme")
    await _use_pipeline("ws-4", "acme")  # held is least recent but has an index, so it is kept
    assert list(integration._pipelines) == [("acme", "ws-1"), ("acme", "ws-4")]

    dropped = await integration.get_pipeline("ws-5", org_id="acme")
    await _use_pipeline("ws-6", "acme")
    released = weakref.ref(dropped)
    del dropped
    gc.collect()
    assert released() is None and ("acme", "ws-5") not in integration._orphans
    assert list(integration._pipelines) == [("acme", "ws-1"), ("acme", "ws-6")]


def test_threads_on_their_own_loops_check_out_while_another_thread_starts(monkeypatch):
    starting, release = threading.Event(), threading.Event()
    started: list[_FakePipeline] = []

    class _SlowStart(_FakePipeline):
        async def start(self) -> None:
            started.append(self)
            if not starting.is_set():
                starting.set()
                release.wait(5)
            await super().start()

    _fresh_cache(monkeypatch, _SlowStart, max_pipelines=4)
    slow, slow_out = _in_thread(lambda: _use_pipeline("ws-1", "acme"))
    assert starting.wait(5)
    others = [_in_thread(lambda w=w: _use_pipeline(w, "acme")) for w in ("ws-2", "ws-1")]
    for thread, _ in others:
        thread.join(5)
    finished_while_one_was_starting = [not thread.is_alive() for thread, _ in others]
    release.set()
    slow.join(5)

    assert finished_while_one_was_starting == [True, True]
    assert slow_out["pipeline"] is others[1][1]["pipeline"]  # one pipeline per key
    assert set(integration._pipelines) == {("acme", "ws-1"), ("acme", "ws-2")}
    assert [p.running for p in started if p not in integration._pipelines.values()] == [False]
    assert integration._borrowers == {}


def test_another_threads_eviction_never_stops_a_pipeline_in_use(monkeypatch):
    processing, release = threading.Event(), threading.Event()
    running_during_processing: list[bool] = []

    class _BusyPipeline(_FakePipeline):
        async def process_text(self, **_kwargs: Any) -> Any:
            processing.set()
            release.wait(5)
            running_during_processing.append(self.running)
            return SimpleNamespace(success=True)

    _fresh_cache(monkeypatch, _BusyPipeline)
    busy_thread, _ = _in_thread(
        lambda: integration.process_text_async("t", workspace_id="ws-1", org_id="acme")
    )
    assert processing.wait(5)
    evicting, evicting_out = _in_thread(lambda: _use_pipeline("ws-2", "acme"))
    evicting.join(5)
    busy = integration._evicted_in_use.copy()
    release.set()
    busy_thread.join(5)

    assert running_during_processing == [True] and evicting_out["pipeline"].running
    assert [p.running for p in busy.values()] == [False] and integration._evicted_in_use == {}


async def test_a_full_cache_skips_optional_ingestion_and_keeps_the_upload(monkeypatch):
    def _full(**_kwargs: Any) -> Any:
        raise CacheCapacityError(64, 64)

    monkeypatch.setattr(integration, "process_text_sync", _full)
    monkeypatch.setattr(integration, "process_document_sync", _full)
    smart_upload = importlib.import_module("aragora.server.handlers.features.smart_upload")
    uploaded = await smart_upload._queue_knowledge_from_result(
        options={"async_knowledge": False},
        category=smart_upload.FileCategory.DOCUMENT,
        action=smart_upload.ProcessingAction.EXTRACT,
        filename="a.txt",
        processing_result={"text": "quarterly report"},
        org_id="acme",
    )
    document = integration.process_uploaded_document(b"d", "d.txt", async_processing=False)

    assert uploaded is not None and uploaded["knowledge_processing"]["status"] == "skipped"
    assert document["knowledge_processing"]["status"] == "skipped"


def test_a_queued_job_reports_the_capacity_error(monkeypatch):
    def _full(**_kwargs: Any) -> Any:
        raise CacheCapacityError(1, 1)

    monkeypatch.setattr(integration, "process_text_sync", _full)
    monkeypatch.setattr(integration, "_executor", SimpleNamespace(submit=lambda run: run()))
    job_id = integration.queue_text_processing("text", workspace_id="ws-1", org_id="acme")

    assert integration.get_job_status(job_id)["error"] == "Processing failed: CacheCapacityError"
