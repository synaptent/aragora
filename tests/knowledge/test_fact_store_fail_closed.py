"""Fact stores fail closed without an organization; organizations never share a workspace."""

from __future__ import annotations

import asyncio
import sqlite3
import uuid
from argparse import Namespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.exceptions import AuthorizationError
from aragora.knowledge import (
    FactFilters,
    FactRelationType,
    FactStore,
    InMemoryEmbeddingService,
    InMemoryFactStore,
    ScopedFactStore,
    SimpleQueryEngine,
)
from aragora.knowledge.fact_store import OrgScopeRequiredError
from tests.knowledge._legacy_rows import seed_unassigned

ACME, BETA = "org-acme", "org-beta"


@pytest.fixture(params=["sqlite", "memory"])
def store(request, tmp_path):
    if request.param == "sqlite":
        return FactStore(db_path=tmp_path / "knowledge.db")
    return InMemoryFactStore()


def _rows(store) -> tuple[int, int]:
    if isinstance(store, FactStore):
        with sqlite3.connect(store.db_path) as conn:
            facts = conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
            fts = conn.execute("SELECT COUNT(*) FROM facts_fts").fetchone()[0]
        return facts, fts
    return len(store._facts), len(store._relations)


UNSCOPED_CALLS = {
    "add_fact": lambda s, fid: s.add_fact("Unscoped write", "default"),
    "add_fact_blank_org": lambda s, fid: s.add_fact("Unscoped write", "default", org_id=" "),
    "get_fact": lambda s, fid: s.get_fact(fid),
    "update_fact": lambda s, fid: s.update_fact(fid, confidence=0.99),
    "query_facts": lambda s, fid: s.query_facts("Northwind", FactFilters(workspace_id="default")),
    "query_facts_no_filters": lambda s, fid: s.query_facts("Northwind"),
    "query_facts_empty_query": lambda s, fid: s.query_facts("", FactFilters()),
    "list_facts": lambda s, fid: s.list_facts(),
    "list_facts_blank_org": lambda s, fid: s.list_facts(FactFilters(org_id="")),
    "get_contradictions": lambda s, fid: s.get_contradictions(fid),
    "add_relation": lambda s, fid: s.add_relation(fid, fid, FactRelationType.SUPPORTS),
    "get_relations": lambda s, fid: s.get_relations(fid),
    "delete_fact": lambda s, fid: s.delete_fact(fid),
    "get_statistics": lambda s, fid: s.get_statistics(),
    "get_statistics_workspace": lambda s, fid: s.get_statistics("default"),
}


def test_error_is_an_authorization_error_and_nothing_that_layers_swallow() -> None:
    assert issubclass(OrgScopeRequiredError, AuthorizationError)
    for swallowed in (ValueError, RuntimeError, OSError, KeyError, TypeError, AttributeError):
        assert not issubclass(OrgScopeRequiredError, swallowed)


@pytest.mark.parametrize("call", sorted(UNSCOPED_CALLS))
def test_every_store_method_without_org_raises(store, call: str) -> None:
    fid = ScopedFactStore(store, ACME).add_fact("Acme acquires Northwind", "default").id
    seed_unassigned(store, "Legacy Northwind note")
    before = _rows(store)
    with pytest.raises(OrgScopeRequiredError):
        UNSCOPED_CALLS[call](store, fid)
    assert _rows(store) == before
    assert ScopedFactStore(store, ACME).get_fact(fid).confidence == 0.5


def test_same_workspace_name_is_a_separate_place_per_org(store) -> None:
    acme, beta = ScopedFactStore(store, ACME), ScopedFactStore(store, BETA)
    a = acme.add_fact("Quarterly target is 10M", "default")
    b = beta.add_fact("Quarterly target is 10M", "default")
    assert a.id != b.id and (a.org_id, b.org_id) == (ACME, BETA)
    only_default = FactFilters(workspace_id="default")
    assert [f.id for f in acme.list_facts(only_default)] == [a.id]
    assert [f.id for f in beta.list_facts(only_default)] == [b.id]
    assert b.id not in {f.id for f in acme.query_facts("Quarterly", only_default)}
    assert acme.get_fact(b.id) is None and beta.get_fact(a.id) is None
    assert acme.get_statistics("default")["total_facts"] == 1


def test_unassigned_facts_reach_no_ordinary_reader(store) -> None:
    legacy = seed_unassigned(store, "Contoso renewal price is 41000 EUR").id
    acme = ScopedFactStore(store, ACME)
    own = acme.add_fact("Contoso renewal price is 41000 EUR", "default")
    assert own.id != legacy and own.org_id == ACME
    assert legacy not in {f.id for f in acme.list_facts(FactFilters(include_superseded=True))}
    assert legacy not in {f.id for f in acme.query_facts("Contoso")}
    assert acme.get_fact(legacy) is None
    assert acme.delete_fact(legacy) is False
    assert acme.get_statistics()["total_facts"] == 1
    with pytest.raises(OrgScopeRequiredError):
        store.get_fact(legacy)


