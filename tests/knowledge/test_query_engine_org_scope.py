"""Org scoping through the query engines, over a scoped view and over a raw store."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.knowledge import FactStore, InMemoryFactStore
from aragora.knowledge.embeddings import ChunkMatch
from aragora.knowledge.fact_store import OrgScopeRequiredError, ScopedFactStore
from aragora.knowledge.query_engine import DatasetQueryEngine, QueryOptions, SimpleQueryEngine
from tests.knowledge._legacy_rows import seed_unassigned


class _Agent:
    name = "extractor"

    def __init__(self, response: str) -> None:
        self.response = response

    async def generate(self, prompt: str, context: list[dict[str, str]]) -> str:
        return self.response


def _embedding_service() -> MagicMock:
    service = MagicMock()
    service.hybrid_search = AsyncMock(
        return_value=[
            ChunkMatch(
                chunk_id="chunk_1",
                document_id="doc_1",
                workspace_id="default",
                content="Renewal notice is due ninety days before the term ends.",
                score=0.9,
            )
        ]
    )
    return service


@pytest.fixture(params=["sqlite", "memory"])
def seeded(request, tmp_path):
    store = (
        FactStore(db_path=tmp_path / "knowledge.db")
        if request.param == "sqlite"
        else InMemoryFactStore()
    )
    own = ScopedFactStore(store, "org_a").add_fact(
        "Renewal notice is due in ninety days", "default", confidence=0.9
    )
    foreign = ScopedFactStore(store, "org_b").add_fact(
        "Renewal notice is due in thirty days", "default", confidence=0.9
    )
    unassigned = seed_unassigned(store, "Renewal notice is due in sixty days")
    return store, own, foreign, unassigned


EXTRACTED = "FACT: Renewal notice is due in thirty days"
# An empty question reads through the org-filtered fact list on both backends;
# SQLite keyword search over the contentless FTS table matches no rows.
ALL = ""


@pytest.mark.asyncio
async def test_simple_engine_over_scoped_view(seeded):
    store, own, _, _ = seeded
    engine = SimpleQueryEngine(ScopedFactStore(store, "org_a"), _embedding_service())

    assert [f.id for f in await engine.get_facts(ALL, "default")] == [own.id]
    result = await engine.query(ALL, "default")
    assert [f.id for f in result.facts] == [own.id]
    assert engine.add_fact("Added through the engine", "default").org_id == "org_a"


@pytest.mark.asyncio
async def test_simple_engine_org_id_on_raw_store(seeded):
    store, own, _, _ = seeded
    engine = SimpleQueryEngine(store, _embedding_service())

    assert [f.id for f in await engine.get_facts(ALL, "default", org_id="org_a")] == [own.id]
    with pytest.raises(OrgScopeRequiredError):
        await engine.get_facts(ALL, "default")
    result = await engine.query(ALL, "default", org_id="org_a")
    assert [f.id for f in result.facts] == [own.id]
    assert engine.add_fact("Added with an org", "default", org_id="org_a").org_id == "org_a"


@pytest.mark.parametrize("scope_by", ["view", "argument"])
@pytest.mark.asyncio
async def test_dataset_engine_query_stays_in_org(seeded, scope_by):
    store, own, foreign, _ = seeded
    if scope_by == "view":
        engine_store, kwargs = ScopedFactStore(store, "org_a"), {}
    else:
        engine_store, kwargs = store, {"org_id": "org_a"}
    engine = DatasetQueryEngine(
        fact_store=engine_store,
        embedding_service=_embedding_service(),
        default_agent=_Agent(EXTRACTED),
    )

    result = await engine.query(ALL, "default", QueryOptions(use_agents=True), **kwargs)

    assert own.id in [f.id for f in result.facts]
    extracted = result.metadata["extracted_facts"]
    assert extracted == 1
    new_fact = result.facts[-1]
    assert new_fact.id != foreign.id
    assert new_fact.org_id == "org_a"
    assert all(f.org_id == "org_a" for f in result.facts)
    facts = await engine.get_facts_for_query(ALL, "default", **kwargs)
    assert {f.org_id for f in facts} == {"org_a"}


@pytest.mark.parametrize("scope_by", ["view", "argument"])
@pytest.mark.asyncio
async def test_dataset_engine_verify_stays_in_org(seeded, scope_by):
    store, own, foreign, unassigned = seeded
    if scope_by == "view":
        engine_store, kwargs = ScopedFactStore(store, "org_a"), {}
    else:
        engine_store, kwargs = store, {"org_id": "org_a"}
    engine = DatasetQueryEngine(fact_store=engine_store, agents=[_Agent("TRUE, it holds")])

    for other in (foreign, unassigned):
        with pytest.raises(ValueError, match="Fact not found"):
            await engine.verify_fact(other.id, **kwargs)
    assert store.get_fact(foreign.id, org_id="org_b").validation_status.value == "unverified"
    verified = await engine.verify_fact(own.id, **kwargs)
    assert verified.validation_status.value == "majority_agreed"
