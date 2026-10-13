"""
Tests for server initialization - subsystem setup and configuration.

Tests individual init_* functions and SubsystemRegistry.
"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
import tempfile
import os

from aragora.server.initialization import (
    SubsystemRegistry,
    get_registry,
    initialize_subsystems,
    initialize_subsystems_async,
    init_persistence,
    init_insight_store,
    init_elo_system,
    init_flip_detector,
    init_persona_manager,
    init_position_ledger,
    init_debate_embeddings,
    init_consensus_memory,
    init_moment_detector,
    init_position_tracker,
    init_continuum_memory,
    init_verification_manager,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_nomic_dir():
    """Create a temporary nomic directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        nomic_dir = Path(tmpdir)
        # Create expected database files (matching LEGACY_DB_NAMES)
        (nomic_dir / "aragora_insights.db").touch()  # INSIGHTS
        (nomic_dir / "agent_elo.db").touch()  # ELO
        (nomic_dir / "grounded_positions.db").touch()  # POSITIONS
        (nomic_dir / "agent_personas.db").touch()  # PERSONAS
        (nomic_dir / "aragora_positions.db").touch()  # TRUTH_GROUNDING
        (nomic_dir / "debate_embeddings.db").touch()  # EMBEDDINGS
        yield nomic_dir


@pytest.fixture
def fresh_registry():
    """Reset the global registry for each test."""
    import aragora.server.initialization as init_module

    old_registry = init_module._registry
    init_module._registry = None
    yield
    init_module._registry = old_registry


# =============================================================================
# init_persistence Tests
# =============================================================================


class TestInitPersistence:
    """Tests for init_persistence function."""

    def test_returns_none_when_disabled(self):
        """Should return None when enable=False."""
        result = init_persistence(enable=False)
        assert result is None

    @patch("aragora.server.initialization.PERSISTENCE_AVAILABLE", False)
    def test_returns_none_when_not_available(self):
        """Should return None when persistence module not available."""
        result = init_persistence(enable=True)
        assert result is None

    @patch("aragora.server.initialization.PERSISTENCE_AVAILABLE", True)
    @patch("aragora.server.initialization.SupabaseClient")
    def test_returns_client_when_configured(self, mock_client_class):
        """Should return client when properly configured."""
        mock_client = MagicMock()
        mock_client.is_configured = True
        mock_client_class.return_value = mock_client

        result = init_persistence(enable=True)
        assert result == mock_client

    @patch("aragora.server.initialization.PERSISTENCE_AVAILABLE", True)
    @patch("aragora.server.initialization.SupabaseClient")
    def test_returns_none_when_not_configured(self, mock_client_class):
        """Should return None when client not configured."""
        mock_client = MagicMock()
        mock_client.is_configured = False
        mock_client_class.return_value = mock_client

        result = init_persistence(enable=True)
        assert result is None


# =============================================================================
# init_insight_store Tests
# =============================================================================


