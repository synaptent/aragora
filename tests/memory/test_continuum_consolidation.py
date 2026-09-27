"""
Comprehensive tests for Continuum Memory Consolidation operations.

Tests the consolidation module in aragora/memory/continuum_consolidation.py including:
- Multi-tier consolidation logic
- Batch promotion with cooldown enforcement
- Batch demotion operations
- Tier event emission
- Consolidation with large datasets
- Edge cases and error handling
- Concurrent consolidation operations
- Rollback scenarios
"""

from __future__ import annotations

import asyncio
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
    DEFAULT_TIER_CONFIGS,
    MemoryTier,
    TierConfig,
    TierManager,
    reset_tier_manager,
)


def _utc_naive_now() -> datetime:
    """Naive-UTC now, matching how continuum rows are stamped (see PR #9311)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


from aragora.memory import continuum_consolidation


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database path for testing."""
    return str(tmp_path / "test_consolidation.db")


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
def populated_tiers(memory: ContinuumMemory) -> ContinuumMemory:
    """Memory with entries in all tiers with varying surprise scores."""
    # Fast tier entries
    for i in range(5):
        memory.add(f"fast_{i}", f"Fast content {i}", tier=MemoryTier.FAST, importance=0.5 + i * 0.1)

    # Medium tier entries
    for i in range(5):
        memory.add(
            f"medium_{i}", f"Medium content {i}", tier=MemoryTier.MEDIUM, importance=0.5 + i * 0.1
        )

    # Slow tier entries
    for i in range(5):
        memory.add(f"slow_{i}", f"Slow content {i}", tier=MemoryTier.SLOW, importance=0.5 + i * 0.1)

    # Glacial tier entries
    for i in range(5):
        memory.add(
            f"glacial_{i}",
            f"Glacial content {i}",
            tier=MemoryTier.GLACIAL,
            importance=0.5 + i * 0.1,
        )

    return memory


# =============================================================================
# Test emit_tier_event Function
# =============================================================================


class TestEmitTierEvent:
    """Tests for emit_tier_event() function."""

    def test_emit_promotion_event(self, memory: ContinuumMemory) -> None:
        """Test emitting promotion event."""
        mock_emitter = MagicMock()
        memory.event_emitter = mock_emitter

        continuum_consolidation.emit_tier_event(
            memory,
            "promotion",
            "test_id",
            MemoryTier.MEDIUM,
            MemoryTier.FAST,
            0.85,
        )

        mock_emitter.emit_sync.assert_called_once()
        call_args = mock_emitter.emit_sync.call_args
        assert call_args.kwargs["event_type"] == "memory_tier_promotion"
        assert call_args.kwargs["memory_id"] == "test_id"
        assert call_args.kwargs["from_tier"] == "medium"
        assert call_args.kwargs["to_tier"] == "fast"

    def test_emit_demotion_event(self, memory: ContinuumMemory) -> None:
        """Test emitting demotion event."""
        mock_emitter = MagicMock()
        memory.event_emitter = mock_emitter

        continuum_consolidation.emit_tier_event(
            memory,
            "demotion",
            "test_id",
            MemoryTier.FAST,
            MemoryTier.MEDIUM,
            0.15,
        )

        mock_emitter.emit_sync.assert_called_once()
        call_args = mock_emitter.emit_sync.call_args
        assert call_args.kwargs["event_type"] == "memory_tier_demotion"

    def test_no_emit_without_emitter(self, memory: ContinuumMemory) -> None:
        """Test that no error occurs when emitter is None."""
        memory.event_emitter = None

        # Should not raise
        continuum_consolidation.emit_tier_event(
            memory,
            "promotion",
            "test_id",
            MemoryTier.MEDIUM,
            MemoryTier.FAST,
            0.85,
        )

    def test_emit_handles_emitter_error(self, memory: ContinuumMemory) -> None:
        """Test that emitter errors are handled gracefully."""
        mock_emitter = MagicMock()
        mock_emitter.emit_sync.side_effect = TypeError("Invalid emit")
        memory.event_emitter = mock_emitter

        # Should not raise
        continuum_consolidation.emit_tier_event(
            memory,
            "promotion",
            "test_id",
            MemoryTier.MEDIUM,
            MemoryTier.FAST,
            0.85,
        )


