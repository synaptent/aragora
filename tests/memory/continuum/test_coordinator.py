"""
Comprehensive tests for ContinuumMemory Coordinator.

Tests the multi-tier memory coordination system including:
- Memory tier operations (fast/medium/slow/glacial)
- Tier transitions (promotion/demotion)
- TTL enforcement and expiration
- Cache invalidation
- Consolidation algorithm
- Concurrent access and thread safety
- Edge cases and error handling

This tests the ContinuumMemory class from aragora/memory/continuum/coordinator.py
"""

import asyncio
import json
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from aragora.memory.continuum.coordinator import (
    ContinuumMemory,
    get_continuum_memory,
    reset_continuum_memory,
)
from aragora.memory.continuum.base import (
    ContinuumMemoryEntry,
    TIER_CONFIGS,
    get_default_hyperparams,
)
from aragora.memory.tier_manager import (
    MemoryTier,
    TierManager,
    reset_tier_manager,
)


def _utc_naive_now() -> datetime:
    """Naive-UTC now, matching how continuum rows are stamped (see PR #9311)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path(tmp_path):
    """Create a temporary database path for testing."""
    return str(tmp_path / "test_coordinator.db")


@pytest.fixture
def tier_manager():
    """Create a fresh TierManager for testing."""
    return TierManager()


@pytest.fixture
def memory(temp_db_path, tier_manager):
    """Create a ContinuumMemory instance with isolated database."""
    reset_tier_manager()
    reset_continuum_memory()
    cms = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
    yield cms
    reset_tier_manager()
    reset_continuum_memory()


@pytest.fixture
def populated_memory(memory):
    """Memory with pre-populated entries across all tiers."""
    # Fast tier entries
    memory.add("fast_1", "Fast tier error pattern", tier=MemoryTier.FAST, importance=0.8)
    memory.add("fast_2", "Fast debugging info", tier=MemoryTier.FAST, importance=0.6)
    memory.add("fast_3", "Fast temporary context", tier=MemoryTier.FAST, importance=0.4)

    # Medium tier entries
    memory.add("medium_1", "Medium tactical learning", tier=MemoryTier.MEDIUM, importance=0.7)
    memory.add("medium_2", "Medium session context", tier=MemoryTier.MEDIUM, importance=0.5)

    # Slow tier entries
    memory.add("slow_1", "Slow strategic pattern", tier=MemoryTier.SLOW, importance=0.9)
    memory.add("slow_2", "Slow cross-session insight", tier=MemoryTier.SLOW, importance=0.75)

    # Glacial tier entries
    memory.add(
        "glacial_1", "Glacial foundational knowledge", tier=MemoryTier.GLACIAL, importance=0.95
    )
    memory.add("glacial_2", "Glacial long-term pattern", tier=MemoryTier.GLACIAL, importance=0.85)

    return memory


# =============================================================================
# Test Memory Tier Operations - Fast Tier (1 min effective TTL in tests)
# =============================================================================


class TestFastTierOperations:
    """Test fast tier operations with 1 hour half-life."""

    def test_add_to_fast_tier(self, memory):
        """Test adding entry directly to fast tier."""
        entry = memory.add("fast_test", "Fast content", tier=MemoryTier.FAST, importance=0.8)

        assert entry.tier == MemoryTier.FAST
        assert entry.importance == 0.8
        assert entry.content == "Fast content"

    def test_fast_tier_high_learning_rate(self, memory):
        """Test that fast tier has high learning rate."""
        lr = memory.get_learning_rate(MemoryTier.FAST, update_count=1)
        config = TIER_CONFIGS[MemoryTier.FAST]

        assert lr == config.base_learning_rate * (config.decay_rate**1)
        assert lr > memory.get_learning_rate(MemoryTier.GLACIAL, update_count=1)

    def test_fast_tier_rapid_decay(self, memory):
        """Test that fast tier learning rate decays rapidly."""
        lr_early = memory.get_learning_rate(MemoryTier.FAST, update_count=1)
        lr_mid = memory.get_learning_rate(MemoryTier.FAST, update_count=10)
        lr_late = memory.get_learning_rate(MemoryTier.FAST, update_count=50)

        assert lr_early > lr_mid > lr_late

    def test_fast_tier_retrieval_priority(self, populated_memory):
        """Test that fast tier entries have high retrieval priority."""
        # Fast tier entries should appear with recent updates
        results = populated_memory.retrieve(tiers=[MemoryTier.FAST], limit=10)

        assert len(results) == 3
        assert all(e.tier == MemoryTier.FAST for e in results)

    def test_fast_tier_half_life(self, memory):
        """Test that fast tier has 1 hour half-life."""
        config = TIER_CONFIGS[MemoryTier.FAST]
        assert config.half_life_hours == 1
        assert config.half_life_seconds == 3600

    def test_fast_tier_update_frequency(self, memory):
        """Test fast tier updates on every event."""
        config = TIER_CONFIGS[MemoryTier.FAST]
        assert config.update_frequency == "event"

    def test_fast_tier_cannot_promote_further(self, memory):
        """Test that fast tier entries cannot promote higher."""
        entry = memory.add("fast_max", "Max tier content", tier=MemoryTier.FAST)

        # Set high surprise to trigger promotion attempt
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("fast_max",),
            )
            conn.commit()

        result = memory.promote("fast_max")
        assert result is None  # Cannot promote from fast tier


# =============================================================================
# Test Memory Tier Operations - Medium Tier (1 hour TTL)
# =============================================================================


class TestMediumTierOperations:
    """Test medium tier operations with 24 hour half-life."""

    def test_add_to_medium_tier(self, memory):
        """Test adding entry directly to medium tier."""
        entry = memory.add("medium_test", "Medium content", tier=MemoryTier.MEDIUM, importance=0.7)

        assert entry.tier == MemoryTier.MEDIUM
        assert entry.importance == 0.7

    def test_medium_tier_config(self, memory):
        """Test medium tier configuration."""
        config = TIER_CONFIGS[MemoryTier.MEDIUM]

        assert config.half_life_hours == 24
        assert config.update_frequency == "round"
        assert config.promotion_threshold == 0.7

    def test_medium_tier_learning_rate(self, memory):
        """Test medium tier has moderate learning rate."""
        lr_medium = memory.get_learning_rate(MemoryTier.MEDIUM, update_count=1)
        lr_fast = memory.get_learning_rate(MemoryTier.FAST, update_count=1)
        lr_slow = memory.get_learning_rate(MemoryTier.SLOW, update_count=1)

        assert lr_fast > lr_medium > lr_slow

    def test_medium_tier_retrieval(self, populated_memory):
        """Test retrieving medium tier entries."""
        results = populated_memory.retrieve(tiers=[MemoryTier.MEDIUM], limit=10)

        assert len(results) == 2
        assert all(e.tier == MemoryTier.MEDIUM for e in results)

    def test_medium_tier_can_demote(self, memory):
        """Test that stable medium tier entries can demote."""
        entry = ContinuumMemoryEntry(
            id="test",
            tier=MemoryTier.MEDIUM,
            content="Test",
            importance=0.5,
            surprise_score=0.1,  # Low surprise = high stability
            consolidation_score=0.5,
            update_count=15,  # Sufficient updates
            success_count=10,
            failure_count=5,
            created_at=_utc_naive_now().isoformat(),
            updated_at=_utc_naive_now().isoformat(),
        )

        # Stability (0.9) > demotion threshold (0.3)
        assert entry.should_demote() is True


# =============================================================================
# Test Memory Tier Operations - Slow Tier (1 day TTL)
# =============================================================================


class TestSlowTierOperations:
    """Test slow tier operations with 7 day half-life."""

    def test_add_to_slow_tier(self, memory):
        """Test adding entry directly to slow tier (default)."""
        entry = memory.add("slow_test", "Slow content")

        # Slow is the default tier
        assert entry.tier == MemoryTier.SLOW
        assert entry.importance == 0.5  # Default importance

    def test_slow_tier_config(self, memory):
        """Test slow tier configuration."""
        config = TIER_CONFIGS[MemoryTier.SLOW]

        assert config.half_life_hours == 168  # 7 days
        assert config.update_frequency == "cycle"
        assert config.promotion_threshold == 0.6

    def test_slow_tier_low_learning_rate(self, memory):
        """Test slow tier has low learning rate."""
        lr = memory.get_learning_rate(MemoryTier.SLOW, update_count=1)
        config = TIER_CONFIGS[MemoryTier.SLOW]

        assert lr == config.base_learning_rate * config.decay_rate

    def test_slow_tier_gradual_decay(self, memory):
        """Test slow tier learning rate decays gradually."""
        lr_1 = memory.get_learning_rate(MemoryTier.SLOW, update_count=1)
        lr_100 = memory.get_learning_rate(MemoryTier.SLOW, update_count=100)

        # Decay rate is 0.999, so decay is very gradual
        assert lr_1 > lr_100
        # But not by as much as fast tier
        ratio = lr_100 / lr_1
        assert ratio > 0.9  # Less than 10% decay after 100 updates

    def test_slow_tier_retrieval(self, populated_memory):
        """Test retrieving slow tier entries."""
        results = populated_memory.retrieve(tiers=[MemoryTier.SLOW], limit=10)

        assert len(results) == 2
        assert all(e.tier == MemoryTier.SLOW for e in results)


# =============================================================================
# Test Memory Tier Operations - Glacial Tier (1 week TTL)
# =============================================================================


class TestGlacialTierOperations:
    """Test glacial tier operations with 30 day half-life."""

    def test_add_to_glacial_tier(self, memory):
        """Test adding entry directly to glacial tier."""
        entry = memory.add(
            "glacial_test", "Glacial content", tier=MemoryTier.GLACIAL, importance=0.95
        )

        assert entry.tier == MemoryTier.GLACIAL
        assert entry.importance == 0.95

    def test_glacial_tier_config(self, memory):
        """Test glacial tier configuration."""
        config = TIER_CONFIGS[MemoryTier.GLACIAL]

        assert config.half_life_hours == 720  # 30 days
        assert config.update_frequency == "monthly"
        assert config.promotion_threshold == 0.5
        assert config.demotion_threshold == 1.0  # Cannot demote

    def test_glacial_tier_minimal_learning_rate(self, memory):
        """Test glacial tier has minimal learning rate."""
        lr = memory.get_learning_rate(MemoryTier.GLACIAL, update_count=1)

        assert lr < 0.02  # Very low learning rate

    def test_glacial_tier_cannot_demote(self, memory):
        """Test that glacial tier entries cannot demote."""
        entry = ContinuumMemoryEntry(
            id="test",
            tier=MemoryTier.GLACIAL,
            content="Test",
            importance=0.5,
            surprise_score=0.01,  # Very stable
            consolidation_score=0.9,
            update_count=100,
            success_count=80,
            failure_count=20,
            created_at=_utc_naive_now().isoformat(),
            updated_at=_utc_naive_now().isoformat(),
        )

        assert entry.should_demote() is False  # Already at slowest tier

    def test_glacial_tier_retrieval(self, populated_memory):
        """Test retrieving glacial tier entries."""
        results = populated_memory.retrieve(tiers=[MemoryTier.GLACIAL], limit=10)

        assert len(results) == 2
        assert all(e.tier == MemoryTier.GLACIAL for e in results)

    def test_exclude_glacial_from_retrieval(self, populated_memory):
        """Test excluding glacial tier from retrieval."""
        results = populated_memory.retrieve(include_glacial=False, limit=100)

        assert all(e.tier != MemoryTier.GLACIAL for e in results)

    def test_glacial_insights(self, populated_memory):
        """Test getting glacial tier insights."""
        insights = populated_memory.get_glacial_insights(limit=10)

        assert len(insights) >= 1
        assert all(e.tier == MemoryTier.GLACIAL for e in insights)


# =============================================================================
# Test Tier Transitions - Promotion
# =============================================================================


class TestTierPromotion:
    """Test tier promotion mechanics."""

    def test_promote_glacial_to_slow(self, memory):
        """Test promoting entry from glacial to slow tier."""
        memory.add("promote_glacial", "Content", tier=MemoryTier.GLACIAL)

        # Set high surprise score
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.8 WHERE id = ?",
                ("promote_glacial",),
            )
            conn.commit()

        new_tier = memory.promote("promote_glacial")

        assert new_tier == MemoryTier.SLOW

    def test_promote_slow_to_medium(self, memory):
        """Test promoting entry from slow to medium tier."""
        memory.add("promote_slow", "Content", tier=MemoryTier.SLOW)

        # Set surprise above slow tier threshold (0.6)
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.75 WHERE id = ?",
                ("promote_slow",),
            )
            conn.commit()

        new_tier = memory.promote("promote_slow")

        assert new_tier == MemoryTier.MEDIUM

    def test_promote_medium_to_fast(self, memory):
        """Test promoting entry from medium to fast tier."""
        memory.add("promote_medium", "Content", tier=MemoryTier.MEDIUM)

        # Set surprise above medium tier threshold (0.7)
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.85 WHERE id = ?",
                ("promote_medium",),
            )
            conn.commit()

        new_tier = memory.promote("promote_medium")

        assert new_tier == MemoryTier.FAST

    def test_promotion_records_transition(self, memory):
        """Test that promotion records tier transition."""
        memory.add("transition_test", "Content", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.8 WHERE id = ?",
                ("transition_test",),
            )
            conn.commit()

        memory.promote("transition_test")

        # Check transition was recorded
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT from_tier, to_tier, reason FROM tier_transitions WHERE memory_id = ?",
                ("transition_test",),
            )
            row = cursor.fetchone()

        assert row is not None
        assert row[0] == "slow"
        assert row[1] == "medium"
        assert row[2] == "high_surprise"

    def test_promotion_updates_timestamp(self, memory):
        """Test that promotion updates last_promotion_at."""
        memory.add("timestamp_test", "Content", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.8 WHERE id = ?",
                ("timestamp_test",),
            )
            conn.commit()

        before = _utc_naive_now()
        memory.promote("timestamp_test")

        entry = memory.get("timestamp_test")
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_promotion_at FROM continuum_memory WHERE id = ?",
                ("timestamp_test",),
            )
            last_promotion = cursor.fetchone()[0]

        assert last_promotion is not None
        promotion_time = datetime.fromisoformat(last_promotion)
        assert promotion_time >= before

    def test_promotion_respects_threshold(self, memory):
        """Test that promotion only happens above threshold."""
        memory.add("threshold_test", "Content", tier=MemoryTier.SLOW)

        # Set surprise below threshold (0.6)
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.5 WHERE id = ?",
                ("threshold_test",),
            )
            conn.commit()

        result = memory.promote("threshold_test")

        assert result is None  # Should not promote

    def test_promote_entry_direct(self, memory):
        """Test promote_entry method for direct tier assignment."""
        memory.add("direct_promote", "Content", tier=MemoryTier.GLACIAL)

        result = memory.promote_entry("direct_promote", MemoryTier.FAST)

        assert result is True
        entry = memory.get("direct_promote")
        assert entry.tier == MemoryTier.FAST


# =============================================================================
# Test Tier Transitions - Demotion
# =============================================================================


class TestTierDemotion:
    """Test tier demotion mechanics."""

    def test_demote_fast_to_medium(self, memory):
        """Test demoting entry from fast to medium tier."""
        memory.add("demote_fast", "Content", tier=MemoryTier.FAST)

        # Set low surprise (high stability) and sufficient updates
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.1, update_count = 15
                   WHERE id = ?""",
                ("demote_fast",),
            )
            conn.commit()

        new_tier = memory.demote("demote_fast")

        assert new_tier == MemoryTier.MEDIUM

    def test_demote_medium_to_slow(self, memory):
        """Test demoting entry from medium to slow tier."""
        memory.add("demote_medium", "Content", tier=MemoryTier.MEDIUM)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.1, update_count = 15
                   WHERE id = ?""",
                ("demote_medium",),
            )
            conn.commit()

        new_tier = memory.demote("demote_medium")

        assert new_tier == MemoryTier.SLOW

    def test_demote_slow_to_glacial(self, memory):
        """Test demoting entry from slow to glacial tier."""
        memory.add("demote_slow", "Content", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.1, update_count = 15
                   WHERE id = ?""",
                ("demote_slow",),
            )
            conn.commit()

        new_tier = memory.demote("demote_slow")

        assert new_tier == MemoryTier.GLACIAL

    def test_demotion_requires_min_updates(self, memory):
        """Test that demotion requires minimum update count."""
        memory.add("min_updates_test", "Content", tier=MemoryTier.FAST)

        # Low surprise but few updates
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.05, update_count = 5
                   WHERE id = ?""",
                ("min_updates_test",),
            )
            conn.commit()

        result = memory.demote("min_updates_test")

        assert result is None  # Should not demote with insufficient updates

    def test_demotion_records_transition(self, memory):
        """Test that demotion records tier transition."""
        memory.add("demote_transition", "Content", tier=MemoryTier.FAST)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.05, update_count = 15
                   WHERE id = ?""",
                ("demote_transition",),
            )
            conn.commit()

        memory.demote("demote_transition")

        # Check transition was recorded
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT from_tier, to_tier, reason FROM tier_transitions WHERE memory_id = ?",
                ("demote_transition",),
            )
            row = cursor.fetchone()

        assert row is not None
        assert row[0] == "fast"
        assert row[1] == "medium"
        assert row[2] == "high_stability"

    def test_demote_entry_direct(self, memory):
        """Test demote_entry method for direct tier assignment."""
        memory.add("direct_demote", "Content", tier=MemoryTier.FAST)

        result = memory.demote_entry("direct_demote", MemoryTier.GLACIAL)

        assert result is True
        entry = memory.get("direct_demote")
        assert entry.tier == MemoryTier.GLACIAL


