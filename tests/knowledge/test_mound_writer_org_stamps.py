"""Knowledge Mound writes take the organization stamp only from an authenticated org_id."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from aragora.knowledge.mound import (
    IngestionRequest,
    KnowledgeMound,
    KnowledgeSource,
    MoundBackend,
    MoundConfig,
)
from aragora.knowledge.pipeline import mound_items_for_org

STAMP = {"org_id": "acme"}


@pytest.fixture
async def mound(tmp_path: Any) -> Any:
    config = MoundConfig(backend=MoundBackend.SQLITE, sqlite_path=str(tmp_path / "mound.db"))
    mound = KnowledgeMound(config=config, workspace_id="research")  # type: ignore[abstract]
    await mound.initialize()
    mound._semantic_store = None
    yield mound
    await mound.close()


def _request(content: str, **metadata: Any) -> Any:
    return IngestionRequest(
        content=content,
        source_type=KnowledgeSource.DOCUMENT,
        workspace_id="research",
        metadata=metadata,
    )


async def test_store_takes_the_stamp_from_org_id_never_from_request_metadata(mound: Any) -> None:
    planted = await mound.store(_request("planted plan", org_id="victim"))
    acme = await mound.store(_request("acme plan", org_id="victim"), org_id="acme")
    added = await mound.add("added plan", metadata={"org_id": "victim"}, org_id="acme")
    stored = [await mound.get(planted.node_id), await mound.get(acme.node_id)]
    stored.append(await mound.get(added))

    assert [i.content for i in mound_items_for_org(stored, "acme")] == ["acme plan", "added plan"]
    assert mound_items_for_org(stored, "victim") == []


async def test_identical_content_from_two_organizations_keeps_one_stamped_copy_each(
    mound: Any, tmp_path: Any
) -> None:
    from aragora.knowledge.mound.semantic_store import SemanticStore
    from aragora.memory.embeddings import EmbeddingProvider

    class _HashEmbedding(EmbeddingProvider):
        async def embed(self, text: str) -> list[float]:
            digest = hashlib.sha256(text.encode()).digest()
            return [byte / 255 for byte in digest[: self.dimension]]

    mound._semantic_store = SemanticStore(
        db_path=str(tmp_path / "semantic.db"),
        embedding_provider=_HashEmbedding(dimension=16),
        default_tenant_id="research",
    )
    acme = await mound.store(_request("shared roadmap"), org_id="acme")
    beta = await mound.store(_request("shared roadmap"), org_id="beta")
    acme_again = await mound.store(_request("shared roadmap"), org_id="acme")

    assert not beta.deduplicated and beta.node_id != acme.node_id
    assert acme_again.deduplicated and acme_again.node_id == acme.node_id
    for node_id, org_id in ((acme.node_id, "acme"), (beta.node_id, "beta")):
        stored = await mound.get(node_id)
        assert stored is not None and stored.metadata["org_id"] == org_id
    hits = await mound._semantic_store.search_similar("shared roadmap", tenant_id="research")
    assert sorted(hit.source_id for hit in hits) == sorted([acme.node_id, beta.node_id])


async def test_vector_hits_keep_the_stamp_their_index_stored(mound: Any) -> None:
    from aragora.knowledge.mound.vector_abstraction import VectorSearchResult

    class _Vectors:
        async def search(self, **kwargs: Any) -> list[Any]:
            hit = VectorSearchResult(id="v1", content="acme plan", score=0.9, metadata=STAMP)
            return [hit]

        async def close(self) -> None:
            return None

    mound._vector_store = _Vectors()
    items = await mound.query_semantic("plan")

    assert [item.content for item in mound_items_for_org(items, "acme")] == ["acme plan"]
    assert mound_items_for_org(items, "beta") == []


@pytest.mark.parametrize(
    "replacement",
    [{"org_id": "victim"}, {"topic": "q3", "org_id": None}, {"superseded_by": "kn_new"}],
    ids=["changed", "removed", "whole-metadata"],
)
async def test_update_keeps_the_stamp_the_node_was_written_with(
    mound: Any, replacement: dict[str, Any]
) -> None:
    node_id = await mound.add("acme plan", metadata={"topic": "q3"}, org_id="acme")

    updated = await mound.update(node_id, {"metadata": replacement})

    assert updated.metadata == {**replacement, "org_id": "acme"}
    assert [i.content for i in mound_items_for_org([updated], "acme")] == ["acme plan"]


async def test_update_never_stamps_an_unstamped_node(mound: Any) -> None:
    node_id = await mound.add("bare plan")

    updated = await mound.update(node_id, {"metadata": STAMP})

    assert mound_items_for_org([updated], "acme") == []
