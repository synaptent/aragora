"""
Statistics, cleanup, and retention logic for Continuum Memory System.

Extracted from continuum.py to reduce module size while maintaining functionality.
All functions operate on ContinuumMemory instances passed as the first parameter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

from aragora.memory.tier_manager import DEFAULT_TIER_CONFIGS, MemoryTier

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory, MaxEntriesPerTier

logger = logging.getLogger(__name__)


def get_stats(cms: ContinuumMemory) -> dict[str, Any]:
    """Get statistics about the continuum memory system."""
    with cms.connection() as conn:
        cursor = conn.cursor()

        stats: dict[str, Any] = {}

        # Count by tier
        cursor.execute("""
            SELECT tier, COUNT(*), AVG(importance), AVG(surprise_score), AVG(consolidation_score)
            FROM continuum_memory
            GROUP BY tier
        """)
        stats["by_tier"] = {
            row[0]: {
                "count": row[1],
                "avg_importance": row[2] or 0,
                "avg_surprise": row[3] or 0,
                "avg_consolidation": row[4] or 0,
            }
            for row in cursor.fetchall()
        }

        # Total counts
        cursor.execute("SELECT COUNT(*) FROM continuum_memory")
        row = cursor.fetchone()
        stats["total_memories"] = row[0] if row else 0

        # Transition history
        cursor.execute("""
            SELECT from_tier, to_tier, COUNT(*)
            FROM tier_transitions
            GROUP BY from_tier, to_tier
        """)
        stats["transitions"] = [
            {"from": row[0], "to": row[1], "count": row[2]} for row in cursor.fetchall()
        ]

    return stats


def export_for_tier(cms: ContinuumMemory, tier: MemoryTier) -> list[dict[str, Any]]:
    """Export all memories for a specific tier."""
    entries = cms.retrieve(tiers=[tier], limit=1000)
    return [
        {
            "id": e.id,
            "content": e.content,
            "importance": e.importance,
            "surprise_score": e.surprise_score,
            "consolidation_score": e.consolidation_score,
            "success_rate": e.success_rate,
            "update_count": e.update_count,
        }
        for e in entries
    ]


def get_memory_pressure(cms: ContinuumMemory) -> float:
    """
    Calculate memory pressure as a 0-1 score based on tier utilization.

    Returns the highest utilization ratio across all tiers, where:
    - 0.0 = All tiers are empty
    - 1.0 = At least one tier is at or above its max_entries limit

    Use this to trigger cleanup when pressure exceeds a threshold (e.g., 0.8).

    Returns:
        Float between 0.0 and 1.0 indicating memory pressure level.
    """
    max_entries: MaxEntriesPerTier = cms.hyperparams["max_entries_per_tier"]
    if not max_entries:
        return 0.0

    with cms.connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT tier, COUNT(*)
            FROM continuum_memory
            GROUP BY tier
        """)
        tier_counts: dict[str, int] = {row[0]: row[1] for row in cursor.fetchall()}

    # Calculate utilization for each tier
    max_pressure = 0.0
    tier_names = ["fast", "medium", "slow", "glacial"]
    for tier_name in tier_names:
        # Use .get() with default to handle incomplete max_entries dicts (e.g., in tests)
        raw_limit = max_entries.get(tier_name, 0)
        limit = int(raw_limit) if isinstance(raw_limit, (int, float, str)) else 0
        if limit <= 0:
            continue
        count = tier_counts.get(tier_name, 0)
        pressure = count / limit
        max_pressure = max(max_pressure, pressure)

    return min(max_pressure, 1.0)


