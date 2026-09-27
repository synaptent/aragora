"""
Continuum Memory System - Main Coordinator.

This module contains the main ContinuumMemory class that coordinates
all memory tiers and provides the unified interface for the system.

The ContinuumMemory class implements Google's Nested Learning paradigm
where memory is treated as a spectrum with modules updating at different
frequency rates, enabling continual learning without catastrophic forgetting.
"""
# mypy: disable-error-code="misc,arg-type,assignment,override"
# Mixin composition uses self-type hints that mypy doesn't understand
# Multiple ContinuumMemory types (coordinator vs core) are structurally compatible

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import (
    MemoryTier,
    TierManager,
    get_tier_manager,
)
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.resilience.retry import PROVIDER_RETRY_POLICIES, with_retry
from aragora.storage.base_store import SQLiteStore
from aragora.storage.schema import SchemaManager
from aragora.utils.datetime_helpers import utc_now_iso_naive
from aragora.utils.json_helpers import safe_json_loads

# Import base types and tier mixins
from aragora.memory.continuum.base import (
    CONTINUUM_SCHEMA_VERSION,
    ContinuumHyperparams,
    ContinuumMemoryEntry,
    get_default_hyperparams,
)
from aragora.memory.continuum.fast_tier import FastTierMixin
from aragora.memory.continuum.medium_tier import MediumTierMixin
from aragora.memory.continuum.slow_tier import SlowTierMixin
from aragora.memory.continuum.glacial_tier import GlacialTierMixin

# Import existing extracted modules for delegation
from aragora.memory.continuum_glacial import ContinuumGlacialMixin
from aragora.memory.continuum_snapshot import ContinuumSnapshotMixin

# Import coordinator mixins (search and tier operations)
from aragora.memory.continuum.coordinator_search import CoordinatorSearchMixin
from aragora.memory.continuum.coordinator_tier_ops import CoordinatorTierOpsMixin

if TYPE_CHECKING:
    from aragora.types.protocols import EventEmitterProtocol
    from aragora.knowledge.mound.adapters.continuum_adapter import ContinuumAdapter

logger = logging.getLogger(__name__)

# Retry configuration for memory operations
_MEMORY_RETRY_CONFIG = PROVIDER_RETRY_POLICIES["memory"]