def test_uuid_workspace_id_round_trips_verbatim(store) -> None:
    workspace = str(uuid.uuid4())
    acme = ScopedFactStore(store, ACME)
    fact = acme.add_fact("Workspace ids are stored as given", workspace)
    assert fact.workspace_id == workspace
    assert acme.get_fact(fact.id).workspace_id == workspace
    assert [f.id for f in acme.list_facts(FactFilters(workspace_id=workspace))] == [fact.id]
    assert ScopedFactStore(store, BETA).list_facts(FactFilters(workspace_id=workspace)) == []


# In-process readers and writers without a trusted organization raise; none returns empty.


def test_query_engine_without_org_raises(store) -> None:
    ScopedFactStore(store, ACME).add_fact("Acme acquires Northwind", "default")
    engine = SimpleQueryEngine(fact_store=store, embedding_service=InMemoryEmbeddingService())
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(engine.get_facts("Northwind", "default"))
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(engine.query("Who buys Northwind?", "default"))


def test_unified_store_fact_query_raises_instead_of_dropping_the_source(store) -> None:
    from aragora.knowledge.unified.unified_store import KnowledgeMound, KnowledgeMoundConfig

    ScopedFactStore(store, ACME).add_fact("Acme acquires Northwind", "default")
    for parallel in (True, False):
        config = KnowledgeMoundConfig(fact_store=store, parallel_queries=parallel)
        mound = KnowledgeMound(config)
        mound._initialized = True
        with pytest.raises(OrgScopeRequiredError):
            asyncio.run(mound.query("Northwind", sources=("fact",)))


def test_fact_extractor_and_audit_adapter_without_org_raise(store) -> None:
    from aragora.audit.knowledge_adapter import AuditKnowledgeAdapter
    from aragora.knowledge.fact_extractor import FactExtractor

    extractor = FactExtractor(fact_store=store)
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(
            extractor.extract_facts(
                "The contract with Contoso renews on 2027-01-01 for 41000 EUR.",
                "chunk-1",
                "doc-1",
                workspace_id="default",
            )
        )
    adapter = AuditKnowledgeAdapter()
    asyncio.run(adapter.initialize())
    adapter._fact_store = store
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(
            adapter.enrich_chunks([{"id": "c1", "content": "Northwind", "document_id": "d"}])
        )


def test_pipeline_reads_without_org_raise(store) -> None:
    from aragora.knowledge.pipeline import KnowledgePipeline, PipelineConfig

    pipeline = KnowledgePipeline(PipelineConfig(workspace_id="default"), fact_store=store)
    pipeline._running = True
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(pipeline.get_facts())
    with pytest.raises(OrgScopeRequiredError):
        pipeline.get_stats()


def test_mound_fact_sync_raises_and_writes_no_node(store) -> None:
    from aragora.knowledge.mound.ops.sync import SyncOperationsMixin

    ScopedFactStore(store, ACME).add_fact("Acme acquires Northwind", "default")
    mound = MagicMock()
    mound.workspace_id = "default"
    mound._facts = store
    mound._batch_store = AsyncMock(return_value=(1, 0, 0, 0, []))
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(SyncOperationsMixin.sync_facts_incremental(mound, workspace_id="default"))
    with pytest.raises(OrgScopeRequiredError):
        asyncio.run(SyncOperationsMixin.sync_from_facts(mound, store))
    mound._batch_store.assert_not_called()


@pytest.mark.parametrize("command", ["facts", "stats"])
def test_cli_fact_commands_fail_closed_with_a_clear_message(command, capsys) -> None:
    from aragora.cli import knowledge as cli

    args = Namespace(
        action="list",
        workspace="default",
        limit=10,
        min_confidence=0.0,
        status=None,
        fact_id=None,
        json=True,
    )
    code = getattr(cli, f"cmd_{command}")(args)
    captured = capsys.readouterr()
    assert code != 0
    assert "organization" in captured.err
    assert '"facts"' not in captured.out


def test_evidence_fetch_no_longer_reads_an_unscoped_store(monkeypatch) -> None:
    import sys

    from aragora.knowledge import fact_store as fact_store_module
    from aragora.skills.builtin import evidence_fetch

    calls: list[str] = []
    monkeypatch.setitem(sys.modules, "aragora.server.http_client_pool", None)
    monkeypatch.setattr(
        fact_store_module.InMemoryFactStore,
        "query_facts",
        lambda self, *a, **k: calls.append("query_facts") or [],
    )
    results = asyncio.run(evidence_fetch.EvidenceFetchSkill()._check_facts("Northwind"))
    assert calls == [] and results == []