class TestInitInsightStore:
    """Tests for init_insight_store function."""

    @patch("aragora.server.initialization.INSIGHTS_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when insights module not available."""
        result = init_insight_store(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.INSIGHTS_AVAILABLE", True)
    @patch("aragora.server.initialization.InsightStore")
    def test_returns_store_when_db_exists(self, mock_store_class, temp_nomic_dir):
        """Should return store when database exists."""
        mock_store = MagicMock()
        mock_store_class.return_value = mock_store

        result = init_insight_store(temp_nomic_dir)
        assert result == mock_store

    @patch("aragora.server.initialization.INSIGHTS_AVAILABLE", True)
    @patch("aragora.server.initialization.InsightStore")
    def test_returns_none_when_store_init_fails(self, mock_store_class):
        """Should return None when InsightStore initialization raises."""
        mock_store_class.side_effect = OSError("Disk full")
        with tempfile.TemporaryDirectory() as tmpdir:
            nomic_dir = Path(tmpdir)
            result = init_insight_store(nomic_dir)
            assert result is None


# =============================================================================
# init_elo_system Tests
# =============================================================================


class TestInitEloSystem:
    """Tests for init_elo_system function."""

    @patch("aragora.server.initialization.RANKING_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when ranking module not available."""
        result = init_elo_system(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.RANKING_AVAILABLE", True)
    @patch("aragora.server.initialization.EloSystem")
    def test_returns_system_when_db_exists(self, mock_elo_class, temp_nomic_dir):
        """Should return system when database exists."""
        mock_elo = MagicMock()
        mock_elo_class.return_value = mock_elo

        result = init_elo_system(temp_nomic_dir)
        assert result == mock_elo


# =============================================================================
# init_flip_detector Tests
# =============================================================================


class TestInitFlipDetector:
    """Tests for init_flip_detector function."""

    @patch("aragora.server.initialization.FLIP_DETECTOR_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when flip detector module not available."""
        result = init_flip_detector(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.FLIP_DETECTOR_AVAILABLE", True)
    @patch("aragora.server.initialization.FlipDetector")
    def test_returns_detector_when_db_exists(self, mock_detector_class, temp_nomic_dir):
        """Should return detector when database exists."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector

        result = init_flip_detector(temp_nomic_dir)
        assert result == mock_detector


# =============================================================================
# init_persona_manager Tests
# =============================================================================


class TestInitPersonaManager:
    """Tests for init_persona_manager function."""

    @patch("aragora.server.initialization.PERSONAS_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when personas module not available."""
        result = init_persona_manager(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.PERSONAS_AVAILABLE", True)
    @patch("aragora.server.initialization.PersonaManager")
    def test_returns_manager(self, mock_manager_class, temp_nomic_dir):
        """Should return manager (creates db if needed)."""
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        result = init_persona_manager(temp_nomic_dir)
        assert result == mock_manager


# =============================================================================
# init_position_ledger Tests
# =============================================================================


class TestInitPositionLedger:
    """Tests for init_position_ledger function."""

    @patch("aragora.server.initialization.POSITION_LEDGER_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when position ledger module not available."""
        result = init_position_ledger(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.POSITION_LEDGER_AVAILABLE", True)
    @patch("aragora.server.initialization.PositionLedger")
    def test_returns_ledger(self, mock_ledger_class, temp_nomic_dir):
        """Should return ledger when initialized successfully."""
        mock_ledger = MagicMock()
        mock_ledger_class.return_value = mock_ledger

        result = init_position_ledger(temp_nomic_dir)
        assert result == mock_ledger

    @patch("aragora.server.initialization.POSITION_LEDGER_AVAILABLE", True)
    @patch("aragora.server.initialization.PositionLedger")
    def test_returns_none_on_error(self, mock_ledger_class, temp_nomic_dir):
        """Should return None on initialization error."""
        mock_ledger_class.side_effect = Exception("Init failed")

        result = init_position_ledger(temp_nomic_dir)
        assert result is None


# =============================================================================
# init_debate_embeddings Tests
# =============================================================================


class TestInitDebateEmbeddings:
    """Tests for init_debate_embeddings function."""

    @patch("aragora.server.initialization.EMBEDDINGS_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when embeddings module not available."""
        result = init_debate_embeddings(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.EMBEDDINGS_AVAILABLE", True)
    @patch("aragora.server.initialization.DebateEmbeddingsDatabase")
    def test_returns_database(self, mock_db_class, temp_nomic_dir):
        """Should return database when initialized successfully."""
        mock_db = MagicMock()
        mock_db_class.return_value = mock_db

        result = init_debate_embeddings(temp_nomic_dir)
        assert result == mock_db

    @patch("aragora.server.initialization.EMBEDDINGS_AVAILABLE", True)
    @patch("aragora.server.initialization.DebateEmbeddingsDatabase")
    def test_returns_none_on_error(self, mock_db_class, temp_nomic_dir):
        """Should return None on initialization error."""
        mock_db_class.side_effect = Exception("Init failed")

        result = init_debate_embeddings(temp_nomic_dir)
        assert result is None


# =============================================================================
# init_consensus_memory Tests
# =============================================================================


class TestInitConsensusMemory:
    """Tests for init_consensus_memory function."""

    @patch("aragora.server.initialization.CONSENSUS_MEMORY_AVAILABLE", False)
    def test_returns_none_when_not_available(self):
        """Should return (None, None) when module not available."""
        memory, retriever = init_consensus_memory()
        assert memory is None
        assert retriever is None

    @patch("aragora.server.initialization.CONSENSUS_MEMORY_AVAILABLE", True)
    @patch("aragora.server.initialization.DissentRetriever")
    @patch("aragora.server.initialization.ConsensusMemory")
    def test_returns_memory_and_retriever(self, mock_memory_class, mock_retriever_class):
        """Should return both memory and retriever when initialized."""
        mock_memory = MagicMock()
        mock_retriever = MagicMock()
        mock_memory_class.return_value = mock_memory
        mock_retriever_class.return_value = mock_retriever

        memory, retriever = init_consensus_memory()
        assert memory == mock_memory
        assert retriever == mock_retriever

    @patch("aragora.server.initialization.CONSENSUS_MEMORY_AVAILABLE", True)
    @patch("aragora.server.initialization.ConsensusMemory")
    def test_returns_none_on_error(self, mock_memory_class):
        """Should return (None, None) on error."""
        mock_memory_class.side_effect = Exception("Init failed")

        memory, retriever = init_consensus_memory()
        assert memory is None
        assert retriever is None


# =============================================================================
# init_moment_detector Tests
# =============================================================================


class TestInitMomentDetector:
    """Tests for init_moment_detector function."""

    @patch("aragora.server.initialization.MOMENT_DETECTOR_AVAILABLE", False)
    def test_returns_none_when_not_available(self):
        """Should return None when module not available."""
        result = init_moment_detector()
        assert result is None

    @patch("aragora.server.initialization.MOMENT_DETECTOR_AVAILABLE", True)
    @patch("aragora.server.initialization.MomentDetector")
    def test_returns_detector(self, mock_detector_class):
        """Should return detector when initialized."""
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector

        mock_elo = MagicMock()
        mock_ledger = MagicMock()

        result = init_moment_detector(elo_system=mock_elo, position_ledger=mock_ledger)
        assert result == mock_detector
        mock_detector_class.assert_called_once_with(
            elo_system=mock_elo, position_ledger=mock_ledger
        )

    @patch("aragora.server.initialization.MOMENT_DETECTOR_AVAILABLE", True)
    @patch("aragora.server.initialization.MomentDetector")
    def test_returns_none_on_error(self, mock_detector_class):
        """Should return None on error."""
        mock_detector_class.side_effect = Exception("Init failed")

        result = init_moment_detector()
        assert result is None


# =============================================================================
# init_position_tracker Tests
# =============================================================================


class TestInitPositionTracker:
    """Tests for init_position_tracker function."""

    @patch("aragora.server.initialization.POSITION_TRACKER_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when module not available."""
        result = init_position_tracker(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.POSITION_TRACKER_AVAILABLE", True)
    @patch("aragora.server.initialization.PositionTracker")
    def test_returns_tracker(self, mock_tracker_class, temp_nomic_dir):
        """Should return tracker when initialized."""
        mock_tracker = MagicMock()
        mock_tracker_class.return_value = mock_tracker

        result = init_position_tracker(temp_nomic_dir)
        assert result == mock_tracker

    @patch("aragora.server.initialization.POSITION_TRACKER_AVAILABLE", True)
    @patch("aragora.server.initialization.PositionTracker")
    def test_returns_none_on_error(self, mock_tracker_class, temp_nomic_dir):
        """Should return None on error."""
        mock_tracker_class.side_effect = Exception("Init failed")

        result = init_position_tracker(temp_nomic_dir)
        assert result is None


# =============================================================================
# init_continuum_memory Tests
# =============================================================================


class TestInitContinuumMemory:
    """Tests for init_continuum_memory function."""

    @patch("aragora.server.initialization.CONTINUUM_AVAILABLE", False)
    def test_returns_none_when_not_available(self, temp_nomic_dir):
        """Should return None when module not available."""
        result = init_continuum_memory(temp_nomic_dir)
        assert result is None

    @patch("aragora.server.initialization.CONTINUUM_AVAILABLE", True)
    @patch("aragora.server.initialization.ContinuumMemory")
    def test_returns_memory(self, mock_memory_class, temp_nomic_dir):
        """Should return memory when initialized."""
        mock_memory = MagicMock()
        mock_memory_class.return_value = mock_memory

        result = init_continuum_memory(temp_nomic_dir)
        assert result == mock_memory

    @patch("aragora.server.initialization.CONTINUUM_AVAILABLE", True)
    @patch("aragora.server.initialization.ContinuumMemory")
    def test_returns_none_on_error(self, mock_memory_class, temp_nomic_dir):
        """Should return None on error."""
        mock_memory_class.side_effect = Exception("Init failed")

        result = init_continuum_memory(temp_nomic_dir)
        assert result is None


# =============================================================================
# init_verification_manager Tests
# =============================================================================


class TestInitVerificationManager:
    """Tests for init_verification_manager function."""

    @patch("aragora.server.initialization.VERIFICATION_AVAILABLE", False)
    def test_returns_none_when_not_available(self):
        """Should return None when module not available."""
        result = init_verification_manager()
        assert result is None

    @patch("aragora.server.initialization.VERIFICATION_AVAILABLE", True)
    @patch("aragora.server.initialization.FormalVerificationManager")
    def test_returns_manager(self, mock_manager_class):
        """Should return manager when initialized."""
        mock_manager = MagicMock()
        mock_manager_class.return_value = mock_manager

        result = init_verification_manager()
        assert result == mock_manager

    @patch("aragora.server.initialization.VERIFICATION_AVAILABLE", True)
    @patch("aragora.server.initialization.FormalVerificationManager")
    def test_returns_none_on_error(self, mock_manager_class):
        """Should return None on error."""
        mock_manager_class.side_effect = Exception("Init failed")

        result = init_verification_manager()
        assert result is None


# =============================================================================
# SubsystemRegistry Tests
# =============================================================================


class TestSubsystemRegistry:
    """Tests for SubsystemRegistry class."""

    def test_init_defaults_to_none(self):
        """All subsystems should default to None."""
        registry = SubsystemRegistry()

        assert registry.persistence is None
        assert registry.insight_store is None
        assert registry.elo_system is None
        assert registry.flip_detector is None
        assert registry.persona_manager is None
        assert registry.position_ledger is None
        assert registry.debate_embeddings is None
        assert registry.consensus_memory is None
        assert registry.dissent_retriever is None
        assert registry.moment_detector is None
        assert registry.position_tracker is None
        assert registry.continuum_memory is None
        assert registry.verification_manager is None

    @patch("aragora.server.initialization.init_persistence")
    @patch("aragora.server.initialization.init_verification_manager")
    def test_initialize_all_without_nomic_dir(self, mock_verify, mock_persist):
        """Should initialize persistence and verification without nomic_dir."""
        mock_persist.return_value = "persistence"
        mock_verify.return_value = "verification"

        registry = SubsystemRegistry()
        result = registry.initialize_all(nomic_dir=None)

        assert result is registry  # Returns self for chaining
        assert registry.persistence == "persistence"
        assert registry.verification_manager == "verification"
        assert registry.elo_system is None  # Requires nomic_dir

    @patch("aragora.server.initialization.init_persistence")
    @patch("aragora.server.initialization.init_insight_store")
    @patch("aragora.server.initialization.init_elo_system")
    @patch("aragora.server.initialization.init_flip_detector")
    @patch("aragora.server.initialization.init_persona_manager")
    @patch("aragora.server.initialization.init_position_ledger")
    @patch("aragora.server.initialization.init_debate_embeddings")
    @patch("aragora.server.initialization.init_position_tracker")
    @patch("aragora.server.initialization.init_continuum_memory")
    @patch("aragora.server.initialization.init_consensus_memory")
    @patch("aragora.server.initialization.init_moment_detector")
    @patch("aragora.server.initialization.init_verification_manager")
    def test_initialize_all_with_nomic_dir(
        self,
        mock_verify,
        mock_moment,
        mock_consensus,
        mock_continuum,
        mock_position_tracker,
        mock_embeddings,
        mock_ledger,
        mock_persona,
        mock_flip,
        mock_elo,
        mock_insight,
        mock_persist,
        temp_nomic_dir,
    ):
        """Should initialize all subsystems with nomic_dir."""
        mock_persist.return_value = "persistence"
        mock_insight.return_value = "insight_store"
        mock_elo.return_value = "elo_system"
        mock_flip.return_value = "flip_detector"
        mock_persona.return_value = "persona_manager"
        mock_ledger.return_value = "position_ledger"
        mock_embeddings.return_value = "embeddings"
        mock_position_tracker.return_value = "position_tracker"
        mock_continuum.return_value = "continuum_memory"
        mock_consensus.return_value = ("consensus_memory", "dissent_retriever")
        mock_moment.return_value = "moment_detector"
        mock_verify.return_value = "verification"

        registry = SubsystemRegistry()
        result = registry.initialize_all(nomic_dir=temp_nomic_dir)

        assert result is registry
        assert registry.persistence == "persistence"
        assert registry.insight_store == "insight_store"
        assert registry.elo_system == "elo_system"
        assert registry.flip_detector == "flip_detector"
        assert registry.persona_manager == "persona_manager"
        assert registry.position_ledger == "position_ledger"
        assert registry.debate_embeddings == "embeddings"
        assert registry.position_tracker == "position_tracker"
        assert registry.continuum_memory == "continuum_memory"
        assert registry.consensus_memory == "consensus_memory"
        assert registry.dissent_retriever == "dissent_retriever"
        assert registry.moment_detector == "moment_detector"
        assert registry.verification_manager == "verification"

    def test_log_availability(self, caplog):
        """Should log available and unavailable subsystems."""
        registry = SubsystemRegistry()
        registry.elo_system = MagicMock()  # Set one as available

        with caplog.at_level("INFO"):
            registry.log_availability()

        # Check that available subsystems are logged
        assert "EloSystem" in caplog.text


# =============================================================================
# get_registry Tests
# =============================================================================


class TestGetRegistry:
    """Tests for get_registry function."""

    def test_creates_registry_on_first_call(self, fresh_registry):
        """Should create registry on first call."""
        registry1 = get_registry()
        assert registry1 is not None
        assert isinstance(registry1, SubsystemRegistry)

    def test_returns_same_registry(self, fresh_registry):
        """Should return same registry on subsequent calls."""
        registry1 = get_registry()
        registry2 = get_registry()
        assert registry1 is registry2


# =============================================================================
# initialize_subsystems Tests
# =============================================================================


class TestInitializeSubsystems:
    """Tests for initialize_subsystems function."""

    @patch("aragora.server.initialization.get_registry")
    def test_initializes_and_logs(self, mock_get_registry, temp_nomic_dir):
        """Should initialize all subsystems and log availability."""
        mock_registry = MagicMock(spec=SubsystemRegistry)
        mock_get_registry.return_value = mock_registry

        result = initialize_subsystems(nomic_dir=temp_nomic_dir)

        assert result is mock_registry
        mock_registry.initialize_all.assert_called_once()
        mock_registry.log_availability.assert_called_once()


# =============================================================================
# initialize_subsystems_async Tests
# =============================================================================


class TestInitializeSubsystemsAsync:
    """Tests for initialize_subsystems_async function."""

    @pytest.mark.asyncio
    @patch("aragora.server.initialization.get_registry")
    async def test_initializes_and_logs_async(self, mock_get_registry, temp_nomic_dir, monkeypatch):
        """Should initialize all subsystems async and log availability."""
        # initialize_subsystems_async ends with demo auto-seeding, which reads
        # the process environment. A leaked ARAGORA_DEMO_MODE would make it read
        # elo_system, which the spec'd mock lacks, and try to seed real demo data.
        monkeypatch.delenv("ARAGORA_DEMO_MODE", raising=False)
        monkeypatch.delenv("ARAGORA_SKIP_SEED", raising=False)
        mock_registry = MagicMock(spec=SubsystemRegistry)
        mock_registry.initialize_all_async = AsyncMock(return_value=mock_registry)
        mock_get_registry.return_value = mock_registry

        result = await initialize_subsystems_async(nomic_dir=temp_nomic_dir)

        assert result is mock_registry
        mock_registry.initialize_all_async.assert_called_once()
        mock_registry.log_availability.assert_called_once()


# =============================================================================
# Integration Tests
# =============================================================================


class TestInitializationIntegration:
    """Integration tests for initialization module."""

    def test_registry_chain_initialization(self, fresh_registry):
        """Registry should support method chaining."""
        registry = SubsystemRegistry()

        # initialize_all returns self for chaining
        result = registry.initialize_all(nomic_dir=None, enable_persistence=False)
        assert result is registry

    @pytest.mark.asyncio
    async def test_async_initialization_completes(self, fresh_registry, temp_nomic_dir):
        """Async initialization should complete without errors."""
        # Disable all optional imports to test async path
        with (
            patch("aragora.server.initialization.PERSISTENCE_AVAILABLE", False),
            patch("aragora.server.initialization.INSIGHTS_AVAILABLE", False),
            patch("aragora.server.initialization.RANKING_AVAILABLE", False),
            patch("aragora.server.initialization.FLIP_DETECTOR_AVAILABLE", False),
            patch("aragora.server.initialization.PERSONAS_AVAILABLE", False),
            patch("aragora.server.initialization.POSITION_LEDGER_AVAILABLE", False),
            patch("aragora.server.initialization.EMBEDDINGS_AVAILABLE", False),
            patch("aragora.server.initialization.CONSENSUS_MEMORY_AVAILABLE", False),
            patch("aragora.server.initialization.MOMENT_DETECTOR_AVAILABLE", False),
            patch("aragora.server.initialization.POSITION_TRACKER_AVAILABLE", False),
            patch("aragora.server.initialization.CONTINUUM_AVAILABLE", False),
            patch("aragora.server.initialization.VERIFICATION_AVAILABLE", False),
        ):
            registry = SubsystemRegistry()
            await registry.initialize_all_async(nomic_dir=temp_nomic_dir)

            # All should be None since we disabled them
            assert registry.elo_system is None
            assert registry.insight_store is None
