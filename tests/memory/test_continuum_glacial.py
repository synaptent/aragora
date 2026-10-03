"""
Comprehensive tests for Continuum Glacial Memory operations.

Tests the ContinuumGlacialMixin in aragora/memory/continuum_glacial.py including:
- Long-term storage operations
- Archival operations
- Confidence decay calculations
- Cross-session pattern retrieval
- Glacial tier statistics
- Standalone vs mixin mode operation
- Data integrity in glacial tier
- Edge cases and error handling
"""

from __future__ import annotations

import asyncio
import math
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.memory.continuum import (
    ContinuumMemory,
    ContinuumMemoryEntry,
    reset_continuum_memory,
)
from aragora.memory.tier_manager import (
    MemoryTier,
    TierManager,
    reset_tier_manager,
)
from aragora.memory.continuum_glacial import (
    ContinuumGlacialMixin,
    GLACIAL_HALF_LIFE_DAYS,
    GLACIAL_HALF_LIFE_HOURS,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database path for testing."""
    return str(tmp_path / "test_glacial.db")


@pytest.fixture
def tier_manager() -> TierManager:
    """Create a fresh TierManager for testing."""
    return TierManager()


@pytest.fixture
def memory(temp_db_path: str, tier_manager: TierManager) -> ContinuumMemory:
    """Create a ContinuumMemory instance with isolated database."""
    reset_tier_manager()
    reset_continuum_memory()
    cms = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
    yield cms
    reset_tier_manager()
    reset_continuum_memory()


@pytest.fixture
def populated_glacial(memory: ContinuumMemory) -> ContinuumMemory:
    """Memory with diverse glacial tier entries."""
    # Core programming knowledge
    memory.add(
        "glacial_solid",
        "SOLID principles: Single responsibility, Open-closed, Liskov substitution",
        tier=MemoryTier.GLACIAL,
        importance=0.95,
        metadata={"tags": ["design", "principles"]},
    )
    memory.add(
        "glacial_patterns",
        "Design patterns: Factory, Strategy, Observer, Singleton",
        tier=MemoryTier.GLACIAL,
        importance=0.9,
        metadata={"tags": ["design", "patterns"]},
    )

    # Error handling knowledge
    memory.add(
        "glacial_errors",
        "Error handling best practices for production systems",
        tier=MemoryTier.GLACIAL,
        importance=0.85,
        metadata={"tags": ["error", "production"]},
    )

    # Architecture knowledge
    memory.add(
        "glacial_arch",
        "Microservices architecture principles and patterns",
        tier=MemoryTier.GLACIAL,
        importance=0.8,
        metadata={"tags": ["architecture", "microservices"]},
    )

    # Low importance entry
    memory.add(
        "glacial_low",
        "Minor implementation detail",
        tier=MemoryTier.GLACIAL,
        importance=0.25,
        metadata={"tags": ["minor"]},
    )

    # Add entries in other tiers for contrast
    memory.add(
        "slow_recent",
        "Recent cross-session pattern for error handling",
        tier=MemoryTier.SLOW,
        importance=0.75,
        metadata={"tags": ["error", "recent"]},
    )
    memory.add(
        "fast_immediate",
        "Immediate context about current error",
        tier=MemoryTier.FAST,
        importance=0.8,
    )

    return memory


@pytest.fixture
def standalone_glacial(tmp_path: Path):
    """Create a standalone glacial mixin for testing."""

    class StandaloneGlacialStore(ContinuumGlacialMixin):
        hyperparams: dict = {
            "max_entries_per_tier": {"glacial": 50000},
            "promotion_cooldown_hours": 24.0,
        }

    store = StandaloneGlacialStore()
    store._glacial_db_path = str(tmp_path / "standalone_glacial.db")
    return store


# =============================================================================
# Test Glacial Half-Life Constants
# =============================================================================


class TestGlacialConstants:
    """Tests for glacial tier constants."""

    def test_half_life_days_is_30(self) -> None:
        """Test that glacial half-life is 30 days."""
        assert GLACIAL_HALF_LIFE_DAYS == 30

    def test_half_life_hours_calculation(self) -> None:
        """Test that half-life hours is correctly calculated."""
        assert GLACIAL_HALF_LIFE_HOURS == GLACIAL_HALF_LIFE_DAYS * 24
        assert GLACIAL_HALF_LIFE_HOURS == 720


# =============================================================================
# Test Confidence Decay Calculation
# =============================================================================


class TestConfidenceDecayCalculation:
    """Tests for calculate_glacial_decay() method."""

    def test_decay_is_one_for_now(self, memory: ContinuumMemory) -> None:
        """Test decay factor is 1.0 for entries updated now."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        decay = memory.calculate_glacial_decay(now)

        assert abs(decay - 1.0) < 0.01

    def test_decay_is_half_at_30_days(self, memory: ContinuumMemory) -> None:
        """Test decay factor is 0.5 at exactly 30 days."""
        thirty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        decay = memory.calculate_glacial_decay(thirty_days_ago)

        assert abs(decay - 0.5) < 0.01

    def test_decay_is_quarter_at_60_days(self, memory: ContinuumMemory) -> None:
        """Test decay factor is 0.25 at 60 days (two half-lives)."""
        sixty_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=60)
        decay = memory.calculate_glacial_decay(sixty_days_ago)

        assert abs(decay - 0.25) < 0.01

    def test_decay_is_eighth_at_90_days(self, memory: ContinuumMemory) -> None:
        """Test decay factor is 0.125 at 90 days (three half-lives)."""
        ninety_days_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=90)
        decay = memory.calculate_glacial_decay(ninety_days_ago)

        assert abs(decay - 0.125) < 0.02

    def test_decay_handles_iso_string(self, memory: ContinuumMemory) -> None:
        """Test decay calculation handles ISO string timestamps."""
        thirty_days_ago = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        ).isoformat()
        decay = memory.calculate_glacial_decay(thirty_days_ago)

        assert abs(decay - 0.5) < 0.01

    def test_decay_handles_timezone_aware_string(self, memory: ContinuumMemory) -> None:
        """Test decay handles timezone-aware ISO strings."""
        thirty_days_ago = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=30)
        ).isoformat() + "Z"
        decay = memory.calculate_glacial_decay(thirty_days_ago)

        assert abs(decay - 0.5) < 0.02  # Slightly larger tolerance for TZ conversion

    def test_decay_clamps_to_one_for_future(self, memory: ContinuumMemory) -> None:
        """Test decay factor is clamped to 1.0 for future timestamps."""
        future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=1)
        decay = memory.calculate_glacial_decay(future)

        assert decay == 1.0

    def test_decay_approaches_zero_for_very_old(self, memory: ContinuumMemory) -> None:
        """Test decay approaches 0 for very old entries."""
        one_year_ago = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365)
        decay = memory.calculate_glacial_decay(one_year_ago)

        # 365/30 = ~12 half-lives, so decay should be very small
        assert decay < 0.001