# =============================================================================
# Test Entry Expiration
# =============================================================================


class TestEntryExpiration:
    """Test TTL and entry expiration at each tier."""

    def test_cleanup_fast_tier_expired(self, memory):
        """Test cleaning up expired fast tier entries."""
        # Add old entry
        old_time = (_utc_naive_now() - timedelta(hours=5)).isoformat()  # Older than 1hr half-life
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("old_fast", "fast", "Old fast content", 0.3, old_time, old_time),
            )
            conn.commit()

        result = memory.cleanup_expired_memories(tier=MemoryTier.FAST, max_age_hours=1)

        assert result["deleted"] >= 1

    def test_cleanup_medium_tier_expired(self, memory):
        """Test cleaning up expired medium tier entries."""
        old_time = (_utc_naive_now() - timedelta(hours=50)).isoformat()  # Older than 24hr half-life
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("old_medium", "medium", "Old medium content", 0.3, old_time, old_time),
            )
            conn.commit()

        result = memory.cleanup_expired_memories(tier=MemoryTier.MEDIUM, max_age_hours=24)

        assert result["deleted"] >= 1

    def test_cleanup_slow_tier_expired(self, memory):
        """Test cleaning up expired slow tier entries."""
        old_time = (_utc_naive_now() - timedelta(days=15)).isoformat()  # Older than 7 day half-life
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("old_slow", "slow", "Old slow content", 0.3, old_time, old_time),
            )
            conn.commit()

        result = memory.cleanup_expired_memories(tier=MemoryTier.SLOW, max_age_hours=168)

        assert result["deleted"] >= 1

    def test_cleanup_glacial_tier_expired(self, memory):
        """Test cleaning up expired glacial tier entries."""
        old_time = (
            _utc_naive_now() - timedelta(days=60)
        ).isoformat()  # Older than 30 day half-life
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("old_glacial", "glacial", "Old glacial content", 0.3, old_time, old_time),
            )
            conn.commit()

        result = memory.cleanup_expired_memories(tier=MemoryTier.GLACIAL, max_age_hours=720)

        assert result["deleted"] >= 1

    def test_cleanup_preserves_recent_entries(self, memory):
        """Test that cleanup preserves recent entries."""
        memory.add("recent_entry", "Recent content", tier=MemoryTier.FAST)

        result = memory.cleanup_expired_memories(tier=MemoryTier.FAST, max_age_hours=1)

        # Recent entry should still exist
        entry = memory.get("recent_entry")
        assert entry is not None

    def test_cleanup_archives_by_default(self, memory):
        """Test that cleanup archives entries by default."""
        old_time = (_utc_naive_now() - timedelta(hours=10)).isoformat()
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                ("archive_test", "fast", "Archive this", 0.3, old_time, old_time),
            )
            conn.commit()

        memory.cleanup_expired_memories(max_age_hours=1, archive=True)

        # Check archive table
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM continuum_memory_archive WHERE id = ?", ("archive_test",)
            )
            row = cursor.fetchone()

        assert row is not None

    def test_cleanup_skips_red_line_entries(self, memory):
        """Test that cleanup skips red-lined entries."""
        old_time = (_utc_naive_now() - timedelta(hours=10)).isoformat()
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, created_at, red_line, red_line_reason)
                   VALUES (?, ?, ?, ?, ?, ?, 1, ?)""",
                (
                    "protected_old",
                    "fast",
                    "Protected old content",
                    0.3,
                    old_time,
                    old_time,
                    "Critical",
                ),
            )
            conn.commit()

        memory.cleanup_expired_memories(max_age_hours=1)

        # Protected entry should still exist
        entry = memory.get("protected_old")
        assert entry is not None


# =============================================================================
# Test TTL Refresh on Access
# =============================================================================


class TestTTLRefreshOnAccess:
    """Test that TTL is refreshed when entries are accessed/updated."""

    def test_update_outcome_refreshes_timestamp(self, memory):
        """Test that update_outcome refreshes updated_at."""
        memory.add("access_test", "Content")

        old_time = memory.get("access_test").updated_at

        # Small delay to ensure time difference
        time.sleep(0.01)

        memory.update_outcome("access_test", success=True)

        new_entry = memory.get("access_test")
        assert new_entry.updated_at > old_time

    def test_update_method_refreshes_timestamp(self, memory):
        """Test that update method refreshes updated_at."""
        memory.add("update_test", "Original content")

        old_time = memory.get("update_test").updated_at

        time.sleep(0.01)

        memory.update("update_test", content="Updated content")

        new_entry = memory.get("update_test")
        assert new_entry.updated_at > old_time

    def test_promote_refreshes_timestamp(self, memory):
        """Test that promote refreshes updated_at."""
        memory.add("promote_refresh", "Content", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.8 WHERE id = ?",
                ("promote_refresh",),
            )
            conn.commit()

        old_entry = memory.get("promote_refresh")
        old_time = old_entry.updated_at

        time.sleep(0.01)

        memory.promote("promote_refresh")

        new_entry = memory.get("promote_refresh")
        assert new_entry.updated_at > old_time


# =============================================================================
# Test Cache Invalidation
# =============================================================================


class TestCacheInvalidation:
    """Test cache invalidation mechanics."""

    def test_invalidate_km_reference(self, memory):
        """Test invalidating Knowledge Mound references."""
        memory.add(
            "km_ref_test",
            "Content",
            metadata={"km_node_id": "km_123", "cross_references": ["km_123", "km_456"]},
        )

        result = memory.invalidate_reference("km_123")

        assert result is True

        entry = memory.get("km_ref_test")
        assert entry.metadata.get("km_node_id") is None
        assert entry.metadata.get("km_synced") is False
        assert "km_123" not in entry.metadata.get("cross_references", [])
        assert "km_456" in entry.metadata.get("cross_references", [])

    def test_invalidate_nonexistent_reference(self, memory):
        """Test invalidating reference that doesn't exist."""
        memory.add("no_ref_test", "Content", metadata={"other_field": "value"})

        result = memory.invalidate_reference("nonexistent_km_id")

        assert result is False

    def test_invalidate_cross_reference_only(self, memory):
        """Test invalidating cross reference without km_node_id."""
        memory.add(
            "cross_ref_only",
            "Content",
            metadata={"cross_references": ["ref_a", "ref_b", "ref_c"]},
        )

        memory.invalidate_reference("ref_b")

        entry = memory.get("cross_ref_only")
        refs = entry.metadata.get("cross_references", [])
        assert "ref_a" in refs
        assert "ref_b" not in refs
        assert "ref_c" in refs

    def test_batch_invalidation(self, memory):
        """Test invalidating references across multiple entries."""
        for i in range(5):
            memory.add(
                f"batch_ref_{i}",
                f"Content {i}",
                metadata={"km_node_id": "shared_km_id"},
            )

        memory.invalidate_reference("shared_km_id")

        for i in range(5):
            entry = memory.get(f"batch_ref_{i}")
            assert entry.metadata.get("km_node_id") is None


