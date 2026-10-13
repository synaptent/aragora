"""The knowledge pipeline cache is bounded and stops only pipelines no caller holds."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from aragora.knowledge import integration
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


async def test_pipeline_cache_is_bounded_and_stops_the_least_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_pipelines", {})
    monkeypatch.setattr(integration, "_MAX_PIPELINES", 2, raising=False)
    monkeypatch.setattr(integration, "KnowledgePipeline", _FakePipeline)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)

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
    monkeypatch.setattr(integration, "_pipelines", {})
    monkeypatch.setattr(integration, "_MAX_PIPELINES", 1, raising=False)
    monkeypatch.setattr(integration, "KnowledgePipeline", _FakePipeline)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)

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

    monkeypatch.setattr(integration, "_pipelines", {})
    monkeypatch.setattr(integration, "_MAX_PIPELINES", 1, raising=False)
    monkeypatch.setattr(integration, "KnowledgePipeline", _BusyPipeline)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)

    await integration.process_document_async(b"x", "a.txt", "ws-1", org_id="acme")

    assert running_during_processing == [True]
    assert busy[0].running is False
    assert list(integration._pipelines) == [("acme", "ws-2")]