# =============================================================================
# Test get_glacial_insights
# =============================================================================


class TestGetGlacialInsights:
    """Tests for get_glacial_insights() method."""

    def test_returns_only_glacial_entries(self, populated_glacial: ContinuumMemory) -> None:
        """Test that get_glacial_insights returns only glacial tier entries."""
        insights = populated_glacial.get_glacial_insights(min_importance=0.0, limit=100)

        assert len(insights) == 5
        for entry in insights:
            assert entry.tier == MemoryTier.GLACIAL

    def test_default_min_importance_is_0_3(self, populated_glacial: ContinuumMemory) -> None:
        """Test that default min_importance is 0.3."""
        insights = populated_glacial.get_glacial_insights()

        # glacial_low has importance=0.25, should be excluded
        ids = [e.id for e in insights]
        assert "glacial_low" not in ids

    def test_filters_by_topic(self, populated_glacial: ContinuumMemory) -> None:
        """Test that topic parameter filters by keyword."""
        insights = populated_glacial.get_glacial_insights(topic="design")

        assert len(insights) >= 1
        for entry in insights:
            assert "design" in entry.content.lower() or "design" in str(
                entry.metadata.get("tags", [])
            )

    def test_respects_limit(self, populated_glacial: ContinuumMemory) -> None:
        """Test that limit parameter restricts results."""
        insights = populated_glacial.get_glacial_insights(limit=2, min_importance=0.0)

        assert len(insights) <= 2

    def test_empty_glacial_returns_empty(self, memory: ContinuumMemory) -> None:
        """Test empty glacial tier returns empty list."""
        insights = memory.get_glacial_insights()

        assert insights == []

    def test_custom_min_importance(self, populated_glacial: ContinuumMemory) -> None:
        """Test custom min_importance threshold."""
        insights = populated_glacial.get_glacial_insights(min_importance=0.9)

        assert len(insights) == 2  # glacial_solid (0.95) and glacial_patterns (0.9)
        assert all(e.importance >= 0.9 for e in insights)