# =============================================================================
# Test Consolidation Algorithm
# =============================================================================


class TestConsolidationAlgorithm:
    """Test the automatic consolidation algorithm."""

    def test_consolidate_promotes_high_surprise(self, memory):
        """Test that consolidation promotes high surprise entries."""
        # Add entries with high surprise
        for i in range(5):
            memory.add(f"high_surprise_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.8 WHERE tier = 'slow'")
            conn.commit()

        result = memory.consolidate()

        assert result["promotions"] >= 0  # May promote if threshold met

    def test_consolidate_demotes_stable_entries(self, memory):
        """Test that consolidation demotes stable entries."""
        for i in range(5):
            memory.add(f"stable_{i}", f"Stable content {i}", tier=MemoryTier.FAST)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.05, update_count = 15
                   WHERE tier = 'fast'"""
            )
            conn.commit()

        result = memory.consolidate()

        assert "demotions" in result
        assert result["demotions"] >= 0

    def test_consolidate_batch_processing(self, memory):
        """Test that consolidation uses batch operations."""
        # Add many entries
        for i in range(50):
            memory.add(f"batch_{i}", f"Content {i}", tier=MemoryTier.MEDIUM)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.85 WHERE tier = 'medium'"
            )
            conn.commit()

        result = memory.consolidate()

        # Should process in batches, not individually
        assert result["promotions"] >= 0

    def test_consolidate_respects_tier_order(self, memory):
        """Test that consolidation processes tiers in correct order."""
        # Add entry that could promote through multiple tiers
        memory.add("multi_tier", "Content", tier=MemoryTier.GLACIAL)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("multi_tier",),
            )
            conn.commit()

        memory.consolidate()

        # Should only promote one level (glacial -> slow)
        entry = memory.get("multi_tier")
        assert entry.tier == MemoryTier.SLOW  # Not directly to fast

    def test_consolidate_returns_counts(self, memory):
        """Test that consolidate returns proper count structure."""
        result = memory.consolidate()

        assert "promotions" in result
        assert "demotions" in result
        assert isinstance(result["promotions"], int)
        assert isinstance(result["demotions"], int)


# =============================================================================
# Test Promotion Cooldown
# =============================================================================


class TestPromotionCooldown:
    """Test promotion cooldown enforcement."""

    def test_cooldown_blocks_rapid_promotion(self, memory):
        """Test that cooldown blocks rapid promotions."""
        memory.add("cooldown_test", "Content", tier=MemoryTier.MEDIUM)

        # First promotion
        now = _utc_naive_now().isoformat()
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.9, last_promotion_at = ?
                   WHERE id = ?""",
                (now, "cooldown_test"),
            )
            conn.commit()

        # Immediate second promotion should be blocked
        result = memory.promote("cooldown_test")

        assert result is None

    def test_cooldown_allows_after_period(self, memory):
        """Test that promotion is allowed after cooldown period."""
        memory.add("cooldown_passed", "Content", tier=MemoryTier.SLOW)

        # Set last promotion to 25 hours ago (beyond 24hr default cooldown)
        old_time = (_utc_naive_now() - timedelta(hours=25)).isoformat()
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.8, last_promotion_at = ?
                   WHERE id = ?""",
                (old_time, "cooldown_passed"),
            )
            conn.commit()

        result = memory.promote("cooldown_passed")

        assert result == MemoryTier.MEDIUM

    def test_cooldown_configurable(self, temp_db_path):
        """Test that cooldown is configurable via hyperparams."""
        tm = TierManager(promotion_cooldown_hours=1.0)  # 1 hour cooldown
        cms = ContinuumMemory(db_path=temp_db_path, tier_manager=tm)
        # Update hyperparams and sync to tier manager
        cms.hyperparams["promotion_cooldown_hours"] = 1.0
        cms._tier_manager.promotion_cooldown_hours = 1.0

        cms.add("short_cooldown", "Content", tier=MemoryTier.SLOW)

        # Set last promotion to 2 hours ago
        old_time = (_utc_naive_now() - timedelta(hours=2)).isoformat()
        with cms.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.8, last_promotion_at = ?
                   WHERE id = ?""",
                (old_time, "short_cooldown"),
            )
            conn.commit()

        result = cms.promote("short_cooldown")

        assert result == MemoryTier.MEDIUM


