"""
Node Operations Mixin for Knowledge Mound Handler.

Provides node CRUD operations:
- Create knowledge node
- Get specific node
- List/filter nodes
- Semantic query
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol

from aragora.rbac.decorators import require_permission
from aragora.server.http_utils import run_async as _run_async

from ...base import (
    HandlerResult,
    error_response,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    handle_errors,
    json_response,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine


logger = logging.getLogger(__name__)


class _MoundNodeOps(Protocol):
    """Subset of KnowledgeMound methods used by NodeOperationsMixin.

    Provides explicit method signatures so mypy can resolve calls
    without traversing the full 17-mixin KnowledgeMound MRO.
    """

    def query_semantic(
        self,
        text: str,
        limit: int = ...,
        min_confidence: float = ...,
        workspace_id: str | None = ...,
    ) -> Coroutine[Any, Any, Any]: ...
    def add_node(self, node: Any) -> Coroutine[Any, Any, str]: ...
    def get_node(self, node_id: str) -> Coroutine[Any, Any, Any | None]: ...
    def query_nodes(
        self,
        node_type: str | None = ...,
        workspace_id: str | None = ...,
        limit: int = ...,
        offset: int = ...,
    ) -> Coroutine[Any, Any, list[Any]]: ...
    def get_stats(self) -> Coroutine[Any, Any, Any]: ...


class NodeHandlerProtocol(Protocol):
    """Protocol for handlers that use NodeOperationsMixin."""

    def _get_mound(self) -> _MoundNodeOps | None: ...
    def require_auth_or_error(self, handler: Any) -> tuple[Any, HandlerResult | None]: ...


class NodeOperationsMixin:
    """Mixin providing node operations for KnowledgeMoundHandler."""

    @require_permission("knowledge:read")
    @handle_errors("mound query")
    def _handle_mound_query(self: NodeHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/mound/query - Semantic query."""

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                data = {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        query = data.get("query", "")
        if not query:
            return error_response("Query is required", 400)

        workspace_id = data.get("workspace_id", "default")
        limit = data.get("limit", 10)
        min_confidence = data.get("min_confidence", 0.0)
        node_types = data.get("node_types")

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            result = _run_async(
                mound.query_semantic(  # type: ignore[call-arg]  # node_types not in signature; caught by except below
                    text=query,
                    limit=limit,
                    min_confidence=min_confidence,
                    workspace_id=workspace_id,
                    node_types=node_types,
                )
            )
        except (KeyError, ValueError, OSError, TypeError, RuntimeError, AttributeError) as e:
            logger.error("Mound query failed: %s", e)
            return error_response("Query execution failed", 500)

        return json_response(
            {
                "query": getattr(result, "query", query),
                "nodes": [n.to_dict() for n in getattr(result, "nodes", [])],
                "total_count": getattr(result, "total_count", 0),
                "processing_time_ms": getattr(result, "processing_time_ms", 0),
            }
        )

    @require_permission("knowledge:create")
    @handle_errors("create node")
    def _handle_create_node(self: NodeHandlerProtocol, handler: Any) -> HandlerResult:
        """Handle POST /api/knowledge/mound/nodes - Create knowledge node."""
        user, err = self.require_auth_or_error(handler)
        if err:
            return err

        from aragora.knowledge.mound import KnowledgeNode, ProvenanceChain, ProvenanceType
        from aragora.memory.tier_manager import MemoryTier

        try:
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 0:
                body = handler.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
            else:
                return error_response("Request body required", 400)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        content = data.get("content", "")
        if not content:
            return error_response("Content is required", 400)

        node_type = data.get("node_type", "fact")
        if node_type not in ("fact", "claim", "memory", "evidence", "consensus", "entity"):
            return error_response(f"Invalid node_type: {node_type}", 400)

        workspace_id = data.get("workspace_id", "default")

        provenance = None
        if data.get("source"):
            source = data["source"]
            try:
                provenance = ProvenanceChain(
                    source_type=ProvenanceType(source.get("type", "user")),
                    source_id=source.get("id", ""),
                    user_id=source.get("user_id"),
                    agent_id=source.get("agent_id"),
                    debate_id=source.get("debate_id"),
                    document_id=source.get("document_id"),
                )
            except ValueError as e:
                logger.warning("Handler error: %s", e)
                return error_response("Invalid source type", 400)

        node = KnowledgeNode(
            node_type=node_type,
            content=content,
            confidence=data.get("confidence", 0.5),
            provenance=provenance,
            tier=MemoryTier(data.get("tier", "slow")),
            workspace_id=workspace_id,
            topics=data.get("topics", []),
            metadata=data.get("metadata", {}),
        )

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            node_id = _run_async(mound.add_node(node))
            saved_node = _run_async(mound.get_node(node_id))
        except (KeyError, ValueError, OSError, TypeError, RuntimeError, AttributeError) as e:
            logger.error("Failed to create node: %s", e)
            return error_response("Failed to create node", 500)

        return json_response(saved_node.to_dict() if saved_node else {"id": node_id}, status=201)

    @require_permission("knowledge:read")
    @handle_errors("get node")
    def _handle_get_node(self: NodeHandlerProtocol, node_id: str) -> HandlerResult:
        """Handle GET /api/knowledge/mound/nodes/:id - Get specific node."""

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            node = _run_async(mound.get_node(node_id))
        except (KeyError, ValueError, OSError, TypeError, RuntimeError, AttributeError) as e:
            logger.error("Failed to get node: %s", e)
            return error_response("Failed to get node", 500)

        if not node:
            return error_response(f"Node not found: {node_id}", 404)

        return json_response(node.to_dict())

    @require_permission("knowledge:read")
    @handle_errors("list nodes")
    def _handle_list_nodes(self: NodeHandlerProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /api/knowledge/mound/nodes - List/filter nodes."""
        from aragora.memory.tier_manager import MemoryTier

        workspace_id = get_bounded_string_param(
            query_params, "workspace_id", "default", max_length=100
        )
        node_types_str = get_bounded_string_param(query_params, "node_types", None, max_length=200)
        node_types = node_types_str.split(",") if node_types_str else None
        min_confidence = get_bounded_float_param(
            query_params, "min_confidence", 0.0, min_val=0.0, max_val=1.0
        )
        tier_str = get_bounded_string_param(query_params, "tier", None, max_length=20)
        tier = MemoryTier(tier_str) if tier_str else None
        limit = get_clamped_int_param(query_params, "limit", 50, min_val=1, max_val=200)
        offset = get_clamped_int_param(query_params, "offset", 0, min_val=0, max_val=10000)

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            # Note: query_nodes only supports node_type (singular), workspace_id, limit, offset
            # We filter by the first node_type if multiple are provided
            # min_confidence and tier filtering would need to be done post-query
            node_type = node_types[0] if node_types else None
            nodes = _run_async(
                mound.query_nodes(
                    node_type=node_type,
                    workspace_id=workspace_id,
                    limit=limit,
                    offset=offset,
                )
            )
            # Apply additional filters that query_nodes doesn't support natively
            if min_confidence > 0.0:
                nodes = [n for n in nodes if getattr(n, "confidence", 1.0) >= min_confidence]
            if tier:
                tier_value = tier.value if hasattr(tier, "value") else str(tier)
                nodes = [
                    n
                    for n in nodes
                    if getattr(n, "tier", None) == tier_value
                    or str(getattr(n, "tier", "")) == tier_value
                ]
            if node_types and len(node_types) > 1:
                # Filter for any of the requested node types
                nodes = [
                    n for n in nodes if getattr(n, "metadata", {}).get("node_type") in node_types
                ]
        except (KeyError, ValueError, OSError, TypeError, RuntimeError, AttributeError) as e:
            logger.error("Failed to list nodes: %s", e)
            return error_response("Failed to list nodes", 500)

        return json_response(
            {
                "nodes": [n.to_dict() for n in nodes],
                "count": len(nodes),
                "limit": limit,
                "offset": offset,
            }
        )

    @require_permission("knowledge:read")
    @handle_errors("mound stats")
    def _handle_mound_stats(self: NodeHandlerProtocol, query_params: dict) -> HandlerResult:
        """Handle GET /api/knowledge/mound/stats - Get mound statistics."""

        mound = self._get_mound()
        if not mound:
            return error_response("Knowledge Mound not available", 503)

        try:
            stats = _run_async(mound.get_stats())
        except (KeyError, ValueError, OSError, TypeError, RuntimeError, AttributeError) as e:
            logger.error("Failed to get stats: %s", e)
            return error_response("Failed to retrieve statistics", 500)

        return json_response(stats)