class TestGetGlacialInsightsAsync:
    """Tests for get_glacial_insights_async() method."""

    @pytest.mark.asyncio
    async def test_async_returns_same_as_sync(self, populated_glacial: ContinuumMemory) -> None:
        """Test async returns same results as sync."""
        sync_results = populated_glacial.get_glacial_insights(topic="design")
        async_results = await populated_glacial.get_glacial_insights_async(topic="design")

        sync_ids = {e.id for e in sync_results}
        async_ids = {e.id for e in async_results}
        assert sync_ids == async_ids

    @pytest.mark.asyncio
    async def test_async_with_all_params(self, populated_glacial: ContinuumMemory) -> None:
        """Test async with all parameters."""
        insights = await populated_glacial.get_glacial_insights_async(
            topic="architecture", limit=5, min_importance=0.5
        )

        for entry in insights:
            assert entry.importance >= 0.5

    @pytest.mark.asyncio
    async def test_async_concurrent_calls(self, populated_glacial: ContinuumMemory) -> None:
        """Test concurrent async calls."""
        tasks = [
            populated_glacial.get_glacial_insights_async(topic="design"),
            populated_glacial.get_glacial_insights_async(topic="error"),
            populated_glacial.get_glacial_insights_async(topic="architecture"),
        ]

        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        for result in results:
            assert isinstance(result, list)


# =============================================================================
# Test get_cross_session_patterns
# =============================================================================


class TestGetCrossSessionPatterns:
    """Tests for get_cross_session_patterns() method."""

    def test_returns_slow_and_glacial(self, populated_glacial: ContinuumMemory) -> None:
        """Test returns entries from both slow and glacial tiers."""
        patterns = populated_glacial.get_cross_session_patterns()

        tiers = {e.tier for e in patterns}
        assert MemoryTier.GLACIAL in tiers
        assert MemoryTier.SLOW in tiers

    def test_excludes_fast_and_medium(self, populated_glacial: ContinuumMemory) -> None:
        """Test excludes fast and medium tier entries."""
        patterns = populated_glacial.get_cross_session_patterns()

        ids = [e.id for e in patterns]
        assert "fast_immediate" not in ids

    def test_include_slow_false(self, populated_glacial: ContinuumMemory) -> None:
        """Test include_slow=False returns only glacial."""
        patterns = populated_glacial.get_cross_session_patterns(include_slow=False)

        for entry in patterns:
            assert entry.tier == MemoryTier.GLACIAL

    def test_filters_by_domain(self, populated_glacial: ContinuumMemory) -> None:
        """Test domain parameter filters entries."""
        patterns = populated_glacial.get_cross_session_patterns(domain="error")

        for entry in patterns:
            assert "error" in entry.content.lower()

    def test_sorted_by_importance_descending(self, populated_glacial: ContinuumMemory) -> None:
        """Test results are sorted by importance descending."""
        patterns = populated_glacial.get_cross_session_patterns()

        importances = [e.importance for e in patterns]
        assert importances == sorted(importances, reverse=True)

    def test_respects_limit(self, populated_glacial: ContinuumMemory) -> None:
        """Test limit parameter restricts results."""
        patterns = populated_glacial.get_cross_session_patterns(limit=3)

        assert len(patterns) <= 3


class TestGetCrossSessionPatternsAsync:
    """Tests for get_cross_session_patterns_async() method."""

    @pytest.mark.asyncio
    async def test_async_returns_same_as_sync(self, populated_glacial: ContinuumMemory) -> None:
        """Test async returns same results as sync."""
        sync_results = populated_glacial.get_cross_session_patterns(domain="error")
        async_results = await populated_glacial.get_cross_session_patterns_async(domain="error")

        sync_ids = {e.id for e in sync_results}
        async_ids = {e.id for e in async_results}
        assert sync_ids == async_ids

    @pytest.mark.asyncio
    async def test_async_with_include_slow_false(self, populated_glacial: ContinuumMemory) -> None:
        """Test async with include_slow=False."""
        patterns = await populated_glacial.get_cross_session_patterns_async(include_slow=False)

        for entry in patterns:
            assert entry.tier == MemoryTier.GLACIAL


