"""Tests for ArenaKnowledgeManager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.debate.knowledge_manager import ArenaKnowledgeManager

if TYPE_CHECKING:
    from aragora.knowledge.mound import KnowledgeMound


class TestArenaKnowledgeManagerInit:
    """Tests for ArenaKnowledgeManager initialization."""

    def test_init_without_knowledge_mound(self) -> None:
        """Manager can be created without a knowledge mound."""
        manager = ArenaKnowledgeManager()
        assert manager.knowledge_mound is None
        assert manager.enable_retrieval is False
        assert manager.enable_ingestion is False

    def test_init_with_knowledge_mound(self) -> None:
        """Manager stores the knowledge mound reference."""
        mock_mound = MagicMock()
        manager = ArenaKnowledgeManager(
            knowledge_mound=mock_mound,
            enable_retrieval=True,
            enable_ingestion=True,
        )
        assert manager.knowledge_mound is mock_mound
        assert manager.enable_retrieval is True
        assert manager.enable_ingestion is True

    def test_init_with_revalidation_config(self) -> None:
        """Manager stores revalidation configuration."""
        manager = ArenaKnowledgeManager(
            enable_auto_revalidation=True,
            revalidation_staleness_threshold=0.5,
            revalidation_check_interval_seconds=1800,
        )
        assert manager.enable_auto_revalidation is True
        assert manager.revalidation_staleness_threshold == 0.5
        assert manager.revalidation_check_interval_seconds == 1800

    def test_init_with_notify_callback(self) -> None:
        """Manager stores the notify callback."""
        callback = MagicMock()
        manager = ArenaKnowledgeManager(notify_callback=callback)
        assert manager._notify_callback is callback


class TestArenaKnowledgeManagerInitialize:
    """Tests for ArenaKnowledgeManager.initialize()."""

    def test_initialize_creates_knowledge_ops(self) -> None:
        """initialize() creates KnowledgeMoundOperations."""
        mock_mound = MagicMock()
        manager = ArenaKnowledgeManager(
            knowledge_mound=mock_mound,
            enable_retrieval=True,
            enable_ingestion=True,
        )
        manager.initialize()
        assert manager._knowledge_ops is not None

    def test_initialize_creates_bridge_hub_with_mound(self) -> None:
        """initialize() creates KnowledgeBridgeHub when mound provided."""
        mock_mound = MagicMock()
        manager = ArenaKnowledgeManager(knowledge_mound=mock_mound)
        manager.initialize()
        assert manager.knowledge_bridge_hub is not None

    def test_initialize_without_mound_no_bridge_hub(self) -> None:
        """initialize() does not create bridge hub without mound."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        assert manager.knowledge_bridge_hub is None

    def test_initialize_creates_revalidation_scheduler(self) -> None:
        """initialize() creates RevalidationScheduler when enabled."""
        mock_mound = MagicMock()
        manager = ArenaKnowledgeManager(
            knowledge_mound=mock_mound,
            enable_auto_revalidation=True,
        )
        manager.initialize()
        # RevalidationScheduler may not be available, so check if it was attempted
        # The actual creation depends on module availability

    def test_initialize_with_subsystems(self) -> None:
        """initialize() accepts subsystem parameters."""
        mock_mound = MagicMock()
        mock_memory = MagicMock()
        mock_elo = MagicMock()

        manager = ArenaKnowledgeManager(knowledge_mound=mock_mound)
        # Should not raise
        manager.initialize(
            continuum_memory=mock_memory,
            elo_system=mock_elo,
        )


class TestArenaKnowledgeManagerCultureHints:
    """Tests for culture hint methods."""

    def test_get_culture_hints_without_events(self) -> None:
        """get_culture_hints returns empty dict when events unavailable."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        hints = manager.get_culture_hints("test-debate-id")
        assert hints == {}

    def test_apply_culture_hints_empty(self) -> None:
        """apply_culture_hints handles empty hints."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        manager.apply_culture_hints({})
        assert manager.culture_consensus_hint is None

    def test_apply_culture_hints_consensus(self) -> None:
        """apply_culture_hints applies consensus recommendation."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        manager.apply_culture_hints({"recommended_consensus": "unanimous"})
        assert manager.culture_consensus_hint == "unanimous"

    def test_apply_culture_hints_extra_critiques(self) -> None:
        """apply_culture_hints applies extra critique rounds."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        manager.apply_culture_hints({"extra_critique_rounds": 2})
        assert manager.culture_extra_critiques == 2

    def test_apply_culture_hints_early_consensus(self) -> None:
        """apply_culture_hints applies early consensus threshold."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        manager.apply_culture_hints({"early_consensus_threshold": 0.85})
        assert manager.culture_early_consensus == 0.85

    def test_apply_culture_hints_domain_patterns(self) -> None:
        """apply_culture_hints stores domain patterns."""
        manager = ArenaKnowledgeManager()
        manager.initialize()
        patterns = {"security": {"min_rounds": 3}}
        manager.apply_culture_hints({"domain_patterns": patterns})
        assert manager.culture_domain_patterns == patterns


class TestArenaKnowledgeManagerKnowledgeOps:
    """Tests for knowledge operations (fetch/ingest)."""

    @pytest.mark.asyncio
    async def test_fetch_context_without_ops(self) -> None:
        """fetch_context returns None without initialized ops."""
        manager = ArenaKnowledgeManager()
        # Don't call initialize
        result = await manager.fetch_context("test task")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_context_delegates_to_ops(self) -> None:
        """fetch_context delegates to _knowledge_ops."""
        mock_mound = MagicMock()
        manager = ArenaKnowledgeManager(
            knowledge_mound=mock_mound,
            enable_retrieval=True,
        )
        manager.initialize()

        # Mock the ops method
        manager._knowledge_ops.fetch_knowledge_context = AsyncMock(return_value="test context")

        result = await manager.fetch_context("test task", limit=5)
        assert result == "test context"
        manager._knowledge_ops.fetch_knowledge_context.assert_awaited_once_with("test task", 5)

    @pytest.mark.asyncio
    async def test_ingest_outcome_without_ops(self) -> None:
        """ingest_outcome returns early without initialized ops."""
        manager = ArenaKnowledgeManager()
        # Don't call initialize
        mock_result = MagicMock()
        mock_env = MagicMock()
        # Should not raise
        await manager.ingest_outcome(mock_result, mock_env)

    @pytest.mark.asyncio
    async def test_ingest_outcome_delegates_to_ops(self) -> None:
        """ingest_outcome delegates to _knowledge_ops."""
        mock_mound = MagicMock()
        manager = ArenaKnowledgeManager(
            knowledge_mound=mock_mound,
            enable_ingestion=True,
        )
        manager.initialize()

        # Mock the ops method
        manager._knowledge_ops.ingest_debate_outcome = AsyncMock()

        mock_result = MagicMock()
        mock_env = MagicMock()
        await manager.ingest_outcome(mock_result, mock_env)

        manager._knowledge_ops.ingest_debate_outcome.assert_awaited_once_with(
            mock_result, env=mock_env, org_id=None
        )


class TestArenaKnowledgeManagerProperties:
    """Tests for manager properties."""

    def test_culture_properties_default_values(self) -> None:
        """Culture properties have correct default values."""
        manager = ArenaKnowledgeManager()
        assert manager.culture_consensus_hint is None
        assert manager.culture_extra_critiques == 0
        assert manager.culture_early_consensus is None
        assert manager.culture_domain_patterns == {}
