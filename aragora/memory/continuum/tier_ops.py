"""
Tier operations mixin for ContinuumMemory.

Provides promote, demote, consolidate, and tier management operations.
"""
# mypy: disable-error-code="misc"
# Mixin classes use self: "ContinuumMemory" type hints which mypy doesn't understand

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from aragora.memory.tier_manager import MemoryTier
from aragora.utils.datetime_helpers import utc_now_iso_naive
from aragora.utils.json_helpers import safe_json_loads

from .entry import ContinuumMemoryEntry

# Import extracted modules for delegation
from aragora.memory import continuum_consolidation as _consolidation
from aragora.memory import continuum_stats as _stats

if TYPE_CHECKING:
    from .core import ContinuumMemory

logger = logging.getLogger(__name__)


class TierOpsMixin:
    """Mixin providing tier operations for ContinuumMemory."""

    def mark_red_line(
        self: ContinuumMemory,
        memory_id: str,
        reason: str,
        promote_to_glacial: bool = True,
    ) -> bool:
        """
        Mark a memory entry as a red line - cannot be forgotten or overwritten.

        Red line entries are critical memories that should never be deleted,
        such as safety-critical decisions, irreversible actions taken, or
        foundational knowledge that must be preserved.

        Args:
            memory_id: The ID of the memory to protect
            reason: Why this entry is critical (for auditing)
            promote_to_glacial: If True, promote to glacial tier for maximum retention

        Returns:
            True if the entry was marked, False if entry not found
        """
        now: str = utc_now_iso_naive()

        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()

            # Check if memory exists
            cursor.execute("SELECT tier FROM continuum_memory WHERE id = ?", (memory_id,))
            row: tuple[Any, ...] | None = cursor.fetchone()
            if not row:
                logger.warning("Cannot mark non-existent memory as red line: %s", memory_id)
                return False

            current_tier: str = row[0]

            # Mark as red line
            if promote_to_glacial and current_tier != MemoryTier.GLACIAL.value:
                cursor.execute(
                    """
                    UPDATE continuum_memory
                    SET red_line = 1, red_line_reason = ?, tier = ?,
                        importance = 1.0, updated_at = ?
                    WHERE id = ?
                    """,
                    (reason, MemoryTier.GLACIAL.value, now, memory_id),
                )
                logger.info(
                    "Marked memory %s as red line and promoted to glacial tier (reason: %s)",
                    memory_id,
                    reason,
                )
            else:
                cursor.execute(
                    """
                    UPDATE continuum_memory
                    SET red_line = 1, red_line_reason = ?, importance = 1.0, updated_at = ?
                    WHERE id = ?
                    """,
                    (reason, now, memory_id),
                )
                logger.info("Marked memory %s as red line (reason: %s)", memory_id, reason)

            conn.commit()
            return True

    def get_red_line_memories(self: ContinuumMemory) -> list[ContinuumMemoryEntry]:
        """Get all red-lined memory entries.

        Returns:
            List of all protected memory entries
        """
        with self.connection() as conn:
            cursor: sqlite3.Cursor = conn.cursor()
            cursor.execute("""
                SELECT id, tier, content, importance, surprise_score, consolidation_score,
                       update_count, success_count, failure_count, created_at, updated_at, metadata,
                       COALESCE(red_line, 0), COALESCE(red_line_reason, '')
                FROM continuum_memory
                WHERE red_line = 1
                ORDER BY created_at ASC
                """)
            rows: list[tuple[Any, ...]] = cursor.fetchall()

        return [
            ContinuumMemoryEntry(
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
            for row in rows
        ]

    def promote(self: ContinuumMemory, id: str) -> MemoryTier | None:
        """
        Promote a memory to a faster tier.

        Uses TierManager for decision logic and records metrics.
        Thread-safe: uses immediate_transaction to prevent TOCTOU race conditions
        across processes/pods. The Python lock provides in-process protection,
        while BEGIN IMMEDIATE provides cross-process protection.

        Returns the new tier if promoted, None otherwise.
        """
        with self._tier_lock, self.immediate_transaction() as conn:
            cursor: sqlite3.Cursor = conn.cursor()

            cursor.execute(
                "SELECT tier, surprise_score, last_promotion_at FROM continuum_memory WHERE id = ?",
                (id,),
            )
            row: tuple[Any, ...] | None = cursor.fetchone()
            if not row:
                return None

            current_tier: MemoryTier = MemoryTier(row[0])
            surprise_score: float = row[1]
            last_promotion: str | None = row[2]

            # Use TierManager for decision
            tm_current: MemoryTier = MemoryTier(current_tier.value)
            if not self._tier_manager.should_promote(tm_current, surprise_score, last_promotion):
                logger.debug(
                    f"[memory] Promotion denied for {id}: tier={current_tier.value}, "
                    f"surprise={surprise_score:.3f}, last_promotion={last_promotion}"
                )
                return None

            # Get next tier using TierManager
            tm_new: MemoryTier | None = self._tier_manager.get_next_tier(tm_current, "faster")
            if tm_new is None:
                logger.debug(
                    "[memory] No faster tier available for %s (already at %s)",
                    id,
                    current_tier.value,
                )
                return None

            new_tier: MemoryTier = MemoryTier(tm_new.value)
            now: str = utc_now_iso_naive()

            logger.info(
                f"[memory] Promoting {id}: {current_tier.value} -> {new_tier.value} "
                f"(surprise={surprise_score:.3f})"
            )

            # Update tier
            cursor.execute(
                """
                UPDATE continuum_memory
                SET tier = ?, last_promotion_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_tier.value, now, now, id),
            )

            # Record transition in database
            cursor.execute(
                """
                INSERT INTO tier_transitions (memory_id, from_tier, to_tier, reason, surprise_score)
                VALUES (?, ?, ?, 'high_surprise', ?)
                """,
                (id, current_tier.value, new_tier.value, surprise_score),
            )

            # Note: commit is handled by immediate_transaction() context manager

        # Record metrics in TierManager
        self._tier_manager.record_promotion(tm_current, tm_new)

        # Emit promotion event if event_emitter is available
        self._emit_tier_event("promotion", id, current_tier, new_tier, surprise_score)

        return new_tier

    def demote(self: ContinuumMemory, id: str) -> MemoryTier | None:
        """
        Demote a memory to a slower tier.

        Uses TierManager for decision logic and records metrics.
        Thread-safe: uses immediate_transaction to prevent TOCTOU race conditions
        across processes/pods. The Python lock provides in-process protection,
        while BEGIN IMMEDIATE provides cross-process protection.

        Returns the new tier if demoted, None otherwise.
        """
        with self._tier_lock, self.immediate_transaction() as conn:
            cursor: sqlite3.Cursor = conn.cursor()

            cursor.execute(
                "SELECT tier, surprise_score, update_count FROM continuum_memory WHERE id = ?",
                (id,),
            )
            row: tuple[Any, ...] | None = cursor.fetchone()
            if not row:
                return None

            current_tier: MemoryTier = MemoryTier(row[0])
            surprise_score: float = row[1]
            update_count: int = row[2]

            # Use TierManager for decision
            tm_current: MemoryTier = MemoryTier(current_tier.value)
            if not self._tier_manager.should_demote(tm_current, surprise_score, update_count):
                logger.debug(
                    f"[memory] Demotion denied for {id}: tier={current_tier.value}, "
                    f"surprise={surprise_score:.3f}, updates={update_count}"
                )
                return None

            # Get next tier using TierManager
            tm_new: MemoryTier | None = self._tier_manager.get_next_tier(tm_current, "slower")
            if tm_new is None:
                logger.debug(
                    "[memory] No slower tier available for %s (already at %s)",
                    id,
                    current_tier.value,
                )
                return None

            new_tier: MemoryTier = MemoryTier(tm_new.value)
            now: str = utc_now_iso_naive()

            logger.info(
                f"[memory] Demoting {id}: {current_tier.value} -> {new_tier.value} "
                f"(surprise={surprise_score:.3f}, updates={update_count})"
            )

            # Update tier
            cursor.execute(
                """
                UPDATE continuum_memory
                SET tier = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_tier.value, now, id),
            )

            # Record transition in database
            cursor.execute(
                """
                INSERT INTO tier_transitions (memory_id, from_tier, to_tier, reason, surprise_score)
                VALUES (?, ?, ?, 'high_stability', ?)
                """,
                (id, current_tier.value, new_tier.value, surprise_score),
            )

            # Note: commit is handled by immediate_transaction() context manager

        # Record metrics in TierManager
        self._tier_manager.record_demotion(tm_current, tm_new)

        # Emit demotion event if event_emitter is available
        self._emit_tier_event("demotion", id, current_tier, new_tier, surprise_score)

        return new_tier

    def _emit_tier_event(
        self: ContinuumMemory,
        event_type: str,
        memory_id: str,
        from_tier: MemoryTier,
        to_tier: MemoryTier,
        surprise_score: float,
    ) -> None:
        """Emit MEMORY_TIER_PROMOTION or MEMORY_TIER_DEMOTION event."""
        _consolidation.emit_tier_event(
            self, event_type, memory_id, from_tier, to_tier, surprise_score
        )

    def _promote_batch(
        self: ContinuumMemory,
        from_tier: MemoryTier,
        to_tier: MemoryTier,
        ids: list[str],
    ) -> int:
        """
        Batch promote memories from one tier to another.

        Uses executemany for efficient batch updates instead of N+1 queries.
        Thread-safe: uses lock to prevent race conditions with single-item operations.
        """
        return _consolidation.promote_batch(self, from_tier, to_tier, ids)

    def _demote_batch(
        self: ContinuumMemory,
        from_tier: MemoryTier,
        to_tier: MemoryTier,
        ids: list[str],
    ) -> int:
        """
        Batch demote memories from one tier to another.

        Uses executemany for efficient batch updates instead of N+1 queries.
        Thread-safe: uses lock to prevent race conditions with single-item operations.
        """
        return _consolidation.demote_batch(self, from_tier, to_tier, ids)

    def consolidate(self: ContinuumMemory) -> dict[str, int]:
        """
        Run tier consolidation: promote/demote memories based on surprise.

        This should be called periodically (e.g., after each nomic cycle).
        Uses batch operations for better performance with large memory stores.
        """
        return _consolidation.consolidate(self)

    def get_stats(self: ContinuumMemory) -> dict[str, Any]:
        """Get statistics about the continuum memory system."""
        return _stats.get_stats(self)

    def export_for_tier(self: ContinuumMemory, tier: MemoryTier) -> list[dict[str, Any]]:
        """Export all memories for a specific tier."""
        return _stats.export_for_tier(self, tier)

    def get_memory_pressure(self: ContinuumMemory) -> float:
        """
        Calculate memory pressure as a 0-1 score based on tier utilization.

        Returns the highest utilization ratio across all tiers, where:
        - 0.0 = All tiers are empty
        - 1.0 = At least one tier is at or above its max_entries limit

        Use this to trigger cleanup when pressure exceeds a threshold (e.g., 0.8).
        """
        return _stats.get_memory_pressure(self)

    def cleanup_expired_memories(
        self: ContinuumMemory,
        tier: MemoryTier | None = None,
        archive: bool = True,
        max_age_hours: float | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Remove or archive expired memories based on tier retention policies.

        Memories are considered expired when they are older than:
        tier_half_life * retention_multiplier (default 2x)

        Args:
            tier: Specific tier to cleanup (None = all tiers)
            archive: If True, move to archive table; if False, delete permanently
            max_age_hours: Override default retention (uses tier half-life * multiplier if None)
            tenant_id: Optional tenant ID for multi-tenant isolation

        Returns:
            Dict with counts: {"archived": N, "deleted": N, "by_tier": {...}}
        """
        return _stats.cleanup_expired_memories(self, tier, archive, max_age_hours, tenant_id)

    def delete(
        self: ContinuumMemory,
        memory_id: str,
        archive: bool = True,
        reason: str = "user_deleted",
        force: bool = False,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Delete a specific memory entry by ID.

        Args:
            memory_id: The ID of the memory to delete
            archive: If True, archive before deletion; if False, delete permanently
            reason: Reason for deletion (stored in archive)
            force: If True, delete even if entry is red-lined (dangerous!)
            tenant_id: Optional tenant ID for multi-tenant isolation.

        Returns:
            Dict with result: {"deleted": bool, "archived": bool, "id": str, "blocked": bool}
        """
        return _stats.delete_memory(self, memory_id, archive, reason, force, tenant_id)

    def enforce_tier_limits(
        self: ContinuumMemory,
        tier: MemoryTier | None = None,
        archive: bool = True,
        tenant_id: str | None = None,
    ) -> dict[str, int]:
        """
        Enforce max entries per tier by removing lowest importance entries.

        When a tier exceeds its limit, the lowest importance entries are
        archived (or deleted) until the tier is within limits.

        Args:
            tier: Specific tier to enforce (None = all tiers)
            archive: If True, archive excess; if False, delete permanently
            tenant_id: If provided, only enforce limits for this tenant

        Returns:
            Dict with counts of removed entries by tier
        """
        return _stats.enforce_tier_limits(self, tier, archive, tenant_id)

    def get_archive_stats(self: ContinuumMemory) -> dict[str, Any]:
        """Get statistics about archived memories."""
        return _stats.get_archive_stats(self)


__all__ = ["TierOpsMixin"]