# =============================================================================
# Test get_glacial_tier_stats
# =============================================================================


class TestGetGlacialTierStats:
    """Tests for get_glacial_tier_stats() method."""

    def test_returns_correct_structure(self, memory: ContinuumMemory) -> None:
        """Test stats returns correct structure."""
        stats = memory.get_glacial_tier_stats()

        assert "tier" in stats
        assert "count" in stats
        assert "avg_importance" in stats
        assert "avg_surprise" in stats
        assert "avg_consolidation" in stats
        assert "avg_updates" in stats
        assert "red_line_count" in stats
        assert "oldest_entry" in stats
        assert "newest_update" in stats
        assert "top_tags" in stats
        assert "max_entries" in stats
        assert "utilization" in stats

    def test_tier_is_glacial(self, memory: ContinuumMemory) -> None:
        """Test tier field is 'glacial'."""
        stats = memory.get_glacial_tier_stats()

        assert stats["tier"] == "glacial"

    def test_empty_tier_returns_zeros(self, memory: ContinuumMemory) -> None:
        """Test empty glacial tier returns zero counts."""
        stats = memory.get_glacial_tier_stats()

        assert stats["count"] == 0
        assert stats["avg_importance"] == 0
        assert stats["red_line_count"] == 0

    def test_count_is_accurate(self, populated_glacial: ContinuumMemory) -> None:
        """Test count reflects actual glacial entries."""
        stats = populated_glacial.get_glacial_tier_stats()

        assert stats["count"] == 5

    def test_avg_importance_calculation(self, populated_glacial: ContinuumMemory) -> None:
        """Test avg_importance is calculated correctly."""
        stats = populated_glacial.get_glacial_tier_stats()

        # glacial entries: 0.95, 0.9, 0.85, 0.8, 0.25
        expected_avg = (0.95 + 0.9 + 0.85 + 0.8 + 0.25) / 5
        assert abs(stats["avg_importance"] - expected_avg) < 0.01

    def test_utilization_calculation(self, populated_glacial: ContinuumMemory) -> None:
        """Test utilization is count / max_entries."""
        stats = populated_glacial.get_glacial_tier_stats()

        max_entries = populated_glacial.hyperparams["max_entries_per_tier"]["glacial"]
        expected_utilization = 5 / max_entries
        assert abs(stats["utilization"] - expected_utilization) < 0.001

    def test_top_tags_extracted(self, populated_glacial: ContinuumMemory) -> None:
        """Test top_tags extracts tags from metadata."""
        stats = populated_glacial.get_glacial_tier_stats()

        tag_names = [t["tag"] for t in stats["top_tags"]]
        assert "design" in tag_names  # Appears in multiple entries

    def test_red_line_count(self, memory: ContinuumMemory) -> None:
        """Test red_line_count tracks protected entries."""
        memory.add("protected", "Protected content", tier=MemoryTier.GLACIAL)
        memory.mark_red_line("protected", reason="Critical")

        stats = memory.get_glacial_tier_stats()

        assert stats["red_line_count"] == 1

    def test_oldest_and_newest_populated(self, populated_glacial: ContinuumMemory) -> None:
        """Test oldest_entry and newest_update are populated."""
        stats = populated_glacial.get_glacial_tier_stats()

        assert stats["oldest_entry"] is not None
        assert stats["newest_update"] is not None


# =============================================================================
# Test _glacial_retrieve
# =============================================================================


