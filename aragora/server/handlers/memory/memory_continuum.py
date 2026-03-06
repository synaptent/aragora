"""Memory continuum operations mixin (MemoryContinuumMixin).

Extracted from memory.py to reduce file size.
Contains continuum retrieval, consolidation, cleanup, and stats operations.

Note: RBAC is handled in MemoryHandler.handle() which calls these mixin methods.
"""

from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

from aragora.rbac.decorators import require_permission  # noqa: F401 - Required for RBAC consistency
from aragora.events.handler_events import emit_handler_event, COMPLETED

# Permission constant - used by parent MemoryHandler
MEMORY_READ_PERMISSION = "memory:read"

from ..base import (
    HandlerResult,
    error_response,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    handle_errors,
    json_response,
    safe_error_message,
)
from ..utils.rate_limit import rate_limit

if TYPE_CHECKING:
    from aragora.memory.continuum import MemoryTier

logger = logging.getLogger(__name__)


class MemoryContinuumMixin:
    """Mixin providing continuum memory operations."""

    # These attributes are defined in the main class
    ctx: dict
    _auth_context: Any

    @rate_limit(requests_per_minute=60, limiter_name="memory_read")
    @handle_errors("continuum memories retrieval")
    def _get_continuum_memories(self, params: dict) -> HandlerResult:
        """Retrieve memories from the continuum memory system."""
        from .memory import CONTINUUM_AVAILABLE, MemoryTier

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        query = get_bounded_string_param(params, "query", "", max_length=500)
        tiers_param = get_bounded_string_param(
            params, "tiers", "fast,medium,slow,glacial", max_length=100
        )
        limit = get_clamped_int_param(params, "limit", 10, min_val=1, max_val=100)
        min_importance = get_bounded_float_param(
            params, "min_importance", 0.0, min_val=0.0, max_val=1.0
        )

        # Parse tiers
        tier_names = [t.strip() for t in tiers_param.split(",")]
        tiers: list[MemoryTier] = []
        for name in tier_names:
            try:
                tiers.append(MemoryTier[name.upper()])
            except KeyError:
                continue

        if not tiers:
            tiers = list(MemoryTier)

        # Retrieve memories (tenant-scoped when available)
        try:
            from aragora.memory.access import (
                filter_entries,
                resolve_tenant_id,
                tenant_enforcement_enabled,
            )
        except ImportError:
            filter_entries = None  # type: ignore[assignment]
            resolve_tenant_id = None  # type: ignore[assignment]
            tenant_enforcement_enabled = None  # type: ignore[assignment]

        enforce_tenant = tenant_enforcement_enabled() if tenant_enforcement_enabled else False
        tenant_id = resolve_tenant_id(self._auth_context) if resolve_tenant_id else None
        if enforce_tenant and not tenant_id:
            if self._auth_context is None:
                enforce_tenant = False
            else:
                return error_response("Tenant/workspace context required for memory access", 400)
        memories = continuum.retrieve(
            query=query,
            tiers=tiers,
            limit=limit,
            min_importance=min_importance,
            tenant_id=tenant_id,
            enforce_tenant_isolation=enforce_tenant,
        )
        if filter_entries:
            memories = filter_entries(memories, self._auth_context)

        return json_response(
            {
                "memories": [
                    {
                        "id": m.id,
                        "tier": m.tier.name.lower(),
                        "content": m.content[:500] + "..." if len(m.content) > 500 else m.content,
                        "importance": m.importance,
                        "surprise_score": getattr(m, "surprise_score", 0.0),
                        "consolidation_score": getattr(m, "consolidation_score", 0.0),
                        "update_count": getattr(m, "update_count", 0),
                        "created_at": str(m.created_at) if hasattr(m, "created_at") else None,
                        "updated_at": str(m.updated_at) if hasattr(m, "updated_at") else None,
                    }
                    for m in memories
                ],
                "count": len(memories),
                "query": query,
                "tiers": [t.name.lower() for t in tiers],
            }
        )

    @rate_limit(requests_per_minute=20, limiter_name="memory_write")
    @handle_errors("memory consolidation")
    def _trigger_consolidation(self) -> HandlerResult:
        """Trigger memory consolidation process."""
        from .memory import CONTINUUM_AVAILABLE

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        start = time.time()

        # Run consolidation
        result = continuum.consolidate()

        duration = time.time() - start

        emit_handler_event("memory", COMPLETED, {"entries_processed": result.get("processed", 0)})
        return json_response(
            {
                "success": True,
                "entries_processed": result.get("processed", 0),
                "entries_promoted": result.get("promoted", 0),
                "entries_consolidated": result.get("consolidated", 0),
                "duration_seconds": round(duration, 2),
            }
        )

    @rate_limit(requests_per_minute=10, limiter_name="memory_delete")
    @handle_errors("memory cleanup")
    def _trigger_cleanup(self, params: dict) -> HandlerResult:
        """Trigger memory cleanup with optional parameters."""
        from .memory import CONTINUUM_AVAILABLE, MemoryTier

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        start = time.time()

        # Parse parameters
        tier_param = get_bounded_string_param(params, "tier", "", max_length=50)
        archive_param = get_bounded_string_param(params, "archive", "true", max_length=10)
        max_age = get_bounded_float_param(
            params, "max_age_hours", 0, min_val=0.0, max_val=8760.0
        )  # Max 1 year

        # Convert tier parameter
        tier = None
        if tier_param:
            try:
                tier = MemoryTier[tier_param.upper()]
            except KeyError:
                return error_response(f"Invalid tier: {tier_param}", 400)

        archive = archive_param.lower() == "true"

        # Run cleanup
        expired_result = continuum.cleanup_expired_memories(
            tier=tier,
            archive=archive,
            max_age_hours=max_age if max_age > 0 else None,
        )

        # Enforce tier limits
        limits_result = continuum.enforce_tier_limits(
            tier=tier,
            archive=archive,
        )

        duration = time.time() - start

        return json_response(
            {
                "success": True,
                "expired": expired_result,
                "tier_limits": limits_result,
                "duration_seconds": round(duration, 2),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="memory_read")
    @handle_errors("tier stats retrieval")
    def _get_tier_stats(self) -> HandlerResult:
        """Get statistics for each memory tier."""
        from .memory import CONTINUUM_AVAILABLE

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        stats = continuum.get_stats()
        return json_response(
            {
                "tiers": stats.get("by_tier", {}),
                "total_memories": stats.get("total_memories", 0),
                "transitions": stats.get("transitions", []),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="memory_read")
    @handle_errors("archive stats retrieval")
    def _get_archive_stats(self) -> HandlerResult:
        """Get statistics for archived memories."""
        from .memory import CONTINUUM_AVAILABLE

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        stats = continuum.get_archive_stats()
        return json_response(stats)

    @rate_limit(requests_per_minute=60, limiter_name="memory_read")
    @handle_errors("memory pressure retrieval")
    def _get_memory_pressure(self) -> HandlerResult:
        """Get current memory pressure and per-tier utilization.

        Returns:
            - pressure: Overall memory pressure (0.0-1.0)
            - status: "normal", "elevated", "high", or "critical"
            - tier_utilization: Dict of tier -> {count, limit, utilization}
            - auto_cleanup_triggered: Whether cleanup was auto-triggered

        Auto-triggers cleanup when pressure > 0.9.
        """
        from .memory import CONTINUUM_AVAILABLE

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        # Get current pressure
        pressure = continuum.get_memory_pressure()

        # Get per-tier stats for utilization breakdown
        stats = continuum.get_stats()
        tier_stats = stats.get("by_tier", {})

        # Build tier utilization breakdown
        tier_utilization = {}
        tier_limits = {
            "FAST": 100,
            "MEDIUM": 500,
            "SLOW": 1000,
            "GLACIAL": 5000,
        }

        for tier_name, tier_data in tier_stats.items():
            count = tier_data.get("count", 0)
            limit = tier_limits.get(tier_name, 1000)
            utilization = count / limit if limit > 0 else 0.0
            tier_utilization[tier_name] = {
                "count": count,
                "limit": limit,
                "utilization": round(utilization, 3),
            }

        # Determine status
        if pressure < 0.5:
            status = "normal"
        elif pressure < 0.8:
            status = "elevated"
        elif pressure < 0.9:
            status = "high"
        else:
            status = "critical"

        # Note: GET endpoints should be idempotent - no auto-cleanup here.
        # Use POST /api/memory/continuum/cleanup to trigger cleanup explicitly.

        response_data = {
            "pressure": round(pressure, 3),
            "status": status,
            "tier_utilization": tier_utilization,
            "total_memories": stats.get("total_memories", 0),
            "cleanup_recommended": pressure > 0.9,  # Hint to caller
        }

        return json_response(response_data)

    @rate_limit(requests_per_minute=10, limiter_name="memory_delete")
    @handle_errors("memory deletion")
    @require_permission("memory:delete")
    def _delete_memory(self, memory_id: str) -> HandlerResult:
        """Delete a memory by ID."""
        from .memory import CONTINUUM_AVAILABLE

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        # Check if delete method exists on continuum
        if not hasattr(continuum, "delete"):
            return error_response(
                "Memory deletion not supported by this continuum backend. "
                "Upgrade to a tier that supports deletion or use a different storage backend.",
                501,
            )

        try:
            try:
                from aragora.memory.access import resolve_tenant_id, tenant_enforcement_enabled
            except (ImportError, AttributeError):
                resolve_tenant_id = None  # type: ignore[assignment]
                tenant_enforcement_enabled = None  # type: ignore[assignment]

            enforce_tenant = tenant_enforcement_enabled() if tenant_enforcement_enabled else False
            tenant_id = resolve_tenant_id(self._auth_context) if resolve_tenant_id else None
            if enforce_tenant and not tenant_id:
                if self._auth_context is None:
                    enforce_tenant = False
                else:
                    return error_response(
                        "Tenant/workspace context required for memory deletion", 400
                    )

            success = continuum.delete(memory_id, tenant_id=tenant_id)
            if success:
                return json_response(
                    {"success": True, "message": f"Memory {memory_id} deleted successfully"}
                )
            else:
                return error_response(f"Memory not found: {memory_id}", 404)
        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            return error_response(safe_error_message(e, "delete memory"), 500)

    @rate_limit(requests_per_minute=60, limiter_name="memory_read")
    @handle_errors("get all tiers")
    def _get_all_tiers(self) -> HandlerResult:
        """Get comprehensive information about all memory tiers.

        Returns detailed stats for each tier including:
        - Name, description, and TTL
        - Current count and limit
        - Utilization percentage
        - Average importance and surprise scores
        - Recent activity count
        """
        from .memory import CONTINUUM_AVAILABLE

        if not CONTINUUM_AVAILABLE:
            return error_response("Continuum memory system not available", 503)

        continuum = self.ctx.get("continuum_memory")
        if not continuum:
            return error_response("Continuum memory not initialized", 503)

        # Get base stats
        stats = continuum.get_stats()
        tier_stats = stats.get("by_tier", {})

        # Tier metadata with explicit types
        tier_info: dict[str, dict[str, str | int]] = {
            "FAST": {
                "name": "Fast",
                "description": "Immediate context, very short-term",
                "ttl_seconds": 60,
                "limit": 100,
            },
            "MEDIUM": {
                "name": "Medium",
                "description": "Session memory, short-term",
                "ttl_seconds": 3600,
                "limit": 500,
            },
            "SLOW": {
                "name": "Slow",
                "description": "Cross-session learning, medium-term",
                "ttl_seconds": 86400,
                "limit": 1000,
            },
            "GLACIAL": {
                "name": "Glacial",
                "description": "Long-term patterns and insights",
                "ttl_seconds": 604800,
                "limit": 5000,
            },
        }

        # Build comprehensive tier data
        tiers = []
        for tier_name, info in tier_info.items():
            tier_data = tier_stats.get(tier_name, {})
            count = tier_data.get("count", 0)
            limit = int(info["limit"])
            ttl_seconds = int(info["ttl_seconds"])
            utilization = count / limit if limit > 0 else 0.0

            tiers.append(
                {
                    "id": tier_name.lower(),
                    "name": info["name"],
                    "description": info["description"],
                    "ttl_seconds": ttl_seconds,
                    "ttl_human": self._format_ttl(ttl_seconds),
                    "count": count,
                    "limit": limit,
                    "utilization": round(utilization, 3),
                    "avg_importance": tier_data.get("avg_importance", 0.0),
                    "avg_surprise": tier_data.get("avg_surprise", 0.0),
                }
            )

        return json_response(
            {
                "tiers": tiers,
                "total_memories": stats.get("total_memories", 0),
                "transitions_24h": len(stats.get("transitions", [])),
            }
        )

    def _format_ttl(self, seconds: int) -> str:
        """Format TTL in human-readable form."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            return f"{seconds // 60}m"
        elif seconds < 86400:
            return f"{seconds // 3600}h"
        else:
            return f"{seconds // 86400}d"