class ContinuumMemory(
    SQLiteStore,
    ContinuumGlacialMixin,
    ContinuumSnapshotMixin,
    CoordinatorSearchMixin,
    CoordinatorTierOpsMixin,
    FastTierMixin,
    MediumTierMixin,
    SlowTierMixin,
    GlacialTierMixin,
):
    """
    Continuum Memory System with multi-timescale updates.

    This implements Google's Nested Learning paradigm where memory is
    treated as a spectrum with modules updating at different frequency rates.

    Inherits from:
        - SQLiteStore: Database operations (must be first for MRO)
        - ContinuumGlacialMixin: Glacial tier access for cross-session learning
        - ContinuumSnapshotMixin: Checkpoint export/restore capabilities
        - FastTierMixin: Fast tier operations (1 hour TTL)
        - MediumTierMixin: Medium tier operations (24 hour TTL)
        - SlowTierMixin: Slow tier operations (7 day TTL)
        - GlacialTierMixin: Glacial tier operations (30 day TTL)

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

    # Type annotations for lazy-initialized attributes
    _hybrid_search: Any | None = None

    INITIAL_SCHEMA = """
        -- Main continuum memory table
        CREATE TABLE IF NOT EXISTS continuum_memory (
            id TEXT PRIMARY KEY,
            tier TEXT NOT NULL DEFAULT 'slow',
            content TEXT NOT NULL,
            importance REAL DEFAULT 0.5,
            surprise_score REAL DEFAULT 0.0,
            consolidation_score REAL DEFAULT 0.0,
            update_count INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failure_count INTEGER DEFAULT 0,
            semantic_centroid BLOB,
            last_promotion_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            metadata TEXT DEFAULT '{}',
            expires_at TEXT,
            red_line INTEGER DEFAULT 0,
            red_line_reason TEXT DEFAULT ''
        );

        -- Indexes for efficient tier-based retrieval
        CREATE INDEX IF NOT EXISTS idx_continuum_tier ON continuum_memory(tier);
        CREATE INDEX IF NOT EXISTS idx_continuum_surprise ON continuum_memory(surprise_score DESC);
        CREATE INDEX IF NOT EXISTS idx_continuum_importance ON continuum_memory(importance DESC);
        -- Composite index for cleanup_expired_memories() performance
        CREATE INDEX IF NOT EXISTS idx_continuum_tier_updated ON continuum_memory(tier, updated_at);
        -- Composite index for tier-filtered retrieval by importance
        CREATE INDEX IF NOT EXISTS idx_continuum_tier_importance ON continuum_memory(tier, importance DESC);
        -- Composite index for promotion queries (tier + surprise_score)
        CREATE INDEX IF NOT EXISTS idx_continuum_tier_surprise ON continuum_memory(tier, surprise_score DESC);
        -- Index for TTL-based cleanup queries
        CREATE INDEX IF NOT EXISTS idx_continuum_expires ON continuum_memory(expires_at);

        -- Meta-learning state table for hyperparameter tracking
        CREATE TABLE IF NOT EXISTS meta_learning_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hyperparams TEXT NOT NULL,
            learning_efficiency REAL,
            pattern_retention_rate REAL,
            forgetting_rate REAL,
            cycles_evaluated INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Tier transition history for analysis
        CREATE TABLE IF NOT EXISTS tier_transitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            memory_id TEXT NOT NULL,
            from_tier TEXT NOT NULL,
            to_tier TEXT NOT NULL,
            reason TEXT,
            surprise_score REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (memory_id) REFERENCES continuum_memory(id)
        );

        -- Archive table for deleted memories
        CREATE TABLE IF NOT EXISTS continuum_memory_archive (
            id TEXT PRIMARY KEY,
            tier TEXT NOT NULL,
            content TEXT NOT NULL,
            importance REAL,
            surprise_score REAL,
            consolidation_score REAL,
            update_count INTEGER,
            success_count INTEGER,
            failure_count INTEGER,
            semantic_centroid BLOB,
            created_at TEXT,
            updated_at TEXT,
            archived_at TEXT DEFAULT CURRENT_TIMESTAMP,
            archive_reason TEXT,
            metadata TEXT
        );

        -- Indexes for archive queries
        CREATE INDEX IF NOT EXISTS idx_archive_tier ON continuum_memory_archive(tier);
        CREATE INDEX IF NOT EXISTS idx_archive_archived_at ON continuum_memory_archive(archived_at);

        -- Index for red line protected entries
        CREATE INDEX IF NOT EXISTS idx_continuum_red_line ON continuum_memory(red_line);
    """

    # Migration from version 2 to version 3: Add red_line columns
    SCHEMA_MIGRATIONS = {
        3: """
            ALTER TABLE continuum_memory ADD COLUMN red_line INTEGER DEFAULT 0;
            ALTER TABLE continuum_memory ADD COLUMN red_line_reason TEXT DEFAULT '';
            CREATE INDEX IF NOT EXISTS idx_continuum_red_line ON continuum_memory(red_line);
        """
    }

    def __init__(
        self,
        db_path: str | Path | None = None,
        tier_manager: TierManager | None = None,
        event_emitter: EventEmitterProtocol | None = None,
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
        self.event_emitter: EventEmitterProtocol | None = event_emitter

        # Hyperparameters (can be modified by MetaLearner)
        self.hyperparams: ContinuumHyperparams = get_default_hyperparams()

        # Sync tier manager settings with hyperparams
        self._tier_manager.promotion_cooldown_hours = self.hyperparams["promotion_cooldown_hours"]

        # Lock for atomic tier transitions (prevents TOCTOU race in promote/demote)
        self._tier_lock: threading.Lock = threading.Lock()

        # Optional Knowledge Mound adapter for bidirectional integration
        self._km_adapter: ContinuumAdapter | None = km_adapter

    def set_km_adapter(self, adapter: ContinuumAdapter) -> None:
        """Set the Knowledge Mound adapter for bidirectional sync.

        Args:
            adapter: ContinuumAdapter instance for KM integration
        """
        self._km_adapter = adapter

    # Search methods provided by CoordinatorSearchMixin:
    #   query_km_for_similar, retrieve, hybrid_search,
    #   rebuild_keyword_index, prewarm_for_query, invalidate_reference
    #
    # Tier operations provided by CoordinatorTierOpsMixin:
    #   promote_entry, demote_entry, mark_red_line, get_red_line_memories,
    #   update_outcome, get_learning_rate, promote, demote, _emit_tier_event,
    #   _promote_batch, _demote_batch, consolidate, get_stats, export_for_tier,
    #   get_memory_pressure, cleanup_expired_memories, delete,
    #   enforce_tier_limits, get_archive_stats

    def register_migrations(self, manager: SchemaManager) -> None:
        """Register schema migrations for ContinuumMemory."""
        pass

    @property
    def tier_manager(self) -> TierManager:
        """Get the tier manager instance."""
        return self._tier_manager

    def get_tier_metrics(self) -> dict[str, Any]:
        """Get tier transition metrics from the tier manager."""
        return self._tier_manager.get_metrics_dict()

    def add(
        self,
        id: str,
        content: str,
        tier: MemoryTier = MemoryTier.SLOW,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """
        Add a new memory entry to the continuum.

        Args:
            id: Unique identifier for the memory
            content: The memory content
            tier: Initial memory tier
            importance: 0-1 importance score
            metadata: Optional additional data

        Returns:
            The created memory entry
        """
        now: str = utc_now_iso_naive()

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO continuum_memory
                (id, tier, content, importance, surprise_score, consolidation_score,
                 update_count, success_count, failure_count, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, 0.0, 0.0, 1, 0, 0, ?, ?, ?)
                """,
                (id, tier.value, content, importance, now, now, json.dumps(metadata or {})),
            )
            conn.commit()

        entry: ContinuumMemoryEntry = ContinuumMemoryEntry(
            id=id,
            tier=tier,
            content=content,
            importance=importance,
            surprise_score=0.0,
            consolidation_score=0.0,
            update_count=1,
            success_count=0,
            failure_count=0,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        # Emit MEMORY_STORED event for cross-subsystem tracking
        if self.event_emitter:
            try:
                self.event_emitter.emit_sync(
                    event_type="memory_stored",
                    debate_id="",
                    memory_id=id,
                    tier=tier.value,
                    importance=importance,
                    content_length=len(content),
                )
            except (ImportError, AttributeError, TypeError):
                pass  # Events module not available

        # Sync to Knowledge Mound if adapter is configured and importance is high
        if self._km_adapter and importance >= 0.7:
            try:
                self._km_adapter.store_memory(entry)
            except (ConnectionError, TimeoutError, OSError) as e:
                logger.debug("Failed to sync memory to KM (network): %s", e)
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("Failed to sync memory to KM (data): %s", e)
            except (RuntimeError, AttributeError) as e:
                logger.warning("Unexpected error syncing memory to KM: %s", e)

        return entry

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def add_async(
        self,
        id: str,
        content: str,
        tier: MemoryTier = MemoryTier.SLOW,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """Async wrapper for add() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.add(
                id=id,
                content=content,
                tier=tier,
                importance=importance,
                metadata=metadata,
            ),
        )

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def store(
        self,
        key: str,
        content: str,
        tier: str | MemoryTier = MemoryTier.SLOW,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> ContinuumMemoryEntry:
        """Async wrapper for add() - offloads blocking I/O to executor."""
        normalized_tier: MemoryTier = MemoryTier(tier) if isinstance(tier, str) else tier
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.add(
                id=key,
                content=content,
                tier=normalized_tier,
                importance=importance,
                metadata=metadata,
            ),
        )

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def get_async(self, id: str) -> ContinuumMemoryEntry | None:
        """Async wrapper for get() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get, id)

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def retrieve_async(
        self,
        query: str | None = None,
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
        include_glacial: bool = True,
        tier: str | MemoryTier | None = None,
    ) -> list[ContinuumMemoryEntry]:
        """Async wrapper for retrieve() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.retrieve(  # type: ignore[return-value]
                query=query,
                tiers=tiers,
                limit=limit,
                min_importance=min_importance,
                include_glacial=include_glacial,
                tier=tier,
            ),
        )

    @with_retry(_MEMORY_RETRY_CONFIG)
    async def update_outcome_async(
        self,
        id: str,
        success: bool,
        agent_prediction_error: float | None = None,
    ) -> float:
        """Async wrapper for update_outcome() - offloads blocking I/O to executor."""
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.update_outcome(id, success, agent_prediction_error),
        )

    def get(self, id: str) -> ContinuumMemoryEntry | None:
        """Get a memory entry by ID."""
        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, tier, content, importance, surprise_score, consolidation_score,
                       update_count, success_count, failure_count, created_at, updated_at, metadata,
                       COALESCE(red_line, 0), COALESCE(red_line_reason, '')
                FROM continuum_memory
                WHERE id = ?
                """,
                (id,),
            )
            row: tuple[Any, ...] | None = cursor.fetchone()

        if not row:
            return None

        return ContinuumMemoryEntry(
            id=row[0],
            tier=MemoryTier(row[1]),
            content=row[2],
            importance=row[3],
            surprise_score=row[4],
            consolidation_score=row[5],
            update_count=row[6],
            success_count=row[7],
            failure_count=row[8],
            created_at=row[9],
            updated_at=row[10],
            metadata=safe_json_loads(row[11], {}),
            red_line=bool(row[12]),
            red_line_reason=row[13],
        )

    def get_entry(self, id: str) -> ContinuumMemoryEntry | None:
        """Alias for get() for interface compatibility with OutcomeMemoryBridge."""
        return self.get(id)

    def update_entry(self, entry: ContinuumMemoryEntry) -> bool:
        """Update an entry's success/failure counts.

        Interface compatibility method for OutcomeMemoryBridge.
        """
        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE continuum_memory
                SET success_count = ?, failure_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (entry.success_count, entry.failure_count, utc_now_iso_naive(), entry.id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update(
        self,
        memory_id: str,
        content: str | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        surprise_score: float | None = None,
        consolidation_score: float | None = None,
    ) -> bool:
        """Update specific fields of a memory entry.

        Flexible update method for modifying individual fields.
        Used by ContinuumAdapter for KM validation reverse flow.

        Args:
            memory_id: The ID of the memory entry to update
            content: New content (optional)
            importance: New importance score (optional)
            metadata: New metadata dict (optional, replaces existing)
            surprise_score: New surprise score (optional)
            consolidation_score: New consolidation score (optional)

        Returns:
            True if the entry was updated, False if not found
        """
        # Build update clauses dynamically
        updates: list[str] = []
        params: list[Any] = []

        if content is not None:
            updates.append("content = ?")
            params.append(content)
        if importance is not None:
            updates.append("importance = ?")
            params.append(importance)
        if metadata is not None:
            updates.append("metadata = ?")
            params.append(json.dumps(metadata))
        if surprise_score is not None:
            updates.append("surprise_score = ?")
            params.append(surprise_score)
        if consolidation_score is not None:
            updates.append("consolidation_score = ?")
            params.append(consolidation_score)

        if not updates:
            return False

        # Always update timestamp
        updates.append("updated_at = ?")
        params.append(utc_now_iso_naive())

        # Add memory_id as final parameter
        params.append(memory_id)

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute(
                f"""
                UPDATE continuum_memory
                SET {", ".join(updates)}
                WHERE id = ?
                """,  # noqa: S608 -- dynamic clause from internal state
                tuple(params),
            )
            conn.commit()
            return cursor.rowcount > 0


# Singleton instance for cross-subsystem access
_global_continuum_memory: ContinuumMemory | None = None


def get_continuum_memory(
    db_path: str | None = None,
    event_emitter: EventEmitterProtocol | None = None,
) -> ContinuumMemory:
    """Get the global ContinuumMemory singleton instance.

    Creates a new instance if one doesn't exist, or returns the existing one.
    Useful for cross-subsystem integration where modules need shared memory access.

    Args:
        db_path: Optional database path (only used on first call)
        event_emitter: Optional event emitter for cross-subsystem events

    Returns:
        ContinuumMemory singleton instance
    """
    global _global_continuum_memory

    if _global_continuum_memory is None:
        _global_continuum_memory = ContinuumMemory(
            db_path=db_path,
            event_emitter=event_emitter,
        )
        logger.debug("Created global ContinuumMemory instance")

    return _global_continuum_memory


def reset_continuum_memory() -> None:
    """Reset the global ContinuumMemory instance (for testing)."""
    global _global_continuum_memory
    if _global_continuum_memory:
        if hasattr(_global_continuum_memory, "close"):
            getattr(_global_continuum_memory, "close")()
    _global_continuum_memory = None


__all__ = [
    "ContinuumMemory",
    "get_continuum_memory",
    "reset_continuum_memory",
]