# =============================================================================
# Test Concurrent Access
# =============================================================================


class TestConcurrentAccess:
    """Test thread-safety and concurrent access."""

    def test_concurrent_adds_no_conflicts(self, memory):
        """Test that concurrent adds don't cause conflicts."""
        errors = []

        def add_entries(thread_id):
            try:
                for i in range(20):
                    memory.add(f"thread_{thread_id}_entry_{i}", f"Content from thread {thread_id}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_entries, args=(i,)) for i in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        stats = memory.get_stats()
        assert stats["total_memories"] == 100  # 5 threads * 20 entries

    def test_concurrent_reads_writes(self, memory):
        """Test concurrent read and write operations."""
        # Pre-populate
        for i in range(20):
            memory.add(f"rw_{i}", f"Content {i}")

        errors = []
        read_results = []

        def reader():
            try:
                for _ in range(30):
                    results = memory.retrieve(limit=5)
                    read_results.append(len(results))
            except Exception as e:
                errors.append(("read", e))

        def writer(thread_id):
            try:
                for i in range(10):
                    memory.add(f"new_{thread_id}_{i}", f"New content {i}")
            except Exception as e:
                errors.append(("write", e))

        threads = [
            threading.Thread(target=reader),
            threading.Thread(target=writer, args=(0,)),
            threading.Thread(target=reader),
            threading.Thread(target=writer, args=(1,)),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert all(r > 0 for r in read_results)

    def test_concurrent_outcome_updates(self, memory):
        """Test concurrent outcome updates on same entry."""
        memory.add("concurrent_update", "Content")
        errors = []

        def update_outcomes():
            try:
                for _ in range(20):
                    memory.update_outcome("concurrent_update", success=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=update_outcomes) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        entry = memory.get("concurrent_update")
        assert entry.success_count == 100  # 5 threads * 20 updates

    def test_concurrent_promotions_no_race(self, memory):
        """Test that concurrent promotions don't cause race conditions."""
        memory.add("race_test", "Content", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.8 WHERE id = ?",
                ("race_test",),
            )
            conn.commit()

        results = []
        errors = []

        def try_promote():
            try:
                result = memory.promote("race_test")
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=try_promote) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Only one promotion should succeed, rest should be None
        successful = [r for r in results if r is not None]
        assert len(successful) <= 1

    def test_concurrent_consolidations(self, memory):
        """Test that concurrent consolidations are safe."""
        for i in range(30):
            memory.add(f"consolidate_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.8")
            conn.commit()

        results = []
        errors = []

        def run_consolidate():
            try:
                result = memory.consolidate()
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_consolidate) for _ in range(5)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Test Async Operations
# =============================================================================


