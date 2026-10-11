"""Organization scoping of pipeline Mound access, in-memory chunk keys and the pipeline cache."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from aragora.knowledge import integration
from aragora.knowledge.embeddings import InMemoryEmbeddingService, chunk_namespace
from aragora.knowledge.fact_store import InMemoryFactStore, OrgScopeRequiredError, ScopedFactStore
from aragora.knowledge.pipeline import KnowledgePipeline, PipelineConfig


def _item(content: str, org_id: str | None) -> Any:
    return SimpleNamespace(content=content, metadata={"org_id": org_id} if org_id else {})


class _RecordingMound:
    """Knowledge Mound double: records every read and write, returns fixed items."""

    def __init__(self, items: list[Any] | None = None) -> None:
        self.items = list(items or [])
        self.queries: list[dict[str, Any]] = []
        self.stored: list[Any] = []

    async def query(self, **kwargs: Any) -> Any:
        self.queries.append(kwargs)
        return SimpleNamespace(items=list(self.items), total_count=len(self.items))

    async def store(self, request: Any) -> Any:
        self.stored.append(request)
        return SimpleNamespace(success=True, node_id=f"node-{len(self.stored)}")

    async def close(self) -> None:
        return None


def _pipeline(
    org_id: str | None, mound: _RecordingMound, fact_store: Any = None
) -> KnowledgePipeline:
    return KnowledgePipeline(
        PipelineConfig(workspace_id="research", org_id=org_id),
        fact_store=fact_store if fact_store is not None else InMemoryFactStore(),
        embedding_service=InMemoryEmbeddingService(),
        knowledge_mound=mound,
    )


MIXED_ITEMS = [
    _item("acme roadmap", "acme"),
    _item("beta payroll", "beta"),
    _item("legacy note without an organization", None),
]


# --- (a) Knowledge Mound reads and writes carry the verified organization ---------


async def test_query_mound_without_an_organization_fails_closed_before_reading() -> None:
    mound = _RecordingMound(MIXED_ITEMS)
    pipeline = _pipeline(None, mound)

    with pytest.raises(OrgScopeRequiredError):
        await pipeline.query_mound("roadmap")
    assert mound.queries == []


async def test_query_mound_returns_only_the_callers_organization_items() -> None:
    mound = _RecordingMound(MIXED_ITEMS)
    result = await _pipeline("acme", mound).query_mound("roadmap")

    assert [i.content for i in result.items] == ["acme roadmap"]
    assert result.total_count == 1


async def test_query_mound_uses_a_caller_built_scoped_store_organization() -> None:
    mound = _RecordingMound(MIXED_ITEMS)
    pipeline = _pipeline(None, mound, fact_store=ScopedFactStore(InMemoryFactStore(), "beta"))
    result = await pipeline.query_mound("payroll")

    assert [i.content for i in result.items] == ["beta payroll"]


async def test_query_without_an_organization_never_reads_the_mound() -> None:
    mound = _RecordingMound(MIXED_ITEMS)
    with pytest.raises(OrgScopeRequiredError):
        await _pipeline(None, mound).query("roadmap")
    assert mound.queries == []


async def test_decision_context_without_an_organization_reads_no_mound_items(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from aragora.core.decision_router import DecisionRouter
    from aragora.knowledge import pipeline as pipeline_module

    mound = _RecordingMound(MIXED_ITEMS)

    class _Pipeline(KnowledgePipeline):
        def __init__(self, config: PipelineConfig) -> None:
            super().__init__(
                config,
                fact_store=InMemoryFactStore(),
                embedding_service=InMemoryEmbeddingService(),
                knowledge_mound=mound,
            )

    monkeypatch.setattr(pipeline_module, "KnowledgePipeline", _Pipeline)
    context = await DecisionRouter()._gather_knowledge_context("roadmap", workspace_id="research")

    assert context == ("", [])
    assert mound.queries == []
    assert "requires an organization" in caplog.text


async def test_debate_decision_reasoning_is_the_rendered_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aragora.core.decision_models import DecisionConfig, DecisionRequest, DecisionType
    from aragora.core.decision_router import DecisionRouter

    monkeypatch.setattr("aragora.agents.get_agents_by_names", lambda _agents=None: [])

    class _Result(SimpleNamespace):
        def summary(self) -> str:
            return "Rendered summary"

    class _Arena:
        def __init__(self, environment: Any, agents: Any, protocol: Any, **_kwargs: Any) -> None:
            pass

        async def run(self) -> _Result:
            return _Result(final_answer="ok", consensus_reached=True, confidence=0.9)

    request = DecisionRequest(
        content="Pick a roadmap",
        decision_type=DecisionType.DEBATE,
        config=DecisionConfig(rounds=1, agents=[], use_knowledge_mound=False),
    )
    result = await DecisionRouter(debate_engine=_Arena).route(request)

    assert result.reasoning == "Rendered summary"


async def test_sync_to_mound_stamps_the_verified_organization_on_every_item() -> None:
    mound = _RecordingMound()
    pipeline = _pipeline("acme", mound)
    document: Any = SimpleNamespace(
        id="doc-1",
        text="Acme roadmap",
        filename="roadmap.txt",
        content_type="text/plain",
        file_size=12,
        metadata={"org_id": "beta"},  # document metadata never names the owner
    )
    chunk: Any = SimpleNamespace(id="chunk-1", content="Acme roadmap", sequence=0, token_count=2)
    fact: Any = SimpleNamespace(
        id="fact-1",
        statement="Acme ships in May",
        confidence=0.8,
        validation_status=None,
        source_documents=["doc-1"],
    )

    synced = await pipeline._sync_to_mound(document, [chunk], [fact])

    assert synced == 3
    assert [r.metadata["org_id"] for r in mound.stored] == ["acme", "acme", "acme"]


async def test_sync_to_mound_without_an_organization_writes_nothing() -> None:
    mound = _RecordingMound()
    document: Any = SimpleNamespace(
        id="doc-1", text="x", filename="x.txt", content_type="text/plain", file_size=1, metadata={}
    )

    with pytest.raises(OrgScopeRequiredError):
        await _pipeline(None, mound)._sync_to_mound(document, [], [])
    assert mound.stored == []


# --- (b) in-memory chunks are keyed by (namespace, chunk_id) ----------------------

ACME = chunk_namespace("research", "acme")
BETA = chunk_namespace("research", "beta")


async def _two_namespaces_with_one_chunk_id() -> InMemoryEmbeddingService:
    service = InMemoryEmbeddingService()
    await service.embed_chunks(
        [{"chunk_id": "c-1", "document_id": "d-acme", "content": "acme alpha plan"}], ACME
    )
    await service.embed_chunks(
        [{"chunk_id": "c-1", "document_id": "d-beta", "content": "beta gamma salaries"}], BETA
    )
    return service


async def test_same_chunk_id_in_two_namespaces_keeps_both_chunks() -> None:
    service = await _two_namespaces_with_one_chunk_id()

    acme = await service.keyword_search("alpha", ACME)
    assert [(m.content, m.document_id) for m in acme] == [("acme alpha plan", "d-acme")]
    beta = await service.keyword_search("gamma", BETA)
    assert [(m.content, m.document_id) for m in beta] == [("beta gamma salaries", "d-beta")]
    assert service.get_statistics()["total_chunks"] == 2


async def test_one_namespace_never_reads_the_other_namespace_chunk() -> None:
    service = await _two_namespaces_with_one_chunk_id()

    assert await service.keyword_search("gamma salaries", ACME) == []
    hybrid = await service.hybrid_search("alpha", ACME)
    assert {m.document_id for m in hybrid} == {"d-acme"}


async def test_deleting_one_namespace_keeps_the_other_namespace_chunk() -> None:
    service = await _two_namespaces_with_one_chunk_id()

    assert await service.delete_workspace_chunks(BETA) == 1
    acme = await service.keyword_search("alpha", ACME)
    assert [m.content for m in acme] == ["acme alpha plan"]
    assert await service.delete_document_chunks("d-acme") == 1
    assert service.get_statistics()["total_chunks"] == 0


# --- (d) a caller-supplied ScopedFactStore must match the verified organization ---


async def test_start_rejects_a_scoped_store_of_another_organization() -> None:
    pipeline = _pipeline("acme", _RecordingMound(), ScopedFactStore(InMemoryFactStore(), "beta"))

    with pytest.raises(OrgScopeRequiredError):
        await pipeline.start()
    assert pipeline._running is False


async def test_start_accepts_a_scoped_store_of_the_same_organization() -> None:
    store = ScopedFactStore(InMemoryFactStore(), "acme")
    pipeline = _pipeline("acme", _RecordingMound(), store)

    await pipeline.start()
    assert pipeline._running is True
    assert pipeline._fact_store is store


# --- (e) the pipeline cache is bounded and stops what it evicts -------------------


class _FakePipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.running = False

    async def start(self) -> None:
        self.running = True

    async def stop(self) -> None:
        self.running = False


async def test_pipeline_cache_is_bounded_and_stops_the_least_recently_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "_pipelines", {})
    monkeypatch.setattr(integration, "_MAX_PIPELINES", 2, raising=False)
    monkeypatch.setattr(integration, "KnowledgePipeline", _FakePipeline)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)

    first = await integration.get_pipeline("ws-1", org_id="acme")
    second = await integration.get_pipeline("ws-2", org_id="acme")
    assert await integration.get_pipeline("ws-1", org_id="acme") is first
    third = await integration.get_pipeline("ws-1", org_id="beta")

    assert list(integration._pipelines) == [("acme", "ws-1"), ("beta", "ws-1")]
    assert integration._pipelines[("beta", "ws-1")] is third
    assert isinstance(second, _FakePipeline) and second.running is False
    assert isinstance(first, _FakePipeline) and first.running is True
