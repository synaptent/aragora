"""
Server initialization - subsystem setup and configuration.

This module centralizes all the initialization logic for optional subsystems
like InsightStore, EloSystem, PersonaManager, etc.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from aragora.config import (
    DB_INSIGHTS_PATH,
)
from aragora.persistence.db_config import (
    DatabaseType,
    get_db_path,
)
from aragora.utils.optional_imports import try_import

logger = logging.getLogger(__name__)

# =============================================================================
# Optional Imports - Centralized
# =============================================================================

# Persistence
_imp, PERSISTENCE_AVAILABLE = try_import("aragora.persistence", "SupabaseClient")
SupabaseClient = _imp.get("SupabaseClient")

# InsightStore for debate insights
_imp, INSIGHTS_AVAILABLE = try_import("aragora.insights.store", "InsightStore")
InsightStore = _imp.get("InsightStore")

# EloSystem for agent rankings
_imp, RANKING_AVAILABLE = try_import("aragora.ranking.elo", "EloSystem")
EloSystem = _imp.get("EloSystem")

# FlipDetector for position reversal detection
_imp, FLIP_DETECTOR_AVAILABLE = try_import(
    "aragora.insights.flip_detector",
    "FlipDetector",
    "format_flip_for_ui",
    "format_consistency_for_ui",
)
FlipDetector = _imp.get("FlipDetector")
format_flip_for_ui = _imp.get("format_flip_for_ui")
format_consistency_for_ui = _imp.get("format_consistency_for_ui")

# Debate orchestrator for ad-hoc debates
_imp1, _avail1 = try_import("aragora.debate.orchestrator", "Arena", "DebateProtocol")
_imp2, _avail2 = try_import("aragora.agents.base", "create_agent")
_imp3, _avail3 = try_import("aragora.core", "Environment")
DEBATE_AVAILABLE = _avail1 and _avail2 and _avail3
Arena = _imp1.get("Arena")
DebateProtocol = _imp1.get("DebateProtocol")
create_agent = _imp2.get("create_agent")
Environment = _imp3.get("Environment")

# PersonaManager for agent specialization
_imp, PERSONAS_AVAILABLE = try_import("aragora.agents.personas", "PersonaManager")
PersonaManager = _imp.get("PersonaManager")

# DebateEmbeddingsDatabase for historical memory
_imp, EMBEDDINGS_AVAILABLE = try_import("aragora.debate.embeddings", "DebateEmbeddingsDatabase")
DebateEmbeddingsDatabase = _imp.get("DebateEmbeddingsDatabase")

# ConsensusMemory for historical consensus data
_imp, CONSENSUS_MEMORY_AVAILABLE = try_import(
    "aragora.memory.consensus", "ConsensusMemory", "DissentRetriever"
)
ConsensusMemory = _imp.get("ConsensusMemory")
DissentRetriever = _imp.get("DissentRetriever")

# CalibrationTracker for agent calibration
_imp, CALIBRATION_AVAILABLE = try_import("aragora.agents.calibration", "CalibrationTracker")
CalibrationTracker = _imp.get("CalibrationTracker")

# PulseManager for trending topics
_imp, PULSE_AVAILABLE = try_import(
    "aragora.pulse.ingestor", "PulseManager", "TrendingTopic", "TwitterIngestor"
)
PulseManager = _imp.get("PulseManager")
TrendingTopic = _imp.get("TrendingTopic")

# FormalVerificationManager for theorem proving
_imp, VERIFICATION_AVAILABLE = try_import(
    "aragora.verification.formal", "FormalVerificationManager"
)
FormalVerificationManager = _imp.get("FormalVerificationManager")

# ContinuumMemory for multi-tier memory
_imp, CONTINUUM_AVAILABLE = try_import("aragora.memory.continuum", "ContinuumMemory")
ContinuumMemory = _imp.get("ContinuumMemory")

# PositionLedger for truth-grounded personas
_imp, POSITION_LEDGER_AVAILABLE = try_import("aragora.genesis.ledger", "PositionLedger")
PositionLedger = _imp.get("PositionLedger")

# MomentDetector for significant agent moments
_imp, MOMENT_DETECTOR_AVAILABLE = try_import("aragora.insights.moments", "MomentDetector")
MomentDetector = _imp.get("MomentDetector")

# PositionTracker for agent positions
_imp, POSITION_TRACKER_AVAILABLE = try_import("aragora.insights.positions", "PositionTracker")
PositionTracker = _imp.get("PositionTracker")

# Broadcast module for podcast generation
_imp1, _avail1 = try_import("aragora.broadcast", "broadcast_debate")
_imp2, _avail2 = try_import("aragora.debate.traces", "DebateTrace")
BROADCAST_AVAILABLE = _avail1 and _avail2
broadcast_debate = _imp1.get("broadcast_debate")
DebateTrace = _imp2.get("DebateTrace")

# RelationshipTracker for agent network analysis
_imp, RELATIONSHIP_TRACKER_AVAILABLE = try_import("aragora.agents.grounded", "RelationshipTracker")
RelationshipTracker = _imp.get("RelationshipTracker")

# CritiqueStore for pattern retrieval
_imp, CRITIQUE_STORE_AVAILABLE = try_import("aragora.memory.store", "CritiqueStore")
CritiqueStore = _imp.get("CritiqueStore")

# Export module for debate artifact export
_imp, EXPORT_AVAILABLE = try_import(
    "aragora.export", "DebateArtifact", "CSVExporter", "DOTExporter", "StaticHTMLExporter"
)
DebateArtifact = _imp.get("DebateArtifact")
CSVExporter = _imp.get("CSVExporter")
DOTExporter = _imp.get("DOTExporter")
StaticHTMLExporter = _imp.get("StaticHTMLExporter")

# CapabilityProber for vulnerability detection
_imp, PROBER_AVAILABLE = try_import("aragora.modes.prober", "CapabilityProber")
CapabilityProber = _imp.get("CapabilityProber")

# RedTeamMode for adversarial testing
_imp, REDTEAM_AVAILABLE = try_import("aragora.modes.redteam", "RedTeamMode")
RedTeamMode = _imp.get("RedTeamMode")

# PersonaLaboratory for emergent traits
_imp, LABORATORY_AVAILABLE = try_import("aragora.agents.laboratory", "PersonaLaboratory")
PersonaLaboratory = _imp.get("PersonaLaboratory")

# BeliefNetwork for debate cruxes
_imp, BELIEF_NETWORK_AVAILABLE = try_import(
    "aragora.reasoning.belief", "BeliefNetwork", "BeliefPropagationAnalyzer"
)
BeliefNetwork = _imp.get("BeliefNetwork")
BeliefPropagationAnalyzer = _imp.get("BeliefPropagationAnalyzer")

# ProvenanceTracker for claim support
_imp, PROVENANCE_AVAILABLE = try_import("aragora.reasoning.provenance", "ProvenanceTracker")
ProvenanceTracker = _imp.get("ProvenanceTracker")

# FormalVerificationManager singleton accessor
_imp, FORMAL_VERIFICATION_AVAILABLE = try_import(
    "aragora.verification.formal", "FormalVerificationManager", "get_formal_verification_manager"
)
FormalVerificationManager = _imp.get("FormalVerificationManager")
get_formal_verification_manager = _imp.get("get_formal_verification_manager")

# ImpasseDetector for debate deadlock detection
_imp, IMPASSE_DETECTOR_AVAILABLE = try_import("aragora.debate.counterfactual", "ImpasseDetector")
ImpasseDetector = _imp.get("ImpasseDetector")

# ConvergenceDetector for semantic position convergence
_imp, CONVERGENCE_DETECTOR_AVAILABLE = try_import(
    "aragora.debate.convergence", "ConvergenceDetector"
)
ConvergenceDetector = _imp.get("ConvergenceDetector")

# AgentSelector for routing recommendations and auto team selection
_imp, ROUTING_AVAILABLE = try_import(
    "aragora.routing.selection", "AgentSelector", "AgentProfile", "TaskRequirements"
)
AgentSelector = _imp.get("AgentSelector")
AgentProfile = _imp.get("AgentProfile")
TaskRequirements = _imp.get("TaskRequirements")

# TournamentManager for tournament standings
_imp, TOURNAMENT_AVAILABLE = try_import("aragora.tournaments.tournament", "TournamentManager")
TournamentManager = _imp.get("TournamentManager")

# PromptEvolver for evolution history
_imp, EVOLUTION_AVAILABLE = try_import("aragora.evolution.evolver", "PromptEvolver")
PromptEvolver = _imp.get("PromptEvolver")

# MemoryTier enum for ContinuumMemory
_imp, _mem_tier_avail = try_import("aragora.memory.continuum", "MemoryTier")
MemoryTier = _imp.get("MemoryTier")

# InsightExtractor for debate insights
_imp, INSIGHT_EXTRACTOR_AVAILABLE = try_import("aragora.insights.extractor", "InsightExtractor")
InsightExtractor = _imp.get("InsightExtractor")

# =============================================================================
# Subsystem Initialization Functions
# =============================================================================


def init_persistence(enable: bool = True) -> Any | None:
    """Initialize Supabase persistence if available and enabled."""
    if not enable or not PERSISTENCE_AVAILABLE or not SupabaseClient:
        return None

    client = SupabaseClient()
    if client.is_configured:
        logger.info("[init] Supabase persistence enabled")
        return client

    return None


def init_insight_store(nomic_dir: Path) -> Any | None:
    """Initialize InsightStore for debate insights with KM adapter."""
    # Check if we should use PostgreSQL backend
    try:
        from aragora.storage.factory import get_storage_backend, StorageBackend

        backend = get_storage_backend()
        if backend in (StorageBackend.POSTGRES, StorageBackend.SUPABASE):
            # Use PostgresInsightStore for distributed deployments
            from aragora.insights.postgres_store import PostgresInsightStore

            try:
                # Try shared pool first (initialized during startup)
                from aragora.storage.pool_manager import get_shared_pool, is_pool_initialized

                if is_pool_initialized():
                    pool = get_shared_pool()
                    if pool:
                        store = PostgresInsightStore(pool)
                        logger.info("[init] PostgresInsightStore initialized via shared pool")
                        return store

                logger.info(
                    "[init] Shared pool not available for PostgresInsightStore, using SQLite"
                )
            except (OSError, ConnectionError, RuntimeError) as e:
                # OSError: file/network issues, ConnectionError: DB connection,
                # RuntimeError: pool/async issues - fallback to SQLite gracefully
                logger.warning("[init] PostgresInsightStore failed, falling back: %s", e)
    except ImportError:
        pass

    # Fall back to SQLite InsightStore
    if not INSIGHTS_AVAILABLE or not InsightStore:
        return None

    insights_path = nomic_dir / DB_INSIGHTS_PATH
    try:
        # Create parent directory if needed
        insights_path.parent.mkdir(parents=True, exist_ok=True)
        store = InsightStore(str(insights_path))

        # Wire KM adapter for bidirectional sync
        try:
            from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

            adapter = InsightsAdapter(enable_dual_write=True)
            store.set_km_adapter(adapter)
            logger.info("[init] InsightStore KM adapter wired for bidirectional sync")
        except ImportError:
            logger.debug("[init] KM InsightsAdapter not available")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            # Adapter configuration or wiring errors - non-critical, store still works
            logger.warning("[init] InsightsAdapter wiring failed: %s", e)

        logger.info("[init] SQLite InsightStore loaded/created for API access")
        return store
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without insights
        logger.warning("[init] InsightStore initialization failed: %s", e)
        return None


def init_elo_system(nomic_dir: Path) -> Any | None:
    """Initialize EloSystem for agent rankings with KM adapter."""
    if not RANKING_AVAILABLE or not EloSystem:
        return None

    elo_path = get_db_path(DatabaseType.ELO, nomic_dir)
    try:
        # Create parent directory if needed - SQLiteStore will create the DB
        elo_path.parent.mkdir(parents=True, exist_ok=True)
        system = EloSystem(str(elo_path))

        # Wire KM adapter for bidirectional sync (ratings -> KM, KM -> team selection)
        try:
            from aragora.knowledge.mound.adapters.performance_adapter import EloAdapter

            adapter = EloAdapter(elo_system=system, enable_dual_write=True)  # type: ignore[abstract]  # EloAdapter intentionally defers some abstract methods to mixin composition
            system.set_km_adapter(adapter)
            logger.info("[init] EloSystem KM adapter wired for skill tracking")
        except ImportError:
            logger.debug("[init] KM EloAdapter not available")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            # Adapter configuration or wiring errors - non-critical, ELO still works
            logger.warning("[init] EloAdapter wiring failed: %s", e)

        logger.info("[init] EloSystem loaded/created for leaderboard API")
        return system
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without rankings
        logger.warning("[init] EloSystem initialization failed: %s", e)
        return None


def init_flip_detector(nomic_dir: Path) -> Any | None:
    """Initialize FlipDetector for position reversal detection with KM adapter."""
    if not FLIP_DETECTOR_AVAILABLE or not FlipDetector:
        return None

    positions_path = get_db_path(DatabaseType.POSITIONS, nomic_dir)
    try:
        # Create parent directory if needed
        positions_path.parent.mkdir(parents=True, exist_ok=True)
        detector = FlipDetector(str(positions_path))

        # Wire KM adapter for bidirectional sync (flip events -> KM)
        try:
            from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

            adapter = InsightsAdapter(enable_dual_write=True)
            detector.set_km_adapter(adapter)
            logger.info("[init] FlipDetector KM adapter wired for flip tracking")
        except ImportError:
            logger.debug("[init] KM InsightsAdapter not available for FlipDetector")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            # Adapter configuration or wiring errors - non-critical, detector still works
            logger.warning("[init] FlipDetector InsightsAdapter wiring failed: %s", e)

        logger.info("[init] FlipDetector loaded/created for position reversal API")
        return detector
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without flip detection
        logger.warning("[init] FlipDetector initialization failed: %s", e)
        return None


def init_persona_manager(nomic_dir: Path) -> Any | None:
    """Initialize PersonaManager for agent specialization."""
    if not PERSONAS_AVAILABLE or not PersonaManager:
        return None

    personas_path = get_db_path(DatabaseType.PERSONAS, nomic_dir)
    manager = PersonaManager(str(personas_path))
    logger.info("[init] PersonaManager loaded for agent specialization")
    return manager


def init_position_ledger(nomic_dir: Path) -> Any | None:
    """Initialize PositionLedger for truth-grounded personas."""
    if not POSITION_LEDGER_AVAILABLE or not PositionLedger:
        return None

    ledger_path = get_db_path(DatabaseType.TRUTH_GROUNDING, nomic_dir)
    try:
        ledger = PositionLedger(db_path=str(ledger_path))
        logger.info("[init] PositionLedger loaded for truth-grounded personas")
        return ledger
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without position ledger
        logger.warning("[init] PositionLedger initialization failed: %s", e)
        return None


def init_debate_embeddings(nomic_dir: Path) -> Any | None:
    """Initialize DebateEmbeddingsDatabase for historical memory."""
    if not EMBEDDINGS_AVAILABLE or not DebateEmbeddingsDatabase:
        return None

    embeddings_path = get_db_path(DatabaseType.EMBEDDINGS, nomic_dir)
    try:
        db = DebateEmbeddingsDatabase(str(embeddings_path))
        logger.info("[init] DebateEmbeddings loaded for historical memory")
        return db
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without embeddings
        logger.warning("[init] DebateEmbeddings initialization failed: %s", e)
        return None


def init_consensus_memory() -> tuple[Any | None, Any | None]:
    """Initialize ConsensusMemory and DissentRetriever with KM adapter."""
    if not CONSENSUS_MEMORY_AVAILABLE or not ConsensusMemory or not DissentRetriever:
        return None, None

    try:
        memory = ConsensusMemory()

        # Wire KM adapter for bidirectional sync (consensus -> KM, KM -> context)
        try:
            from aragora.knowledge.mound.adapters.consensus_adapter import ConsensusAdapter

            adapter = ConsensusAdapter(consensus=memory, enable_dual_write=True)
            memory.set_km_adapter(adapter)
            logger.info("[init] ConsensusMemory KM adapter wired for bidirectional sync")
        except ImportError:
            logger.debug("[init] KM ConsensusAdapter not available")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            # Adapter configuration or wiring errors - non-critical, memory still works
            logger.warning("[init] ConsensusAdapter wiring failed: %s", e)

        retriever = DissentRetriever(memory)
        logger.info("[init] DissentRetriever loaded for historical minority views")
        return memory, retriever
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without consensus memory
        logger.warning("[init] DissentRetriever initialization failed: %s", e)
        return None, None


def init_moment_detector(
    elo_system: Any | None = None,
    position_ledger: Any | None = None,
) -> Any | None:
    """Initialize MomentDetector for significant agent moments."""
    if not MOMENT_DETECTOR_AVAILABLE or not MomentDetector:
        return None

    try:
        detector = MomentDetector(
            elo_system=elo_system,
            position_ledger=position_ledger,
        )
        logger.info("[init] MomentDetector loaded for agent moments API")
        return detector
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without moments
        logger.warning("[init] MomentDetector initialization failed: %s", e)
        return None


def init_position_tracker(nomic_dir: Path) -> Any | None:
    """Initialize PositionTracker for agent positions."""
    if not POSITION_TRACKER_AVAILABLE or not PositionTracker:
        return None

    positions_path = nomic_dir / "aragora_positions.db"
    try:
        tracker = PositionTracker(str(positions_path))
        logger.info("[init] PositionTracker loaded for agent positions")
        return tracker
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without position tracking
        logger.warning("[init] PositionTracker initialization failed: %s", e)
        return None


def init_continuum_memory(nomic_dir: Path) -> Any | None:
    """Initialize ContinuumMemory for multi-tier memory with KM adapter."""
    if not CONTINUUM_AVAILABLE or not ContinuumMemory:
        return None

    try:
        memory = ContinuumMemory(base_dir=str(nomic_dir))

        # Wire KM adapter for bidirectional sync (memories -> KM, KM -> context)
        try:
            from aragora.knowledge.mound.adapters.continuum_adapter import ContinuumAdapter

            adapter = ContinuumAdapter(continuum=memory, enable_dual_write=True)
            memory.set_km_adapter(adapter)
            logger.info("[init] ContinuumMemory KM adapter wired for bidirectional sync")
        except ImportError:
            logger.debug("[init] KM ContinuumAdapter not available")
        except (TypeError, ValueError, AttributeError, RuntimeError) as e:
            # Adapter configuration or wiring errors - non-critical, memory still works
            logger.warning("[init] ContinuumAdapter wiring failed: %s", e)

        logger.info("[init] ContinuumMemory loaded for multi-tier memory")
        return memory
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without continuum memory
        logger.warning("[init] ContinuumMemory initialization failed: %s", e)
        return None


def init_verification_manager() -> Any | None:
    """Initialize FormalVerificationManager for theorem proving."""
    if not VERIFICATION_AVAILABLE or not FormalVerificationManager:
        return None

    try:
        manager = FormalVerificationManager()
        logger.info("[init] FormalVerificationManager loaded")
        return manager
    except Exception as e:  # noqa: BLE001 - graceful degradation, server continues without verification
        logger.warning("[init] FormalVerificationManager initialization failed: %s", e)
        return None


def init_translation_service(
    cache_max_entries: int = 10000,
    cache_ttl_seconds: float = 3600.0,
) -> tuple[Any | None, Any | None]:
    """
    Initialize translation service and multilingual debate manager.

    Returns:
        Tuple of (TranslationService, MultilingualDebateManager) or (None, None)
    """
    try:
        from aragora.debate.translation import (
            TranslationCache,
            TranslationService,
            MultilingualDebateManager,
            MultilingualDebateConfig,
        )

        # Initialize cache with configurable settings
        cache = TranslationCache(
            max_entries=cache_max_entries,
            ttl_seconds=cache_ttl_seconds,
        )

        # Initialize translation service
        service = TranslationService(cache=cache)

        # Initialize multilingual manager
        config = MultilingualDebateConfig()
        manager = MultilingualDebateManager(
            translation_service=service,
            config=config,
        )

        logger.info(
            "[init] Translation service initialized (cache: %s entries, %ss TTL)",
            cache_max_entries,
            cache_ttl_seconds,
        )
        return service, manager

    except ImportError as e:
        logger.debug("[init] Translation module not available: %s", e)
        return None, None
    except (OSError, RuntimeError, ValueError, TypeError) as e:
        logger.warning("[init] Translation service initialization failed: %s", e)
        return None, None


# =============================================================================
# Batch Initialization
# =============================================================================


class SubsystemRegistry:
    """
    Registry of initialized subsystems.

    Provides a single point of access for all optional subsystems.
    """

    def __init__(self):
        self.persistence = None
        self.insight_store = None
        self.elo_system = None
        self.flip_detector = None
        self.persona_manager = None
        self.position_ledger = None
        self.debate_embeddings = None
        self.consensus_memory = None
        self.dissent_retriever = None
        self.moment_detector = None
        self.position_tracker = None
        self.continuum_memory = None
        self.verification_manager = None
        self.translation_service = None
        self.multilingual_manager = None

    def initialize_all(
        self,
        nomic_dir: Path | None = None,
        enable_persistence: bool = True,
    ) -> SubsystemRegistry:
        """
        Initialize all available subsystems.

        Args:
            nomic_dir: Path to nomic state directory
            enable_persistence: Whether to enable Supabase persistence

        Returns:
            Self for chaining
        """
        # Persistence (no nomic_dir required)
        self.persistence = init_persistence(enable_persistence)

        if nomic_dir:
            # Core subsystems
            self.insight_store = init_insight_store(nomic_dir)
            self.elo_system = init_elo_system(nomic_dir)
            self.flip_detector = init_flip_detector(nomic_dir)
            self.persona_manager = init_persona_manager(nomic_dir)
            self.position_ledger = init_position_ledger(nomic_dir)
            self.debate_embeddings = init_debate_embeddings(nomic_dir)
            self.position_tracker = init_position_tracker(nomic_dir)
            self.continuum_memory = init_continuum_memory(nomic_dir)

            # Memory subsystems
            self.consensus_memory, self.dissent_retriever = init_consensus_memory()

            # Dependent subsystems (need other subsystems initialized first)
            self.moment_detector = init_moment_detector(
                elo_system=self.elo_system,
                position_ledger=self.position_ledger,
            )

        # Standalone subsystems
        self.verification_manager = init_verification_manager()
        self.translation_service, self.multilingual_manager = init_translation_service()

        return self

    async def initialize_all_async(
        self,
        nomic_dir: Path | None = None,
        enable_persistence: bool = True,
    ) -> SubsystemRegistry:
        """
        Initialize all available subsystems in parallel where possible.

        This is the async version that parallelizes independent initializations
        using a thread pool executor, significantly reducing startup time.

        Args:
            nomic_dir: Path to nomic state directory
            enable_persistence: Whether to enable Supabase persistence

        Returns:
            Self for chaining
        """
        loop = asyncio.get_running_loop()

        # Use a thread pool for I/O-bound initialization
        with ThreadPoolExecutor(max_workers=8) as executor:
            # Persistence (no nomic_dir required, run first)
            self.persistence = await loop.run_in_executor(
                executor, init_persistence, enable_persistence
            )

            if nomic_dir:
                # Phase 1: Initialize independent subsystems in parallel
                # These don't depend on each other
                independent_futures: list[asyncio.Future[Any]] = [
                    loop.run_in_executor(executor, init_insight_store, nomic_dir),
                    loop.run_in_executor(executor, init_elo_system, nomic_dir),
                    loop.run_in_executor(executor, init_flip_detector, nomic_dir),
                    loop.run_in_executor(executor, init_persona_manager, nomic_dir),
                    loop.run_in_executor(executor, init_position_ledger, nomic_dir),
                    loop.run_in_executor(executor, init_debate_embeddings, nomic_dir),
                    loop.run_in_executor(executor, init_position_tracker, nomic_dir),
                    loop.run_in_executor(executor, init_continuum_memory, nomic_dir),
                    loop.run_in_executor(executor, init_consensus_memory),
                ]

                results: list[Any] = await asyncio.gather(*independent_futures)

                # Assign results
                (
                    self.insight_store,
                    self.elo_system,
                    self.flip_detector,
                    self.persona_manager,
                    self.position_ledger,
                    self.debate_embeddings,
                    self.position_tracker,
                    self.continuum_memory,
                    consensus_result,
                ) = results

                # Unpack consensus memory result
                self.consensus_memory, self.dissent_retriever = consensus_result

                # Phase 2: Initialize dependent subsystems
                # MomentDetector depends on elo_system and position_ledger
                self.moment_detector = await loop.run_in_executor(
                    executor,
                    lambda: init_moment_detector(
                        elo_system=self.elo_system,
                        position_ledger=self.position_ledger,
                    ),
                )

            # Standalone subsystems (can run in parallel with nothing)
            self.verification_manager = await loop.run_in_executor(
                executor, init_verification_manager
            )

        logger.info("[init] Async initialization completed")
        return self

    def log_availability(self) -> None:
        """Log which subsystems are available."""
        available = []
        unavailable = []

        checks = [
            ("Persistence", self.persistence),
            ("InsightStore", self.insight_store),
            ("EloSystem", self.elo_system),
            ("FlipDetector", self.flip_detector),
            ("PersonaManager", self.persona_manager),
            ("PositionLedger", self.position_ledger),
            ("DebateEmbeddings", self.debate_embeddings),
            ("ConsensusMemory", self.consensus_memory),
            ("DissentRetriever", self.dissent_retriever),
            ("MomentDetector", self.moment_detector),
            ("PositionTracker", self.position_tracker),
            ("ContinuumMemory", self.continuum_memory),
            ("VerificationManager", self.verification_manager),
        ]

        for name, instance in checks:
            if instance is not None:
                available.append(name)
            else:
                unavailable.append(name)

        if available:
            logger.info("[init] Available: %s", ", ".join(available))
        if unavailable:
            logger.debug("[init] Unavailable: %s", ", ".join(unavailable))


# Global registry instance
_registry: SubsystemRegistry | None = None


def get_registry() -> SubsystemRegistry:
    """Get or create the global subsystem registry."""
    global _registry
    if _registry is None:
        _registry = SubsystemRegistry()
    return _registry


def initialize_subsystems(
    nomic_dir: Path | None = None,
    enable_persistence: bool = True,
) -> SubsystemRegistry:
    """
    Initialize all subsystems and return the registry.

    This is the main entry point for server initialization (synchronous version).
    """
    registry = get_registry()
    registry.initialize_all(nomic_dir, enable_persistence)
    registry.log_availability()
    return registry


async def initialize_subsystems_async(
    nomic_dir: Path | None = None,
    enable_persistence: bool = True,
) -> SubsystemRegistry:
    """
    Initialize all subsystems asynchronously and return the registry.

    This is the async entry point for server initialization, parallelizing
    independent subsystem initializations for faster startup.
    """
    registry = get_registry()
    await registry.initialize_all_async(nomic_dir, enable_persistence)
    registry.log_availability()

    # Auto-seed demo data when DEMO_MODE is active and no data exists
    await _maybe_seed_demo_data(registry, nomic_dir)

    return registry


async def _maybe_seed_demo_data(
    registry: SubsystemRegistry,
    nomic_dir: Path | None = None,
) -> None:
    """Auto-seed demo data on first server start in DEMO_MODE.

    Only seeds if:
    1. ARAGORA_DEMO_MODE is truthy
    2. The ELO leaderboard is empty (indicates first run)
    3. ARAGORA_SKIP_SEED is NOT set (escape hatch)

    This replaces the need to manually run `python scripts/seed_demo.py`.
    """
    import os

    demo_mode = os.environ.get("ARAGORA_DEMO_MODE", "").lower() in ("true", "1", "yes")
    skip_seed = os.environ.get("ARAGORA_SKIP_SEED", "").lower() in ("true", "1", "yes")

    if not demo_mode or skip_seed:
        return

    # Check if data already exists (any ELO entries = already seeded)
    if registry.elo_system is not None:
        try:
            leaderboard = registry.elo_system.get_leaderboard(limit=1)
            if leaderboard:
                return  # Already has data
        except (TypeError, ValueError, AttributeError, RuntimeError):
            pass

    logger.info("[init] DEMO_MODE active with empty database — auto-seeding demo data")

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, _seed_demo_data_sync, nomic_dir)
        logger.info("[init] Demo data seeded successfully")
    except (ImportError, RuntimeError, OSError) as e:
        logger.warning("[init] Auto-seed failed (non-fatal): %s", e)


def _seed_demo_data_sync(nomic_dir: Path | None = None) -> None:
    """Synchronous demo data seeding (runs in executor thread)."""
    import importlib
    import sys
    from pathlib import Path as _Path

    # Add scripts directory to path for import
    scripts_dir = _Path(__file__).parent.parent.parent / "scripts"
    if scripts_dir.exists() and str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    try:
        seed_mod = importlib.import_module("seed_demo")
        if hasattr(seed_mod, "seed_all"):
            seed_mod.seed_all()
        elif hasattr(seed_mod, "main"):
            seed_mod.main()
        else:
            logger.debug("[init] seed_demo module found but no seed_all/main function")
    except ImportError:
        logger.debug("[init] seed_demo script not importable")
    except (RuntimeError, OSError, ValueError) as e:
        logger.warning("[init] Demo seeding error: %s", e)


# =============================================================================
# Cache Pre-Warming
# =============================================================================


async def prewarm_caches(
    registry: SubsystemRegistry | None = None,
    nomic_dir: Path | None = None,
) -> dict:
    """
    Pre-warm caches with commonly accessed data.

    Call during server startup after subsystem initialization to reduce
    cold-start latency for the first requests.

    Pre-warms:
    - Top 20 leaderboard entries
    - Top 10 agent profiles
    - Consensus stats summary

    Args:
        registry: Optional SubsystemRegistry with initialized subsystems
        nomic_dir: Path to nomic directory for database access

    Returns:
        Dictionary with counts of pre-warmed entries
    """
    result = {
        "leaderboard_entries": 0,
        "agent_profiles": 0,
        "consensus_stats": False,
    }

    if registry is None:
        registry = get_registry()

    loop = asyncio.get_running_loop()

    # Pre-warm leaderboard cache
    if registry.elo_system is not None:
        try:
            # Import cache and populate
            from aragora.utils.cache import get_method_cache

            cache = get_method_cache()

            # Fetch top 20 leaderboard entries
            def _fetch_leaderboard():
                leaderboard = registry.elo_system.get_leaderboard(limit=20)
                # Cache each entry
                for entry in leaderboard:
                    agent_name = entry.get("agent", entry.get("name", ""))
                    if agent_name:
                        cache.set(f"leaderboard:agent:{agent_name}", entry)
                # Cache the full list
                cache.set("leaderboard:top20", leaderboard)
                return len(leaderboard)

            result["leaderboard_entries"] = await loop.run_in_executor(None, _fetch_leaderboard)
            logger.debug("[prewarm] Cached %s leaderboard entries", result["leaderboard_entries"])

        except (OSError, sqlite3.Error, KeyError, AttributeError) as e:
            # Cache or storage errors during prewarm - non-critical, cache will populate on demand
            logger.debug("[prewarm] Leaderboard cache failed: %s", e)

    # Pre-warm agent profiles
    if registry.persona_manager is not None:
        try:
            from aragora.utils.cache import get_method_cache

            cache = get_method_cache()

            def _fetch_profiles():
                # Get top agents by activity/score
                profiles = registry.persona_manager.get_all_profiles(limit=10)
                for profile in profiles:
                    agent_name = profile.get("name", "")
                    if agent_name:
                        cache.set(f"profile:{agent_name}", profile)
                return len(profiles)

            result["agent_profiles"] = await loop.run_in_executor(None, _fetch_profiles)
            logger.debug("[prewarm] Cached %s agent profiles", result["agent_profiles"])

        except (OSError, sqlite3.Error, KeyError, AttributeError) as e:
            # Cache or storage errors during prewarm - non-critical, cache will populate on demand
            logger.debug("[prewarm] Agent profile cache failed: %s", e)

    # Pre-warm consensus stats
    if registry.consensus_memory is not None:
        try:
            from aragora.utils.cache import get_method_cache

            cache = get_method_cache()

            def _fetch_consensus_stats():
                stats = registry.consensus_memory.get_summary_stats()
                cache.set("consensus:summary_stats", stats)
                return True

            result["consensus_stats"] = await loop.run_in_executor(None, _fetch_consensus_stats)
            logger.debug("[prewarm] Cached consensus stats")

        except (OSError, sqlite3.Error, KeyError, AttributeError) as e:
            # Cache or storage errors during prewarm - non-critical, cache will populate on demand
            logger.debug("[prewarm] Consensus stats cache failed: %s", e)

    total = (
        result["leaderboard_entries"]
        + result["agent_profiles"]
        + (1 if result["consensus_stats"] else 0)
    )
    if total > 0:
        logger.info("[prewarm] Pre-warmed %s cache entries", total)

    return result


# =============================================================================
# Handler Context Builder
# =============================================================================


def init_budget_notifications() -> bool:
    """Wire budget alert notifier to the BudgetManager singleton.

    Registers the notifier callback so budget threshold crossings
    trigger Slack/Teams/webhook notifications.

    Returns:
        True if wired successfully, False otherwise.
    """
    try:
        from aragora.billing.budget_manager import get_budget_manager
        from aragora.billing.budget_alert_notifier import setup_budget_notifications

        manager = get_budget_manager()
        setup_budget_notifications(manager)
        logger.info("[init] Budget alert notifications wired to BudgetManager")
        return True
    except ImportError:
        logger.debug("[init] Budget notification modules not available")
        return False
    except (TypeError, ValueError, AttributeError, RuntimeError) as e:
        logger.warning("[init] Budget alert notification setup failed: %s", e)
        return False


def init_handler_stores(nomic_dir: Path) -> dict:
    """Initialize document, audio, video stores and connectors for handlers.

    This initializes the non-database subsystems that handlers need:
    - DocumentStore for file uploads
    - AudioFileStore for broadcast audio
    - VideoGenerator for YouTube
    - TwitterPosterConnector for social posting
    - YouTubeUploaderConnector for video uploads
    - UserStore for user/org persistence
    - UsageTracker for billing events

    Args:
        nomic_dir: Path to nomic state directory

    Returns:
        Dictionary with initialized stores/connectors (values may be None)
    """
    stores: dict = {
        "document_store": None,
        "audio_store": None,
        "video_generator": None,
        "twitter_connector": None,
        "youtube_connector": None,
        "user_store": None,
        "usage_tracker": None,
    }

    # DocumentStore for file uploads
    try:
        from aragora.server.documents import DocumentStore

        doc_dir = nomic_dir / "documents"
        stores["document_store"] = DocumentStore(doc_dir)
        logger.info("[init] DocumentStore initialized at %s", doc_dir)
    except ImportError as e:
        logger.debug("[init] DocumentStore unavailable: %s", e)

    # AudioFileStore for broadcast audio
    try:
        from aragora.broadcast.storage import AudioFileStore

        audio_dir = nomic_dir / "audio"
        stores["audio_store"] = AudioFileStore(audio_dir)
        logger.info("[init] AudioFileStore initialized at %s", audio_dir)
    except ImportError as e:
        logger.debug("[init] AudioFileStore unavailable: %s", e)

    # TwitterPosterConnector for social posting
    try:
        from aragora.connectors.twitter_poster import TwitterPosterConnector

        connector = TwitterPosterConnector()
        stores["twitter_connector"] = connector
        if connector.is_configured:
            logger.info("[init] TwitterPosterConnector initialized")
        else:
            logger.debug("[init] TwitterPosterConnector created (credentials not configured)")
    except ImportError as e:
        logger.debug("[init] TwitterPosterConnector unavailable: %s", e)

    # YouTubeUploaderConnector for video uploads
    try:
        from aragora.connectors.youtube_uploader import YouTubeUploaderConnector

        youtube_connector = YouTubeUploaderConnector()
        stores["youtube_connector"] = youtube_connector
        if youtube_connector.is_configured:
            logger.info("[init] YouTubeUploaderConnector initialized")
        else:
            logger.debug("[init] YouTubeUploaderConnector created (credentials not configured)")
    except ImportError as e:
        logger.debug("[init] YouTubeUploaderConnector unavailable: %s", e)

    # VideoGenerator for YouTube
    try:
        from aragora.broadcast.video_gen import VideoGenerator

        video_dir = nomic_dir / "videos"
        stores["video_generator"] = VideoGenerator(video_dir)
        logger.info("[init] VideoGenerator initialized at %s", video_dir)
    except ImportError as e:
        logger.debug("[init] VideoGenerator unavailable: %s", e)

    # UserStore for user/org persistence
    # Uses PostgreSQL in production for distributed deployments
    try:
        from aragora.storage.user_store import PostgresUserStore, UserStore
        from aragora.storage.connection_factory import create_persistent_store

        stores["user_store"] = create_persistent_store(
            store_name="user_store",
            sqlite_class=UserStore,
            postgres_class=PostgresUserStore,
            db_filename="users.db",
            data_dir=str(nomic_dir),
        )
        store_type = type(stores["user_store"]).__name__
        logger.info("[init] UserStore initialized (%s)", store_type)
    except ImportError as e:
        logger.debug("[init] UserStore unavailable: %s", e)
    except (OSError, PermissionError, ConnectionError, RuntimeError) as e:
        # Connection or file system errors - try SQLite fallback
        logger.error("[init] UserStore initialization failed: %s", e)
        # Try SQLite fallback
        try:
            from aragora.storage.user_store import UserStore as SQLiteUserStore

            user_db_path = nomic_dir / "users.db"
            stores["user_store"] = SQLiteUserStore(user_db_path)
            logger.warning("[init] UserStore fell back to SQLite at %s", user_db_path)
        except (OSError, PermissionError, sqlite3.Error) as fallback_error:
            # SQLite fallback also failed - server continues without user store
            logger.error("[init] UserStore SQLite fallback failed: %s", fallback_error)

    # UsageTracker for billing events
    try:
        from aragora.billing.usage import UsageTracker

        usage_db_path = nomic_dir / "usage.db"
        stores["usage_tracker"] = UsageTracker(db_path=usage_db_path)
        logger.info("[init] UsageTracker initialized at %s", usage_db_path)
    except ImportError as e:
        logger.debug("[init] UsageTracker unavailable: %s", e)

    return stores


# =============================================================================
# PostgreSQL Store Initialization (Production)
# =============================================================================


async def init_postgres_stores() -> dict[str, bool]:
    """
    Initialize all PostgreSQL stores for production deployment.

    This function initializes all PostgreSQL-backed storage modules when
    the server is configured to use PostgreSQL (via ARAGORA_POSTGRES_DSN
    or DATABASE_URL environment variables).

    Should be called during server startup when using PostgreSQL backend.

    Returns:
        Dictionary mapping store names to initialization status (True = success)
    """
    from aragora.storage.factory import get_storage_backend, StorageBackend

    backend = get_storage_backend()
    if backend not in (StorageBackend.POSTGRES, StorageBackend.SUPABASE):
        logger.debug("[init] PostgreSQL backend not configured, skipping store initialization")
        return {}

    results: dict[str, bool] = {}

    # Use the shared pool from pool_manager if available (preferred path)
    pool = None
    try:
        from aragora.storage.pool_manager import get_shared_pool, is_pool_initialized

        if is_pool_initialized():
            pool = get_shared_pool()
            if pool:
                logger.info("[init] Using shared PostgreSQL pool from pool_manager")
    except ImportError:
        pass

    # Fall back to creating a new pool if shared pool not available
    if pool is None:
        try:
            from aragora.storage.postgres_store import get_postgres_pool

            pool = await get_postgres_pool()
            logger.info("[init] PostgreSQL connection pool created (standalone)")
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            # Connection errors - cannot proceed with PostgreSQL stores
            logger.error("[init] Failed to create PostgreSQL pool: %s", e)
            return {"_connection": False}

    # List of PostgreSQL stores to initialize
    stores_to_init: list[tuple[str, str, str, str | None]] = [
        (
            "webhook_configs",
            "aragora.storage.webhook_config_store",
            "PostgresWebhookConfigStore",
            "set_webhook_config_store",
        ),
        (
            "integrations",
            "aragora.storage.integration_store",
            "PostgresIntegrationStore",
            "set_integration_store",
        ),
        ("gmail_tokens", "aragora.storage.gmail_token_store", "PostgresGmailTokenStore", None),
        (
            "finding_workflows",
            "aragora.storage.finding_workflow_store",
            "PostgresFindingWorkflowStore",
            None,
        ),
        ("gauntlet_runs", "aragora.storage.gauntlet_run_store", "PostgresGauntletRunStore", None),
        ("job_queue", "aragora.storage.job_queue_store", "PostgresJobQueueStore", None),
        ("governance", "aragora.storage.governance_store", "PostgresGovernanceStore", None),
        ("marketplace", "aragora.storage.marketplace_store", "PostgresMarketplaceStore", None),
        (
            "federation_registry",
            "aragora.storage.federation_registry_store",
            "PostgresFederationRegistryStore",
            None,
        ),
        (
            "approval_requests",
            "aragora.storage.approval_request_store",
            "PostgresApprovalRequestStore",
            None,
        ),
        ("token_blacklist", "aragora.storage.token_blacklist_store", "PostgresBlacklist", None),
        ("users", "aragora.storage.user_store", "PostgresUserStore", None),
        (
            "webhooks",
            "aragora.storage.webhook_store",
            "PostgresWebhookStore",
            "set_webhook_store",
        ),
        # Phase 2 migration stores (facts handled by KnowledgeMound postgres_store)
        ("insights", "aragora.insights.postgres_store", "PostgresInsightStore", None),
        ("debates", "aragora.server.postgres_storage", "PostgresDebateStorage", None),
        (
            "scheduled_debates",
            "aragora.pulse.postgres_store",
            "PostgresScheduledDebateStore",
            None,
        ),
        (
            "cycle_learning",
            "aragora.nomic.postgres_cycle_store",
            "PostgresCycleLearningStore",
            None,
        ),
    ]

    for name, module_path, class_name, setter_name in stores_to_init:
        try:
            module = importlib.import_module(module_path)
            store_class = getattr(module, class_name)
            store = store_class(pool)
            await store.initialize()
            if setter_name:
                setter = getattr(module, setter_name, None)
                if callable(setter):
                    setter(store)
            results[name] = True
            logger.info("[init] PostgreSQL store initialized: %s", name)
        except ImportError as e:
            logger.warning("[init] Could not import %s: %s", class_name, e)
            results[name] = False
        except (OSError, ConnectionError, TimeoutError, RuntimeError, AttributeError) as e:
            # Connection, configuration, or schema errors - log and continue with other stores
            logger.error("[init] Failed to initialize %s: %s", name, e)
            results[name] = False

    # Summary
    succeeded = sum(1 for s in results.values() if s)
    failed = sum(1 for s in results.values() if not s)
    logger.info("[init] PostgreSQL stores: %s initialized, %s failed", succeeded, failed)

    return results


def init_postgres_stores_sync() -> dict[str, bool]:
    """
    Synchronous wrapper for init_postgres_stores().

    Use this when calling from synchronous server startup code.

    NOTE: This function should ONLY be called BEFORE the async event loop starts.
    asyncpg connection pools are bound to specific event loops. If called from
    within a running event loop, this will return an empty dict and log a warning.
    """
    import asyncio

    try:
        asyncio.get_running_loop()
        # We're in an async context - CAN'T use ThreadPoolExecutor approach
        # because asyncpg pools would be bound to the wrong event loop
        logger.warning(
            "[init] init_postgres_stores_sync() called from async context. "
            "asyncpg pools are event-loop bound and cannot be created in a "
            "ThreadPoolExecutor. Call this BEFORE starting the event loop, "
            "or use 'await init_postgres_stores()' directly."
        )
        return {}
    except RuntimeError:
        # No running loop - safe to use asyncio.run()
        return asyncio.run(init_postgres_stores())


async def upgrade_handler_stores(nomic_dir: Path | None) -> dict[str, str]:
    """Upgrade handler stores from SQLite to PostgreSQL using the shared pool.

    Called during server ``start()`` AFTER ``run_startup_sequence()`` creates
    the shared pool.  The first call to ``init_handler_stores()`` happens in
    ``__init__()`` (synchronous, no pool), so this function re-creates the
    PostgreSQL-capable stores once the pool is available.

    Args:
        nomic_dir: Path to nomic state directory

    Returns:
        Dictionary mapping store name → backend type ("postgres" or "skipped")
    """

    from aragora.storage.pool_manager import get_shared_pool, is_pool_initialized

    if not is_pool_initialized():
        logger.info("[upgrade] Shared pool not available, skipping store upgrade")
        return {}

    pool = get_shared_pool()
    if not pool:
        logger.info("[upgrade] get_shared_pool() returned None")
        return {}

    # Verify pool health before upgrading stores
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
        # Pool connection issues - skip upgrade, continue with existing stores
        logger.warning("[upgrade] Pool health check failed, skipping upgrade: %s", e)
        return {}

    results: dict[str, str] = {}

    # Upgrade UserStore
    try:
        from aragora.storage.user_store import PostgresUserStore

        store = PostgresUserStore(pool)
        if hasattr(store, "initialize"):
            await store.initialize()
        results["user_store"] = "postgres"
        logger.info("[upgrade] UserStore upgraded to PostgreSQL")

        # Wire to handler
        from aragora.server.handler_registry import UnifiedHandler

        setattr(UnifiedHandler, "user_store", store)
    except (ImportError, OSError, ConnectionError, RuntimeError, AttributeError) as e:
        # Import, connection, or wiring errors - continue with SQLite store
        logger.info("[upgrade] UserStore upgrade failed: %s: %s", type(e).__name__, e)
        results["user_store"] = "skipped"
    except Exception as e:  # noqa: BLE001 - final fallback to protect server startup
        # Catch-all for unexpected errors (e.g., read-only replicas)
        logger.warning("[upgrade] UserStore upgrade failed: %s: %s", type(e).__name__, e)
        results["user_store"] = "skipped"

    # Upgrade additional stores (job queue, governance, inbox).
    # Each entry: (name, module_path, class_name, setter_module, setter_func)
    store_upgrades: list[tuple[str, str, str, str | None, str | None]] = [
        (
            "job_queue",
            "aragora.storage.job_queue_store",
            "PostgresJobQueueStore",
            "aragora.storage.job_queue_store",
            "set_job_store",
        ),
        (
            "governance",
            "aragora.storage.governance_store",
            "PostgresGovernanceStore",
            None,  # Uses module-global _postgres_store directly
            None,
        ),
        (
            "inbox",
            "aragora.storage.unified_inbox_store",
            "PostgresUnifiedInboxStore",
            "aragora.storage.unified_inbox_store",
            "set_unified_inbox_store",
        ),
    ]

    for name, module_path, class_name, setter_module, setter_func in store_upgrades:
        try:
            module = __import__(module_path, fromlist=[class_name])
            store_class = getattr(module, class_name)
            store = store_class(pool)
            if hasattr(store, "initialize"):
                await store.initialize()

            # Wire the upgraded store into the module-level singleton so
            # handlers that call get_*_store() receive the PostgreSQL instance.
            if setter_module and setter_func:
                setter_mod = __import__(setter_module, fromlist=[setter_func])
                getattr(setter_mod, setter_func)(store)
            elif name == "governance":
                # governance_store uses _postgres_store module global
                import aragora.storage.governance_store as _gov_mod

                setattr(_gov_mod, "_postgres_store", store)

            results[name] = "postgres"
            logger.info("[upgrade] %s upgraded to PostgreSQL", name)
        except ImportError:
            results[name] = "skipped"
        except (OSError, ConnectionError, RuntimeError, AttributeError) as e:
            # Connection or wiring errors - continue with existing store
            logger.info("[upgrade] %s upgrade failed: %s: %s", name, type(e).__name__, e)
            results[name] = "skipped"
        except Exception as e:  # noqa: BLE001 - final fallback to protect server startup
            # Catch-all for unexpected errors (e.g., read-only replicas)
            logger.warning("[upgrade] %s upgrade failed: %s: %s", name, type(e).__name__, e)
            results[name] = "skipped"

    upgraded = sum(1 for v in results.values() if v == "postgres")
    if upgraded:
        logger.warning("[startup] %s store(s) upgraded to PostgreSQL", upgraded)
    return results