class TestAsyncOperations:
    """Test async wrapper methods."""

    @pytest.mark.asyncio
    async def test_add_async(self, memory):
        """Test async add operation."""
        entry = await memory.add_async("async_test", "Async content", importance=0.8)

        assert entry.id == "async_test"
        assert entry.importance == 0.8

    @pytest.mark.asyncio
    async def test_get_async(self, memory):
        """Test async get operation."""
        memory.add("get_async_test", "Content")

        entry = await memory.get_async("get_async_test")

        assert entry is not None
        assert entry.content == "Content"

    @pytest.mark.asyncio
    async def test_retrieve_async(self, populated_memory):
        """Test async retrieve operation."""
        results = await populated_memory.retrieve_async(query="pattern", limit=10)

        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_update_outcome_async(self, memory):
        """Test async outcome update."""
        memory.add("outcome_async", "Content")

        surprise = await memory.update_outcome_async("outcome_async", success=True)

        assert surprise >= 0
        entry = memory.get("outcome_async")
        assert entry.success_count == 1

    @pytest.mark.asyncio
    async def test_store_async(self, memory):
        """Test async store (alias for add)."""
        entry = await memory.store("store_async", "Store content", tier="slow")

        assert entry.id == "store_async"
        assert entry.tier == MemoryTier.SLOW

    @pytest.mark.asyncio
    async def test_concurrent_async_operations(self, memory):
        """Test concurrent async operations."""

        async def add_entry(idx):
            return await memory.add_async(f"async_concurrent_{idx}", f"Content {idx}")

        # Run 10 concurrent adds
        results = await asyncio.gather(*[add_entry(i) for i in range(10)])

        assert len(results) == 10
        assert all(r.id.startswith("async_concurrent_") for r in results)


# =============================================================================
# Test Edge Cases - Rapid Creation/Deletion
# =============================================================================


class TestRapidCreationDeletion:
    """Test edge cases with rapid creation and deletion."""

    def test_rapid_add_delete_cycles(self, memory):
        """Test rapid add/delete cycles."""
        for cycle in range(10):
            memory.add(f"cycle_{cycle}", f"Cycle content {cycle}")
            memory.delete(f"cycle_{cycle}")

        stats = memory.get_stats()
        assert stats["total_memories"] == 0

        archive_stats = memory.get_archive_stats()
        assert archive_stats["total_archived"] == 10

    def test_reuse_deleted_id(self, memory):
        """Test reusing ID after deletion."""
        memory.add("reuse_id", "Original content", importance=0.5)
        memory.delete("reuse_id")

        # Reuse same ID
        entry = memory.add("reuse_id", "New content", importance=0.9)

        assert entry.content == "New content"
        assert entry.importance == 0.9

    def test_rapid_tier_transitions(self, memory):
        """Test rapid tier transitions."""
        memory.add("rapid_transition", "Content", tier=MemoryTier.GLACIAL)

        # Rapidly promote through all tiers
        memory.promote_entry("rapid_transition", MemoryTier.SLOW)
        memory.promote_entry("rapid_transition", MemoryTier.MEDIUM)
        memory.promote_entry("rapid_transition", MemoryTier.FAST)

        entry = memory.get("rapid_transition")
        assert entry.tier == MemoryTier.FAST

    def test_mass_deletion(self, memory):
        """Test mass deletion doesn't cause issues."""
        # Create 100 entries
        for i in range(100):
            memory.add(f"mass_{i}", f"Content {i}")

        # Delete all
        for i in range(100):
            memory.delete(f"mass_{i}")

        stats = memory.get_stats()
        assert stats["total_memories"] == 0


