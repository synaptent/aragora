"""
Continuum Memory System (CMS) for Nested Learning.

Implements Google Research's Nested Learning paradigm with multi-timescale
memory updates. Memory is treated as a spectrum where different modules
update at different frequencies, enabling continual learning without
catastrophic forgetting.

Based on: https://research.google/blog/introducing-nested-learning-a-new-ml-paradigm-for-continual-learning/

Key concepts:
- Fast tier: Updates on every event (immediate patterns, 1h half-life)
- Medium tier: Updates per debate round (tactical learning, 24h half-life)
- Slow tier: Updates per nomic cycle (strategic learning, 7d half-life)
- Glacial tier: Updates monthly (foundational knowledge, 30d half-life)
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import (
    MemoryTier,
    TierManager,
    get_tier_manager,
)
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import SchemaManager

# Import mixins
from aragora.memory.continuum_glacial import ContinuumGlacialMixin
from aragora.memory.continuum_snapshot import ContinuumSnapshotMixin

from .crud import CrudMixin
from .retrieval import RetrievalMixin
from .outcome import OutcomeMixin
from .tier_ops import TierOpsMixin
from .km_integration import KMIntegrationMixin
from .types import (
    CONTINUUM_SCHEMA_VERSION,
    DEFAULT_RETENTION_MULTIPLIER,
    INITIAL_SCHEMA,
    SCHEMA_MIGRATIONS,
    ContinuumHyperparams,
    MaxEntriesPerTier,
)

if TYPE_CHECKING:
    from aragora.protocols import LegacyEventEmitterProtocol
    from aragora.knowledge.mound.adapters.continuum_adapter import ContinuumAdapter

logger = logging.getLogger(__name__)


class ContinuumMemory(
    SQLiteStore,
    CrudMixin,
    RetrievalMixin,
    OutcomeMixin,
    TierOpsMixin,
    KMIntegrationMixin,
    ContinuumGlacialMixin,
    ContinuumSnapshotMixin,
):
    """
    Continuum Memory System with multi-timescale updates.

    This implements Google's Nested Learning paradigm where memory is
    treated as a spectrum with modules updating at different frequency rates.

    Inherits from:
        - SQLiteStore: Database operations (must be first for MRO)
        - CrudMixin: CRUD operations (add, get, update, delete)
        - RetrievalMixin: Search and retrieval operations
        - OutcomeMixin: Surprise scoring and outcome tracking
        - TierOpsMixin: Tier promotion/demotion operations
        - KMIntegrationMixin: Knowledge Mound integration
        - ContinuumGlacialMixin: Glacial tier access for cross-session learning
        - ContinuumSnapshotMixin: Checkpoint export/restore capabilities

    Usage:
        cms = ContinuumMemory()

        # Add a fast-tier memory (immediate pattern)
        cms.add("error_pattern_123", "TypeError in agent response",
                tier=MemoryTier.FAST, importance=0.8)

        # Retrieve memories for a specific context
        relevant = cms.retrieve(query="type errors", tiers=[MemoryTier.FAST, MemoryTier.MEDIUM])

        # Update surprise score after observing outcome
        cms.update_surprise("error_pattern_123", observed_success=True)

        # Periodic tier consolidation
        cms.consolidate()
    """

    SCHEMA_NAME: str = "continuum_memory"
    SCHEMA_VERSION: int = CONTINUUM_SCHEMA_VERSION

    # Type annotations for lazy-initialized attributes (HybridMemorySearch is lazy-imported)
    _hybrid_search: Any | None = None

    INITIAL_SCHEMA = INITIAL_SCHEMA
    SCHEMA_MIGRATIONS = SCHEMA_MIGRATIONS

    def __init__(
        self,
        db_path: str | Path | None = None,
        tier_manager: TierManager | None = None,
        event_emitter: LegacyEventEmitterProtocol | None = None,
        storage_path: str | None = None,
        base_dir: str | None = None,
        km_adapter: ContinuumAdapter | None = None,
    ) -> None:
        if db_path is None:
            db_path = get_db_path(DatabaseType.CONTINUUM_MEMORY)
        resolved_path: str | Path = db_path
        base_path: str | None = storage_path or base_dir
        if base_path:
            base: Path = Path(base_path)
            if base.suffix:
                resolved_path = base
            else:
                resolved_path = base / "continuum_memory.db"
        else:
            candidate: Path = Path(db_path)
            if candidate.exists() and candidate.is_dir():
                resolved_path = candidate / "continuum_memory.db"

        # Initialize SQLiteStore base class (handles schema creation)
        super().__init__(resolved_path)

        # Use provided TierManager or get the shared instance
        self._tier_manager: TierManager = tier_manager or get_tier_manager()

        # Optional event emitter for WebSocket streaming
        self.event_emitter: LegacyEventEmitterProtocol | None = event_emitter

        # Hyperparameters (can be modified by MetaLearner)
        # TypedDict constructor returns dict; mypy cannot verify nested TypedDict compatibility
        self.hyperparams: ContinuumHyperparams = ContinuumHyperparams(  # type: ignore[assignment]
            surprise_weight_success=0.3,  # Weight for success rate surprise
            surprise_weight_semantic=0.3,  # Weight for semantic novelty
            surprise_weight_temporal=0.2,  # Weight for timing surprise
            surprise_weight_agent=0.2,  # Weight for agent prediction error
            consolidation_threshold=100.0,  # Updates to reach full consolidation
            promotion_cooldown_hours=24.0,  # Minimum time between promotions
            # Retention policy settings
            max_entries_per_tier=MaxEntriesPerTier(
                fast=1000,
                medium=5000,
                slow=10000,
                glacial=50000,
            ),
            retention_multiplier=DEFAULT_RETENTION_MULTIPLIER,  # multiplier * half_life for cleanup
        )

        # Sync tier manager settings with hyperparams
        self._tier_manager.promotion_cooldown_hours = self.hyperparams["promotion_cooldown_hours"]

        # Lock for atomic tier transitions (prevents TOCTOU race in promote/demote)
        self._tier_lock: threading.Lock = threading.Lock()

        # Optional Knowledge Mound adapter for bidirectional integration
        self._km_adapter: ContinuumAdapter | None = km_adapter

    def register_migrations(self, manager: SchemaManager) -> None:
        """Register schema migrations for ContinuumMemory."""
        # Migration from v1 to v2 is handled by including archive table in INITIAL_SCHEMA
        # since v2 is the current version. Old v1 databases will get the archive table
        # automatically when the schema is applied.
        pass

    @property
    def tier_manager(self) -> TierManager:
        """Get the tier manager instance."""
        return self._tier_manager

    def get_tier_metrics(self) -> dict[str, Any]:
        """Get tier transition metrics from the tier manager."""
        return self._tier_manager.get_metrics_dict()


__all__ = [
    "ContinuumMemory",
    "MemoryTier",
]