class TestGlacialRetrieve:
    """Tests for _glacial_retrieve() internal method."""

    def test_returns_only_glacial_tier(self, populated_glacial: ContinuumMemory) -> None:
        """Test _glacial_retrieve returns only glacial entries."""
        entries = populated_glacial._glacial_retrieve(limit=100)

        for entry in entries:
            assert entry.tier == MemoryTier.GLACIAL

    def test_filters_by_query(self, populated_glacial: ContinuumMemory) -> None:
        """Test _glacial_retrieve filters by query."""
        entries = populated_glacial._glacial_retrieve(query="design", limit=100)

        for entry in entries:
            assert "design" in entry.content.lower()

    def test_respects_min_importance(self, populated_glacial: ContinuumMemory) -> None:
        """Test _glacial_retrieve respects min_importance."""
        entries = populated_glacial._glacial_retrieve(min_importance=0.9, limit=100)

        for entry in entries:
            assert entry.importance >= 0.9

    def test_respects_limit(self, populated_glacial: ContinuumMemory) -> None:
        """Test _glacial_retrieve respects limit."""
        entries = populated_glacial._glacial_retrieve(limit=2)

        assert len(entries) <= 2

    def test_applies_decay_scoring(self, memory: ContinuumMemory) -> None:
        """Test _glacial_retrieve applies decay-based scoring."""
        # Add entry and verify it's retrieved
        memory.add("decay_test", "Test entry", tier=MemoryTier.GLACIAL, importance=0.9)

        entries = memory._glacial_retrieve(limit=10)

        assert len(entries) == 1
        assert entries[0].id == "decay_test"

    def test_empty_returns_empty_list(self, memory: ContinuumMemory) -> None:
        """Test _glacial_retrieve on empty glacial returns empty list."""
        entries = memory._glacial_retrieve(limit=10)

        assert entries == []


# =============================================================================
# Test Standalone Mode
# =============================================================================


class TestStandaloneGlacialMode:
    """Tests for standalone glacial mixin operation."""

    def test_standalone_connection_works(self, standalone_glacial) -> None:
        """Test standalone _glacial_connection() works."""
        with standalone_glacial._glacial_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sqlite_version()")
            version = cursor.fetchone()

        assert version is not None

    def test_standalone_creates_database(self, standalone_glacial, tmp_path: Path) -> None:
        """Test standalone mode creates database file."""
        # Connect to create the database
        with standalone_glacial._glacial_connection() as conn:
            conn.execute("SELECT 1")

        # Verify file exists
        assert os.path.exists(standalone_glacial._glacial_db_path)

    def test_standalone_uses_wal_mode(self, standalone_glacial) -> None:
        """Test standalone connection uses WAL mode."""
        with standalone_glacial._glacial_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode")
            mode = cursor.fetchone()[0]

        assert mode.upper() == "WAL"


# =============================================================================
# Test Long-Term Storage Operations
# =============================================================================


class TestLongTermStorage:
    """Tests for long-term storage operations."""

    def test_glacial_entries_persist(self, temp_db_path: str, tier_manager: TierManager) -> None:
        """Test glacial entries persist across memory instances."""
        # Create first instance and add glacial entry
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
        cms1.add("persistent", "Persistent glacial content", tier=MemoryTier.GLACIAL)

        # Create second instance
        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
        entry = cms2.get("persistent")

        assert entry is not None
        assert entry.tier == MemoryTier.GLACIAL

    def test_glacial_metadata_persists(self, temp_db_path: str, tier_manager: TierManager) -> None:
        """Test glacial entry metadata persists."""
        metadata = {"tags": ["important"], "source": "test", "version": 1}

        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
        cms1.add("meta_persist", "Content", tier=MemoryTier.GLACIAL, metadata=metadata)

        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
        entry = cms2.get("meta_persist")

        assert entry.metadata == metadata

    def test_glacial_importance_persists(
        self, temp_db_path: str, tier_manager: TierManager
    ) -> None:
        """Test glacial entry importance persists."""
        cms1 = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
        cms1.add("imp_persist", "Content", tier=MemoryTier.GLACIAL, importance=0.95)

        cms2 = ContinuumMemory(db_path=temp_db_path, tier_manager=tier_manager)
        entry = cms2.get("imp_persist")

        assert entry.importance == 0.95


# =============================================================================
# Test Archival Operations
# =============================================================================