def cleanup_expired_memories(
    cms: ContinuumMemory,
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
        cms: ContinuumMemory instance
        tier: Specific tier to cleanup (None = all tiers)
        archive: If True, move to archive table; if False, delete permanently
        max_age_hours: Override default retention (uses tier half-life * multiplier if None)
        tenant_id: Optional tenant ID for multi-tenant isolation.
                   When provided, only cleans up memories belonging to the
                   specified tenant. CRITICAL for multi-tenant environments.

    Returns:
        Dict with counts: {"archived": N, "deleted": N, "by_tier": {...}}
    """
    results: dict[str, Any] = {"archived": 0, "deleted": 0, "by_tier": {}}
    tiers_to_process = [tier] if tier else list(MemoryTier)
    retention_multiplier = cms.hyperparams["retention_multiplier"]

    with cms.connection() as conn:
        cursor = conn.cursor()

        for t in tiers_to_process:
            config = DEFAULT_TIER_CONFIGS[t]
            tier_name = t.value

            # Calculate cutoff time
            if max_age_hours is not None:
                retention_hours = max_age_hours
            else:
                retention_hours = config.half_life_hours * retention_multiplier

            # Naive-UTC clock: rows are stamped with naive-UTC strings
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
                hours=retention_hours
            )
            cutoff_str = cutoff.isoformat()

            # Build tenant filter clause if needed
            tenant_clause = ""
            tenant_params: list[Any] = []
            if tenant_id is not None:
                tenant_clause = " AND json_extract(metadata, '$.tenant_id') = ?"
                tenant_params = [tenant_id]

            if archive:
                # Archive expired entries (excluding red-lined memories)
                cursor.execute(
                    f"""
                    INSERT INTO continuum_memory_archive
                        (id, tier, content, importance, surprise_score,
                         consolidation_score, update_count, success_count,
                         failure_count, semantic_centroid, created_at,
                         updated_at, archive_reason, metadata)
                    SELECT id, tier, content, importance, surprise_score,
                           consolidation_score, update_count, success_count,
                           failure_count, semantic_centroid, created_at,
                           updated_at, 'expired', metadata
                    FROM continuum_memory
                    WHERE tier = ?
                      AND datetime(updated_at) < datetime(?)
                      AND COALESCE(red_line, 0) = 0
                      {tenant_clause}
                    """,  # noqa: S608 -- dynamic clause from internal state
                    (tier_name, cutoff_str, *tenant_params),
                )
                archived_count = cursor.rowcount
            else:
                archived_count = 0

            # Delete from main table (excluding red-lined memories)
            cursor.execute(
                f"""
                DELETE FROM continuum_memory
                WHERE tier = ?
                  AND datetime(updated_at) < datetime(?)
                  AND COALESCE(red_line, 0) = 0
                  {tenant_clause}
                """,  # noqa: S608 -- dynamic clause from internal state
                (tier_name, cutoff_str, *tenant_params),
            )
            deleted_count = cursor.rowcount

            results["by_tier"][tier_name] = {
                "archived": archived_count if archive else 0,
                "deleted": deleted_count,
                "cutoff_hours": retention_hours,
            }
            results["archived"] += archived_count if archive else 0
            results["deleted"] += deleted_count

        conn.commit()

    logger.info(
        "Memory cleanup: archived=%d, deleted=%d",
        results["archived"],
        results["deleted"],
    )
    return results


def delete_memory(
    cms: ContinuumMemory,
    memory_id: str,
    archive: bool = True,
    reason: str = "user_deleted",
    force: bool = False,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """
    Delete a specific memory entry by ID.

    Args:
        cms: ContinuumMemory instance
        memory_id: The ID of the memory to delete
        archive: If True, archive before deletion; if False, delete permanently
        reason: Reason for deletion (stored in archive)
        force: If True, delete even if entry is red-lined (dangerous!)
        tenant_id: Optional tenant ID for multi-tenant isolation.
                   When provided, validates that the entry belongs to
                   the specified tenant before deletion. CRITICAL for
                   preventing cross-tenant data access.

    Returns:
        Dict with result: {"deleted": bool, "archived": bool, "id": str, "blocked": bool}
    """
    result: dict[str, Any] = {
        "deleted": False,
        "archived": False,
        "id": memory_id,
        "blocked": False,
    }

    with cms.connection() as conn:
        cursor = conn.cursor()

        # Check if memory exists and if it's red-lined
        cursor.execute(
            "SELECT id, red_line, red_line_reason, metadata FROM continuum_memory WHERE id = ?",
            (memory_id,),
        )
        row = cursor.fetchone()
        if not row:
            logger.debug("Memory %s not found for deletion", memory_id)
            return result

        # Validate tenant isolation before deletion
        if tenant_id is not None:
            import json

            entry_metadata = json.loads(row[3]) if row[3] else {}
            entry_tenant = entry_metadata.get("tenant_id")
            if entry_tenant and entry_tenant != tenant_id:
                logger.warning(
                    "Cross-tenant deletion blocked: memory=%s entry_tenant=%s request_tenant=%s",
                    memory_id,
                    entry_tenant,
                    tenant_id,
                )
                result["blocked"] = True
                result["reason"] = "cross_tenant_access"
                return result

        # Block deletion of red-lined entries unless forced
        if row[1] and not force:  # red_line is True
            logger.warning(
                "Blocked deletion of red-lined memory %s (reason: %s)",
                memory_id,
                row[2] or "unspecified",
            )
            result["blocked"] = True
            result["red_line_reason"] = row[2] or "unspecified"
            return result

        if archive:
            # Archive the entry before deletion
            cursor.execute(
                """
                INSERT INTO continuum_memory_archive
                    (id, tier, content, importance, surprise_score,
                     consolidation_score, update_count, success_count,
                     failure_count, semantic_centroid, created_at,
                     updated_at, archive_reason, metadata)
                SELECT id, tier, content, importance, surprise_score,
                       consolidation_score, update_count, success_count,
                       failure_count, semantic_centroid, created_at,
                       updated_at, ?, metadata
                FROM continuum_memory
                WHERE id = ?
                """,
                (reason, memory_id),
            )
            result["archived"] = cursor.rowcount > 0

        # Delete from main table
        cursor.execute(
            "DELETE FROM continuum_memory WHERE id = ?",
            (memory_id,),
        )
        result["deleted"] = cursor.rowcount > 0

        conn.commit()

    if result["deleted"]:
        logger.info(
            "Memory %s deleted (archived=%s, reason=%s)", memory_id, result["archived"], reason
        )

    return result


def enforce_tier_limits(
    cms: ContinuumMemory,
    tier: MemoryTier | None = None,
    archive: bool = True,
    tenant_id: str | None = None,
) -> dict[str, int]:
    """
    Enforce max entries per tier by removing lowest importance entries.

    When a tier exceeds its limit, the lowest importance entries are
    archived (or deleted) until the tier is within limits.

    Args:
        cms: ContinuumMemory instance
        tier: Specific tier to enforce (None = all tiers)
        archive: If True, archive excess; if False, delete permanently
        tenant_id: Optional tenant ID for multi-tenant isolation.
                   When provided, only enforces limits for memories belonging
                   to the specified tenant. CRITICAL for multi-tenant environments
                   to prevent cross-tenant data loss during cleanup.

    Returns:
        Dict with counts of removed entries by tier
    """
    results: dict[str, int] = {}
    tiers_to_process = [tier] if tier else list(MemoryTier)
    max_entries: MaxEntriesPerTier = cms.hyperparams["max_entries_per_tier"]

    # Build tenant filter clause if needed
    tenant_clause = ""
    tenant_params: list[Any] = []
    if tenant_id is not None:
        tenant_clause = " AND json_extract(metadata, '$.tenant_id') = ?"
        tenant_params = [tenant_id]

    with cms.connection() as conn:
        cursor = conn.cursor()

        for t in tiers_to_process:
            tier_name = t.value
            # get() returns int | None but we provide a default, so result is always int
            limit = cast(int, max_entries.get(tier_name, 10000))

            # Count current entries (filtered by tenant if specified)
            cursor.execute(
                f"SELECT COUNT(*) FROM continuum_memory WHERE tier = ?{tenant_clause}",  # noqa: S608 -- internal query construction
                (tier_name, *tenant_params),
            )
            row = cursor.fetchone()
            count: int = row[0] if row else 0

            if count <= limit:
                results[tier_name] = 0
                continue

            excess: int = count - limit

            if archive:
                # Archive lowest importance entries (excluding red-lined)
                cursor.execute(
                    f"""
                    INSERT INTO continuum_memory_archive
                        (id, tier, content, importance, surprise_score,
                         consolidation_score, update_count, success_count,
                         failure_count, semantic_centroid, created_at,
                         updated_at, archive_reason, metadata)
                    SELECT id, tier, content, importance, surprise_score,
                           consolidation_score, update_count, success_count,
                           failure_count, semantic_centroid, created_at,
                           updated_at, 'tier_limit', metadata
                    FROM continuum_memory
                    WHERE tier = ?
                      AND COALESCE(red_line, 0) = 0
                      {tenant_clause}
                    ORDER BY importance ASC, updated_at ASC
                    LIMIT ?
                    """,  # noqa: S608 -- dynamic clause from internal state
                    (tier_name, *tenant_params, excess),
                )

            # Delete excess entries (lowest importance first, excluding red-lined)
            cursor.execute(
                f"""
                DELETE FROM continuum_memory
                WHERE id IN (
                    SELECT id FROM continuum_memory
                    WHERE tier = ?
                      AND COALESCE(red_line, 0) = 0
                      {tenant_clause}
                    ORDER BY importance ASC, updated_at ASC
                    LIMIT ?
                )
                """,  # noqa: S608 -- dynamic clause from internal state
                (tier_name, *tenant_params, excess),
            )

            results[tier_name] = cursor.rowcount
            logger.info(
                "Tier limit enforced: tier=%s, removed=%d (limit=%d)%s",
                tier_name,
                cursor.rowcount,
                limit,
                f" tenant={tenant_id}" if tenant_id else "",
            )

        conn.commit()

    return results


def get_archive_stats(cms: ContinuumMemory) -> dict[str, Any]:
    """Get statistics about archived memories."""
    with cms.connection() as conn:
        cursor = conn.cursor()

        stats: dict[str, Any] = {}

        # Count by tier and reason
        cursor.execute("""
            SELECT tier, archive_reason, COUNT(*)
            FROM continuum_memory_archive
            GROUP BY tier, archive_reason
        """)
        by_tier_reason: dict[str, dict[str, int]] = {}
        for row in cursor.fetchall():
            tier, reason, count = row
            if tier not in by_tier_reason:
                by_tier_reason[tier] = {}
            by_tier_reason[tier][reason or "unknown"] = count
        stats["by_tier_reason"] = by_tier_reason

        # Total archived
        cursor.execute("SELECT COUNT(*) FROM continuum_memory_archive")
        row = cursor.fetchone()
        stats["total_archived"] = row[0] if row else 0

        # Oldest and newest archived
        cursor.execute("""
            SELECT MIN(archived_at), MAX(archived_at)
            FROM continuum_memory_archive
        """)
        row = cursor.fetchone()
        stats["oldest_archived"] = row[0]
        stats["newest_archived"] = row[1]

    return stats