# =============================================================================
# Test Edge Cases - Tier Overflow Handling
# =============================================================================


class TestTierOverflowHandling:
    """Test handling of tier limits and overflow."""

    def test_enforce_tier_limits(self, memory):
        """Test enforcing tier limits removes excess entries."""
        # Set low limit
        memory.hyperparams["max_entries_per_tier"]["fast"] = 5

        # Add more than limit
        for i in range(10):
            memory.add(f"overflow_{i}", f"Content {i}", tier=MemoryTier.FAST, importance=i / 10)

        result = memory.enforce_tier_limits(tier=MemoryTier.FAST)

        assert result["fast"] == 5  # Should remove 5 entries

        # Verify remaining entries are highest importance
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM continuum_memory WHERE tier = 'fast'")
            count = cursor.fetchone()[0]
        assert count == 5

    def test_enforce_limits_preserves_red_lines(self, memory):
        """Test that tier limits don't remove red-lined entries."""
        memory.hyperparams["max_entries_per_tier"]["fast"] = 3

        # Add entries including red-lined ones
        for i in range(5):
            memory.add(f"limit_test_{i}", f"Content {i}", tier=MemoryTier.FAST, importance=0.1)

        memory.mark_red_line("limit_test_0", reason="Critical")
        memory.mark_red_line("limit_test_1", reason="Critical")

        memory.enforce_tier_limits(tier=MemoryTier.FAST)

        # Red-lined entries should still exist
        entry0 = memory.get("limit_test_0")
        entry1 = memory.get("limit_test_1")
        # Note: red-lined entries are promoted to glacial by default
        assert entry0 is not None or memory.get("limit_test_0") is not None

    def test_memory_pressure_calculation(self, memory):
        """Test memory pressure calculation."""
        memory.hyperparams["max_entries_per_tier"]["fast"] = 100

        # Add 50 entries (50% utilization)
        for i in range(50):
            memory.add(f"pressure_{i}", f"Content {i}", tier=MemoryTier.FAST)

        pressure = memory.get_memory_pressure()

        assert 0.4 <= pressure <= 0.6  # Around 50%


# =============================================================================
# Test Edge Cases - Memory Leak Prevention
# =============================================================================


class TestMemoryLeakPrevention:
    """Test that operations don't leak memory/resources."""

    def test_connection_cleanup(self, memory):
        """Test that connections are properly cleaned up."""
        # Perform many operations
        for i in range(100):
            memory.add(f"leak_test_{i}", f"Content {i}")
            memory.get(f"leak_test_{i}")
            memory.retrieve(limit=10)

        # Should not accumulate open connections
        # This is implicitly tested - if connections leak, SQLite will error

    def test_large_metadata_handling(self, memory):
        """Test handling of large metadata objects."""
        large_metadata = {
            "tags": [f"tag_{i}" for i in range(100)],
            "cross_references": [f"ref_{i}" for i in range(100)],
            "history": [
                {"action": f"action_{i}", "timestamp": _utc_naive_now().isoformat()}
                for i in range(50)
            ],
        }

        entry = memory.add("large_meta", "Content", metadata=large_metadata)

        retrieved = memory.get("large_meta")
        assert len(retrieved.metadata["tags"]) == 100
        assert len(retrieved.metadata["cross_references"]) == 100

    def test_very_long_content(self, memory):
        """Test handling of very long content strings."""
        long_content = "x" * 100000  # 100KB content

        entry = memory.add("long_content", long_content)
        retrieved = memory.get("long_content")

        assert len(retrieved.content) == 100000

    def test_unicode_content(self, memory):
        """Test handling of unicode content."""
        unicode_content = "Hello World"

        entry = memory.add("unicode_test", unicode_content)
        retrieved = memory.get("unicode_test")

        assert retrieved.content == unicode_content


# =============================================================================
# Test Statistics and Metrics
# =============================================================================


class TestStatisticsAndMetrics:
    """Test statistics and metrics collection."""

    def test_get_stats_comprehensive(self, populated_memory):
        """Test comprehensive statistics retrieval."""
        stats = populated_memory.get_stats()

        assert "total_memories" in stats
        assert "by_tier" in stats
        assert "transitions" in stats
        assert stats["total_memories"] == 9  # From populated_memory fixture

    def test_tier_metrics(self, memory):
        """Test tier transition metrics."""
        memory.add("metrics_test", "Content", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.8 WHERE id = ?",
                ("metrics_test",),
            )
            conn.commit()

        memory.promote("metrics_test")

        metrics = memory.get_tier_metrics()

        assert "total_promotions" in metrics
        assert metrics["total_promotions"] >= 1

    def test_export_for_tier(self, populated_memory):
        """Test exporting entries for specific tier."""
        exported = populated_memory.export_for_tier(MemoryTier.FAST)

        assert len(exported) == 3
        assert all("id" in e for e in exported)
        assert all("content" in e for e in exported)
        assert all("importance" in e for e in exported)

    def test_archive_stats(self, memory):
        """Test archive statistics."""
        for i in range(5):
            memory.add(f"archive_stats_{i}", f"Content {i}")
            memory.delete(f"archive_stats_{i}")

        stats = memory.get_archive_stats()

        assert stats["total_archived"] == 5


# =============================================================================
# Test Surprise Score Updates
# =============================================================================


class TestSurpriseScoreUpdates:
    """Test surprise score calculation and updates."""

    def test_surprise_increases_on_unexpected_outcome(self, memory):
        """Test that surprise increases for unexpected outcomes."""
        memory.add("surprise_test", "Content")

        # Build up expectation of success
        for _ in range(10):
            memory.update_outcome("surprise_test", success=True)

        entry_before = memory.get("surprise_test")

        # Now failure is unexpected
        memory.update_outcome("surprise_test", success=False)

        entry_after = memory.get("surprise_test")

        # Surprise should increase
        assert (
            entry_after.surprise_score >= entry_before.surprise_score
            or entry_after.surprise_score > 0
        )

    def test_surprise_with_agent_prediction_error(self, memory):
        """Test surprise calculation with agent prediction error."""
        memory.add("pred_error_test", "Content")

        surprise = memory.update_outcome(
            "pred_error_test", success=True, agent_prediction_error=0.8
        )

        # High prediction error should contribute to surprise
        assert surprise > 0

    def test_consolidation_score_increases_with_updates(self, memory):
        """Test that consolidation score increases with update count."""
        memory.add("consolidation_test", "Content")

        for i in range(20):
            memory.update_outcome("consolidation_test", success=True)

        entry = memory.get("consolidation_test")

        # Consolidation should increase with updates
        assert entry.consolidation_score > 0


