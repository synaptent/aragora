"""In-process fact readers given a trusted organization see only that organization's facts.

Every case shares one workspace id between org A, org B and a legacy fact with
no organization, so a workspace-only filter would leak.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.audit.document_auditor import (
    AuditFinding,
    AuditSession,
    AuditType,
    FindingSeverity,
)
from aragora.audit.knowledge_adapter import AuditKnowledgeAdapter, KnowledgeAuditConfig
from aragora.knowledge import integration
from aragora.knowledge.embeddings import (
    InMemoryEmbeddingService,
    WeaviateEmbeddingService,
    chunk_namespace,
)
from aragora.knowledge.fact_store import (
    FactStore,
    InMemoryFactStore,
    OrgScopeRequiredError,
    ScopedFactStore,
)
from aragora.knowledge.pipeline import KnowledgePipeline, PipelineConfig
from aragora.knowledge.types import FactFilters

WS = "shared-ws"
A_FACT = "Payment terms invoices are paid within thirty days for org A"
B_FACT = "Payment terms invoices are paid within thirty days for org B"
NULL_FACT = "Payment terms invoices are paid within thirty days for nobody"


def _add(store: FactStore | InMemoryFactStore, statement: str, org_id: str | None) -> None:
    fact = store.add_fact(
        statement,
        WS,
        source_documents=["doc-source"],
        confidence=0.9,
        topics=["payment"],
        org_id=org_id or "seed-only",
    )
    if org_id is not None:
        return
    if isinstance(store, FactStore):
        with store.connection() as conn:
            conn.execute("UPDATE facts SET org_id = NULL WHERE id = ?", (fact.id,))
    else:
        store._facts[fact.id].org_id = None


def _seed(store: FactStore | InMemoryFactStore) -> None:
    _add(store, A_FACT, "org-a")
    _add(store, B_FACT, "org-b")
    _add(store, NULL_FACT, None)


@pytest.fixture(params=["memory", "sqlite"])
def store(request: Any, tmp_path: Path) -> FactStore | InMemoryFactStore:
    if request.param == "memory":
        return InMemoryFactStore()
    return FactStore(db_path=tmp_path / "facts.db")


class _FactAgent:
    async def generate(self, prompt: str, context: list[Any]) -> str:
        return "FACT: Org A renews the supply contract every year"


class TestPipelineOrgScope:
    @pytest.mark.asyncio
    async def test_reads_only_its_org(self, store: FactStore | InMemoryFactStore) -> None:
        _seed(store)
        pipeline = KnowledgePipeline(
            PipelineConfig(workspace_id=WS, org_id="org-a"), fact_store=store
        )
        await pipeline.start()
        try:
            assert [f.statement for f in await pipeline.get_facts()] == [A_FACT]
            queried = [
                {f.statement for f in await pipeline.get_facts(query="invoices")},
                {f.statement for f in (await pipeline.query("invoices")).facts},
            ]
            # FactStore's full-text index is contentless, so its joins return no
            # rows; on SQLite only the exclusion of other orgs can be asserted.
            assert all(found <= {A_FACT} for found in queried)
            if isinstance(store, InMemoryFactStore):
                assert queried == [{A_FACT}, {A_FACT}]
            assert pipeline.get_stats()["fact_stats"]["total_facts"] == 1
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_extracted_facts_belong_to_its_org(self) -> None:
        store = InMemoryFactStore()
        pipeline = KnowledgePipeline(
            PipelineConfig(workspace_id=WS, org_id="org-a"),
            fact_store=store,
            agents=[_FactAgent()],
        )
        result = await pipeline.process_text("The supply contract renews yearly.", "c.txt")
        await pipeline.stop()

        assert result.success and [f.org_id for f in result.facts] == ["org-a"]
        org_b = FactFilters(workspace_id=WS, org_id="org-b")
        assert store.list_facts(org_b) == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("org_id", [None, ""])
    async def test_without_org_fails_closed(
        self, store: FactStore | InMemoryFactStore, org_id: str | None
    ) -> None:
        _seed(store)
        pipeline = KnowledgePipeline(
            PipelineConfig(workspace_id=WS, org_id=org_id), fact_store=store
        )
        await pipeline.start()
        try:
            with pytest.raises(OrgScopeRequiredError):
                await pipeline.get_facts()
            with pytest.raises(OrgScopeRequiredError):
                pipeline.get_stats()
        finally:
            await pipeline.stop()

    @pytest.mark.asyncio
    async def test_store_scoped_to_another_org_is_refused(self) -> None:
        store = InMemoryFactStore()
        _seed(store)
        pipeline = KnowledgePipeline(
            PipelineConfig(workspace_id=WS, org_id="org-a"),
            fact_store=ScopedFactStore(store, "org-b"),
        )
        await pipeline.start()
        try:
            with pytest.raises(ValueError, match="scoped org"):
                await pipeline.get_facts()
        finally:
            await pipeline.stop()


def _chunk_pipeline(org_id: str | None, service: Any) -> KnowledgePipeline:
    config = PipelineConfig(workspace_id=WS, org_id=org_id, extract_facts=False)
    return KnowledgePipeline(config, fact_store=InMemoryFactStore(), embedding_service=service)


class TestChunkOrgScope:
    """Two organizations share one embedding store and one workspace id."""

    @pytest.mark.asyncio
    async def test_search_returns_only_its_orgs_chunks(self) -> None:
        shared = InMemoryEmbeddingService()
        org_a, org_b = _chunk_pipeline("org-a", shared), _chunk_pipeline("org-b", shared)
        a_doc = (await org_a.process_text(A_FACT, "a.txt")).document_id
        try:
            assert [m.document_id for m in await org_a.search("invoices")] == [a_doc]
            assert [m.workspace_id for m in await org_a.search("invoices")] == [WS]
            assert await org_b.search("invoices") == []
            assert (await org_b.query("invoices")).evidence_ids == []
            assert org_b.get_stats()["embedding_stats"]["total_chunks"] == 0
        finally:
            await org_a.stop()
            await org_b.stop()

    @pytest.mark.asyncio
    async def test_search_without_org_fails_closed(self) -> None:
        shared = InMemoryEmbeddingService()
        writer, reader = _chunk_pipeline(None, shared), _chunk_pipeline("", shared)
        org_a = _chunk_pipeline("org-a", shared)
        await writer.process_text(NULL_FACT, "legacy.txt")
        try:
            with pytest.raises(OrgScopeRequiredError):
                await reader.search("invoices")
            with pytest.raises(OrgScopeRequiredError):
                await reader.query("invoices")
            assert await org_a.search("invoices") == []
        finally:
            for pipeline in (writer, reader, org_a):
                await pipeline.stop()

    @pytest.mark.asyncio
    async def test_weaviate_writes_and_filters_by_the_org_key(self) -> None:
        service = MagicMock(spec=WeaviateEmbeddingService)
        service.embed_chunks = AsyncMock(return_value=1)
        service.hybrid_search = AsyncMock(return_value=[])
        keys = []
        for org in ("org-a", "org-b"):
            pipeline = _chunk_pipeline(org, service)
            await pipeline.process_text(A_FACT, "a.txt")
            await pipeline.search("invoices")
            await pipeline.stop()
            written = service.embed_chunks.await_args.args[1]
            assert service.hybrid_search.await_args.args[1] == written
            keys.append(written)
        assert len({*keys, WS}) == 3

    def test_chunk_keys_keep_every_pair_distinct(self) -> None:
        pairs = [("a", "b/c"), ("a/b", "c"), ("a", "b"), ("b", "a")]
        assert len({chunk_namespace(ws, org) for org, ws in pairs}) == len(pairs)
        assert chunk_namespace(WS, None) == WS
        with pytest.raises(ValueError, match="reserved"):
            chunk_namespace(chunk_namespace(WS, "org-a"), None)
        with pytest.raises(OrgScopeRequiredError):
            chunk_namespace(WS, "", require_org=True)


@pytest.fixture
def default_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Point the integration's default fact store at a temporary database.

    The module's asyncio lock binds to the first event loop that waits on it,
    so each test gets a fresh one; one worker keeps queued jobs from
    contending for it from several threads at once.
    """
    db_path = tmp_path / "knowledge.db"
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(FactStore, "DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(integration, "_should_use_knowledge_mound", lambda: False)
    monkeypatch.setattr(integration, "_should_use_weaviate", lambda: False)
    monkeypatch.setattr(integration, "_pipelines", {})
    monkeypatch.setattr(integration, "_pipeline_lock", asyncio.Lock())
    monkeypatch.setattr(integration, "_executor", executor)
    yield db_path
    executor.shutdown(wait=True)
    for pipeline in list(integration._pipelines.values()):
        asyncio.run(pipeline.stop())


def _processed(org_id: str | None) -> int:
    pipeline = asyncio.run(integration.get_pipeline(WS, org_id=org_id))
    return int(pipeline.get_stats()["pipeline_stats"]["documents_processed"])


class TestIntegrationOrgScope:
    def test_cache_is_keyed_by_org_and_workspace(self, default_db: Path) -> None:
        async def fetch() -> list[KnowledgePipeline]:
            return [
                await integration.get_pipeline(WS, org_id="org-a"),
                await integration.get_pipeline(WS, org_id="org-a"),
                await integration.get_pipeline(WS, org_id="org-b"),
                await integration.get_pipeline(WS),
                await integration.get_pipeline("other-ws", org_id="org-a"),
            ]

        a1, a2, b, unscoped, other_ws = asyncio.run(fetch())
        assert a1 is a2
        assert len({id(a1), id(b), id(unscoped), id(other_ws)}) == 4
        assert (a1.config.org_id, b.config.org_id, unscoped.config.org_id) == (
            "org-a",
            "org-b",
            None,
        )

    def test_org_pipelines_sharing_a_workspace_are_isolated(self, default_db: Path) -> None:
        _seed(FactStore(db_path=default_db))

        async def read() -> tuple[list[str], list[str]]:
            a = await integration.get_pipeline(WS, org_id="org-a")
            b = await integration.get_pipeline(WS, org_id="org-b")
            return (
                [f.statement for f in await a.get_facts()],
                [f.statement for f in await b.get_facts()],
            )

        assert asyncio.run(read()) == ([A_FACT], [B_FACT])

    def test_pipeline_without_org_fails_closed(self, default_db: Path) -> None:
        _seed(FactStore(db_path=default_db))
        pipeline = asyncio.run(integration.get_pipeline(WS))
        with pytest.raises(OrgScopeRequiredError):
            asyncio.run(pipeline.get_facts())

    def test_sync_upload_uses_its_org_pipeline(self, default_db: Path) -> None:
        integration.process_uploaded_text(
            "Org A meeting notes.", workspace_id=WS, async_processing=False, org_id="org-a"
        )
        integration.process_uploaded_document(
            b"Org A contract text.",
            "a.txt",
            workspace_id=WS,
            async_processing=False,
            org_id="org-a",
        )
        assert (_processed("org-a"), _processed("org-b")) == (2, 0)

    def test_queued_upload_uses_its_org_pipeline(self, default_db: Path) -> None:
        uploads = [
            integration.process_uploaded_text("Org B notes.", workspace_id=WS, org_id="org-b"),
            integration.process_uploaded_document(
                b"Org B contract.", "b.txt", workspace_id=WS, org_id="org-b"
            ),
        ]
        job_ids = [u["knowledge_processing"]["job_id"] for u in uploads]
        deadline = time.monotonic() + 30
        statuses: list[Any] = []
        while time.monotonic() < deadline:
            statuses = [(integration.get_job_status(j) or {}).get("status") for j in job_ids]
            if all(s in ("completed", "failed") for s in statuses):
                break
            time.sleep(0.05)
        assert statuses == ["completed", "completed"]
        assert (_processed("org-b"), _processed("org-a")) == (2, 0)

    def test_shutdown_stops_every_org_pipeline(self, default_db: Path) -> None:
        async def run() -> list[bool]:
            pipelines = [
                await integration.get_pipeline(WS, org_id="org-a"),
                await integration.get_pipeline(WS, org_id="org-b"),
            ]
            await integration.shutdown_pipeline()
            return [p._running for p in pipelines]

        assert asyncio.run(run()) == [False, False]
        assert integration._pipelines == {}


FINDING = AuditFinding(
    id="finding-1",
    title="Payment terms",
    description="invoices are paid within thirty days",
    severity=FindingSeverity.MEDIUM,
    confidence=0.9,
    audit_type=AuditType.CONSISTENCY,
    category="payment",
    document_id="doc-audit",
)


@pytest.fixture
async def adapter() -> AsyncIterator[AuditKnowledgeAdapter]:
    adapter = AuditKnowledgeAdapter(KnowledgeAuditConfig(workspace_id=WS))
    await adapter.initialize()
    shared = InMemoryFactStore()
    _seed(shared)
    adapter._fact_store = shared
    yield adapter


class TestAuditAdapterOrgScope:
    @pytest.mark.asyncio
    async def test_reads_only_the_callers_org(self, adapter: AuditKnowledgeAdapter) -> None:
        chunk = {"id": "c1", "document_id": "doc-audit", "content": "Payment schedule"}
        enriched = await adapter.enrich_chunks([chunk], org_id="org-a")
        refs = await adapter.query_for_cross_references(FINDING, org_id="org-a")
        validation = await adapter.validate_finding_with_knowledge(FINDING, org_id="org-a")

        assert [f["statement"] for f in enriched[0].related_facts] == [A_FACT]
        assert [r["statement"] for r in refs if r["type"] == "fact"] == [A_FACT]
        assert [f["statement"] for f in validation["supporting_facts"]] == [A_FACT]

    @pytest.mark.asyncio
    async def test_chunk_reads_stay_in_the_callers_org(
        self, adapter: AuditKnowledgeAdapter
    ) -> None:
        chunk = {"chunk_id": "a1", "document_id": "doc-other", "content": FINDING.description}
        assert adapter._embedding_service is not None
        await adapter._embedding_service.embed_chunks([chunk], chunk_namespace(WS, "org-a"))

        refs = {
            org: [
                r["chunk_id"]
                for r in await adapter.query_for_cross_references(FINDING, org_id=org)
                if r["type"] == "chunk"
            ]
            for org in ("org-a", "org-b")
        }
        assert refs == {"org-a": ["a1"], "org-b": []}

    @pytest.mark.asyncio
    async def test_reads_without_org_fail_closed(self, adapter: AuditKnowledgeAdapter) -> None:
        chunk = {"id": "c1", "document_id": "doc-audit", "content": "Payment schedule"}
        with pytest.raises(OrgScopeRequiredError):
            await adapter.enrich_chunks([chunk])
        with pytest.raises(OrgScopeRequiredError):
            await adapter.query_for_cross_references(FINDING)
        with pytest.raises(OrgScopeRequiredError):
            await adapter.validate_finding_with_knowledge(FINDING)

    @pytest.mark.asyncio
    async def test_session_findings_are_stored_under_the_session_org(
        self, adapter: AuditKnowledgeAdapter
    ) -> None:
        session = AuditSession(document_ids=["doc-audit"], org_id="org-a", findings=[FINDING])
        assert await adapter.store_session_findings(session) == 1

        store = adapter._fact_store
        assert store is not None
        statement = f"{FINDING.title}: {FINDING.description}"
        org_a = store.list_facts(FactFilters(workspace_id=WS, org_id="org-a"))
        org_b = store.list_facts(FactFilters(workspace_id=WS, org_id="org-b"))
        assert statement in [f.statement for f in org_a]
        assert statement not in [f.statement for f in org_b]

    @pytest.mark.asyncio
    async def test_session_without_org_fails_closed(self, adapter: AuditKnowledgeAdapter) -> None:
        session = AuditSession(document_ids=["doc-audit"], findings=[FINDING])
        with pytest.raises(OrgScopeRequiredError):
            await adapter.store_session_findings(session)
