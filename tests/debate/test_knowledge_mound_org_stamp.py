"""Debate outcomes written to the Knowledge Mound carry the authenticated org stamp.

The organization reaches the writer only through ``arena.knowledge_org_id``
(set by the server's debate factory from an authenticated request) or an
explicit ``org_id`` keyword. A stamped outcome is also marked
``organization``-visible, so visibility-aware reads return it to actors of
that organization in any workspace and to no other organization. Without an
organization the outcome stays unstamped and carries no visibility key, as
before, so organization-filtered reads never return it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.debate.knowledge_manager import ArenaKnowledgeManager
from aragora.debate.knowledge_mound_ops import KnowledgeMoundOperations
from aragora.debate.post_debate_coordinator import PostDebateCoordinator

ORG_KEY = "org_id"
VISIBILITY_KEY = "visibility"


def _result(**overrides) -> SimpleNamespace:
    values = dict(
        id="debate-1",
        final_answer="Use a token bucket",
        confidence=0.92,
        consensus_reached=True,
        rounds_used=3,
        participants=["agent-a", "agent-b"],
        winner="agent-a",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _mound() -> AsyncMock:
    mound = AsyncMock()
    mound.workspace_id = "ws-1"
    mound.store = AsyncMock(return_value=SimpleNamespace(node_id="node-1"))
    return mound


def _stored_metadata(mound: AsyncMock) -> dict:
    mound.store.assert_awaited_once()
    return mound.store.call_args.args[0].metadata


class TestOpsStamp:
    @pytest.mark.asyncio
    async def test_org_id_is_stamped(self):
        mound = _mound()
        ops = KnowledgeMoundOperations(knowledge_mound=mound)

        await ops.ingest_debate_outcome(_result(), SimpleNamespace(task="t"), org_id="org-a")

        metadata = _stored_metadata(mound)
        assert metadata[ORG_KEY] == "org-a"
        assert metadata[VISIBILITY_KEY] == "organization"

    @pytest.mark.asyncio
    async def test_no_org_leaves_outcome_unstamped(self):
        mound = _mound()
        ops = KnowledgeMoundOperations(knowledge_mound=mound)

        await ops.ingest_debate_outcome(_result(), SimpleNamespace(task="t"))

        metadata = _stored_metadata(mound)
        assert ORG_KEY not in metadata
        assert VISIBILITY_KEY not in metadata

    @pytest.mark.asyncio
    @pytest.mark.parametrize("org_id", ["", None, 123])
    async def test_empty_or_non_string_org_leaves_outcome_unstamped(self, org_id):
        mound = _mound()
        ops = KnowledgeMoundOperations(knowledge_mound=mound)

        await ops.ingest_debate_outcome(_result(), SimpleNamespace(task="t"), org_id=org_id)

        metadata = _stored_metadata(mound)
        assert ORG_KEY not in metadata
        assert VISIBILITY_KEY not in metadata


class TestManagerPassThrough:
    @pytest.mark.asyncio
    async def test_org_id_reaches_ops(self):
        manager = ArenaKnowledgeManager(knowledge_mound=MagicMock(), enable_ingestion=True)
        manager.initialize()
        manager._knowledge_ops.ingest_debate_outcome = AsyncMock()
        result, env = MagicMock(), MagicMock()

        await manager.ingest_outcome(result, env, org_id="org-a")

        manager._knowledge_ops.ingest_debate_outcome.assert_awaited_once_with(
            result, env=env, org_id="org-a"
        )

    @pytest.mark.asyncio
    async def test_default_is_unstamped(self):
        manager = ArenaKnowledgeManager(knowledge_mound=MagicMock(), enable_ingestion=True)
        manager.initialize()
        manager._knowledge_ops.ingest_debate_outcome = AsyncMock()
        result, env = MagicMock(), MagicMock()

        await manager.ingest_outcome(result, env)

        manager._knowledge_ops.ingest_debate_outcome.assert_awaited_once_with(
            result, env=env, org_id=None
        )


class TestPostDebateCoordinatorPassThrough:
    def test_org_id_is_stamped(self):
        mound = _mound()
        coordinator = PostDebateCoordinator(knowledge_mound=mound, org_id="org-a")

        assert coordinator._step_ingest_outcome("debate-1", _result(), "task") is True

        metadata = _stored_metadata(mound)
        assert metadata[ORG_KEY] == "org-a"
        assert metadata[VISIBILITY_KEY] == "organization"

    def test_default_is_unstamped(self):
        mound = _mound()
        coordinator = PostDebateCoordinator(knowledge_mound=mound)

        assert coordinator._step_ingest_outcome("debate-1", _result(), "task") is True

        metadata = _stored_metadata(mound)
        assert ORG_KEY not in metadata
        assert VISIBILITY_KEY not in metadata


class TestArenaDelegate:
    def _arena(self):
        from aragora.debate.orchestrator import Arena

        arena = Arena.__new__(Arena)
        arena._km_manager = MagicMock()
        arena._km_manager.ingest_outcome = AsyncMock()
        arena.env = MagicMock()
        return arena

    @pytest.mark.asyncio
    async def test_knowledge_org_id_reaches_manager(self):
        arena = self._arena()
        arena.knowledge_org_id = "org-a"
        result = MagicMock()

        await arena._ingest_debate_outcome(result)

        arena._km_manager.ingest_outcome.assert_awaited_once_with(result, arena.env, org_id="org-a")

    @pytest.mark.asyncio
    async def test_unset_attribute_is_unstamped_even_with_billing_org(self):
        arena = self._arena()
        arena.org_id = "billing-org"
        result = MagicMock()

        await arena._ingest_debate_outcome(result)

        arena._km_manager.ingest_outcome.assert_awaited_once_with(result, arena.env, org_id=None)


async def _sqlite_mound(tmp_path, monkeypatch, workspace_id: str):
    from aragora.knowledge.mound import KnowledgeMound, MoundBackend, MoundConfig
    from aragora.knowledge.mound.semantic_store import EmbeddingProvider, SemanticStore

    # Hash embeddings keep the test offline; the org stamp does not depend on them.
    monkeypatch.setattr(
        SemanticStore,
        "_auto_detect_provider",
        lambda self: EmbeddingProvider(dimension=256),
    )
    mound = KnowledgeMound(  # type: ignore[abstract]
        config=MoundConfig(backend=MoundBackend.SQLITE, sqlite_path=tmp_path / "km.db"),
        workspace_id=workspace_id,
    )
    await mound.initialize()
    return mound


class TestRealSqliteMound:
    @pytest.mark.asyncio
    async def test_stamp_persists_through_real_mound_for_inline_org_filter(
        self, tmp_path, monkeypatch
    ):
        """Reads that compare the stamp inline see only their organization's outcome."""
        mound = await _sqlite_mound(tmp_path, monkeypatch, "ws-org")
        try:
            ops = KnowledgeMoundOperations(knowledge_mound=mound)
            env = SimpleNamespace(task="Design a rate limiter")
            await ops.ingest_debate_outcome(
                _result(id="d-a", final_answer="Org A picks a token bucket"), env, org_id="org-a"
            )
            await ops.ingest_debate_outcome(
                _result(id="d-none", final_answer="Anonymous run picks a leaky bucket"), env
            )

            items = (await mound.query("Debate Conclusion", limit=50)).items
        finally:
            await mound.close()

        def for_org(org: str) -> list:
            return [
                i for i in items if isinstance(i.metadata, dict) and i.metadata.get(ORG_KEY) == org
            ]

        assert len(items) == 2
        assert [i.metadata["debate_id"] for i in for_org("org-a")] == ["d-a"]
        assert for_org("org-b") == []
        unstamped = [i for i in items if i.metadata.get("debate_id") == "d-none"]
        assert len(unstamped) == 1 and ORG_KEY not in unstamped[0].metadata

    @pytest.mark.asyncio
    async def test_stamped_outcome_is_visible_across_workspaces_to_its_org_only(
        self, tmp_path, monkeypatch
    ):
        # The server's singleton Mound writes debate outcomes to the shared "default" workspace.
        mound = await _sqlite_mound(tmp_path, monkeypatch, "default")
        try:
            ops = KnowledgeMoundOperations(knowledge_mound=mound)
            env = SimpleNamespace(task="Design a rate limiter")
            await ops.ingest_debate_outcome(
                _result(id="d-a", final_answer="Org A picks a token bucket"), env, org_id="org-a"
            )
            await ops.ingest_debate_outcome(
                _result(id="d-none", final_answer="Anonymous run picks a leaky bucket"), env
            )
            # Identical text from another organization deduplicates onto org-a's node.
            await ops.ingest_debate_outcome(
                _result(id="d-b", final_answer="Org A picks a token bucket"), env, org_id="org-b"
            )

            async def visible(org: str | None, actor_workspace: str) -> list[str]:
                found = await mound.query_with_visibility(
                    "Debate Conclusion",
                    actor_id="user-1",
                    actor_workspace_id=actor_workspace,
                    actor_org_id=org,
                    limit=50,
                    workspace_id="default",
                )
                return sorted(i.metadata["debate_id"] for i in found.items)

            assert await visible("org-a", "ws-other") == ["d-a"]
            assert await visible("org-a", "default") == ["d-a"]
            assert await visible("org-b", "default") == []
            assert await visible("org-b", "ws-other") == []
            assert await visible(None, "default") == []

            stored = (await mound.query("Debate Conclusion", limit=50)).items
        finally:
            await mound.close()

        by_debate = {i.metadata["debate_id"]: i.metadata for i in stored}
        assert sorted(by_debate) == ["d-a", "d-none"]
        assert by_debate["d-a"][ORG_KEY] == "org-a"
        assert by_debate["d-a"][VISIBILITY_KEY] == "organization"
        # Unstamped outcomes keep main's shape. store() records no workspace_id in metadata,
        # so the default workspace rule returns them to no actor, exactly as before.
        assert ORG_KEY not in by_debate["d-none"]
        assert VISIBILITY_KEY not in by_debate["d-none"]


def test_stamp_key_matches_the_key_org_filtered_reads_compare():
    from aragora.debate import knowledge_mound_ops

    assert knowledge_mound_ops.MOUND_ORG_KEY == ORG_KEY