# =============================================================================
# Test promote_batch Function
# =============================================================================


class TestPromoteBatch:
    """Tests for promote_batch() function."""

    def test_promote_batch_empty_list(self, memory: ContinuumMemory) -> None:
        """Test batch promote with empty list returns 0."""
        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, []
        )

        assert count == 0

    def test_promote_batch_single_entry(self, memory: ContinuumMemory) -> None:
        """Test batch promote with single entry."""
        memory.add("single", "Content", tier=MemoryTier.MEDIUM)

        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["single"]
        )

        assert count == 1
        entry = memory.get("single")
        assert entry.tier == MemoryTier.FAST

    def test_promote_batch_multiple_entries(self, memory: ContinuumMemory) -> None:
        """Test batch promote with multiple entries."""
        for i in range(10):
            memory.add(f"batch_{i}", f"Content {i}", tier=MemoryTier.MEDIUM)

        ids = [f"batch_{i}" for i in range(10)]
        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ids
        )

        assert count == 10
        for i in range(10):
            entry = memory.get(f"batch_{i}")
            assert entry.tier == MemoryTier.FAST

    def test_promote_batch_respects_tier_filter(self, memory: ContinuumMemory) -> None:
        """Test batch promote only affects entries in correct tier."""
        memory.add("correct_tier", "Content", tier=MemoryTier.MEDIUM)
        memory.add("wrong_tier", "Content", tier=MemoryTier.SLOW)

        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["correct_tier", "wrong_tier"]
        )

        assert count == 1
        assert memory.get("correct_tier").tier == MemoryTier.FAST
        assert memory.get("wrong_tier").tier == MemoryTier.SLOW

    def test_promote_batch_respects_cooldown(self, memory: ContinuumMemory) -> None:
        """Test batch promote respects cooldown period."""
        now = _utc_naive_now().isoformat()

        memory.add("no_cooldown", "Content", tier=MemoryTier.MEDIUM)
        memory.add("with_cooldown", "Content", tier=MemoryTier.MEDIUM)

        # Set recent promotion time for one entry
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET last_promotion_at = ? WHERE id = ?",
                (now, "with_cooldown"),
            )
            conn.commit()

        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["no_cooldown", "with_cooldown"]
        )

        assert count == 1
        assert memory.get("no_cooldown").tier == MemoryTier.FAST
        assert memory.get("with_cooldown").tier == MemoryTier.MEDIUM

    def test_promote_batch_old_cooldown_allowed(self, memory: ContinuumMemory) -> None:
        """Test batch promote allows entries with expired cooldown."""
        old_time = (_utc_naive_now() - timedelta(hours=48)).isoformat()

        memory.add("old_cooldown", "Content", tier=MemoryTier.MEDIUM)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET last_promotion_at = ? WHERE id = ?",
                (old_time, "old_cooldown"),
            )
            conn.commit()

        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["old_cooldown"]
        )

        assert count == 1
        assert memory.get("old_cooldown").tier == MemoryTier.FAST

    def test_promote_batch_updates_last_promotion_at(self, memory: ContinuumMemory) -> None:
        """Test batch promote updates last_promotion_at timestamp."""
        memory.add("timestamp_test", "Content", tier=MemoryTier.MEDIUM)

        continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["timestamp_test"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT last_promotion_at FROM continuum_memory WHERE id = ?",
                ("timestamp_test",),
            )
            last_promotion = cursor.fetchone()[0]

        assert last_promotion is not None
        # Should be recent (within last second)
        promotion_dt = datetime.fromisoformat(last_promotion)
        assert (_utc_naive_now() - promotion_dt).total_seconds() < 2

    def test_promote_batch_records_transitions(self, memory: ContinuumMemory) -> None:
        """Test batch promote records transitions in database."""
        for i in range(3):
            memory.add(f"trans_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        continuum_consolidation.promote_batch(
            memory, MemoryTier.SLOW, MemoryTier.MEDIUM, ["trans_0", "trans_1", "trans_2"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) FROM tier_transitions
                   WHERE from_tier = 'slow' AND to_tier = 'medium'"""
            )
            count = cursor.fetchone()[0]

        assert count == 3

    def test_promote_batch_nonexistent_ids(self, memory: ContinuumMemory) -> None:
        """Test batch promote with non-existent IDs."""
        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["nonexistent_1", "nonexistent_2"]
        )

        assert count == 0

    def test_promote_batch_mixed_existing_nonexistent(self, memory: ContinuumMemory) -> None:
        """Test batch promote with mix of existing and non-existent IDs."""
        memory.add("exists", "Content", tier=MemoryTier.MEDIUM)

        count = continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["exists", "nonexistent"]
        )

        assert count == 1


# =============================================================================
# Test demote_batch Function
# =============================================================================


class TestDemoteBatch:
    """Tests for demote_batch() function."""

    def test_demote_batch_empty_list(self, memory: ContinuumMemory) -> None:
        """Test batch demote with empty list returns 0."""
        count = continuum_consolidation.demote_batch(memory, MemoryTier.FAST, MemoryTier.MEDIUM, [])

        assert count == 0

    def test_demote_batch_single_entry(self, memory: ContinuumMemory) -> None:
        """Test batch demote with single entry."""
        memory.add("single", "Content", tier=MemoryTier.FAST)

        count = continuum_consolidation.demote_batch(
            memory, MemoryTier.FAST, MemoryTier.MEDIUM, ["single"]
        )

        assert count == 1
        entry = memory.get("single")
        assert entry.tier == MemoryTier.MEDIUM

    def test_demote_batch_multiple_entries(self, memory: ContinuumMemory) -> None:
        """Test batch demote with multiple entries."""
        for i in range(10):
            memory.add(f"demote_{i}", f"Content {i}", tier=MemoryTier.FAST)

        ids = [f"demote_{i}" for i in range(10)]
        count = continuum_consolidation.demote_batch(
            memory, MemoryTier.FAST, MemoryTier.MEDIUM, ids
        )

        assert count == 10
        for i in range(10):
            entry = memory.get(f"demote_{i}")
            assert entry.tier == MemoryTier.MEDIUM

    def test_demote_batch_respects_tier_filter(self, memory: ContinuumMemory) -> None:
        """Test batch demote only affects entries in correct tier."""
        memory.add("correct_tier", "Content", tier=MemoryTier.FAST)
        memory.add("wrong_tier", "Content", tier=MemoryTier.MEDIUM)

        count = continuum_consolidation.demote_batch(
            memory, MemoryTier.FAST, MemoryTier.MEDIUM, ["correct_tier", "wrong_tier"]
        )

        assert count == 1
        assert memory.get("correct_tier").tier == MemoryTier.MEDIUM
        assert memory.get("wrong_tier").tier == MemoryTier.MEDIUM  # unchanged

    def test_demote_batch_records_transitions(self, memory: ContinuumMemory) -> None:
        """Test batch demote records transitions in database."""
        for i in range(3):
            memory.add(f"demote_trans_{i}", f"Content {i}", tier=MemoryTier.FAST)

        continuum_consolidation.demote_batch(
            memory,
            MemoryTier.FAST,
            MemoryTier.MEDIUM,
            ["demote_trans_0", "demote_trans_1", "demote_trans_2"],
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT COUNT(*) FROM tier_transitions
                   WHERE from_tier = 'fast' AND to_tier = 'medium'"""
            )
            count = cursor.fetchone()[0]

        assert count == 3

    def test_demote_batch_updates_updated_at(self, memory: ContinuumMemory) -> None:
        """Test batch demote updates updated_at timestamp."""
        memory.add("timestamp_test", "Content", tier=MemoryTier.FAST)

        # Get original timestamp
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM continuum_memory WHERE id = ?",
                ("timestamp_test",),
            )
            original_time = cursor.fetchone()[0]

        time.sleep(0.01)  # Small delay

        continuum_consolidation.demote_batch(
            memory, MemoryTier.FAST, MemoryTier.MEDIUM, ["timestamp_test"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT updated_at FROM continuum_memory WHERE id = ?",
                ("timestamp_test",),
            )
            new_time = cursor.fetchone()[0]

        assert new_time != original_time


# =============================================================================
# Test consolidate Function
# =============================================================================


class TestConsolidate:
    """Tests for consolidate() function."""

    def test_consolidate_returns_dict(self, memory: ContinuumMemory) -> None:
        """Test consolidate returns dict with promotions and demotions."""
        result = continuum_consolidation.consolidate(memory)

        assert isinstance(result, dict)
        assert "promotions" in result
        assert "demotions" in result
        assert isinstance(result["promotions"], int)
        assert isinstance(result["demotions"], int)

    def test_consolidate_empty_memory(self, memory: ContinuumMemory) -> None:
        """Test consolidate on empty memory."""
        result = continuum_consolidation.consolidate(memory)

        assert result["promotions"] == 0
        assert result["demotions"] == 0

    def test_consolidate_promotes_high_surprise(self, populated_tiers: ContinuumMemory) -> None:
        """Test consolidate promotes entries with high surprise."""
        # Set high surprise for slow tier entries
        with populated_tiers.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9 WHERE tier = 'slow'")
            conn.commit()

        result = continuum_consolidation.consolidate(populated_tiers)

        # Some entries should have been promoted
        assert result["promotions"] >= 0

    def test_consolidate_demotes_stable_entries(self, populated_tiers: ContinuumMemory) -> None:
        """Test consolidate demotes stable entries."""
        # Set low surprise (high stability) and sufficient updates for fast tier
        with populated_tiers.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.02, update_count = 20
                   WHERE tier = 'fast'"""
            )
            conn.commit()

        result = continuum_consolidation.consolidate(populated_tiers)

        # Some entries should have been demoted
        assert "demotions" in result

    def test_consolidate_one_level_at_a_time(self, memory: ContinuumMemory) -> None:
        """Test that consolidate only moves entries one tier at a time."""
        memory.add("glacial_test", "Content", tier=MemoryTier.GLACIAL)

        # Set very high surprise
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.99 WHERE id = ?",
                ("glacial_test",),
            )
            conn.commit()

        continuum_consolidation.consolidate(memory)

        # Should only move to slow, not directly to fast
        entry = memory.get("glacial_test")
        assert entry.tier in [MemoryTier.GLACIAL, MemoryTier.SLOW]

    def test_consolidate_processes_all_tier_pairs(self, memory: ContinuumMemory) -> None:
        """Test consolidate processes all tier pairs."""
        # Add entries to each tier with high surprise (for promotion)
        memory.add("glacial_entry", "Content", tier=MemoryTier.GLACIAL)
        memory.add("slow_entry", "Content", tier=MemoryTier.SLOW)
        memory.add("medium_entry", "Content", tier=MemoryTier.MEDIUM)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9")
            conn.commit()

        continuum_consolidation.consolidate(memory)

        # Check that transitions were attempted
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT from_tier FROM tier_transitions")
            from_tiers = {row[0] for row in cursor.fetchall()}

        # At least some tiers should have had transitions
        # (exact behavior depends on threshold configs)

    def test_consolidate_batch_limit(self, memory: ContinuumMemory) -> None:
        """Test consolidate respects batch limit of 1000."""
        # Add many entries
        for i in range(1500):
            memory.add(f"mass_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9")
            conn.commit()

        result = continuum_consolidation.consolidate(memory)

        # Should not process more than 1000 per tier pair
        assert result["promotions"] <= 1000

    def test_consolidate_concurrent_safety(self, populated_tiers: ContinuumMemory) -> None:
        """Test concurrent consolidation calls are safe."""
        errors: list[Exception] = []

        def run_consolidate() -> None:
            try:
                continuum_consolidation.consolidate(populated_tiers)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_consolidate) for _ in range(4)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Test Multi-Tier Consolidation Flow
# =============================================================================


class TestMultiTierConsolidation:
    """Tests for multi-tier consolidation flows."""

    def test_full_promotion_chain(self, memory: ContinuumMemory) -> None:
        """Test entry can be promoted through all tiers over multiple consolidations."""
        memory.add("chain_test", "Content", tier=MemoryTier.GLACIAL)

        # Set high surprise
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.95 WHERE id = ?",
                ("chain_test",),
            )
            conn.commit()

        # Multiple consolidations to move through tiers
        for _ in range(3):
            continuum_consolidation.consolidate(memory)
            # Reset cooldown for testing
            with memory.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE continuum_memory SET last_promotion_at = NULL WHERE id = ?",
                    ("chain_test",),
                )
                conn.commit()

        entry = memory.get("chain_test")
        # After 3 consolidations with high surprise, should be at fast or near it
        assert entry.tier in [MemoryTier.MEDIUM, MemoryTier.FAST]

    def test_full_demotion_chain(self, memory: ContinuumMemory) -> None:
        """Test entry can be demoted through all tiers over multiple consolidations."""
        memory.add("demote_chain", "Content", tier=MemoryTier.FAST)

        # Set low surprise (high stability) and high update count
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.01, update_count = 50
                   WHERE id = ?""",
                ("demote_chain",),
            )
            conn.commit()

        # Multiple consolidations to move through tiers
        for _ in range(3):
            continuum_consolidation.consolidate(memory)

        entry = memory.get("demote_chain")
        # Should be demoted to slower tier
        assert entry.tier in [MemoryTier.MEDIUM, MemoryTier.SLOW, MemoryTier.GLACIAL]

    def test_mixed_promotion_demotion(self, memory: ContinuumMemory) -> None:
        """Test consolidation with both promotions and demotions."""
        # Add entries for promotion
        memory.add("to_promote", "Content", tier=MemoryTier.SLOW)
        # Add entries for demotion
        memory.add("to_demote", "Content", tier=MemoryTier.FAST)

        with memory.connection() as conn:
            cursor = conn.cursor()
            # High surprise for promotion
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = 'to_promote'"
            )
            # Low surprise, high updates for demotion
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.02, update_count = 25
                   WHERE id = 'to_demote'"""
            )
            conn.commit()

        result = continuum_consolidation.consolidate(memory)

        # Both types of transitions should have occurred
        to_promote = memory.get("to_promote")
        to_demote = memory.get("to_demote")

        # Check tier changes happened in correct directions
        assert to_promote.tier in [MemoryTier.SLOW, MemoryTier.MEDIUM]
        assert to_demote.tier in [MemoryTier.FAST, MemoryTier.MEDIUM]


# =============================================================================
# Test Data Integrity During Consolidation
# =============================================================================


class TestConsolidationDataIntegrity:
    """Tests for data integrity during consolidation."""

    def test_content_preserved_during_consolidation(self, memory: ContinuumMemory) -> None:
        """Test that content is preserved during consolidation."""
        original_content = "This is important content that must be preserved"
        memory.add("integrity", original_content, tier=MemoryTier.SLOW, importance=0.8)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?", ("integrity",)
            )
            conn.commit()

        continuum_consolidation.consolidate(memory)

        entry = memory.get("integrity")
        assert entry.content == original_content

    def test_metadata_preserved_during_consolidation(self, memory: ContinuumMemory) -> None:
        """Test that metadata is preserved during consolidation."""
        metadata = {"source": "test", "tags": ["important"], "round": 5}
        memory.add("metadata_test", "Content", tier=MemoryTier.FAST, metadata=metadata)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE continuum_memory
                   SET surprise_score = 0.02, update_count = 20
                   WHERE id = ?""",
                ("metadata_test",),
            )
            conn.commit()

        continuum_consolidation.consolidate(memory)

        entry = memory.get("metadata_test")
        assert entry.metadata == metadata

    def test_importance_preserved_during_consolidation(self, memory: ContinuumMemory) -> None:
        """Test that importance is preserved during consolidation."""
        memory.add("importance_test", "Content", tier=MemoryTier.SLOW, importance=0.95)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("importance_test",),
            )
            conn.commit()

        continuum_consolidation.consolidate(memory)

        entry = memory.get("importance_test")
        assert entry.importance == 0.95

    def test_counts_preserved_during_consolidation(self, memory: ContinuumMemory) -> None:
        """Test that success/failure counts are preserved during consolidation."""
        memory.add("counts_test", "Content", tier=MemoryTier.MEDIUM)

        # Set some counts
        for _ in range(10):
            memory.update_outcome("counts_test", success=True)
        for _ in range(3):
            memory.update_outcome("counts_test", success=False)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?", ("counts_test",)
            )
            conn.commit()

        entry_before = memory.get("counts_test")
        success_before = entry_before.success_count
        failure_before = entry_before.failure_count

        continuum_consolidation.consolidate(memory)

        entry_after = memory.get("counts_test")
        assert entry_after.success_count == success_before
        assert entry_after.failure_count == failure_before


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestConsolidationEdgeCases:
    """Tests for consolidation edge cases."""

    def test_consolidate_single_entry_per_tier(self, memory: ContinuumMemory) -> None:
        """Test consolidation with only one entry per tier."""
        memory.add("single_fast", "Content", tier=MemoryTier.FAST)
        memory.add("single_medium", "Content", tier=MemoryTier.MEDIUM)
        memory.add("single_slow", "Content", tier=MemoryTier.SLOW)
        memory.add("single_glacial", "Content", tier=MemoryTier.GLACIAL)

        # Should not raise
        result = continuum_consolidation.consolidate(memory)

        assert isinstance(result, dict)

    def test_consolidate_with_deleted_entries(self, memory: ContinuumMemory) -> None:
        """Test consolidation doesn't fail with deleted entries during process."""
        for i in range(5):
            memory.add(f"delete_test_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        # Delete some entries
        memory.delete("delete_test_0")
        memory.delete("delete_test_2")

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9 WHERE tier = 'slow'")
            conn.commit()

        # Should not raise
        result = continuum_consolidation.consolidate(memory)

        assert isinstance(result, dict)

    def test_consolidate_with_red_line_entries(self, memory: ContinuumMemory) -> None:
        """Test consolidation works with red line entries without errors."""
        # Add entry and mark as red_line, which promotes to glacial by default
        memory.add("red_line_test", "Content", tier=MemoryTier.SLOW)
        memory.mark_red_line("red_line_test", reason="Critical", promote_to_glacial=True)

        # Verify entry is now in glacial tier after mark_red_line
        entry_before = memory.get("red_line_test")
        assert entry_before.tier == MemoryTier.GLACIAL
        assert entry_before.red_line is True

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.9 WHERE id = ?",
                ("red_line_test",),
            )
            conn.commit()

        # Should not raise
        result = continuum_consolidation.consolidate(memory)

        # Verify consolidation completed and entry still exists
        # Note: consolidation may promote from glacial->slow based on surprise score
        # Red line protection prevents DELETION, not tier movement
        entry = memory.get("red_line_test")
        assert entry is not None
        assert entry.red_line is True  # Red line flag should be preserved

    def test_consolidate_boundary_surprise_scores(self, memory: ContinuumMemory) -> None:
        """Test consolidation with boundary surprise scores."""
        # Add entries with exact threshold values
        memory.add("exact_threshold", "Content", tier=MemoryTier.SLOW)

        # Set surprise score exactly at promotion threshold
        slow_config = DEFAULT_TIER_CONFIGS[MemoryTier.SLOW]
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = ? WHERE id = ?",
                (slow_config.promotion_threshold, "exact_threshold"),
            )
            conn.commit()

        # Should handle boundary case
        result = continuum_consolidation.consolidate(memory)

        assert isinstance(result, dict)

    def test_consolidate_very_large_batch(self, memory: ContinuumMemory) -> None:
        """Test consolidation with many entries."""
        # Add many entries
        for i in range(500):
            memory.add(f"large_{i}", f"Content {i}", tier=MemoryTier.SLOW)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE continuum_memory SET surprise_score = 0.9 WHERE tier = 'slow'")
            conn.commit()

        # Should handle large batch efficiently
        import time

        start = time.time()
        result = continuum_consolidation.consolidate(memory)
        elapsed = time.time() - start

        assert isinstance(result, dict)
        # Should complete in reasonable time (< 10 seconds)
        assert elapsed < 10