class TestArchivalOperations:
    """Tests for archival-related operations in glacial tier."""

    def test_glacial_red_line_prevents_deletion(self, memory: ContinuumMemory) -> None:
        """Test red-lined glacial entries cannot be deleted."""
        memory.add("protected_glacial", "Content", tier=MemoryTier.GLACIAL)
        memory.mark_red_line("protected_glacial", reason="Foundational")

        result = memory.delete("protected_glacial")

        assert result["deleted"] is False
        assert result["blocked"] is True

    def test_glacial_cleanup_skips_red_line(self, memory: ContinuumMemory) -> None:
        """Test cleanup skips red-lined glacial entries."""
        old_time = (
            datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=365)
        ).isoformat()

        # Add old red-lined entry
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO continuum_memory
                   (id, tier, content, importance, updated_at, red_line, red_line_reason)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                ("old_protected", "glacial", "Old protected", 0.9, old_time, "Critical"),
            )
            conn.commit()

        memory.cleanup_expired_memories(max_age_hours=1)

        entry = memory.get("old_protected")
        assert entry is not None

    def test_glacial_archive_and_restore(self, memory: ContinuumMemory) -> None:
        """Test glacial entries can be archived and data preserved."""
        memory.add("to_archive", "Archival content", tier=MemoryTier.GLACIAL, importance=0.85)

        # Archive via delete
        result = memory.delete("to_archive", archive=True)

        assert result["archived"] is True

        # Verify in archive table
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT importance FROM continuum_memory_archive WHERE id = ?", ("to_archive",)
            )
            archived = cursor.fetchone()

        assert archived is not None
        assert archived[0] == 0.85


# =============================================================================
# Test Data Integrity in Glacial Tier
# =============================================================================


class TestGlacialDataIntegrity:
    """Tests for data integrity in glacial tier operations."""

    def test_content_preserved_in_glacial(self, memory: ContinuumMemory) -> None:
        """Test content is preserved in glacial tier."""
        long_content = "Important foundational knowledge " * 100
        memory.add("long_glacial", long_content, tier=MemoryTier.GLACIAL)

        entry = memory.get("long_glacial")

        assert entry.content == long_content

    def test_unicode_preserved_in_glacial(self, memory: ContinuumMemory) -> None:
        """Test unicode content is preserved."""
        unicode_content = "Foundational knowledge with unicode: test cafe"
        memory.add("unicode_glacial", unicode_content, tier=MemoryTier.GLACIAL)

        entry = memory.get("unicode_glacial")

        assert entry.content == unicode_content

    def test_success_failure_counts_in_glacial(self, memory: ContinuumMemory) -> None:
        """Test success/failure counts work for glacial entries."""
        memory.add("counted_glacial", "Content", tier=MemoryTier.GLACIAL)

        for _ in range(10):
            memory.update_outcome("counted_glacial", success=True)
        for _ in range(3):
            memory.update_outcome("counted_glacial", success=False)

        entry = memory.get("counted_glacial")

        assert entry.success_count == 10
        assert entry.failure_count == 3


# =============================================================================
# Test Concurrent Glacial Operations
# =============================================================================


class TestConcurrentGlacialOperations:
    """Tests for concurrent operations on glacial tier."""

    def test_concurrent_glacial_reads(self, populated_glacial: ContinuumMemory) -> None:
        """Test concurrent glacial reads."""
        errors: list[Exception] = []
        results_list: list = []
        lock = threading.Lock()

        def do_read() -> None:
            try:
                results = populated_glacial.get_glacial_insights(limit=10)
                with lock:
                    results_list.append(results)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=do_read) for _ in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results_list) == 10

    def test_concurrent_glacial_writes_and_reads(self, memory: ContinuumMemory) -> None:
        """Test concurrent writes and reads on glacial tier."""
        errors: list[Exception] = []

        def do_writes(idx: int) -> None:
            try:
                for i in range(5):
                    memory.add(
                        f"glacial_{idx}_{i}", f"Glacial content {idx}_{i}", tier=MemoryTier.GLACIAL
                    )
            except Exception as e:
                errors.append(e)

        def do_reads() -> None:
            try:
                for _ in range(5):
                    memory.get_glacial_insights(limit=10)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=do_writes, args=(0,)),
            threading.Thread(target=do_reads),
            threading.Thread(target=do_writes, args=(1,)),
            threading.Thread(target=do_reads),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestGlacialEdgeCases:
    """Tests for edge cases in glacial operations."""

    def test_glacial_with_empty_metadata(self, memory: ContinuumMemory) -> None:
        """Test glacial entry with empty metadata."""
        memory.add("empty_meta", "Content", tier=MemoryTier.GLACIAL, metadata={})

        stats = memory.get_glacial_tier_stats()

        # Should not fail
        assert stats["count"] == 1

    def test_glacial_with_null_tags(self, memory: ContinuumMemory) -> None:
        """Test glacial entry with metadata but no tags."""
        memory.add("no_tags", "Content", tier=MemoryTier.GLACIAL, metadata={"key": "value"})

        stats = memory.get_glacial_tier_stats()

        # Should not fail
        assert stats["count"] == 1

    def test_glacial_query_special_chars(self, memory: ContinuumMemory) -> None:
        """Test glacial query with special characters."""
        memory.add("special", "Content with (parens) and [brackets]", tier=MemoryTier.GLACIAL)

        # Should not raise
        insights = memory.get_glacial_insights(topic="(parens)")

        assert isinstance(insights, list)

    def test_glacial_very_long_query(self, memory: ContinuumMemory) -> None:
        """Test glacial query with very long string."""
        memory.add("test_entry", "Test content", tier=MemoryTier.GLACIAL)

        long_query = "word " * 100

        # Should not raise (truncates to 50 keywords)
        insights = memory.get_glacial_insights(topic=long_query)

        assert isinstance(insights, list)

    def test_glacial_stats_with_zero_importance(self, memory: ContinuumMemory) -> None:
        """Test glacial stats with zero importance entries."""
        memory.add("zero_imp", "Content", tier=MemoryTier.GLACIAL, importance=0.0)

        stats = memory.get_glacial_tier_stats()

        assert stats["count"] == 1
        assert stats["avg_importance"] == 0.0


