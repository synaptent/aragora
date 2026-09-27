"""
Memory Namespace API

Provides methods for interacting with the memory system:
- Memory search across tiers
- Statistics and monitoring (stats, tier-stats, archive-stats, pressure, analytics)
- Tier listing
- Continuum retrieval
- Critique operations (list, store)

Note: Several "Advanced Operations" methods below (query, get_tier, move,
demote, store_critique, ...) target routes that are declared in the memory
handler's ROUTES list but never dispatched. Because ``MemoryHandler.can_handle``
claims all of ``/api/v1/memory/*``, these calls do not 404: the dispatcher
matches the handler, gets no result, and returns HTTP 500 with code
``handler_no_result`` (or, where a same-path GET branch exists, silently falls
through to it and returns 200 with the GET response). They are kept for
backward compatibility, emit :class:`DeprecationWarning` at runtime, and are
marked DEPRECATED in their docstrings; prefer the documented working methods.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import quote

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient

MemoryTier = Literal["fast", "medium", "slow", "glacial"]


def _warn_deprecated(message: str) -> None:
    """Emit a runtime DeprecationWarning for a dead or drifted SDK method."""
    warnings.warn(message, DeprecationWarning, stacklevel=3)


class MemoryAPI:
    """Synchronous Memory API."""

    def __init__(self, client: AragoraClient):
        self._client = client

    # ===========================================================================
    # Search Operations
    # ===========================================================================

    def search(
        self,
        query: str,
        *,
        tier: list[MemoryTier] | None = None,
        limit: int = 20,
        min_importance: float = 0.0,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        """Search memories across tiers."""
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "min_importance": min_importance,
            "sort": sort,
        }
        if tier:
            params["tier"] = ",".join(tier)
        return self._client.request("GET", "/api/v1/memory/search", params=params)

    # ===========================================================================
    # Statistics and Monitoring
    # ===========================================================================

    def stats(self) -> dict[str, Any]:
        """
        Get memory system statistics.

        DEPRECATED: No memory-handler branch serves GET /api/v1/memory/stats.
        After version-stripping the request is routed to the analytics
        handler's GET /api/memory/stats, which requires the ``analytics:read``
        permission (not ``memory:read``) and returns only
        ``{"stats": {"embeddings_db": bool, "insights_db": bool,
        "continuum_memory": bool}}`` -- database file-existence flags, not
        memory statistics. Use get_tier_stats(), list_tiers(), or
        get_pressure() for real memory metrics.

        Returns:
            Dict with analytics-handler file-existence flags (see above)
        """
        return self._client.request("GET", "/api/v1/memory/stats")

    def get_tier_stats(self) -> dict[str, Any]:
        """Get tier statistics."""
        return self._client.request("GET", "/api/v1/memory/tier-stats")

    def get_archive_stats(self) -> dict[str, Any]:
        """Get archive statistics."""
        return self._client.request("GET", "/api/v1/memory/archive-stats")

    def get_pressure(self) -> dict[str, Any]:
        """
        Get memory pressure and utilization.

        Returns:
            Dict with utilization percentage, pressure level, and recommendations
        """
        return self._client.request("GET", "/api/v1/memory/pressure")

    def get_analytics(
        self,
        *,
        days: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        granularity: str | None = None,
    ) -> dict[str, Any]:
        """
        Get per-tier memory analytics.

        GET /api/v1/memory/analytics returns tier stats, promotion
        effectiveness, learning velocity, and recommendations over a
        ``days`` window.

        Args:
            days: Analysis window in days (1-365, server default 30) --
                the only parameter the server reads
            start_time: DEPRECATED -- ignored by the server
            end_time: DEPRECATED -- ignored by the server
            granularity: DEPRECATED -- ignored by the server; sent on the
                wire only when explicitly provided

        Returns:
            Dict with per-tier analytics (``tier_stats``,
            ``promotion_effectiveness``, ``learning_velocity``, ...)
        """
        params: dict[str, Any] = {}
        if days is not None:
            params["days"] = days
        if granularity is not None:
            params["granularity"] = granularity
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return self._client.request("GET", "/api/v1/memory/analytics", params=params)

    # ===========================================================================
    # Tier Operations
    # ===========================================================================

    def list_tiers(self) -> dict[str, Any]:
        """List all memory tiers with detailed stats."""
        return self._client.request("GET", "/api/v1/memory/tiers")

    def tiers(self) -> dict[str, Any]:
        """
        Get information about memory tiers.

        Alias for list_tiers() for TypeScript SDK compatibility.
        """
        return self.list_tiers()

    # ===========================================================================
    # Continuum Operations
    # ===========================================================================

    def retrieve_continuum(
        self,
        query: str = "",
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> dict[str, Any]:
        """Retrieve memories from the continuum."""
        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_importance": min_importance,
        }
        if tiers:
            params["tiers"] = ",".join(tiers)
        return self._client.request("GET", "/api/v1/memory/continuum/retrieve", params=params)

    def retrieve_from_continuum(
        self,
        query: str,
        *,
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> dict[str, Any]:
        """
        Retrieve content from the continuum memory system.

        Alias for retrieve_continuum() for TypeScript SDK compatibility.
        """
        return self.retrieve_continuum(
            query, tiers=tiers, limit=limit, min_importance=min_importance
        )

    def consolidate(self) -> dict[str, Any]:
        """
        Trigger continuum memory consolidation.

        POST /api/v1/memory/continuum/consolidate (requires authentication).
        This is the supported server-side maintenance operation; prefer it
        over the deprecated prune()/compact()/sync_memories()/vacuum()
        methods, whose routes are never dispatched.

        Returns:
            Dict with consolidation result
        """
        return self._client.request("POST", "/api/v1/memory/continuum/consolidate", json={})

    # ===========================================================================
    # Critique Operations
    # ===========================================================================

    def list_critiques(
        self,
        agent: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Browse critique store entries."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if agent:
            params["agent"] = agent
        return self._client.request("GET", "/api/v1/memory/critiques", params=params)

    def critiques(
        self,
        *,
        agent: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Get stored critiques from memory.

        Alias for list_critiques() for TypeScript SDK compatibility.
        """
        return self.list_critiques(agent=agent, limit=limit, offset=offset)

    def store(
        self,
        content: str,
        *,
        tier: str = "fast",
        importance: float | None = None,
    ) -> dict[str, Any]:
        """
        Store a new memory entry in continuum memory.

        Args:
            content: The memory content to store
            tier: Target memory tier (fast, medium, slow, glacial)
            importance: Importance score between 0.0 and 1.0

        Returns:
            Dict with the stored entry ID and tier
        """
        body: dict[str, Any] = {"content": content, "tier": tier}
        if importance is not None:
            body["importance"] = importance
        return self._client.request("POST", "/api/v1/memory/store", json=body)

    def delete_entry(self, memory_id: str) -> dict[str, Any]:
        """
        Delete a continuum memory entry by ID.

        Args:
            memory_id: ID of the entry to delete (as returned by store())

        Returns:
            Dict with success flag and message (404 if the entry does not exist)
        """
        return self._client.request("DELETE", f"/api/v1/memory/continuum/{memory_id}")

    def store_critique(
        self,
        critique: str,
        *,
        agent: str,
        debate_id: str | None = None,
        target_agent: str | None = None,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Store a critique in memory.

        DEPRECATED: The server has no store-critique endpoint. This POST
        is a silent no-op that LOOKS successful: ``MemoryHandler.handle_post``
        has no /critiques branch, so the dispatcher falls through to the GET
        handler and returns HTTP 200 with the critique *listing* -- nothing
        is stored and no critique ID is returned. Critiques are recorded
        server-side during debates.

        Args:
            critique: The critique content
            agent: Agent that generated the critique
            debate_id: Associated debate ID
            target_agent: Agent being critiqued
            score: Critique quality score
            metadata: Additional metadata

        Returns:
            The critique listing (not a stored-critique receipt)
        """
        _warn_deprecated(
            "memory.store_critique() is a silent no-op: the server has no "
            "store-critique endpoint; the POST returns the critique listing "
            "and stores nothing."
        )
        body: dict[str, Any] = {"critique": critique, "agent": agent}
        if debate_id:
            body["debate_id"] = debate_id
        if target_agent:
            body["target_agent"] = target_agent
        if score is not None:
            body["score"] = score
        if metadata:
            body["metadata"] = metadata
        return self._client.request("POST", "/api/v1/memory/critiques", json=body)

    # ===========================================================================
    # Progressive Retrieval & Viewer
    # ===========================================================================

    def search_index(
        self,
        query: str,
        *,
        limit: int = 20,
        min_importance: float = 0.0,
        tiers: list[MemoryTier] | None = None,
        use_hybrid: bool = False,
    ) -> dict[str, Any]:
        """
        Progressive retrieval stage 1: compact index entries.

        GET /api/v1/memory/search-index

        Args:
            query: Search query
            limit: Maximum entries to return (1-100)
            min_importance: Minimum importance threshold (0.0-1.0)
            tiers: Filter by memory tiers
            use_hybrid: Enable hybrid search mode

        Returns:
            Dict with compact index entries for progressive loading
        """
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "min_importance": min_importance,
            "use_hybrid": str(use_hybrid).lower(),
        }
        if tiers:
            params["tiers"] = ",".join(tiers)
        return self._client.request("GET", "/api/v1/memory/search-index", params=params)

    def search_timeline(
        self,
        query: str,
        *,
        limit: int = 20,
        min_importance: float = 0.0,
        tiers: list[MemoryTier] | None = None,
    ) -> dict[str, Any]:
        """
        Progressive retrieval: timeline-ordered search results.

        GET /api/v1/memory/search-timeline

        Args:
            query: Search query
            limit: Maximum entries to return
            min_importance: Minimum importance threshold
            tiers: Filter by memory tiers

        Returns:
            Dict with timeline-ordered memory entries
        """
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "min_importance": min_importance,
        }
        if tiers:
            params["tiers"] = ",".join(tiers)
        return self._client.request("GET", "/api/v1/memory/search-timeline", params=params)

    def list_entries(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        tier: MemoryTier | None = None,
    ) -> dict[str, Any]:
        """
        List memory entries.

        GET /api/v1/memory/entries

        Args:
            limit: Maximum entries to return
            offset: Pagination offset
            tier: Filter by memory tier

        Returns:
            Dict with memory entries and pagination
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if tier:
            params["tier"] = tier
        return self._client.request("GET", "/api/v1/memory/entries", params=params)

    def get_viewer(self) -> dict[str, Any]:
        """
        Get memory viewer HTML interface.

        GET /api/v1/memory/viewer

        Returns:
            Dict with viewer HTML content
        """
        return self._client.request("GET", "/api/v1/memory/viewer")

    # ===========================================================================
    # Advanced Operations
    # ===========================================================================

    def compact(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger memory compaction.

        DEPRECATED: POST /api/v1/memory/compact is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Use
        consolidate() for the supported maintenance operation.
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/memory/compact", json=body)

    def get_context(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get memory context for current session.

        DEPRECATED: GET /api/v1/memory/context is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). The server
        has no memory-context store; there is no replacement endpoint.
        """
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/v1/memory/context", params=params)

    def get_cross_debate(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get cross-debate memory entries.

        DEPRECATED: GET /api/v1/memory/cross-debate is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Cross-debate
        memory is injected automatically during debates
        (``enable_cross_debate_memory``); there is no HTTP endpoint.
        """
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/v1/memory/cross-debate", params=params)

    def inject_cross_debate(
        self,
        debate_id: str,
        entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Inject cross-debate memories into a debate.

        DEPRECATED: POST /api/v1/memory/cross-debate/inject is declared in
        the memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        Cross-debate memory is injected automatically during debates
        (``enable_cross_debate_memory``); there is no HTTP endpoint.
        """
        body: dict[str, Any] = {"debate_id": debate_id}
        if entries:
            body["entries"] = entries
        return self._client.request("POST", "/api/v1/memory/cross-debate/inject", json=body)

    def export_memories(
        self,
        format: str = "json",
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Export memories.

        DEPRECATED: POST /api/v1/memory/export is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). There is
        no replacement endpoint.
        """
        body: dict[str, Any] = {"format": format}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/memory/export", json=body)

    def import_memories(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import memories from exported data.

        DEPRECATED: POST /api/v1/memory/import is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). There is
        no replacement endpoint.
        """
        return self._client.request("POST", "/api/v1/memory/import", json=data)

    def prune(
        self,
        workspace_id: str | None = None,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        """Prune old or low-importance memories.

        DEPRECATED: POST /api/v1/memory/prune is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Expired
        entries are cleaned via POST /api/v1/memory/continuum/cleanup; see
        also consolidate().
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        if max_age_days is not None:
            body["max_age_days"] = max_age_days
        return self._client.request("POST", "/api/v1/memory/prune", json=body)

    def query(
        self,
        prompt: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Query memories using natural language.

        DEPRECATED: POST /api/v1/memory/query is declared in the handler's
        ROUTES list but never dispatched, so this method always fails with
        HTTP 500 (``handler_no_result``). Use search() or
        retrieve_continuum() instead.
        """
        _warn_deprecated(
            "memory.query() targets an undispatched route (HTTP 500 "
            "handler_no_result); use search() or retrieve_continuum()."
        )
        body: dict[str, Any] = {"prompt": prompt}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/memory/query", json=body)

    def rebuild_index(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Rebuild the memory search index.

        DEPRECATED: POST /api/v1/memory/rebuild-index is declared in the
        memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        There is no replacement endpoint.
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/memory/rebuild-index", json=body)

    def semantic_search(
        self,
        query: str,
        *,
        limit: int = 20,
        min_similarity: float = 0.5,
    ) -> dict[str, Any]:
        """Perform semantic search across memories.

        DEPRECATED: POST /api/v1/memory/semantic-search is declared in the
        memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        Use search() or search_index(use_hybrid=True) instead.
        """
        body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_similarity": min_similarity,
        }
        return self._client.request("POST", "/api/v1/memory/semantic-search", json=body)

    def list_snapshots(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List memory snapshots.

        DEPRECATED: GET /api/v1/memory/snapshots is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). There is
        no replacement endpoint.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.request("GET", "/api/v1/memory/snapshots", params=params)

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Get a specific memory snapshot.

        DEPRECATED: GET /api/v1/memory/snapshots/{id} is declared in the
        memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        There is no replacement endpoint.
        """
        return self._client.request("GET", f"/api/v1/memory/snapshots/{snapshot_id}")

    def restore_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Restore a memory snapshot.

        DEPRECATED: POST /api/v1/memory/snapshots/{id}/restore is declared in
        the memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        There is no replacement endpoint.
        """
        return self._client.request(
            "POST", f"/api/v1/memory/snapshots/{snapshot_id}/restore", json={}
        )

    def sync_memories(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Sync memories across tiers.

        DEPRECATED: POST /api/v1/memory/sync is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Use
        consolidate() for the supported maintenance operation.
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/memory/sync", json=body)

    def get_tier(self, tier: str) -> dict[str, Any]:
        """Get detailed information about a specific memory tier.

        DEPRECATED: GET /api/v1/memory/tier/{tier} is declared in the
        handler's ROUTES list but never dispatched, so this method always
        fails with HTTP 500 (``handler_no_result``). Use list_tiers() for
        tier stats or retrieve_continuum(tiers=[...]) for entries.
        """
        _warn_deprecated(
            "memory.get_tier() targets an undispatched route (HTTP 500 "
            "handler_no_result); use list_tiers() or retrieve_continuum()."
        )
        return self._client.request("GET", f"/api/v1/memory/tier/{tier}")

    def vacuum(self) -> dict[str, Any]:
        """Run vacuum to reclaim storage space.

        DEPRECATED: POST /api/v1/memory/vacuum is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Use
        consolidate() for the supported maintenance operation.
        """
        return self._client.request("POST", "/api/v1/memory/vacuum", json={})

    def promote(self, key: str, target_tier: str | None = None) -> dict[str, Any]:
        """Promote a memory entry to a higher tier.

        DEPRECATED: The server requires ``target_tier`` -- calls without it
        fail with 400 -- and responds with
        ``{"success": bool, "previous_tier": str | None}``. Use
        promote_entry() instead.
        """
        _warn_deprecated(
            "memory.promote() fails with 400 unless target_tier is given "
            "and its documented response shape is wrong; use promote_entry()."
        )
        body: dict[str, Any] = {}
        if target_tier:
            body["target_tier"] = target_tier
        return self._client.request("POST", f"/api/v1/memory/{key}/promote", json=body)

    def promote_entry(self, memory_id: str, target_tier: str) -> dict[str, Any]:
        """
        Promote a continuum memory entry to a target tier.

        Matches the server contract for POST /api/v1/memory/{id}/promote.

        Args:
            memory_id: ID of the entry to promote (as returned by the store endpoint)
            target_tier: Tier to promote the entry to (fast, medium, slow, glacial)

        Returns:
            Dict with ``success`` flag and ``previous_tier``. A missing
            entry is HTTP 200 with ``{"success": False, "previous_tier":
            None, "error": "Memory entry not found"}``, not a 404.
        """
        # Hoisted so contract extractors see a plain {placeholder} path.
        encoded_id = quote(memory_id, safe="")
        return self._client.request(
            "POST",
            f"/api/v1/memory/{encoded_id}/promote",
            json={"target_tier": target_tier},
        )

    def demote(self, key: str, target_tier: str | None = None) -> dict[str, Any]:
        """Demote a memory entry to a lower tier.

        DEPRECATED: POST /api/v1/memory/{key}/demote is declared in the
        handler's ROUTES list but never dispatched, so this method always
        fails with HTTP 500 (``handler_no_result``). The server has no
        demote endpoint -- demotion happens automatically during
        consolidation and cleanup.
        """
        _warn_deprecated(
            "memory.demote() targets an undispatched route (HTTP 500 "
            "handler_no_result); the server has no demote endpoint."
        )
        body: dict[str, Any] = {}
        if target_tier:
            body["target_tier"] = target_tier
        return self._client.request("POST", f"/api/v1/memory/{key}/demote", json=body)

    def move(self, key: str, target_tier: str) -> dict[str, Any]:
        """Move a memory entry to a specific tier.

        DEPRECATED: POST /api/v1/memory/{key}/move is declared in the
        handler's ROUTES list but never dispatched, so this method always
        fails with HTTP 500 (``handler_no_result``). The only server-side
        tier mutation is promotion -- use promote_entry().
        """
        _warn_deprecated(
            "memory.move() targets an undispatched route (HTTP 500 "
            "handler_no_result); use promote_entry()."
        )
        body: dict[str, Any] = {"target_tier": target_tier}
        return self._client.request("POST", f"/api/v1/memory/{key}/move", json=body)


class AsyncMemoryAPI:
    """Asynchronous Memory API."""

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    # ===========================================================================
    # Search Operations
    # ===========================================================================

    async def search(
        self,
        query: str,
        *,
        tier: list[MemoryTier] | None = None,
        limit: int = 20,
        min_importance: float = 0.0,
        sort: str = "relevance",
    ) -> dict[str, Any]:
        """Search memories across tiers."""
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "min_importance": min_importance,
            "sort": sort,
        }
        if tier:
            params["tier"] = ",".join(tier)
        return await self._client.request("GET", "/api/v1/memory/search", params=params)

    # ===========================================================================
    # Statistics and Monitoring
    # ===========================================================================

    async def stats(self) -> dict[str, Any]:
        """
        Get memory system statistics.

        DEPRECATED: No memory-handler branch serves GET /api/v1/memory/stats.
        After version-stripping the request is routed to the analytics
        handler's GET /api/memory/stats, which requires the ``analytics:read``
        permission (not ``memory:read``) and returns only
        ``{"stats": {"embeddings_db": bool, "insights_db": bool,
        "continuum_memory": bool}}`` -- database file-existence flags, not
        memory statistics. Use get_tier_stats(), list_tiers(), or
        get_pressure() for real memory metrics.

        Returns:
            Dict with analytics-handler file-existence flags (see above)
        """
        return await self._client.request("GET", "/api/v1/memory/stats")

    async def get_tier_stats(self) -> dict[str, Any]:
        """Get tier statistics."""
        return await self._client.request("GET", "/api/v1/memory/tier-stats")

    async def get_archive_stats(self) -> dict[str, Any]:
        """Get archive statistics."""
        return await self._client.request("GET", "/api/v1/memory/archive-stats")

    async def get_pressure(self) -> dict[str, Any]:
        """
        Get memory pressure and utilization.

        Returns:
            Dict with utilization percentage, pressure level, and recommendations
        """
        return await self._client.request("GET", "/api/v1/memory/pressure")

    async def get_analytics(
        self,
        *,
        days: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        granularity: str | None = None,
    ) -> dict[str, Any]:
        """
        Get per-tier memory analytics.

        GET /api/v1/memory/analytics returns tier stats, promotion
        effectiveness, learning velocity, and recommendations over a
        ``days`` window.

        Args:
            days: Analysis window in days (1-365, server default 30) --
                the only parameter the server reads
            start_time: DEPRECATED -- ignored by the server
            end_time: DEPRECATED -- ignored by the server
            granularity: DEPRECATED -- ignored by the server; sent on the
                wire only when explicitly provided

        Returns:
            Dict with per-tier analytics (``tier_stats``,
            ``promotion_effectiveness``, ``learning_velocity``, ...)
        """
        params: dict[str, Any] = {}
        if days is not None:
            params["days"] = days
        if granularity is not None:
            params["granularity"] = granularity
        if start_time:
            params["start_time"] = start_time
        if end_time:
            params["end_time"] = end_time
        return await self._client.request("GET", "/api/v1/memory/analytics", params=params)

    # ===========================================================================
    # Tier Operations
    # ===========================================================================

    async def list_tiers(self) -> dict[str, Any]:
        """List all memory tiers with detailed stats."""
        return await self._client.request("GET", "/api/v1/memory/tiers")

    async def tiers(self) -> dict[str, Any]:
        """
        Get information about memory tiers.

        Alias for list_tiers() for TypeScript SDK compatibility.
        """
        return await self.list_tiers()

    # ===========================================================================
    # Continuum Operations
    # ===========================================================================

    async def retrieve_continuum(
        self,
        query: str = "",
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> dict[str, Any]:
        """Retrieve memories from the continuum."""
        params: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_importance": min_importance,
        }
        if tiers:
            params["tiers"] = ",".join(tiers)
        return await self._client.request("GET", "/api/v1/memory/continuum/retrieve", params=params)

    async def retrieve_from_continuum(
        self,
        query: str,
        *,
        tiers: list[MemoryTier] | None = None,
        limit: int = 10,
        min_importance: float = 0.0,
    ) -> dict[str, Any]:
        """
        Retrieve content from the continuum memory system.

        Alias for retrieve_continuum() for TypeScript SDK compatibility.
        """
        return await self.retrieve_continuum(
            query, tiers=tiers, limit=limit, min_importance=min_importance
        )

    async def consolidate(self) -> dict[str, Any]:
        """
        Trigger continuum memory consolidation.

        POST /api/v1/memory/continuum/consolidate (requires authentication).
        This is the supported server-side maintenance operation; prefer it
        over the deprecated prune()/compact()/sync_memories()/vacuum()
        methods, whose routes are never dispatched.

        Returns:
            Dict with consolidation result
        """
        return await self._client.request("POST", "/api/v1/memory/continuum/consolidate", json={})

    # ===========================================================================
    # Critique Operations
    # ===========================================================================

    async def list_critiques(
        self,
        agent: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Browse critique store entries."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if agent:
            params["agent"] = agent
        return await self._client.request("GET", "/api/v1/memory/critiques", params=params)

    async def critiques(
        self,
        *,
        agent: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        Get stored critiques from memory.

        Alias for list_critiques() for TypeScript SDK compatibility.
        """
        return await self.list_critiques(agent=agent, limit=limit, offset=offset)

    async def store(
        self,
        content: str,
        *,
        tier: str = "fast",
        importance: float | None = None,
    ) -> dict[str, Any]:
        """
        Store a new memory entry in continuum memory.

        Args:
            content: The memory content to store
            tier: Target memory tier (fast, medium, slow, glacial)
            importance: Importance score between 0.0 and 1.0

        Returns:
            Dict with the stored entry ID and tier
        """
        body: dict[str, Any] = {"content": content, "tier": tier}
        if importance is not None:
            body["importance"] = importance
        return await self._client.request("POST", "/api/v1/memory/store", json=body)

    async def delete_entry(self, memory_id: str) -> dict[str, Any]:
        """
        Delete a continuum memory entry by ID.

        Args:
            memory_id: ID of the entry to delete (as returned by store())

        Returns:
            Dict with success flag and message (404 if the entry does not exist)
        """
        return await self._client.request("DELETE", f"/api/v1/memory/continuum/{memory_id}")

    async def store_critique(
        self,
        critique: str,
        *,
        agent: str,
        debate_id: str | None = None,
        target_agent: str | None = None,
        score: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Store a critique in memory.

        DEPRECATED: The server has no store-critique endpoint. This POST
        is a silent no-op that LOOKS successful: ``MemoryHandler.handle_post``
        has no /critiques branch, so the dispatcher falls through to the GET
        handler and returns HTTP 200 with the critique *listing* -- nothing
        is stored and no critique ID is returned. Critiques are recorded
        server-side during debates.

        Args:
            critique: The critique content
            agent: Agent that generated the critique
            debate_id: Associated debate ID
            target_agent: Agent being critiqued
            score: Critique quality score
            metadata: Additional metadata

        Returns:
            The critique listing (not a stored-critique receipt)
        """
        _warn_deprecated(
            "memory.store_critique() is a silent no-op: the server has no "
            "store-critique endpoint; the POST returns the critique listing "
            "and stores nothing."
        )
        body: dict[str, Any] = {"critique": critique, "agent": agent}
        if debate_id:
            body["debate_id"] = debate_id
        if target_agent:
            body["target_agent"] = target_agent
        if score is not None:
            body["score"] = score
        if metadata:
            body["metadata"] = metadata
        return await self._client.request("POST", "/api/v1/memory/critiques", json=body)

    # ===========================================================================
    # Progressive Retrieval & Viewer
    # ===========================================================================

    async def search_index(
        self,
        query: str,
        *,
        limit: int = 20,
        min_importance: float = 0.0,
        tiers: list[MemoryTier] | None = None,
        use_hybrid: bool = False,
    ) -> dict[str, Any]:
        """Progressive retrieval stage 1: compact index entries. GET /api/v1/memory/search-index"""
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "min_importance": min_importance,
            "use_hybrid": str(use_hybrid).lower(),
        }
        if tiers:
            params["tiers"] = ",".join(tiers)
        return await self._client.request("GET", "/api/v1/memory/search-index", params=params)

    async def search_timeline(
        self,
        query: str,
        *,
        limit: int = 20,
        min_importance: float = 0.0,
        tiers: list[MemoryTier] | None = None,
    ) -> dict[str, Any]:
        """Progressive retrieval: timeline-ordered results. GET /api/v1/memory/search-timeline"""
        params: dict[str, Any] = {
            "q": query,
            "limit": limit,
            "min_importance": min_importance,
        }
        if tiers:
            params["tiers"] = ",".join(tiers)
        return await self._client.request("GET", "/api/v1/memory/search-timeline", params=params)

    async def list_entries(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        tier: MemoryTier | None = None,
    ) -> dict[str, Any]:
        """List memory entries. GET /api/v1/memory/entries"""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if tier:
            params["tier"] = tier
        return await self._client.request("GET", "/api/v1/memory/entries", params=params)

    async def get_viewer(self) -> dict[str, Any]:
        """Get memory viewer HTML interface. GET /api/v1/memory/viewer"""
        return await self._client.request("GET", "/api/v1/memory/viewer")

    # ===========================================================================
    # Advanced Operations
    # ===========================================================================

    async def compact(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger memory compaction.

        DEPRECATED: POST /api/v1/memory/compact is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Use
        consolidate() for the supported maintenance operation.
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/memory/compact", json=body)

    async def get_context(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get memory context for current session.

        DEPRECATED: GET /api/v1/memory/context is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). The server
        has no memory-context store; there is no replacement endpoint.
        """
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/v1/memory/context", params=params)

    async def get_cross_debate(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get cross-debate memory entries.

        DEPRECATED: GET /api/v1/memory/cross-debate is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Cross-debate
        memory is injected automatically during debates
        (``enable_cross_debate_memory``); there is no HTTP endpoint.
        """
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/v1/memory/cross-debate", params=params)

    async def inject_cross_debate(
        self,
        debate_id: str,
        entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Inject cross-debate memories into a debate.

        DEPRECATED: POST /api/v1/memory/cross-debate/inject is declared in
        the memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        Cross-debate memory is injected automatically during debates
        (``enable_cross_debate_memory``); there is no HTTP endpoint.
        """
        body: dict[str, Any] = {"debate_id": debate_id}
        if entries:
            body["entries"] = entries
        return await self._client.request("POST", "/api/v1/memory/cross-debate/inject", json=body)

    async def export_memories(
        self,
        format: str = "json",
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Export memories.

        DEPRECATED: POST /api/v1/memory/export is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). There is
        no replacement endpoint.
        """
        body: dict[str, Any] = {"format": format}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/memory/export", json=body)

    async def import_memories(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import memories from exported data.

        DEPRECATED: POST /api/v1/memory/import is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). There is
        no replacement endpoint.
        """
        return await self._client.request("POST", "/api/v1/memory/import", json=data)

    async def prune(
        self,
        workspace_id: str | None = None,
        max_age_days: int | None = None,
    ) -> dict[str, Any]:
        """Prune old or low-importance memories.

        DEPRECATED: POST /api/v1/memory/prune is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Expired
        entries are cleaned via POST /api/v1/memory/continuum/cleanup; see
        also consolidate().
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        if max_age_days is not None:
            body["max_age_days"] = max_age_days
        return await self._client.request("POST", "/api/v1/memory/prune", json=body)

    async def query(
        self,
        prompt: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Query memories using natural language.

        DEPRECATED: POST /api/v1/memory/query is declared in the handler's
        ROUTES list but never dispatched, so this method always fails with
        HTTP 500 (``handler_no_result``). Use search() or
        retrieve_continuum() instead.
        """
        _warn_deprecated(
            "memory.query() targets an undispatched route (HTTP 500 "
            "handler_no_result); use search() or retrieve_continuum()."
        )
        body: dict[str, Any] = {"prompt": prompt}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/memory/query", json=body)

    async def rebuild_index(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Rebuild the memory search index.

        DEPRECATED: POST /api/v1/memory/rebuild-index is declared in the
        memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        There is no replacement endpoint.
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/memory/rebuild-index", json=body)

    async def semantic_search(
        self,
        query: str,
        *,
        limit: int = 20,
        min_similarity: float = 0.5,
    ) -> dict[str, Any]:
        """Perform semantic search across memories.

        DEPRECATED: POST /api/v1/memory/semantic-search is declared in the
        memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        Use search() or search_index(use_hybrid=True) instead.
        """
        body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "min_similarity": min_similarity,
        }
        return await self._client.request("POST", "/api/v1/memory/semantic-search", json=body)

    async def list_snapshots(self, limit: int = 20, offset: int = 0) -> dict[str, Any]:
        """List memory snapshots.

        DEPRECATED: GET /api/v1/memory/snapshots is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). There is
        no replacement endpoint.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return await self._client.request("GET", "/api/v1/memory/snapshots", params=params)

    async def get_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Get a specific memory snapshot.

        DEPRECATED: GET /api/v1/memory/snapshots/{id} is declared in the
        memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        There is no replacement endpoint.
        """
        return await self._client.request("GET", f"/api/v1/memory/snapshots/{snapshot_id}")

    async def restore_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Restore a memory snapshot.

        DEPRECATED: POST /api/v1/memory/snapshots/{id}/restore is declared in
        the memory handler's ROUTES list but never dispatched, so this method
        always fails against a live server (HTTP 500 handler_no_result).
        There is no replacement endpoint.
        """
        return await self._client.request(
            "POST", f"/api/v1/memory/snapshots/{snapshot_id}/restore", json={}
        )

    async def sync_memories(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Sync memories across tiers.

        DEPRECATED: POST /api/v1/memory/sync is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Use
        consolidate() for the supported maintenance operation.
        """
        body: dict[str, Any] = {}
        if workspace_id:
            body["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/memory/sync", json=body)

    async def get_tier(self, tier: str) -> dict[str, Any]:
        """Get detailed information about a specific memory tier.

        DEPRECATED: GET /api/v1/memory/tier/{tier} is declared in the
        handler's ROUTES list but never dispatched, so this method always
        fails with HTTP 500 (``handler_no_result``). Use list_tiers() for
        tier stats or retrieve_continuum(tiers=[...]) for entries.
        """
        _warn_deprecated(
            "memory.get_tier() targets an undispatched route (HTTP 500 "
            "handler_no_result); use list_tiers() or retrieve_continuum()."
        )
        return await self._client.request("GET", f"/api/v1/memory/tier/{tier}")

    async def vacuum(self) -> dict[str, Any]:
        """Run vacuum to reclaim storage space.

        DEPRECATED: POST /api/v1/memory/vacuum is declared in the memory
        handler's ROUTES list but never dispatched, so this method always
        fails against a live server (HTTP 500 handler_no_result). Use
        consolidate() for the supported maintenance operation.
        """
        return await self._client.request("POST", "/api/v1/memory/vacuum", json={})

    async def promote(self, key: str, target_tier: str | None = None) -> dict[str, Any]:
        """Promote a memory entry to a higher tier.

        DEPRECATED: The server requires ``target_tier`` -- calls without it
        fail with 400 -- and responds with
        ``{"success": bool, "previous_tier": str | None}``. Use
        promote_entry() instead.
        """
        _warn_deprecated(
            "memory.promote() fails with 400 unless target_tier is given "
            "and its documented response shape is wrong; use promote_entry()."
        )
        body: dict[str, Any] = {}
        if target_tier:
            body["target_tier"] = target_tier
        return await self._client.request("POST", f"/api/v1/memory/{key}/promote", json=body)

    async def promote_entry(self, memory_id: str, target_tier: str) -> dict[str, Any]:
        """
        Promote a continuum memory entry to a target tier.

        Matches the server contract for POST /api/v1/memory/{id}/promote.

        Args:
            memory_id: ID of the entry to promote (as returned by the store endpoint)
            target_tier: Tier to promote the entry to (fast, medium, slow, glacial)

        Returns:
            Dict with ``success`` flag and ``previous_tier``. A missing
            entry is HTTP 200 with ``{"success": False, "previous_tier":
            None, "error": "Memory entry not found"}``, not a 404.
        """
        # Hoisted so contract extractors see a plain {placeholder} path.
        encoded_id = quote(memory_id, safe="")
        return await self._client.request(
            "POST",
            f"/api/v1/memory/{encoded_id}/promote",
            json={"target_tier": target_tier},
        )

    async def demote(self, key: str, target_tier: str | None = None) -> dict[str, Any]:
        """Demote a memory entry to a lower tier.

        DEPRECATED: POST /api/v1/memory/{key}/demote is declared in the
        handler's ROUTES list but never dispatched, so this method always
        fails with HTTP 500 (``handler_no_result``). The server has no
        demote endpoint -- demotion happens automatically during
        consolidation and cleanup.
        """
        _warn_deprecated(
            "memory.demote() targets an undispatched route (HTTP 500 "
            "handler_no_result); the server has no demote endpoint."
        )
        body: dict[str, Any] = {}
        if target_tier:
            body["target_tier"] = target_tier
        return await self._client.request("POST", f"/api/v1/memory/{key}/demote", json=body)

    async def move(self, key: str, target_tier: str) -> dict[str, Any]:
        """Move a memory entry to a specific tier.

        DEPRECATED: POST /api/v1/memory/{key}/move is declared in the
        handler's ROUTES list but never dispatched, so this method always
        fails with HTTP 500 (``handler_no_result``). The only server-side
        tier mutation is promotion -- use promote_entry().
        """
        _warn_deprecated(
            "memory.move() targets an undispatched route (HTTP 500 "
            "handler_no_result); use promote_entry()."
        )
        body: dict[str, Any] = {"target_tier": target_tier}
        return await self._client.request("POST", f"/api/v1/memory/{key}/move", json=body)