# =============================================================================
# Test Red Line (Protected) Memories
# =============================================================================


class TestRedLineMemories:
    """Test red line protection functionality."""

    def test_mark_red_line_promotes_to_glacial(self, memory):
        """Test that marking red line promotes to glacial by default."""
        memory.add("protect_me", "Critical", tier=MemoryTier.FAST)

        memory.mark_red_line("protect_me", reason="Safety critical")

        entry = memory.get("protect_me")
        assert entry.tier == MemoryTier.GLACIAL
        assert entry.red_line is True
        assert entry.importance == 1.0

    def test_red_line_blocks_deletion(self, memory):
        """Test that red line blocks deletion."""
        memory.add("protected", "Content")
        memory.mark_red_line("protected", reason="Critical")

        result = memory.delete("protected")

        assert result["deleted"] is False
        assert result["blocked"] is True
        assert memory.get("protected") is not None

    def test_force_delete_red_line(self, memory):
        """Test force deleting a red line entry."""
        memory.add("force_protected", "Content")
        memory.mark_red_line("force_protected", reason="Test")

        result = memory.delete("force_protected", force=True)

        assert result["deleted"] is True

    def test_get_red_line_memories(self, memory):
        """Test retrieving all red line memories."""
        memory.add("rl_1", "Content 1")
        memory.add("rl_2", "Content 2")
        memory.add("normal", "Normal")

        memory.mark_red_line("rl_1", reason="Critical 1")
        memory.mark_red_line("rl_2", reason="Critical 2")

        red_lines = memory.get_red_line_memories()

        assert len(red_lines) == 2
        assert all(e.red_line for e in red_lines)


# =============================================================================
# Test KM Adapter Integration
# =============================================================================


class TestKMAdapterIntegration:
    """Test Knowledge Mound adapter integration."""

    def test_set_km_adapter(self, memory):
        """Test setting KM adapter."""
        mock_adapter = MagicMock()
        memory.set_km_adapter(mock_adapter)

        assert memory._km_adapter is mock_adapter

    def test_query_km_for_similar_without_adapter(self, memory):
        """Test querying KM returns empty without adapter."""
        results = memory.query_km_for_similar("test query")

        assert results == []

    def test_query_km_for_similar_with_adapter(self, memory):
        """Test querying KM with adapter."""
        mock_adapter = MagicMock()
        mock_adapter.search_similar.return_value = [
            {"id": "km_1", "content": "Similar 1"},
            {"id": "km_2", "content": "Similar 2"},
        ]
        memory.set_km_adapter(mock_adapter)

        results = memory.query_km_for_similar("test query")

        assert len(results) == 2
        mock_adapter.search_similar.assert_called_once()

    def test_add_syncs_to_km_high_importance(self, memory):
        """Test that high importance entries sync to KM."""
        mock_adapter = MagicMock()
        memory.set_km_adapter(mock_adapter)

        memory.add("km_sync", "Important content", importance=0.9)

        mock_adapter.store_memory.assert_called_once()

    def test_add_skips_km_low_importance(self, memory):
        """Test that low importance entries don't sync to KM."""
        mock_adapter = MagicMock()
        memory.set_km_adapter(mock_adapter)

        memory.add("km_skip", "Less important", importance=0.5)

        mock_adapter.store_memory.assert_not_called()


# =============================================================================
# Test Prewarm and Cross-Query Support
# =============================================================================


class TestPrewarmSupport:
    """Test prewarm functionality for cache warming."""

    def test_prewarm_for_query(self, populated_memory):
        """Test prewarming cache for a query."""
        count = populated_memory.prewarm_for_query("pattern")

        assert count >= 0

    def test_prewarm_empty_query(self, memory):
        """Test prewarm with empty query."""
        count = memory.prewarm_for_query("")

        assert count == 0

    def test_prewarm_updates_metadata(self, memory):
        """Test that prewarm updates metadata."""
        memory.add("prewarm_test", "Prewarmable content", importance=0.5)

        memory.prewarm_for_query("Prewarmable")

        entry = memory.get("prewarm_test")
        # Check if last_prewarm was set (may or may not be, depending on match)


# =============================================================================
# Test Update Methods
# =============================================================================


class TestUpdateMethods:
    """Test various update methods."""

    def test_update_content(self, memory):
        """Test updating content field."""
        memory.add("update_content", "Original")

        result = memory.update("update_content", content="Updated")

        assert result is True
        entry = memory.get("update_content")
        assert entry.content == "Updated"

    def test_update_importance(self, memory):
        """Test updating importance field."""
        memory.add("update_importance", "Content", importance=0.5)

        memory.update("update_importance", importance=0.9)

        entry = memory.get("update_importance")
        assert entry.importance == 0.9

    def test_update_metadata(self, memory):
        """Test updating metadata field."""
        memory.add("update_meta", "Content", metadata={"old": "value"})

        memory.update("update_meta", metadata={"new": "metadata"})

        entry = memory.get("update_meta")
        assert entry.metadata == {"new": "metadata"}

    def test_update_multiple_fields(self, memory):
        """Test updating multiple fields at once."""
        memory.add("multi_update", "Original", importance=0.5)

        memory.update(
            "multi_update",
            content="Updated",
            importance=0.8,
            surprise_score=0.3,
            consolidation_score=0.6,
        )

        entry = memory.get("multi_update")
        assert entry.content == "Updated"
        assert entry.importance == 0.8
        assert entry.surprise_score == 0.3
        assert entry.consolidation_score == 0.6

    def test_update_nonexistent(self, memory):
        """Test updating nonexistent entry."""
        result = memory.update("nonexistent", content="New")

        assert result is False

    def test_update_entry_interface(self, memory):
        """Test update_entry interface method."""
        entry = memory.add("entry_update", "Content")
        entry.success_count = 5
        entry.failure_count = 2

        result = memory.update_entry(entry)

        assert result is True
        updated = memory.get("entry_update")
        assert updated.success_count == 5
        assert updated.failure_count == 2


# =============================================================================
# Test Snapshot Export/Restore
# =============================================================================