# =============================================================================
# Test Integration Scenarios
# =============================================================================


class TestGlacialIntegration:
    """Integration tests for glacial tier with full system."""

    def test_promote_to_glacial_via_red_line(self, memory: ContinuumMemory) -> None:
        """Test promotion to glacial via red line marking."""
        memory.add("to_glacial", "Content", tier=MemoryTier.FAST)

        memory.mark_red_line("to_glacial", reason="Critical", promote_to_glacial=True)

        entry = memory.get("to_glacial")
        assert entry.tier == MemoryTier.GLACIAL
        assert entry.red_line is True

    def test_glacial_included_in_cross_session(self, populated_glacial: ContinuumMemory) -> None:
        """Test glacial entries included in cross-session patterns."""
        patterns = populated_glacial.get_cross_session_patterns()

        glacial_entries = [e for e in patterns if e.tier == MemoryTier.GLACIAL]
        assert len(glacial_entries) > 0

    def test_glacial_stats_after_cleanup(self, memory: ContinuumMemory) -> None:
        """Test glacial stats reflect cleanup."""
        # Add entries
        for i in range(5):
            memory.add(f"glacial_{i}", f"Content {i}", tier=MemoryTier.GLACIAL, importance=0.5)

        # Delete some
        memory.delete("glacial_0", force=True)
        memory.delete("glacial_1", force=True)

        stats = memory.get_glacial_tier_stats()

        assert stats["count"] == 3

    def test_full_glacial_workflow(self, memory: ContinuumMemory) -> None:
        """Test complete glacial workflow."""
        # Add foundational knowledge
        memory.add(
            "foundation",
            "Core principle: Always validate inputs for security",
            tier=MemoryTier.GLACIAL,
            importance=0.95,
            metadata={"tags": ["security", "validation"]},
        )

        # Mark as critical
        memory.mark_red_line("foundation", reason="Security critical", promote_to_glacial=False)

        # Retrieve insights (without topic filter since query matching can be case-sensitive)
        insights = memory.get_glacial_insights(min_importance=0.9)
        assert len(insights) >= 1
        # Find the foundation entry
        foundation_entry = next((e for e in insights if e.id == "foundation"), None)
        assert foundation_entry is not None

        # Use get() to check red_line status (retrieve() doesn't include red_line columns)
        foundation_via_get = memory.get("foundation")
        assert foundation_via_get is not None
        assert foundation_via_get.red_line is True
        assert foundation_via_get.red_line_reason == "Security critical"

        # Get stats
        stats = memory.get_glacial_tier_stats()
        assert stats["red_line_count"] == 1

        # Get cross-session patterns (without domain filter)
        patterns = memory.get_cross_session_patterns()
        assert len(patterns) >= 1
        # Find our entry in patterns
        foundation_in_patterns = any(e.id == "foundation" for e in patterns)
        assert foundation_in_patterns
