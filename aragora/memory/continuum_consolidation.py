"""
Consolidation and batch tier operations for Continuum Memory System.

Extracted from continuum.py to reduce module size while maintaining functionality.
All functions operate on ContinuumMemory instances passed as the first parameter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
import importlib.util
from typing import TYPE_CHECKING

from aragora.memory.tier_manager import DEFAULT_TIER_CONFIGS, MemoryTier
from aragora.utils.datetime_helpers import utc_now_iso_naive

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory

logger = logging.getLogger(__name__)


def emit_tier_event(
    cms: ContinuumMemory,
    event_type: str,
    memory_id: str,
    from_tier: MemoryTier,
    to_tier: MemoryTier,
    surprise_score: float,
) -> None:
    """Emit MEMORY_TIER_PROMOTION or MEMORY_TIER_DEMOTION event."""
    if not cms.event_emitter:
        return

    if importlib.util.find_spec("aragora.server.stream") is None:
        logger.debug("[memory] Stream module not available for tier event emission")
        return

    try:
        event_type_str = (
            "memory_tier_promotion" if event_type == "promotion" else "memory_tier_demotion"
        )
        cms.event_emitter.emit_sync(
            event_type=event_type_str,
            debate_id="",
            memory_id=memory_id,
            from_tier=from_tier.value,
            to_tier=to_tier.value,
            surprise_score=surprise_score,
        )
    except (AttributeError, TypeError) as e:
        # event_emitter not properly configured or emit() signature mismatch
        logger.debug("[memory] Event emitter configuration error: %s", e)
    except (ValueError, KeyError) as e:
        # Invalid event data
        logger.warning("[memory] Invalid tier event data: %s", e)
    except (ConnectionError, OSError) as e:
        # Network/IO errors during event emission - non-critical
        logger.debug("[memory] Event emission network error: %s", e)


def promote_batch(
    cms: ContinuumMemory,
    from_tier: MemoryTier,
    to_tier: MemoryTier,
    ids: list[str],
) -> int:
    """
    Batch promote memories from one tier to another.

    Uses executemany for efficient batch updates instead of N+1 queries.
    Thread-safe: uses immediate_transaction to prevent race conditions across
    processes/pods. The Python lock provides in-process protection,
    while BEGIN IMMEDIATE provides cross-process protection.

    Args:
        cms: ContinuumMemory instance
        from_tier: Source tier
        to_tier: Target tier (must be one level faster)
        ids: List of memory IDs to promote

    Returns:
        Number of successfully promoted entries
    """
    if not ids:
        return 0

    # Naive-UTC clock: rows are aged with UTC julianday('now') comparisons
    now_dt = datetime.now(timezone.utc).replace(tzinfo=None)
    now = now_dt.isoformat()
    cooldown_hours = cms.hyperparams["promotion_cooldown_hours"]
    cutoff_time = (now_dt - timedelta(hours=cooldown_hours)).isoformat()

    with cms._tier_lock, cms.immediate_transaction() as conn:
        cursor = conn.cursor()

        # Batch UPDATE with cooldown check
        # Only promote entries where last_promotion_at is NULL or older than cooldown
        placeholders = ",".join("?" * len(ids))
        cursor.execute(
            f"""
            UPDATE continuum_memory
            SET tier = ?, last_promotion_at = ?, updated_at = ?
            WHERE id IN ({placeholders})
              AND tier = ?
              AND (last_promotion_at IS NULL OR last_promotion_at < ?)
            """,  # noqa: S608 -- parameterized query
            (to_tier.value, now, now, *ids, from_tier.value, cutoff_time),
        )
        promoted_count = cursor.rowcount

        # Batch INSERT tier transitions for promoted entries
        # Only insert for entries that were actually updated
        if promoted_count > 0:
            cursor.execute(
                f"""
                SELECT id, surprise_score FROM continuum_memory
                WHERE id IN ({placeholders}) AND tier = ?
                """,  # noqa: S608 -- parameterized query
                (*ids, to_tier.value),
            )
            promoted_entries = cursor.fetchall()

            if promoted_entries:
                cursor.executemany(
                    """
                    INSERT INTO tier_transitions
                    (memory_id, from_tier, to_tier, reason, surprise_score)
                    VALUES (?, ?, ?, 'high_surprise', ?)
                    """,
                    [
                        (entry[0], from_tier.value, to_tier.value, entry[1])
                        for entry in promoted_entries
                    ],
                )

        # Note: commit is handled by immediate_transaction() context manager

    if promoted_count > 0:
        logger.info(
            "[memory] Batch promoted %s/%s entries: %s -> %s",
            promoted_count,
            len(ids),
            from_tier.value,
            to_tier.value,
        )

    return promoted_count


def demote_batch(
    cms: ContinuumMemory,
    from_tier: MemoryTier,
    to_tier: MemoryTier,
    ids: list[str],
) -> int:
    """
    Batch demote memories from one tier to another.

    Uses executemany for efficient batch updates instead of N+1 queries.
    Thread-safe: uses immediate_transaction to prevent race conditions across
    processes/pods. The Python lock provides in-process protection,
    while BEGIN IMMEDIATE provides cross-process protection.

    Args:
        cms: ContinuumMemory instance
        from_tier: Source tier
        to_tier: Target tier (must be one level slower)
        ids: List of memory IDs to demote

    Returns:
        Number of successfully demoted entries
    """
    if not ids:
        return 0

    now = utc_now_iso_naive()

    with cms._tier_lock, cms.immediate_transaction() as conn:
        cursor = conn.cursor()

        # Batch UPDATE - update_count check is already done in candidate selection
        placeholders = ",".join("?" * len(ids))
        cursor.execute(
            f"""
            UPDATE continuum_memory
            SET tier = ?, updated_at = ?
            WHERE id IN ({placeholders}) AND tier = ?
            """,  # noqa: S608 -- parameterized query
            (to_tier.value, now, *ids, from_tier.value),
        )
        demoted_count = cursor.rowcount

        # Batch INSERT tier transitions for demoted entries
        if demoted_count > 0:
            cursor.execute(
                f"""
                SELECT id, surprise_score FROM continuum_memory
                WHERE id IN ({placeholders}) AND tier = ?
                """,  # noqa: S608 -- parameterized query
                (*ids, to_tier.value),
            )
            demoted_entries = cursor.fetchall()

            if demoted_entries:
                cursor.executemany(
                    """
                    INSERT INTO tier_transitions
                    (memory_id, from_tier, to_tier, reason, surprise_score)
                    VALUES (?, ?, ?, 'high_stability', ?)
                    """,
                    [
                        (entry[0], from_tier.value, to_tier.value, entry[1])
                        for entry in demoted_entries
                    ],
                )

    if demoted_count > 0:
        logger.info(
            "[memory] Batch demoted %s/%s entries: %s -> %s",
            demoted_count,
            len(ids),
            from_tier.value,
            to_tier.value,
        )

    return demoted_count


def consolidate(cms: ContinuumMemory) -> dict[str, int]:
    """
    Run tier consolidation: promote/demote memories based on surprise.

    This should be called periodically (e.g., after each nomic cycle).

    Uses batch operations to avoid N+1 query patterns for better performance
    with large memory stores.

    Each entry is only promoted/demoted once per consolidate call (one level
    at a time), matching the behavior of the individual promote/demote methods.

    Args:
        cms: ContinuumMemory instance

    Returns:
        Dict with counts of promotions and demotions
    """
    logger.debug("[memory] Starting tier consolidation")
    promotions = 0
    demotions = 0

    # Tier order for promotions: glacial -> slow -> medium -> fast
    promotion_pairs = [
        (MemoryTier.GLACIAL, MemoryTier.SLOW),
        (MemoryTier.SLOW, MemoryTier.MEDIUM),
        (MemoryTier.MEDIUM, MemoryTier.FAST),
    ]

    # Tier order for demotions: fast -> medium -> slow -> glacial
    demotion_pairs = [
        (MemoryTier.FAST, MemoryTier.MEDIUM),
        (MemoryTier.MEDIUM, MemoryTier.SLOW),
        (MemoryTier.SLOW, MemoryTier.GLACIAL),
    ]

    # Collect ALL candidates upfront before any processing
    # This ensures each entry only moves one level per consolidate call
    promotion_candidates: dict[tuple, list[str]] = {}
    demotion_candidates: dict[tuple, list[str]] = {}

    with cms.connection() as conn:
        cursor = conn.cursor()

        # Collect promotion candidates for all tier pairs
        # Limit to 1000 per tier to prevent memory issues with large databases
        batch_limit = 1000
        for from_tier, to_tier in promotion_pairs:
            config = DEFAULT_TIER_CONFIGS[from_tier]
            cursor.execute(
                """
                SELECT id FROM continuum_memory
                WHERE tier = ? AND surprise_score > ?
                ORDER BY surprise_score DESC
                LIMIT ?
                """,
                (from_tier.value, config.promotion_threshold, batch_limit),
            )
            ids = [row[0] for row in cursor.fetchall()]
            if ids:
                promotion_candidates[(from_tier, to_tier)] = ids

        # Collect demotion candidates for all tier pairs
        for from_tier, to_tier in demotion_pairs:
            config = DEFAULT_TIER_CONFIGS[from_tier]
            cursor.execute(
                """
                SELECT id FROM continuum_memory
                WHERE tier = ?
                  AND (1.0 - surprise_score) > ?
                  AND update_count > 10
                ORDER BY updated_at ASC
                LIMIT ?
                """,
                (from_tier.value, config.demotion_threshold, batch_limit),
            )
            ids = [row[0] for row in cursor.fetchall()]
            if ids:
                demotion_candidates[(from_tier, to_tier)] = ids

    # Process all promotions (outside the collection connection)
    for (from_tier, to_tier), ids in promotion_candidates.items():
        count = promote_batch(cms, from_tier, to_tier, ids)
        promotions += count
        logger.debug(
            "Promoted %s/%s entries from %s to %s", count, len(ids), from_tier.value, to_tier.value
        )

    # Process all demotions (outside the collection connection)
    for (from_tier, to_tier), ids in demotion_candidates.items():
        count = demote_batch(cms, from_tier, to_tier, ids)
        demotions += count
        logger.debug(
            "Demoted %s/%s entries from %s to %s", count, len(ids), from_tier.value, to_tier.value
        )

    if promotions > 0 or demotions > 0:
        logger.info(
            "[memory] Consolidation complete: %s promotions, %s demotions", promotions, demotions
        )
    else:
        logger.debug("[memory] Consolidation complete: no tier changes")

    return {"promotions": promotions, "demotions": demotions}