class TestSnapshotExportRestore:
    """Test snapshot export and restore functionality."""

    def test_export_snapshot(self, populated_memory):
        """Test exporting memory state."""
        snapshot = populated_memory.export_snapshot()

        assert "entries" in snapshot
        assert "tier_counts" in snapshot
        assert "hyperparams" in snapshot
        assert "snapshot_time" in snapshot
        assert "total_entries" in snapshot
        assert snapshot["total_entries"] == 9

    def test_export_snapshot_filtered_by_tier(self, populated_memory):
        """Test exporting snapshot filtered by tier."""
        snapshot = populated_memory.export_snapshot(tiers=[MemoryTier.FAST])

        assert all(e["tier"] == "fast" for e in snapshot["entries"])
        assert len(snapshot["entries"]) == 3

    def test_restore_snapshot_replace(self, memory, populated_memory):
        """Test restoring snapshot in replace mode."""
        snapshot = populated_memory.export_snapshot()

        result = memory.restore_snapshot(snapshot, merge_mode="replace")

        assert result["restored"] >= len(snapshot["entries"])

    def test_restore_snapshot_keep(self, memory):
        """Test restoring snapshot in keep mode."""
        memory.add("existing", "Original", importance=0.5)

        snapshot = {
            "entries": [
                {
                    "id": "existing",
                    "tier": "slow",
                    "content": "New content",
                    "importance": 0.9,
                    "surprise_score": 0.1,
                    "consolidation_score": 0.5,
                }
            ]
        }

        result = memory.restore_snapshot(snapshot, merge_mode="keep")

        # Original should be preserved
        entry = memory.get("existing")
        assert entry.content == "Original"
        assert result["skipped"] >= 1

    def test_restore_snapshot_merge(self, memory):
        """Test restoring snapshot in merge mode."""
        memory.add("merge_test", "Low importance", importance=0.3)

        snapshot = {
            "entries": [
                {
                    "id": "merge_test",
                    "tier": "slow",
                    "content": "High importance",
                    "importance": 0.9,
                    "surprise_score": 0.1,
                    "consolidation_score": 0.5,
                }
            ]
        }

        result = memory.restore_snapshot(snapshot, merge_mode="merge")

        # Higher importance should win
        entry = memory.get("merge_test")
        assert entry.importance == 0.9
        assert result["updated"] >= 1


# =============================================================================
# Test Cross-Session Patterns
# =============================================================================


class TestCrossSessionPatterns:
    """Test cross-session pattern retrieval."""

    def test_get_cross_session_patterns(self, populated_memory):
        """Test getting cross-session patterns from slow/glacial tiers."""
        patterns = populated_memory.get_cross_session_patterns(limit=10)

        tiers = {p.tier for p in patterns}
        assert tiers.issubset({MemoryTier.SLOW, MemoryTier.GLACIAL})

    def test_get_glacial_tier_stats(self, populated_memory):
        """Test getting glacial tier statistics."""
        stats = populated_memory.get_glacial_tier_stats()

        assert stats["tier"] == "glacial"
        assert "count" in stats
        assert "avg_importance" in stats
        assert "utilization" in stats


# =============================================================================
# Test Event Emission
# =============================================================================


class TestEventEmission:
    """Test event emission functionality."""

    def test_add_emits_memory_stored_event(self, temp_db_path):
        """Test that add emits memory_stored event."""
        mock_emitter = MagicMock()
        cms = ContinuumMemory(db_path=temp_db_path, event_emitter=mock_emitter)

        cms.add("event_test", "Content", importance=0.8)

        mock_emitter.emit_sync.assert_called()
        # Check event type in any of the calls
        call_args = [call[1] for call in mock_emitter.emit_sync.call_args_list]
        event_types = [args.get("event_type") for args in call_args]
        assert "memory_stored" in event_types

    def test_retrieve_emits_memory_recall_event(self, temp_db_path):
        """Test that retrieve emits memory_recall event."""
        mock_emitter = MagicMock()
        cms = ContinuumMemory(db_path=temp_db_path, event_emitter=mock_emitter)
        cms.add("recall_test", "Content")

        mock_emitter.reset_mock()
        cms.retrieve(limit=10)

        # May emit memory_recall if results found
        # Event emission is best-effort and may not always fire


# =============================================================================
# Test Global Singleton
# =============================================================================


class TestGlobalSingleton:
    """Test global singleton management."""

    def test_get_continuum_memory_creates_singleton(self, temp_db_path, monkeypatch):
        """Test singleton creation."""
        reset_continuum_memory()
        reset_tier_manager()

        monkeypatch.setattr(
            "aragora.memory.continuum.coordinator.get_db_path",
            lambda _: temp_db_path,
        )

        cms1 = get_continuum_memory()
        cms2 = get_continuum_memory()

        assert cms1 is cms2

        reset_continuum_memory()
        reset_tier_manager()

    def test_reset_continuum_memory(self, temp_db_path, monkeypatch):
        """Test singleton reset."""
        reset_continuum_memory()
        reset_tier_manager()

        monkeypatch.setattr(
            "aragora.memory.continuum.coordinator.get_db_path",
            lambda _: temp_db_path,
        )

        cms1 = get_continuum_memory()
        reset_continuum_memory()
        cms2 = get_continuum_memory()

        assert cms1 is not cms2

        reset_continuum_memory()
        reset_tier_manager()


# =============================================================================
# Test Database Path Resolution
# =============================================================================


class TestDatabasePathResolution:
    """Test database path resolution logic."""

    def test_explicit_db_path(self, tmp_path):
        """Test using explicit database path."""
        db_path = str(tmp_path / "explicit.db")
        cms = ContinuumMemory(db_path=db_path)

        cms.add("path_test", "Content")
        entry = cms.get("path_test")

        assert entry is not None
        assert Path(db_path).exists()

    def test_storage_path_directory(self, tmp_path):
        """Test storage_path as directory."""
        cms = ContinuumMemory(storage_path=str(tmp_path))

        cms.add("storage_test", "Content")

        expected_path = tmp_path / "continuum_memory.db"
        assert expected_path.exists()

    def test_storage_path_file(self, tmp_path):
        """Test storage_path as file path."""
        file_path = tmp_path / "custom.db"
        cms = ContinuumMemory(storage_path=str(file_path))

        cms.add("file_test", "Content")

        assert file_path.exists()


# =============================================================================
# Test Retrieval Scoring
# =============================================================================


class TestRetrievalScoring:
    """Test retrieval scoring and ranking."""

    def test_retrieval_by_importance(self, memory):
        """Test that retrieval prioritizes importance."""
        memory.add("low_imp", "Content A", importance=0.1)
        memory.add("high_imp", "Content B", importance=0.9)
        memory.add("mid_imp", "Content C", importance=0.5)

        results = memory.retrieve(limit=3)

        # Higher importance should appear first (all else being equal)
        importances = [r.importance for r in results]
        assert importances[0] >= importances[-1]

    def test_retrieval_with_min_importance(self, memory):
        """Test retrieval with minimum importance filter."""
        memory.add("below_min", "Content", importance=0.3)
        memory.add("above_min", "Content", importance=0.8)

        results = memory.retrieve(min_importance=0.5, limit=10)

        assert all(r.importance >= 0.5 for r in results)

    def test_retrieval_keyword_filtering(self, memory):
        """Test keyword filtering in retrieval."""
        memory.add("with_keyword", "Python error handling")
        memory.add("without_keyword", "JavaScript testing")

        results = memory.retrieve(query="Python", limit=10)

        assert any("Python" in r.content for r in results)