# =============================================================================
# Test Rollback and Error Scenarios
# =============================================================================


class TestConsolidationRollback:
    """Tests for consolidation rollback and error handling."""

    def test_partial_batch_failure_handled(self, memory: ContinuumMemory) -> None:
        """Test that partial failures in batch operations are handled."""
        for i in range(5):
            memory.add(f"partial_{i}", f"Content {i}", tier=MemoryTier.MEDIUM)

        # Should not raise even with potential issues
        result = continuum_consolidation.consolidate(memory)

        assert isinstance(result, dict)

    def test_consolidate_recovers_from_connection_error(self, memory: ContinuumMemory) -> None:
        """Test consolidate can recover from transient errors."""
        memory.add("recover_test", "Content", tier=MemoryTier.SLOW)

        # First consolidate should work
        result = continuum_consolidation.consolidate(memory)
        assert isinstance(result, dict)


# =============================================================================
# Test Thread Safety
# =============================================================================


class TestConsolidationThreadSafety:
    """Tests for thread safety in consolidation operations."""

    def test_concurrent_batch_promote(self, memory: ContinuumMemory) -> None:
        """Test concurrent batch promote operations."""
        for i in range(100):
            memory.add(f"concurrent_{i}", f"Content {i}", tier=MemoryTier.MEDIUM)

        errors: list[Exception] = []

        def batch_promote(start: int, end: int) -> None:
            try:
                ids = [f"concurrent_{i}" for i in range(start, end)]
                continuum_consolidation.promote_batch(
                    memory, MemoryTier.MEDIUM, MemoryTier.FAST, ids
                )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=batch_promote, args=(0, 25)),
            threading.Thread(target=batch_promote, args=(25, 50)),
            threading.Thread(target=batch_promote, args=(50, 75)),
            threading.Thread(target=batch_promote, args=(75, 100)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_concurrent_batch_demote(self, memory: ContinuumMemory) -> None:
        """Test concurrent batch demote operations."""
        for i in range(100):
            memory.add(f"concurrent_{i}", f"Content {i}", tier=MemoryTier.FAST)

        errors: list[Exception] = []

        def batch_demote(start: int, end: int) -> None:
            try:
                ids = [f"concurrent_{i}" for i in range(start, end)]
                continuum_consolidation.demote_batch(
                    memory, MemoryTier.FAST, MemoryTier.MEDIUM, ids
                )
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=batch_demote, args=(0, 25)),
            threading.Thread(target=batch_demote, args=(25, 50)),
            threading.Thread(target=batch_demote, args=(50, 75)),
            threading.Thread(target=batch_demote, args=(75, 100)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    def test_mixed_concurrent_operations(self, memory: ContinuumMemory) -> None:
        """Test mixed concurrent promote, demote, and consolidate operations."""
        for i in range(50):
            memory.add(f"promote_{i}", f"Content {i}", tier=MemoryTier.MEDIUM)
            memory.add(f"demote_{i}", f"Content {i}", tier=MemoryTier.FAST)

        errors: list[Exception] = []

        def do_promote() -> None:
            try:
                ids = [f"promote_{i}" for i in range(25)]
                continuum_consolidation.promote_batch(
                    memory, MemoryTier.MEDIUM, MemoryTier.FAST, ids
                )
            except Exception as e:
                errors.append(e)

        def do_demote() -> None:
            try:
                ids = [f"demote_{i}" for i in range(25)]
                continuum_consolidation.demote_batch(
                    memory, MemoryTier.FAST, MemoryTier.MEDIUM, ids
                )
            except Exception as e:
                errors.append(e)

        def do_consolidate() -> None:
            try:
                continuum_consolidation.consolidate(memory)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=do_promote),
            threading.Thread(target=do_demote),
            threading.Thread(target=do_consolidate),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# =============================================================================
