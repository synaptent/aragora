"""
Knowledge Namespace API

Provides methods for interacting with the Knowledge Base:
- Fact listing and creation
- Natural language queries and semantic search
- Knowledge Mound operations (nodes, graph, contradictions, dedup, pruning)
- Governance, analytics, extraction, confidence, curation
- Dashboard and export operations

Note: Several methods below target routes the server declares (handler
ROUTES membership) but never dispatches. Because the knowledge handlers'
``can_handle`` claims the whole path family, those calls do not 404
cleanly: undispatched paths return HTTP 500 with code ``handler_no_result``,
and unrecognized ``/facts/...`` sub-paths fall into the get-fact-by-ID
branch (404 "fact not found") or the facts sub-route 404. They are kept
for backward compatibility, emit :class:`DeprecationWarning` at runtime,
and are marked DEPRECATED in their docstrings; prefer the documented
working methods named in each docstring (see #9396).
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AragoraAsyncClient, AragoraClient
    from ..pagination import AsyncPaginator, SyncPaginator


def _warn_deprecated(message: str) -> None:
    """Emit a runtime DeprecationWarning for a dead or drifted SDK method."""
    warnings.warn(message, DeprecationWarning, stacklevel=3)


class KnowledgeAPI:
    """Synchronous Knowledge Base API."""

    def __init__(self, client: AragoraClient):
        self._client = client

    def search(
        self,
        query: str,
        workspace_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search knowledge chunks via embeddings."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/v1/knowledge/search", params=params)

    def query(self, prompt: str) -> dict[str, Any]:
        """Run a natural-language query against the knowledge base."""
        return self._client.request("POST", "/api/v1/knowledge/query", json={"prompt": prompt})

    def list_facts(
        self,
        workspace_id: str | None = None,
        topic: str | None = None,
        min_confidence: float = 0.0,
        status: str | None = None,
        include_superseded: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List facts with filtering."""
        params: dict[str, Any] = {
            "min_confidence": min_confidence,
            "include_superseded": include_superseded,
            "limit": limit,
            "offset": offset,
        }
        if workspace_id:
            params["workspace_id"] = workspace_id
        if topic:
            params["topic"] = topic
        if status:
            params["status"] = status
        return self._client.request("GET", "/api/v1/knowledge/facts", params=params)

    def list_all_facts(
        self,
        workspace_id: str | None = None,
        topic: str | None = None,
        min_confidence: float = 0.0,
        status: str | None = None,
        include_superseded: bool = False,
        page_size: int = 50,
    ) -> SyncPaginator:
        """
        Iterate through all facts with automatic pagination.

        Args:
            workspace_id: Filter by workspace
            topic: Filter by topic
            min_confidence: Minimum confidence threshold
            status: Filter by status
            include_superseded: Include superseded facts
            page_size: Number of facts per page (default 50)

        Returns:
            SyncPaginator yielding fact dictionaries

        Example::

            for fact in client.knowledge.list_all_facts(topic="security"):
                print(fact["statement"])
        """
        from ..pagination import SyncPaginator

        params: dict[str, Any] = {
            "min_confidence": min_confidence,
            "include_superseded": include_superseded,
        }
        if workspace_id:
            params["workspace_id"] = workspace_id
        if topic:
            params["topic"] = topic
        if status:
            params["status"] = status

        return SyncPaginator(self._client, "/api/v1/knowledge/facts", params, page_size)

    def create_fact(
        self,
        statement: str,
        workspace_id: str = "default",
        confidence: float = 0.5,
        topics: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        source_documents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new fact."""
        payload: dict[str, Any] = {
            "statement": statement,
            "workspace_id": workspace_id,
            "confidence": confidence,
        }
        if topics is not None:
            payload["topics"] = topics
        if evidence_ids is not None:
            payload["evidence_ids"] = evidence_ids
        if source_documents is not None:
            payload["source_documents"] = source_documents
        if metadata is not None:
            payload["metadata"] = metadata
        return self._client.request("POST", "/api/v1/knowledge/facts", json=payload)

    def get_fact(self, fact_id: str) -> dict[str, Any]:
        """Get a specific fact by ID."""
        return self._client.request("GET", f"/api/v1/knowledge/facts/{fact_id}")

    def verify_fact(self, fact_id: str) -> dict[str, Any]:
        """Verify a fact."""
        return self._client.request("POST", f"/api/v1/knowledge/facts/{fact_id}/verify")

    def get_fact_contradictions(self, fact_id: str) -> dict[str, Any]:
        """Get contradictions for a specific fact."""
        return self._client.request("GET", f"/api/v1/knowledge/facts/{fact_id}/contradictions")

    def get_fact_relations(self, fact_id: str, limit: int = 50) -> dict[str, Any]:
        """Get relations for a specific fact."""
        params: dict[str, Any] = {"limit": limit}
        return self._client.request(
            "GET", f"/api/v1/knowledge/facts/{fact_id}/relations", params=params
        )

    def create_fact_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> dict[str, Any]:
        """Create a relation between facts."""
        payload: dict[str, Any] = {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
        }
        return self._client.request("POST", "/api/v1/knowledge/facts/relations", json=payload)

    def batch_create_facts(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Create multiple facts in batch.

        DEPRECATED: The server has no facts batch endpoint. POST
        /api/v1/knowledge/facts/batch falls into the facts sub-route
        dispatcher and always fails with HTTP 404 ("Unknown endpoint").
        Use create_fact() per fact instead.
        """
        _warn_deprecated(
            "knowledge.batch_create_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); use create_fact() per fact."
        )
        return self._client.request("POST", "/api/v1/knowledge/facts/batch", json={"facts": facts})

    def batch_delete_facts(self, fact_ids: list[str]) -> dict[str, Any]:
        """Delete multiple facts in batch.

        DEPRECATED: The server has no facts batch-delete endpoint. POST
        /api/v1/knowledge/facts/batch/delete always fails with HTTP 404
        ("Unknown endpoint"). Delete facts one at a time via the documented
        DELETE /api/v1/knowledge/facts/{fact_id} route.
        """
        _warn_deprecated(
            "knowledge.batch_delete_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); delete facts individually via "
            "DELETE /api/v1/knowledge/facts/{fact_id}."
        )
        return self._client.request(
            "POST", "/api/v1/knowledge/facts/batch/delete", json={"fact_ids": fact_ids}
        )

    def merge_facts(
        self,
        source_ids: list[str],
        target_id: str | None = None,
    ) -> dict[str, Any]:
        """Merge multiple facts.

        DEPRECATED: The server has no facts merge endpoint. POST
        /api/v1/knowledge/facts/merge always fails with HTTP 404
        ("Unknown endpoint"). For Knowledge Mound duplicate handling use
        the mound dedup endpoints (POST /api/v1/knowledge/mound/dedup/merge).
        """
        _warn_deprecated(
            "knowledge.merge_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); use the mound dedup merge endpoint."
        )
        data: dict[str, Any] = {"source_ids": source_ids}
        if target_id:
            data["target_id"] = target_id
        return self._client.request("POST", "/api/v1/knowledge/facts/merge", json=data)

    def list_fact_relationships(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List fact relationships.

        DEPRECATED: The server has no relationships listing endpoint. GET
        /api/v1/knowledge/facts/relationships falls into the get-fact-by-ID
        branch with the literal ID "relationships" and always fails with
        HTTP 404 ("Fact not found"). Use get_fact_relations(fact_id) for a
        specific fact's relations.
        """
        _warn_deprecated(
            "knowledge.list_fact_relationships() targets a nonexistent "
            "endpoint (HTTP 404 Fact not found); use get_fact_relations(fact_id)."
        )
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.request("GET", "/api/v1/knowledge/facts/relationships", params=params)

    def get_fact_stats(self) -> dict[str, Any]:
        """Get fact statistics.

        DEPRECATED: The server has no facts stats endpoint. GET
        /api/v1/knowledge/facts/stats falls into the get-fact-by-ID branch
        with the literal ID "stats" and always fails with HTTP 404
        ("Fact not found"). Use get_stats() for knowledge base statistics.
        """
        _warn_deprecated(
            "knowledge.get_fact_stats() targets a nonexistent endpoint "
            "(HTTP 404 Fact not found); use get_stats()."
        )
        return self._client.request("GET", "/api/v1/knowledge/facts/stats")

    def validate_facts(self, fact_ids: list[str] | None = None) -> dict[str, Any]:
        """Validate facts.

        DEPRECATED: The server has no facts validate endpoint. POST
        /api/v1/knowledge/facts/validate always fails with HTTP 404
        ("Unknown endpoint"). Use verify_fact(fact_id) for agent-backed
        verification of a specific fact.
        """
        _warn_deprecated(
            "knowledge.validate_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); use verify_fact(fact_id)."
        )
        data: dict[str, Any] = {}
        if fact_ids:
            data["fact_ids"] = fact_ids
        return self._client.request("POST", "/api/v1/knowledge/facts/validate", json=data)

    # ========== Index Operations ==========

    def create_index(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a knowledge index.

        .. note:: Uses the Knowledge Mound index repository endpoint.
        """
        return self._client.request("POST", "/api/v1/knowledge/mound/index/repository", json=data)

    def embed_batch(self, texts: list[str]) -> dict[str, Any]:
        """Create embeddings for a batch of texts.

        DEPRECATED: POST /api/v1/knowledge/embeddings is declared in the
        knowledge handler's ROUTES list but never dispatched, so this method
        always fails with HTTP 500 (``handler_no_result``). The server has
        no client-facing embeddings endpoint; use search() for embedding-
        backed retrieval.
        """
        _warn_deprecated(
            "knowledge.embed_batch() targets an undispatched route (HTTP 500 "
            "handler_no_result); the server has no embeddings endpoint."
        )
        return self._client.request("POST", "/api/v1/knowledge/embeddings", json={"texts": texts})

    def search_index(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search the knowledge index."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        return self._client.request("GET", "/api/v1/knowledge/search", params=params)

    def create_embeddings(self, text: str, **kwargs: Any) -> dict[str, Any]:
        """Create embeddings for text.

        DEPRECATED: POST /api/v1/knowledge/embeddings is declared in the
        knowledge handler's ROUTES list but never dispatched, so this method
        always fails with HTTP 500 (``handler_no_result``). The server has
        no client-facing embeddings endpoint; use search() for embedding-
        backed retrieval.
        """
        _warn_deprecated(
            "knowledge.create_embeddings() targets an undispatched route "
            "(HTTP 500 handler_no_result); the server has no embeddings endpoint."
        )
        payload: dict[str, Any] = {"text": text, **kwargs}
        return self._client.request("POST", "/api/v1/knowledge/embeddings", json=payload)

    def get_entry_embeddings(self, entry_id: str) -> dict[str, Any]:
        """Get embeddings for a knowledge entry."""
        return self._client.request("GET", f"/api/v1/knowledge/entries/{entry_id}/embeddings")

    def get_entry_sources(self, entry_id: str) -> dict[str, Any]:
        """Get sources for a knowledge entry."""
        return self._client.request("GET", f"/api/v1/knowledge/entries/{entry_id}/sources")

    def export_knowledge(
        self, format: str = "json", workspace_id: str | None = None
    ) -> dict[str, Any]:
        """Export knowledge data."""
        params: dict[str, Any] = {"format": format}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/v1/knowledge/export", params=params)

    def refresh(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Refresh knowledge base.

        DEPRECATED: POST /api/v1/knowledge/refresh is declared in the
        knowledge handler's ROUTES list but never dispatched, so this method
        always fails with HTTP 500 (``handler_no_result``). The server has
        no refresh endpoint; mound revalidation is available via
        revalidate_entry(entry_id).
        """
        _warn_deprecated(
            "knowledge.refresh() targets an undispatched route (HTTP 500 "
            "handler_no_result); the server has no refresh endpoint."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/knowledge/refresh", json=payload)

    def validate(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Validate knowledge base integrity.

        DEPRECATED: POST /api/v1/knowledge/validate is declared in the
        knowledge handler's ROUTES list but never dispatched, so this method
        always fails with HTTP 500 (``handler_no_result``). Use
        verify_fact(fact_id) for per-fact verification.
        """
        _warn_deprecated(
            "knowledge.validate() targets an undispatched route (HTTP 500 "
            "handler_no_result); use verify_fact(fact_id)."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/knowledge/validate", json=payload)

    def get_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get knowledge base statistics."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/v1/knowledge/stats", params=params)

    def get_mound_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get Knowledge Mound statistics (if enabled)."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/v1/knowledge/mound/stats", params=params)

    # ========== Knowledge Mound Node Operations ==========

    def mound_query(
        self,
        query: str,
        workspace_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Semantic query against Knowledge Mound."""
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/knowledge/mound/query", json=payload)

    def add_node(
        self,
        content: str,
        node_type: str = "fact",
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a knowledge node to the mound."""
        payload: dict[str, Any] = {"content": content, "node_type": node_type}
        if metadata:
            payload["metadata"] = metadata
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/knowledge/mound/nodes", json=payload)

    def list_nodes(
        self,
        workspace_id: str | None = None,
        node_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List knowledge nodes with filtering."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if node_type:
            params["node_type"] = node_type
        return self._client.request("GET", "/api/knowledge/mound/nodes", params=params)

    def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a relationship between nodes."""
        payload: dict[str, Any] = {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
        }
        if metadata:
            payload["metadata"] = metadata
        return self._client.request("POST", "/api/knowledge/mound/relationships", json=payload)

    # ========== Graph Operations ==========

    def get_lineage(self, node_id: str) -> dict[str, Any]:
        """Get lineage (provenance chain) for a node."""
        return self._client.request("GET", f"/api/knowledge/mound/graph/{node_id}/lineage")

    def get_related(
        self,
        node_id: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get semantically related nodes."""
        params: dict[str, Any] = {"limit": limit}
        return self._client.request(
            "GET", f"/api/knowledge/mound/graph/{node_id}/related", params=params
        )

    # ========== Export Operations ==========

    def export_d3(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Export knowledge graph as D3 JSON."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/knowledge/mound/export/d3", params=params)

    def export_graphml(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Export knowledge graph as GraphML."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/knowledge/mound/export/graphml", params=params)

    # ========== Contradiction Detection ==========

    def detect_contradictions(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger contradiction detection scan."""
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request(
            "POST", "/api/knowledge/mound/contradictions/detect", json=payload
        )

    def list_mound_contradictions(self, workspace_id: str | None = None) -> dict[str, Any]:
        """List unresolved contradictions in the mound."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request("GET", "/api/knowledge/mound/contradictions", params=params)

    def resolve_contradiction(
        self,
        contradiction_id: str,
        resolution: str,
        keep_node_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a contradiction."""
        payload: dict[str, Any] = {"resolution": resolution}
        if keep_node_id:
            payload["keep_node_id"] = keep_node_id
        return self._client.request(
            "POST", f"/api/knowledge/mound/contradictions/{contradiction_id}/resolve", json=payload
        )

    def contradiction_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get contradiction statistics."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._client.request(
            "GET", "/api/knowledge/mound/contradictions/stats", params=params
        )

    # =========================================================================
    # KM Checkpoints
    # =========================================================================

    def list_checkpoints(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List Knowledge Mound checkpoints."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.request("GET", "/api/v1/km/checkpoints", params=params)

    # =========================================================================
    # Culture Documents & Promote
    # =========================================================================

    def add_culture_document(self, document: dict[str, Any]) -> dict[str, Any]:
        """Add a culture document to the Knowledge Mound."""
        return self._client.request(
            "POST", "/api/v1/knowledge/mound/culture/documents", json=document
        )

    def promote_culture(self, node_id: str, **options: Any) -> dict[str, Any]:
        """Promote a node to culture knowledge."""
        data: dict[str, Any] = {"node_id": node_id, **options}
        return self._client.request("POST", "/api/v1/knowledge/mound/culture/promote", json=data)

    # =========================================================================
    # Culture, Revalidation & Sync
    # =========================================================================

    def get_culture_entry(self, culture_id: str) -> dict[str, Any]:
        """Get a specific culture entry by ID."""
        return self._client.request("GET", f"/api/v1/knowledge/mound/culture/{culture_id}")

    def revalidate_entry(self, entry_id: str) -> dict[str, Any]:
        """Revalidate a knowledge mound entry."""
        return self._client.request("POST", f"/api/v1/knowledge/mound/revalidate/{entry_id}")

    def sync_entry(self, target_id: str) -> dict[str, Any]:
        """Sync a knowledge mound entry to a target."""
        return self._client.request("POST", f"/api/v1/knowledge/mound/sync/{target_id}")

    # ========== Mound Node Detail Operations ==========

    def get_node(self, node_id: str) -> dict[str, Any]:
        """Get a specific knowledge node by ID."""
        return self._client.request("GET", f"/api/v1/knowledge/mound/nodes/{node_id}")

    def get_node_relationships(self, node_id: str) -> dict[str, Any]:
        """Get relationships for a specific node."""
        return self._client.request("GET", f"/api/v1/knowledge/mound/nodes/{node_id}/relationships")

    def get_node_visibility(self, node_id: str) -> dict[str, Any]:
        """Get visibility settings for a node."""
        return self._client.request("GET", f"/api/v1/knowledge/mound/nodes/{node_id}/visibility")

    def get_node_access(self, node_id: str) -> dict[str, Any]:
        """Get access grants for a node."""
        return self._client.request("GET", f"/api/v1/knowledge/mound/nodes/{node_id}/access")

    # ========== Bulk Revalidation & Sync ==========

    def revalidate(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger bulk revalidation of stale knowledge.

        DEPRECATED: POST /api/v1/knowledge/mound/revalidate (no entry ID) is
        declared in the mound handler's ROUTES list but never dispatched, so
        this method always fails with HTTP 500 (``handler_no_result``). Use
        revalidate_entry(entry_id) (POST /api/v1/knowledge/mound/revalidate/{id})
        per entry, or schedule batch revalidation via
        POST /api/v1/knowledge/mound/schedule-revalidation.
        """
        _warn_deprecated(
            "knowledge.revalidate() targets an undispatched route (HTTP 500 "
            "handler_no_result); use revalidate_entry(entry_id)."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/knowledge/mound/revalidate", json=payload)

    def sync(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger bulk sync of knowledge mound.

        DEPRECATED: POST /api/v1/knowledge/mound/sync (no adapter) is
        declared in the mound handler's ROUTES list but never dispatched, so
        this method always fails with HTTP 500 (``handler_no_result``). Use
        sync_entry(target) with "continuum", "consensus", or "facts"
        (POST /api/v1/knowledge/mound/sync/{adapter}).
        """
        _warn_deprecated(
            "knowledge.sync() targets an undispatched route (HTTP 500 "
            "handler_no_result); use sync_entry('continuum'|'consensus'|'facts')."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return self._client.request("POST", "/api/v1/knowledge/mound/sync", json=payload)

    # ========== Sharing ==========

    def share(
        self,
        item_id: str,
        target_id: str,
        target_type: str = "user",
        permission: str = "read",
    ) -> dict[str, Any]:
        """Share a knowledge item."""
        payload: dict[str, Any] = {
            "item_id": item_id,
            "target_id": target_id,
            "target_type": target_type,
            "permission": permission,
        }
        return self._client.request("POST", "/api/v1/knowledge/mound/share", json=payload)

    def get_shared_with_me(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get items shared with the current user."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.request("GET", "/api/v1/knowledge/mound/shared-with-me", params=params)

    def get_my_shares(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get items shared by the current user."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.request("GET", "/api/v1/knowledge/mound/my-shares", params=params)

    # ========== Global Knowledge ==========

    def get_global_knowledge(self, query: str | None = None) -> dict[str, Any]:
        """Get global knowledge entries."""
        params: dict[str, Any] = {}
        if query:
            params["query"] = query
        return self._client.request("GET", "/api/v1/knowledge/mound/global", params=params)

    def get_global_facts(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get global knowledge facts."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return self._client.request("GET", "/api/v1/knowledge/mound/global/facts", params=params)

    def promote_to_global(self, node_id: str) -> dict[str, Any]:
        """Promote a knowledge node to global scope."""
        return self._client.request(
            "POST", "/api/v1/knowledge/mound/global/promote", json={"node_id": node_id}
        )

    # ========== Federation ==========

    def list_federation_regions(self) -> dict[str, Any]:
        """List federation regions."""
        return self._client.request("GET", "/api/v1/knowledge/mound/federation/regions")

    def delete_federation_region(self, region_id: str) -> dict[str, Any]:
        """Delete a federation region."""
        return self._client.request(
            "DELETE", f"/api/v1/knowledge/mound/federation/regions/{region_id}"
        )

    def get_federation_status(self) -> dict[str, Any]:
        """Get federation sync status."""
        return self._client.request("GET", "/api/v1/knowledge/mound/federation/status")

    def federation_sync_push(self, region_id: str) -> dict[str, Any]:
        """Push knowledge to a federation region."""
        return self._client.request(
            "POST", "/api/v1/knowledge/mound/federation/sync/push", json={"region_id": region_id}
        )

    def federation_sync_pull(self, region_id: str) -> dict[str, Any]:
        """Pull knowledge from a federation region."""
        return self._client.request(
            "POST", "/api/v1/knowledge/mound/federation/sync/pull", json={"region_id": region_id}
        )

    def federation_sync_all(self) -> dict[str, Any]:
        """Sync knowledge across all federation regions."""
        return self._client.request("POST", "/api/v1/knowledge/mound/federation/sync/all", json={})

    # ========== Index ==========

    def index_repository(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Index a repository into the knowledge mound."""
        payload: dict[str, Any] = {"url": url, **kwargs}
        return self._client.request(
            "POST", "/api/v1/knowledge/mound/index/repository", json=payload
        )

    # ========== Governance (additional) ==========

    def list_governance_permissions(self) -> dict[str, Any]:
        """List all governance permissions."""
        return self._client.request("GET", "/api/v1/knowledge/mound/governance/permissions")

    def get_user_audit(self, user_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Get governance audit trail for a user."""
        params: dict[str, Any] = {"limit": limit}
        if user_id:
            params["user_id"] = user_id
        return self._client.request(
            "GET", "/api/v1/knowledge/mound/governance/audit/user", params=params
        )

    # ========== Short Alias Routes (/api/v1/facts/*, /api/v1/index/*) ==========

    def facts_batch_create(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch create facts (short alias)."""
        return self._client.request("POST", "/api/v1/facts/batch", json={"facts": facts})

    def facts_batch_delete(self, fact_ids: list[str]) -> dict[str, Any]:
        """Batch delete facts (short alias)."""
        return self._client.request(
            "POST", "/api/v1/facts/batch/delete", json={"fact_ids": fact_ids}
        )

    def facts_merge(self, source_id: str, target_id: str) -> dict[str, Any]:
        """Merge two facts (short alias)."""
        return self._client.request(
            "POST", "/api/v1/facts/merge", json={"source_id": source_id, "target_id": target_id}
        )

    def facts_relationships(self, fact_id: str | None = None) -> dict[str, Any]:
        """List fact relationships (short alias)."""
        params: dict[str, Any] = {}
        if fact_id:
            params["fact_id"] = fact_id
        return self._client.request(
            "GET", "/api/v1/facts/relationships", params=params if params else None
        )

    def facts_stats(self) -> dict[str, Any]:
        """Get fact statistics (short alias)."""
        return self._client.request("GET", "/api/v1/facts/stats")

    def facts_validate(self, fact_ids: list[str] | None = None) -> dict[str, Any]:
        """Validate facts (short alias)."""
        data: dict[str, Any] = {}
        if fact_ids:
            data["fact_ids"] = fact_ids
        return self._client.request("POST", "/api/v1/facts/validate", json=data)

    def index_create(self, name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a search index (short alias)."""
        data: dict[str, Any] = {"name": name}
        if config:
            data["config"] = config
        return self._client.request("POST", "/api/v1/index", json=data)

    def index_embed_batch(self, texts: list[str]) -> dict[str, Any]:
        """Embed a batch of texts (short alias)."""
        return self._client.request("POST", "/api/v1/index/embed-batch", json={"texts": texts})

    def index_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search the index (short alias)."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        return self._client.request("GET", "/api/v1/index/search", params=params)

    def list_adapters(self) -> dict[str, Any]:
        """List registered knowledge adapters.

        Returns:
            Dict with adapters array and their configurations.
        """
        return self._client.request("GET", "/api/v1/knowledge/adapters")


class AsyncKnowledgeAPI:
    """Asynchronous Knowledge Base API."""

    def __init__(self, client: AragoraAsyncClient):
        self._client = client

    async def search(
        self,
        query: str,
        workspace_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "limit": limit}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/v1/knowledge/search", params=params)

    async def query(self, prompt: str) -> dict[str, Any]:
        return await self._client.request(
            "POST", "/api/v1/knowledge/query", json={"prompt": prompt}
        )

    async def list_facts(
        self,
        workspace_id: str | None = None,
        topic: str | None = None,
        min_confidence: float = 0.0,
        status: str | None = None,
        include_superseded: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "min_confidence": min_confidence,
            "include_superseded": include_superseded,
            "limit": limit,
            "offset": offset,
        }
        if workspace_id:
            params["workspace_id"] = workspace_id
        if topic:
            params["topic"] = topic
        if status:
            params["status"] = status
        return await self._client.request("GET", "/api/v1/knowledge/facts", params=params)

    def list_all_facts(
        self,
        workspace_id: str | None = None,
        topic: str | None = None,
        min_confidence: float = 0.0,
        status: str | None = None,
        include_superseded: bool = False,
        page_size: int = 50,
    ) -> AsyncPaginator:
        """
        Iterate through all facts with automatic pagination.

        Args:
            workspace_id: Filter by workspace
            topic: Filter by topic
            min_confidence: Minimum confidence threshold
            status: Filter by status
            include_superseded: Include superseded facts
            page_size: Number of facts per page (default 50)

        Returns:
            AsyncPaginator yielding fact dictionaries

        Example::

            async for fact in client.knowledge.list_all_facts(topic="security"):
                print(fact["statement"])
        """
        from ..pagination import AsyncPaginator

        params: dict[str, Any] = {
            "min_confidence": min_confidence,
            "include_superseded": include_superseded,
        }
        if workspace_id:
            params["workspace_id"] = workspace_id
        if topic:
            params["topic"] = topic
        if status:
            params["status"] = status

        return AsyncPaginator(self._client, "/api/v1/knowledge/facts", params, page_size)

    async def create_fact(
        self,
        statement: str,
        workspace_id: str = "default",
        confidence: float = 0.5,
        topics: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        source_documents: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "statement": statement,
            "workspace_id": workspace_id,
            "confidence": confidence,
        }
        if topics is not None:
            payload["topics"] = topics
        if evidence_ids is not None:
            payload["evidence_ids"] = evidence_ids
        if source_documents is not None:
            payload["source_documents"] = source_documents
        if metadata is not None:
            payload["metadata"] = metadata
        return await self._client.request("POST", "/api/v1/knowledge/facts", json=payload)

    async def get_fact(self, fact_id: str) -> dict[str, Any]:
        """Get a specific fact by ID."""
        return await self._client.request("GET", f"/api/v1/knowledge/facts/{fact_id}")

    async def verify_fact(self, fact_id: str) -> dict[str, Any]:
        """Verify a fact."""
        return await self._client.request("POST", f"/api/v1/knowledge/facts/{fact_id}/verify")

    async def get_fact_contradictions(self, fact_id: str) -> dict[str, Any]:
        """Get contradictions for a specific fact."""
        return await self._client.request(
            "GET", f"/api/v1/knowledge/facts/{fact_id}/contradictions"
        )

    async def get_fact_relations(self, fact_id: str, limit: int = 50) -> dict[str, Any]:
        """Get relations for a specific fact."""
        params: dict[str, Any] = {"limit": limit}
        return await self._client.request(
            "GET", f"/api/v1/knowledge/facts/{fact_id}/relations", params=params
        )

    async def create_fact_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
    ) -> dict[str, Any]:
        """Create a relation between facts."""
        payload: dict[str, Any] = {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
        }
        return await self._client.request("POST", "/api/v1/knowledge/facts/relations", json=payload)

    async def batch_create_facts(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Create multiple facts in batch.

        DEPRECATED: The server has no facts batch endpoint (HTTP 404
        "Unknown endpoint"). Use create_fact() per fact instead.
        """
        _warn_deprecated(
            "knowledge.batch_create_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); use create_fact() per fact."
        )
        return await self._client.request(
            "POST", "/api/v1/knowledge/facts/batch", json={"facts": facts}
        )

    async def batch_delete_facts(self, fact_ids: list[str]) -> dict[str, Any]:
        """Delete multiple facts in batch.

        DEPRECATED: The server has no facts batch-delete endpoint (HTTP 404
        "Unknown endpoint"). Delete facts one at a time via the documented
        DELETE /api/v1/knowledge/facts/{fact_id} route.
        """
        _warn_deprecated(
            "knowledge.batch_delete_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); delete facts individually via "
            "DELETE /api/v1/knowledge/facts/{fact_id}."
        )
        return await self._client.request(
            "POST", "/api/v1/knowledge/facts/batch/delete", json={"fact_ids": fact_ids}
        )

    async def merge_facts(
        self, source_ids: list[str], target_id: str | None = None
    ) -> dict[str, Any]:
        """Merge multiple facts.

        DEPRECATED: The server has no facts merge endpoint (HTTP 404
        "Unknown endpoint"). For Knowledge Mound duplicate handling use the
        mound dedup endpoints (POST /api/v1/knowledge/mound/dedup/merge).
        """
        _warn_deprecated(
            "knowledge.merge_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); use the mound dedup merge endpoint."
        )
        data: dict[str, Any] = {"source_ids": source_ids}
        if target_id:
            data["target_id"] = target_id
        return await self._client.request("POST", "/api/v1/knowledge/facts/merge", json=data)

    async def list_fact_relationships(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List fact relationships.

        DEPRECATED: The server has no relationships listing endpoint; the
        path falls into the get-fact-by-ID branch (HTTP 404 "Fact not
        found"). Use get_fact_relations(fact_id) for a specific fact.
        """
        _warn_deprecated(
            "knowledge.list_fact_relationships() targets a nonexistent "
            "endpoint (HTTP 404 Fact not found); use get_fact_relations(fact_id)."
        )
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return await self._client.request(
            "GET", "/api/v1/knowledge/facts/relationships", params=params
        )

    async def get_fact_stats(self) -> dict[str, Any]:
        """Get fact statistics.

        DEPRECATED: The server has no facts stats endpoint; the path falls
        into the get-fact-by-ID branch (HTTP 404 "Fact not found"). Use
        get_stats() for knowledge base statistics.
        """
        _warn_deprecated(
            "knowledge.get_fact_stats() targets a nonexistent endpoint "
            "(HTTP 404 Fact not found); use get_stats()."
        )
        return await self._client.request("GET", "/api/v1/knowledge/facts/stats")

    async def validate_facts(self, fact_ids: list[str] | None = None) -> dict[str, Any]:
        """Validate facts.

        DEPRECATED: The server has no facts validate endpoint (HTTP 404
        "Unknown endpoint"). Use verify_fact(fact_id) for agent-backed
        verification of a specific fact.
        """
        _warn_deprecated(
            "knowledge.validate_facts() targets a nonexistent endpoint "
            "(HTTP 404 Unknown endpoint); use verify_fact(fact_id)."
        )
        data: dict[str, Any] = {}
        if fact_ids:
            data["fact_ids"] = fact_ids
        return await self._client.request("POST", "/api/v1/knowledge/facts/validate", json=data)

    async def create_index(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a knowledge index.

        .. note:: Uses the Knowledge Mound index repository endpoint.
        """
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/index/repository", json=data
        )

    async def embed_batch(self, texts: list[str]) -> dict[str, Any]:
        """Create embeddings for a batch of texts.

        DEPRECATED: POST /api/v1/knowledge/embeddings is declared in ROUTES
        but never dispatched (HTTP 500 ``handler_no_result``). The server has
        no client-facing embeddings endpoint; use search() instead.
        """
        _warn_deprecated(
            "knowledge.embed_batch() targets an undispatched route (HTTP 500 "
            "handler_no_result); the server has no embeddings endpoint."
        )
        return await self._client.request(
            "POST", "/api/v1/knowledge/embeddings", json={"texts": texts}
        )

    async def search_index(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search the knowledge index."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        return await self._client.request("GET", "/api/v1/knowledge/search", params=params)

    # ========== KM Checkpoints ==========

    async def list_checkpoints(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """List Knowledge Mound checkpoints."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return await self._client.request("GET", "/api/v1/km/checkpoints", params=params)

    # ========== Culture Documents & Promote ==========

    async def add_culture_document(self, document: dict[str, Any]) -> dict[str, Any]:
        """Add a culture document to the Knowledge Mound."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/culture/documents", json=document
        )

    async def promote_culture(self, node_id: str, **options: Any) -> dict[str, Any]:
        """Promote a node to culture knowledge."""
        data: dict[str, Any] = {"node_id": node_id, **options}
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/culture/promote", json=data
        )

    async def create_embeddings(self, text: str, **kwargs: Any) -> dict[str, Any]:
        """Create embeddings for text.

        DEPRECATED: POST /api/v1/knowledge/embeddings is declared in ROUTES
        but never dispatched (HTTP 500 ``handler_no_result``). The server has
        no client-facing embeddings endpoint; use search() instead.
        """
        _warn_deprecated(
            "knowledge.create_embeddings() targets an undispatched route "
            "(HTTP 500 handler_no_result); the server has no embeddings endpoint."
        )
        payload: dict[str, Any] = {"text": text, **kwargs}
        return await self._client.request("POST", "/api/v1/knowledge/embeddings", json=payload)

    async def get_entry_embeddings(self, entry_id: str) -> dict[str, Any]:
        """Get embeddings for a knowledge entry."""
        return await self._client.request("GET", f"/api/v1/knowledge/entries/{entry_id}/embeddings")

    async def get_entry_sources(self, entry_id: str) -> dict[str, Any]:
        """Get sources for a knowledge entry."""
        return await self._client.request("GET", f"/api/v1/knowledge/entries/{entry_id}/sources")

    async def export_knowledge(
        self, format: str = "json", workspace_id: str | None = None
    ) -> dict[str, Any]:
        """Export knowledge data."""
        params: dict[str, Any] = {"format": format}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/v1/knowledge/export", params=params)

    async def refresh(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Refresh knowledge base.

        DEPRECATED: POST /api/v1/knowledge/refresh is declared in ROUTES but
        never dispatched (HTTP 500 ``handler_no_result``). The server has no
        refresh endpoint; mound revalidation is available via
        revalidate_entry(entry_id).
        """
        _warn_deprecated(
            "knowledge.refresh() targets an undispatched route (HTTP 500 "
            "handler_no_result); the server has no refresh endpoint."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/knowledge/refresh", json=payload)

    async def validate(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Validate knowledge base integrity.

        DEPRECATED: POST /api/v1/knowledge/validate is declared in ROUTES but
        never dispatched (HTTP 500 ``handler_no_result``). Use
        verify_fact(fact_id) for per-fact verification.
        """
        _warn_deprecated(
            "knowledge.validate() targets an undispatched route (HTTP 500 "
            "handler_no_result); use verify_fact(fact_id)."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/knowledge/validate", json=payload)

    async def get_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/v1/knowledge/stats", params=params)

    async def get_mound_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/v1/knowledge/mound/stats", params=params)

    # ========== Knowledge Mound Node Operations ==========

    async def mound_query(
        self,
        query: str,
        workspace_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Semantic query against Knowledge Mound."""
        payload: dict[str, Any] = {"query": query, "limit": limit}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/knowledge/mound/query", json=payload)

    async def add_node(
        self,
        content: str,
        node_type: str = "fact",
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Add a knowledge node to the mound."""
        payload: dict[str, Any] = {"content": content, "node_type": node_type}
        if metadata:
            payload["metadata"] = metadata
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/knowledge/mound/nodes", json=payload)

    async def list_nodes(
        self,
        workspace_id: str | None = None,
        node_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """List knowledge nodes with filtering."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if workspace_id:
            params["workspace_id"] = workspace_id
        if node_type:
            params["node_type"] = node_type
        return await self._client.request("GET", "/api/knowledge/mound/nodes", params=params)

    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a relationship between nodes."""
        payload: dict[str, Any] = {
            "source_id": source_id,
            "target_id": target_id,
            "relation_type": relation_type,
        }
        if metadata:
            payload["metadata"] = metadata
        return await self._client.request(
            "POST", "/api/knowledge/mound/relationships", json=payload
        )

    # ========== Graph Operations ==========

    async def get_lineage(self, node_id: str) -> dict[str, Any]:
        """Get lineage (provenance chain) for a node."""
        return await self._client.request("GET", f"/api/knowledge/mound/graph/{node_id}/lineage")

    async def get_related(
        self,
        node_id: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Get semantically related nodes."""
        params: dict[str, Any] = {"limit": limit}
        return await self._client.request(
            "GET", f"/api/knowledge/mound/graph/{node_id}/related", params=params
        )

    # ========== Export Operations ==========

    async def export_d3(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Export knowledge graph as D3 JSON."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request("GET", "/api/knowledge/mound/export/d3", params=params)

    async def export_graphml(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Export knowledge graph as GraphML."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request(
            "GET", "/api/knowledge/mound/export/graphml", params=params
        )

    # ========== Contradiction Detection ==========

    async def detect_contradictions(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger contradiction detection scan."""
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request(
            "POST", "/api/knowledge/mound/contradictions/detect", json=payload
        )

    async def list_mound_contradictions(self, workspace_id: str | None = None) -> dict[str, Any]:
        """List unresolved contradictions in the mound."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request(
            "GET", "/api/knowledge/mound/contradictions", params=params
        )

    async def resolve_contradiction(
        self,
        contradiction_id: str,
        resolution: str,
        keep_node_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve a contradiction."""
        payload: dict[str, Any] = {"resolution": resolution}
        if keep_node_id:
            payload["keep_node_id"] = keep_node_id
        return await self._client.request(
            "POST",
            f"/api/knowledge/mound/contradictions/{contradiction_id}/resolve",
            json=payload,
        )

    async def contradiction_stats(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get contradiction statistics."""
        params: dict[str, Any] = {}
        if workspace_id:
            params["workspace_id"] = workspace_id
        return await self._client.request(
            "GET", "/api/knowledge/mound/contradictions/stats", params=params
        )

    # ========== Deduplication ==========

    async def get_duplicate_clusters(
        self, threshold: float = 0.9, limit: int = 50
    ) -> dict[str, Any]:
        """Find duplicate clusters by similarity threshold."""
        return await self._client.request(
            "GET",
            "/api/v1/knowledge/mound/dedup/clusters",
            params={"threshold": threshold, "limit": limit},
        )

    async def get_dedup_report(self) -> dict[str, Any]:
        """Generate deduplication analysis report."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/dedup/report")

    async def merge_duplicate_cluster(
        self,
        cluster_id: str,
        primary_id: str | None = None,
        strategy: str = "highest_confidence",
    ) -> dict[str, Any]:
        """Merge a specific duplicate cluster."""
        payload: dict[str, Any] = {"cluster_id": cluster_id, "strategy": strategy}
        if primary_id:
            payload["primary_id"] = primary_id
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/dedup/merge", json=payload
        )

    async def auto_merge_exact_duplicates(self, dry_run: bool = False) -> dict[str, Any]:
        """Automatically merge exact duplicates."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/dedup/auto-merge",
            json={"dry_run": dry_run},
        )

    # ========== Pruning ==========

    async def get_prunable_items(
        self,
        max_age_days: int | None = None,
        min_staleness: float | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Get items eligible for pruning by staleness/age."""
        params: dict[str, Any] = {"limit": limit}
        if max_age_days:
            params["max_age_days"] = max_age_days
        if min_staleness:
            params["min_staleness"] = min_staleness
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/pruning/items", params=params
        )

    async def execute_prune(self, node_ids: list[str], action: str = "archive") -> dict[str, Any]:
        """Prune specified items (archive or delete)."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/pruning/execute",
            json={"node_ids": node_ids, "action": action},
        )

    async def auto_prune(self, policy: str = "moderate", dry_run: bool = False) -> dict[str, Any]:
        """Run auto-prune with policy."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/pruning/auto",
            json={"policy": policy, "dry_run": dry_run},
        )

    async def get_prune_history(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get pruning history."""
        return await self._client.request(
            "GET",
            "/api/v1/knowledge/mound/pruning/history",
            params={"limit": limit, "offset": offset},
        )

    async def restore_pruned_item(self, node_id: str) -> dict[str, Any]:
        """Restore an archived item."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/pruning/restore",
            json={"node_id": node_id},
        )

    # ========== Culture ==========

    async def get_culture(self) -> dict[str, Any]:
        """Get organization culture profile."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/culture")

    async def get_culture_entry(self, culture_id: str) -> dict[str, Any]:
        """Get a specific culture entry by ID."""
        return await self._client.request("GET", f"/api/v1/knowledge/mound/culture/{culture_id}")

    # ========== Revalidation & Sync ==========

    async def revalidate_entry(self, entry_id: str) -> dict[str, Any]:
        """Revalidate a knowledge mound entry."""
        return await self._client.request("POST", f"/api/v1/knowledge/mound/revalidate/{entry_id}")

    async def sync_entry(self, target_id: str) -> dict[str, Any]:
        """Sync a knowledge mound entry to a target."""
        return await self._client.request("POST", f"/api/v1/knowledge/mound/sync/{target_id}")

    # ========== Mound Node Detail Operations ==========

    async def get_node(self, node_id: str) -> dict[str, Any]:
        """Get a specific knowledge node by ID."""
        return await self._client.request("GET", f"/api/v1/knowledge/mound/nodes/{node_id}")

    async def get_node_relationships(self, node_id: str) -> dict[str, Any]:
        """Get relationships for a specific node."""
        return await self._client.request(
            "GET", f"/api/v1/knowledge/mound/nodes/{node_id}/relationships"
        )

    async def get_node_visibility(self, node_id: str) -> dict[str, Any]:
        """Get visibility settings for a node."""
        return await self._client.request(
            "GET", f"/api/v1/knowledge/mound/nodes/{node_id}/visibility"
        )

    async def get_node_access(self, node_id: str) -> dict[str, Any]:
        """Get access grants for a node."""
        return await self._client.request("GET", f"/api/v1/knowledge/mound/nodes/{node_id}/access")

    # ========== Bulk Revalidation & Sync ==========

    async def revalidate(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger bulk revalidation of stale knowledge.

        DEPRECATED: POST /api/v1/knowledge/mound/revalidate (no entry ID) is
        declared in ROUTES but never dispatched (HTTP 500
        ``handler_no_result``). Use revalidate_entry(entry_id) per entry, or
        POST /api/v1/knowledge/mound/schedule-revalidation for batches.
        """
        _warn_deprecated(
            "knowledge.revalidate() targets an undispatched route (HTTP 500 "
            "handler_no_result); use revalidate_entry(entry_id)."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/revalidate", json=payload
        )

    async def sync(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Trigger bulk sync of knowledge mound.

        DEPRECATED: POST /api/v1/knowledge/mound/sync (no adapter) is
        declared in ROUTES but never dispatched (HTTP 500
        ``handler_no_result``). Use sync_entry(target) with "continuum",
        "consensus", or "facts" (POST /api/v1/knowledge/mound/sync/{adapter}).
        """
        _warn_deprecated(
            "knowledge.sync() targets an undispatched route (HTTP 500 "
            "handler_no_result); use sync_entry('continuum'|'consensus'|'facts')."
        )
        payload: dict[str, Any] = {}
        if workspace_id:
            payload["workspace_id"] = workspace_id
        return await self._client.request("POST", "/api/v1/knowledge/mound/sync", json=payload)

    # ========== Sharing ==========

    async def share(
        self,
        item_id: str,
        target_id: str,
        target_type: str = "user",
        permission: str = "read",
    ) -> dict[str, Any]:
        """Share a knowledge item."""
        payload: dict[str, Any] = {
            "item_id": item_id,
            "target_id": target_id,
            "target_type": target_type,
            "permission": permission,
        }
        return await self._client.request("POST", "/api/v1/knowledge/mound/share", json=payload)

    async def get_shared_with_me(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get items shared with the current user."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/shared-with-me", params=params
        )

    async def get_my_shares(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get items shared by the current user."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return await self._client.request("GET", "/api/v1/knowledge/mound/my-shares", params=params)

    # ========== Global Knowledge ==========

    async def get_global_knowledge(self, query: str | None = None) -> dict[str, Any]:
        """Get global knowledge entries."""
        params: dict[str, Any] = {}
        if query:
            params["query"] = query
        return await self._client.request("GET", "/api/v1/knowledge/mound/global", params=params)

    async def get_global_facts(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get global knowledge facts."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/global/facts", params=params
        )

    async def promote_to_global(self, node_id: str) -> dict[str, Any]:
        """Promote a knowledge node to global scope."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/global/promote", json={"node_id": node_id}
        )

    # ========== Federation ==========

    async def list_federation_regions(self) -> dict[str, Any]:
        """List federation regions."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/federation/regions")

    async def delete_federation_region(self, region_id: str) -> dict[str, Any]:
        """Delete a federation region."""
        return await self._client.request(
            "DELETE", f"/api/v1/knowledge/mound/federation/regions/{region_id}"
        )

    async def get_federation_status(self) -> dict[str, Any]:
        """Get federation sync status."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/federation/status")

    async def federation_sync_push(self, region_id: str) -> dict[str, Any]:
        """Push knowledge to a federation region."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/federation/sync/push", json={"region_id": region_id}
        )

    async def federation_sync_pull(self, region_id: str) -> dict[str, Any]:
        """Pull knowledge from a federation region."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/federation/sync/pull", json={"region_id": region_id}
        )

    async def federation_sync_all(self) -> dict[str, Any]:
        """Sync knowledge across all federation regions."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/federation/sync/all", json={}
        )

    # ========== Index ==========

    async def index_repository(self, url: str, **kwargs: Any) -> dict[str, Any]:
        """Index a repository into the knowledge mound."""
        payload: dict[str, Any] = {"url": url, **kwargs}
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/index/repository", json=payload
        )

    # ========== Governance (additional) ==========

    async def list_governance_permissions(self) -> dict[str, Any]:
        """List all governance permissions."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/governance/permissions")

    async def get_user_audit(self, user_id: str | None = None, limit: int = 50) -> dict[str, Any]:
        """Get governance audit trail for a user."""
        params: dict[str, Any] = {"limit": limit}
        if user_id:
            params["user_id"] = user_id
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/governance/audit/user", params=params
        )

    # ========== Dashboard & Metrics ==========

    async def get_dashboard_health(self) -> dict[str, Any]:
        """Get Knowledge Mound health status and recommendations."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/dashboard/health")

    async def get_dashboard_metrics(self) -> dict[str, Any]:
        """Get detailed operational metrics."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/dashboard/metrics")

    async def reset_dashboard_metrics(self) -> dict[str, Any]:
        """Reset metrics counters."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/dashboard/metrics/reset", json={}
        )

    async def get_dashboard_adapters(self) -> dict[str, Any]:
        """Get adapter status and health."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/dashboard/adapters")

    # ========== Governance ==========

    async def create_governance_role(
        self,
        name: str,
        permissions: list[str],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a custom role for knowledge governance."""
        payload: dict[str, Any] = {"name": name, "permissions": permissions}
        if description:
            payload["description"] = description
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/governance/roles", json=payload
        )

    async def assign_governance_role(self, user_id: str, role_id: str) -> dict[str, Any]:
        """Assign a role to a user."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/governance/roles/assign",
            json={"user_id": user_id, "role_id": role_id},
        )

    async def revoke_governance_role(self, user_id: str, role_id: str) -> dict[str, Any]:
        """Revoke a role from a user."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/governance/roles/revoke",
            json={"user_id": user_id, "role_id": role_id},
        )

    async def get_user_governance_permissions(self, user_id: str) -> dict[str, Any]:
        """Get user permissions for knowledge governance."""
        return await self._client.request(
            "GET", f"/api/v1/knowledge/mound/governance/permissions/{user_id}"
        )

    async def check_governance_permission(self, user_id: str, permission: str) -> dict[str, Any]:
        """Check if user has a specific permission."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/governance/permissions/check",
            json={"user_id": user_id, "permission": permission},
        )

    async def query_governance_audit(
        self,
        user_id: str | None = None,
        action: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Query the governance audit trail."""
        params: dict[str, Any] = {"limit": limit}
        if user_id:
            params["user_id"] = user_id
        if action:
            params["action"] = action
        if since:
            params["since"] = since
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/governance/audit", params=params
        )

    # ========== Analytics ==========

    async def analyze_coverage(self, topics: list[str] | None = None) -> dict[str, Any]:
        """Analyze domain coverage by topic."""
        params: dict[str, Any] = {}
        if topics:
            params["topics"] = ",".join(topics)
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/analytics/coverage", params=params
        )

    async def analyze_usage(self, period: str = "week", since: str | None = None) -> dict[str, Any]:
        """Analyze usage patterns over time."""
        params: dict[str, Any] = {"period": period}
        if since:
            params["since"] = since
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/analytics/usage", params=params
        )

    async def record_usage_event(
        self,
        node_id: str,
        event_type: str,  # 'query' | 'view' | 'cite' | 'share' | 'export'
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Record a usage event."""
        payload: dict[str, Any] = {"node_id": node_id, "event_type": event_type}
        if metadata:
            payload["metadata"] = metadata
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/analytics/usage/record", json=payload
        )

    async def capture_quality_snapshot(self) -> dict[str, Any]:
        """Capture quality metrics snapshot."""
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/analytics/quality/snapshot", json={}
        )

    async def get_quality_trend(
        self, period: str = "week", metrics: list[str] | None = None
    ) -> dict[str, Any]:
        """Get quality metrics trend over time."""
        params: dict[str, Any] = {"period": period}
        if metrics:
            params["metrics"] = ",".join(metrics)
        return await self._client.request(
            "GET", "/api/v1/knowledge/mound/analytics/quality/trend", params=params
        )

    # ========== Extraction ==========

    async def extract_from_debate(
        self,
        debate_id: str,
        confidence_threshold: float = 0.7,
        auto_promote: bool = False,
    ) -> dict[str, Any]:
        """Extract claims/knowledge from a debate."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/extraction/debate",
            json={
                "debate_id": debate_id,
                "confidence_threshold": confidence_threshold,
                "auto_promote": auto_promote,
            },
        )

    async def promote_extracted(
        self, claim_ids: list[str], target_tier: str | None = None
    ) -> dict[str, Any]:
        """Promote extracted claims to main knowledge."""
        payload: dict[str, Any] = {"claim_ids": claim_ids}
        if target_tier:
            payload["target_tier"] = target_tier
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/extraction/promote", json=payload
        )

    # ========== Confidence Decay ==========

    async def apply_confidence_decay(
        self, scope: str = "workspace", decay_rate: float | None = None
    ) -> dict[str, Any]:
        """Apply confidence decay to workspace knowledge."""
        payload: dict[str, Any] = {"scope": scope}
        if decay_rate:
            payload["decay_rate"] = decay_rate
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/confidence/decay", json=payload
        )

    async def record_confidence_event(
        self,
        node_id: str,
        event_type: str,  # 'validation' | 'contradiction' | 'citation' | 'correction'
        impact: float,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Record a confidence-affecting event."""
        payload: dict[str, Any] = {
            "node_id": node_id,
            "type": event_type,
            "impact": impact,
        }
        if notes:
            payload["notes"] = notes
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/confidence/event", json=payload
        )

    async def get_confidence_history(
        self, node_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Get confidence adjustment history for a node."""
        return await self._client.request(
            "GET",
            "/api/v1/knowledge/mound/confidence/history",
            params={"node_id": node_id, "limit": limit, "offset": offset},
        )

    # ========== Auto-Curation ==========

    async def get_curation_policy(self) -> dict[str, Any]:
        """Get curation policy for workspace."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/curation/policy")

    async def set_curation_policy(
        self,
        auto_promote: bool | None = None,
        auto_archive_days: int | None = None,
        quality_threshold: float | None = None,
    ) -> dict[str, Any]:
        """Set curation policy."""
        payload: dict[str, Any] = {}
        if auto_promote is not None:
            payload["auto_promote"] = auto_promote
        if auto_archive_days is not None:
            payload["auto_archive_days"] = auto_archive_days
        if quality_threshold is not None:
            payload["quality_threshold"] = quality_threshold
        return await self._client.request(
            "POST", "/api/v1/knowledge/mound/curation/policy", json=payload
        )

    async def get_curation_status(self) -> dict[str, Any]:
        """Get curation status."""
        return await self._client.request("GET", "/api/v1/knowledge/mound/curation/status")

    async def run_curation(self, dry_run: bool = False) -> dict[str, Any]:
        """Trigger a curation run."""
        return await self._client.request(
            "POST",
            "/api/v1/knowledge/mound/curation/run",
            json={"dry_run": dry_run},
        )

    async def get_curation_history(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Get curation history."""
        return await self._client.request(
            "GET",
            "/api/v1/knowledge/mound/curation/history",
            params={"limit": limit, "offset": offset},
        )

    # ========== Short Alias Routes (/api/v1/facts/*, /api/v1/index/*) ==========

    async def facts_batch_create(self, facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Batch create facts (short alias)."""
        return await self._client.request("POST", "/api/v1/facts/batch", json={"facts": facts})

    async def facts_batch_delete(self, fact_ids: list[str]) -> dict[str, Any]:
        """Batch delete facts (short alias)."""
        return await self._client.request(
            "POST", "/api/v1/facts/batch/delete", json={"fact_ids": fact_ids}
        )

    async def facts_merge(self, source_id: str, target_id: str) -> dict[str, Any]:
        """Merge two facts (short alias)."""
        return await self._client.request(
            "POST", "/api/v1/facts/merge", json={"source_id": source_id, "target_id": target_id}
        )

    async def facts_relationships(self, fact_id: str | None = None) -> dict[str, Any]:
        """List fact relationships (short alias)."""
        params: dict[str, Any] = {}
        if fact_id:
            params["fact_id"] = fact_id
        return await self._client.request(
            "GET", "/api/v1/facts/relationships", params=params if params else None
        )

    async def facts_stats(self) -> dict[str, Any]:
        """Get fact statistics (short alias)."""
        return await self._client.request("GET", "/api/v1/facts/stats")

    async def facts_validate(self, fact_ids: list[str] | None = None) -> dict[str, Any]:
        """Validate facts (short alias)."""
        data: dict[str, Any] = {}
        if fact_ids:
            data["fact_ids"] = fact_ids
        return await self._client.request("POST", "/api/v1/facts/validate", json=data)

    async def index_create(self, name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a search index (short alias)."""
        data: dict[str, Any] = {"name": name}
        if config:
            data["config"] = config
        return await self._client.request("POST", "/api/v1/index", json=data)

    async def index_embed_batch(self, texts: list[str]) -> dict[str, Any]:
        """Embed a batch of texts (short alias)."""
        return await self._client.request(
            "POST", "/api/v1/index/embed-batch", json={"texts": texts}
        )

    async def index_search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search the index (short alias)."""
        params: dict[str, Any] = {"q": query, "limit": limit}
        return await self._client.request("GET", "/api/v1/index/search", params=params)

    async def list_adapters(self) -> dict[str, Any]:
        """List registered knowledge adapters."""
        return await self._client.request("GET", "/api/v1/knowledge/adapters")
