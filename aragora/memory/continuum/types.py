"""
Type definitions and constants for Continuum Memory System.

Contains TypedDicts, constants, and schema definitions used throughout
the continuum memory package.
"""

from __future__ import annotations

from typing import TypedDict

from aragora.memory.tier_manager import (
    DEFAULT_TIER_CONFIGS,
    MemoryTier,
    TierConfig,  # re-exported for backwards compatibility
)

# Schema version for ContinuumMemory
CONTINUUM_SCHEMA_VERSION = 3

# Default retention multiplier (entries older than multiplier * half_life are eligible for cleanup)
DEFAULT_RETENTION_MULTIPLIER = 2.0

# Re-export for backwards compatibility (use DEFAULT_TIER_CONFIGS from tier_manager)
TIER_CONFIGS = DEFAULT_TIER_CONFIGS


class MaxEntriesPerTier(TypedDict):
    """Type definition for max entries per tier configuration."""

    fast: int
    medium: int
    slow: int
    glacial: int


class ContinuumHyperparams(TypedDict):
    """
    Type definition for ContinuumMemory hyperparameters.

    These parameters control memory consolidation, tier transitions,
    and retention policies. They can be modified by MetaLearner.
    """

    surprise_weight_success: float  # Weight for success rate surprise
    surprise_weight_semantic: float  # Weight for semantic novelty
    surprise_weight_temporal: float  # Weight for timing surprise
    surprise_weight_agent: float  # Weight for agent prediction error
    consolidation_threshold: float  # Updates to reach full consolidation
    promotion_cooldown_hours: float  # Minimum time between promotions
    max_entries_per_tier: MaxEntriesPerTier  # Max entries per tier
    retention_multiplier: float  # multiplier * half_life for cleanup


# SQL schema for ContinuumMemory tables
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


__all__ = [
    "CONTINUUM_SCHEMA_VERSION",
    "DEFAULT_RETENTION_MULTIPLIER",
    "TIER_CONFIGS",
    "MaxEntriesPerTier",
    "ContinuumHyperparams",
    "INITIAL_SCHEMA",
    "SCHEMA_MIGRATIONS",
    "MemoryTier",
    "TierConfig",
]