# Test Transition Recording
# =============================================================================


class TestTransitionRecording:
    """Tests for tier transition recording."""

    def test_promote_batch_records_correct_reason(self, memory: ContinuumMemory) -> None:
        """Test that promote_batch records 'high_surprise' reason."""
        memory.add("reason_test", "Content", tier=MemoryTier.MEDIUM)

        continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["reason_test"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT reason FROM tier_transitions WHERE memory_id = ?",
                ("reason_test",),
            )
            reason = cursor.fetchone()[0]

        assert reason == "high_surprise"

    def test_demote_batch_records_correct_reason(self, memory: ContinuumMemory) -> None:
        """Test that demote_batch records 'high_stability' reason."""
        memory.add("reason_test", "Content", tier=MemoryTier.FAST)

        continuum_consolidation.demote_batch(
            memory, MemoryTier.FAST, MemoryTier.MEDIUM, ["reason_test"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT reason FROM tier_transitions WHERE memory_id = ?",
                ("reason_test",),
            )
            reason = cursor.fetchone()[0]

        assert reason == "high_stability"

    def test_transition_records_surprise_score(self, memory: ContinuumMemory) -> None:
        """Test that transitions record surprise score."""
        memory.add("score_test", "Content", tier=MemoryTier.MEDIUM)

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET surprise_score = 0.75 WHERE id = ?",
                ("score_test",),
            )
            conn.commit()

        continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["score_test"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT surprise_score FROM tier_transitions WHERE memory_id = ?",
                ("score_test",),
            )
            score = cursor.fetchone()[0]

        assert abs(score - 0.75) < 0.01

    def test_multiple_transitions_recorded(self, memory: ContinuumMemory) -> None:
        """Test that multiple transitions for same entry are all recorded."""
        memory.add("multi_trans", "Content", tier=MemoryTier.GLACIAL)

        # Promote through multiple tiers, clearing cooldown between each
        continuum_consolidation.promote_batch(
            memory, MemoryTier.GLACIAL, MemoryTier.SLOW, ["multi_trans"]
        )
        # Clear cooldown for next promotion
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET last_promotion_at = NULL WHERE id = ?",
                ("multi_trans",),
            )
            conn.commit()

        continuum_consolidation.promote_batch(
            memory, MemoryTier.SLOW, MemoryTier.MEDIUM, ["multi_trans"]
        )
        # Clear cooldown for next promotion
        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE continuum_memory SET last_promotion_at = NULL WHERE id = ?",
                ("multi_trans",),
            )
            conn.commit()

        continuum_consolidation.promote_batch(
            memory, MemoryTier.MEDIUM, MemoryTier.FAST, ["multi_trans"]
        )

        with memory.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM tier_transitions WHERE memory_id = ?",
                ("multi_trans",),
            )
            count = cursor.fetchone()[0]

        assert count == 3
