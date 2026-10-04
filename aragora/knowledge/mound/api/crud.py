"""
CRUD Operations Mixin for Knowledge Mound.

Provides core create, read, update, delete operations:
- store: Store with provenance tracking and deduplication
- get: Retrieve by ID with caching
- update: Update node fields
- delete: Delete with optional archival
- add: Simplified content addition
- add_node: KnowledgeNode adapter
- get_node: KnowledgeNode retrieval adapter

NOTE: This is a mixin class designed to be composed with KnowledgeMound.
Attribute accesses like self._ensure_initialized, self.store, self._cache, etc.
are provided by the composed class. The ``# type: ignore[attr-defined]``
comments suppress mypy warnings that are expected for this mixin pattern.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Generator
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol

# Distributed tracing support
from contextlib import contextmanager


# Mock span for when tracing is not available
class _MockSpan:
    def set_tag(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def set_error(self, error: Exception) -> None:
        pass


@contextmanager
def _mock_trace_context(
    operation: str,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
) -> Generator[_MockSpan, None, None]:
    """Mock trace_context for when tracing is not available."""
    yield _MockSpan()


# Pre-declare trace_context for optional import
trace_context: Any = _mock_trace_context
try:
    from aragora.observability.middleware.tracing import trace_context  # type: ignore[no-redef]

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False


from aragora.knowledge.mound.validation import (
    ValidationError,
    validate_content,
    validate_id,
    validate_metadata,
    validate_topics,
    validate_workspace_id,
)


def _serialize_for_storage(value: Any) -> Any:
    """Recursively serialize complex types for storage.

    Handles datetime objects, objects with to_dict() methods,
    nested dicts, and lists.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, dict):
        return {k: _serialize_for_storage(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_serialize_for_storage(item) for item in value]
    return value


if TYPE_CHECKING:
    from aragora.knowledge.mound.types import (
        IngestionRequest,
        IngestionResult,
        KnowledgeItem,
        MoundConfig,
    )

logger = logging.getLogger(__name__)


class CRUDProtocol(Protocol):
    """Protocol defining expected interface for CRUD mixin."""

    config: MoundConfig
    workspace_id: str
    _cache: Any | None
    _semantic_store: Any | None
    _graph_store: Any | None
    _initialized: bool
    event_emitter: Any | None

    def _ensure_initialized(self) -> None: ...
    async def _save_node(self, node_data: dict[str, Any]) -> None: ...
    async def _get_node(self, node_id: str) -> KnowledgeItem | None: ...
    async def _update_node(self, node_id: str, updates: dict[str, Any]) -> None: ...
    async def _delete_node(self, node_id: str) -> bool: ...
    async def _archive_node(self, node_id: str) -> None: ...
    async def _save_relationship(self, from_id: str, to_id: str, rel_type: str) -> None: ...
    async def _find_by_content_hash(self, content_hash: str, workspace_id: str) -> str | None: ...
    async def _increment_update_count(self, node_id: str) -> None: ...
    async def _get_access_grants_impl(self, node_id: str) -> list[dict[str, Any]]: ...
    async def query(
        self,
        query: str,
        filters: Any = None,
        limit: int = 100,
        offset: int = 0,
        workspace_id: str | None = None,
        sources: list[str] | None = None,
    ) -> Any: ...

    # Mixin methods that call each other - included for type checking
    async def store(self, request: IngestionRequest) -> IngestionResult: ...
    async def get(self, node_id: str) -> KnowledgeItem | None: ...
    async def add(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        node_type: str = "fact",
        confidence: float = 0.7,
        tier: str = "medium",
    ) -> str: ...


# Use Protocol as base class only for type checking
if TYPE_CHECKING:
    _CRUDMixinBase = CRUDProtocol
else:
    _CRUDMixinBase = object


class CRUDOperationsMixin(_CRUDMixinBase):
    """Mixin providing CRUD operations for KnowledgeMound."""

    async def store(self, request: IngestionRequest) -> IngestionResult:
        """
        Store a new knowledge item with full provenance tracking.

        Args:
            request: Ingestion request with content and metadata

        Returns:
            IngestionResult with node ID and status

        Raises:
            ValidationError: If request data is invalid
        """
        from aragora.knowledge.mound.types import IngestionResult

        self._ensure_initialized()

        with trace_context("km.store") as span:
            span.set_tag("workspace_id", request.workspace_id)
            span.set_tag("node_type", request.node_type)
            span.set_tag("source_type", request.source_type.value)

            # Validate inputs
            try:
                validate_content(request.content)
                validate_workspace_id(request.workspace_id)
                request.topics = validate_topics(request.topics)
                request.metadata = validate_metadata(request.metadata)
                span.add_event("validation_complete")
            except ValidationError as e:
                logger.warning("Validation failed for store request: %s", e.message)
                span.set_tag("error", "validation_failed")
                return IngestionResult(
                    node_id="",
                    success=False,
                    message=f"Validation error: {e.message}",
                )

            # Generate node ID
            node_id = f"kn_{uuid.uuid4().hex[:16]}"
            span.set_tag("node_id", node_id)

            # Check for duplicates if enabled
            if self.config.enable_deduplication:
                content_hash = hashlib.sha256(request.content.encode()).hexdigest()[:32]
                existing = await self._find_by_content_hash(content_hash, request.workspace_id)
                if existing:
                    # Update existing node
                    await self._increment_update_count(existing)
                    span.set_tag("deduplicated", True)
                    span.add_event("deduplication_found", {"existing_id": existing})
                    return IngestionResult(
                        node_id=existing,
                        success=True,
                        deduplicated=True,
                        existing_node_id=existing,
                        message="Merged with existing node",
                    )

            # Create node data
            node_data = {
                "id": node_id,
                "workspace_id": request.workspace_id,
                "node_type": request.node_type,
                "content": request.content,
                "content_hash": hashlib.sha256(request.content.encode()).hexdigest()[:32],
                "confidence": request.confidence,
                "tier": request.tier,
                "source_type": request.source_type.value,
                "document_id": request.document_id,
                "debate_id": request.debate_id,
                "agent_id": request.agent_id,
                "user_id": request.user_id,
                "topics": request.topics,
                "metadata": request.metadata,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }

            # Save to store
            await self._save_node(node_data)
            span.add_event("node_saved")

            # Index in semantic store for embedding-based search
            if self._semantic_store:
                try:
                    await self._semantic_store.index_item(
                        source_type=request.source_type,
                        source_id=node_id,
                        content=request.content,
                        tenant_id=request.workspace_id,
                        domain=request.topics[0] if request.topics else "general",
                        importance=request.confidence,
                    )
                    span.add_event("semantic_indexed")
                except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:  # noqa: BLE001 - adapter isolation
                    logger.warning("Failed to index in semantic store: %s", e)
                    span.add_event("semantic_index_failed", {"error": "Semantic indexing failed"})

            # Create relationships
            relationships_created = 0
            for target_id in request.supports:
                await self._save_relationship(node_id, target_id, "supports")
                relationships_created += 1
            for target_id in request.contradicts:
                await self._save_relationship(node_id, target_id, "contradicts")
                relationships_created += 1
            for target_id in request.derived_from:
                await self._save_relationship(node_id, target_id, "derived_from")
                relationships_created += 1

            if relationships_created > 0:
                span.add_event("relationships_created", {"count": relationships_created})
            span.set_tag("relationships_count", relationships_created)

            # Invalidate cache
            if self._cache:
                await self._cache.invalidate_queries(request.workspace_id)
                span.add_event("cache_invalidated")

            logger.debug("Stored knowledge node: %s", node_id)

            # Emit KNOWLEDGE_INDEXED event for cross-subsystem tracking
            if self.event_emitter:
                try:
                    from aragora.events.types import StreamEvent, StreamEventType

                    self.event_emitter.emit(
                        StreamEvent(
                            type=StreamEventType.KNOWLEDGE_INDEXED,
                            data={
                                "node_id": node_id,
                                "content": request.content[:200],
                                "node_type": request.node_type,
                                "workspace_id": request.workspace_id,
                                "source_type": request.source_type.value,
                                "confidence": request.confidence,
                            },
                        )
                    )
                except (ImportError, AttributeError, TypeError):
                    pass  # Events module not available

            span.set_tag("success", True)
            return IngestionResult(
                node_id=node_id,
                success=True,
                relationships_created=relationships_created,
            )

    async def get(self, node_id: str) -> KnowledgeItem | None:
        """Get a knowledge node by ID.

        Args:
            node_id: ID of node to retrieve

        Returns:
            KnowledgeItem if found, None otherwise

        Raises:
            ValidationError: If node_id is invalid
        """
        self._ensure_initialized()

        with trace_context("km.get") as span:
            span.set_tag("node_id", node_id)

            # Validate input
            validate_id(node_id, field_name="node_id")

            # Check cache first
            if self._cache:
                cached = await self._cache.get_node(node_id)
                if cached:
                    span.set_tag("cache_hit", True)
                    span.add_event("cache_hit")
                    return cached

            span.set_tag("cache_hit", False)

            # Query store
            node = await self._get_node(node_id)
            span.add_event("node_retrieved", {"found": node is not None})

            # Cache result
            if self._cache and node:
                await self._cache.set_node(node_id, node)
                span.add_event("node_cached")

            span.set_tag("found", node is not None)
            return node

    async def update(self, node_id: str, updates: dict[str, Any]) -> KnowledgeItem | None:
        """Update a knowledge node.

        Args:
            node_id: ID of node to update
            updates: Dict of fields to update

        Returns:
            Updated KnowledgeItem if found, None otherwise

        Raises:
            ValidationError: If inputs are invalid
        """
        self._ensure_initialized()

        with trace_context("km.update") as span:
            span.set_tag("node_id", node_id)
            span.set_tag("update_fields", list(updates.keys()))

            # Validate inputs
            validate_id(node_id, field_name="node_id")
            if "content" in updates:
                validate_content(updates["content"])
            if "topics" in updates:
                updates["topics"] = validate_topics(updates["topics"])
            if "metadata" in updates:
                updates["metadata"] = validate_metadata(updates["metadata"])
            span.add_event("validation_complete")

            updates["updated_at"] = datetime.now().isoformat()

            # Serialize complex types before storage
            if "provenance" in updates:
                updates["provenance"] = _serialize_for_storage(updates["provenance"])
            if "metadata" in updates:
                updates["metadata"] = _serialize_for_storage(updates["metadata"])

            await self._update_node(node_id, updates)
            span.add_event("node_updated")

            # Invalidate cache
            if self._cache:
                await self._cache.invalidate_node(node_id)
                span.add_event("cache_invalidated")

            result = await self.get(node_id)
            span.set_tag("success", result is not None)
            return result

    async def delete(self, node_id: str, archive: bool = True) -> bool:
        """Delete a knowledge node.

        Args:
            node_id: ID of node to delete
            archive: Whether to archive before deleting (default True)

        Returns:
            True if deleted, False if not found

        Raises:
            ValidationError: If node_id is invalid
        """
        self._ensure_initialized()

        with trace_context("km.delete") as span:
            span.set_tag("node_id", node_id)
            span.set_tag("archive", archive)

            # Validate input
            validate_id(node_id, field_name="node_id")

            if archive:
                await self._archive_node(node_id)
                span.add_event("node_archived")

            result = await self._delete_node(node_id)
            span.add_event("node_deleted", {"success": result})

            # Invalidate cache
            if self._cache:
                await self._cache.invalidate_node(node_id)
                span.add_event("cache_invalidated")

            # Emit MOUND_UPDATED event for structural change
            if result and self.event_emitter:
                try:
                    from aragora.events.types import StreamEvent, StreamEventType

                    self.event_emitter.emit(
                        StreamEvent(
                            type=StreamEventType.MOUND_UPDATED,
                            data={
                                "node_id": node_id,
                                "update_type": "node_deleted",
                                "archived": archive,
                                "workspace_id": self.workspace_id,
                            },
                        )
                    )
                except (ImportError, AttributeError, TypeError):
                    pass

            span.set_tag("success", result)
            return result

    async def add(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
        node_type: str = "fact",
        confidence: float = 0.7,
        tier: str = "medium",
    ) -> str:
        """
        Simplified method to add content to the Knowledge Mound.

        This is a convenience wrapper around store() for simpler use cases
        like repository crawling, document indexing, etc.

        Args:
            content: The content to store
            metadata: Optional metadata dictionary
            workspace_id: Workspace ID (defaults to self.workspace_id)
            node_type: Type of knowledge node (default: "fact")
            confidence: Confidence score 0-1 (default: 0.7)
            tier: Memory tier (default: "medium")

        Returns:
            The created node ID
        """
        from aragora.knowledge.mound.types import IngestionRequest, KnowledgeSource

        request = IngestionRequest(
            content=content,
            workspace_id=workspace_id or self.workspace_id,
            node_type=node_type,
            confidence=confidence,
            tier=tier,
            source_type=KnowledgeSource.EXTERNAL,
            metadata=metadata or {},
        )
        result = await self.store(request)
        return result.node_id

    async def add_node(self, node: Any) -> str:
        """
        Add a KnowledgeNode to the mound.

        This is an adapter method for compatibility with checkpoint_store
        and other components that use the KnowledgeNode interface.

        Args:
            node: KnowledgeNode with node_type, content, confidence, etc.

        Returns:
            The created node ID
        """
        from aragora.knowledge.mound_core import KnowledgeNode

        if not isinstance(node, KnowledgeNode):
            raise TypeError(f"Expected KnowledgeNode, got {type(node)}")

        # Convert tier to string if it's an enum
        tier_str = node.tier.value if hasattr(node.tier, "value") else str(node.tier)

        return await self.add(
            content=node.content,
            metadata={
                "provenance": node.provenance.to_dict() if node.provenance else None,
                "node_type": node.node_type,
            },
            workspace_id=node.workspace_id or self.workspace_id,
            node_type=node.node_type if isinstance(node.node_type, str) else node.node_type,
            confidence=node.confidence,
            tier=tier_str,
        )

    async def get_node(self, node_id: str) -> Any | None:
        """
        Get a KnowledgeNode by ID.

        This is an adapter method for compatibility with checkpoint_store
        and other components that use the KnowledgeNode interface.

        Args:
            node_id: The node ID to retrieve

        Returns:
            A dict-like object with node_type, content, etc., or None
        """

        item = await self.get(node_id)
        if item is None:
            return None

        # Return a dict-like object that has node_type and content
        # This maintains compatibility with code expecting KnowledgeNode interface
        class NodeProxy:
            def __init__(self, item: KnowledgeItem) -> None:
                self.id = item.id
                self.content = item.content
                # ConfidenceLevel is a string enum (e.g., "medium"), map to numeric
                if hasattr(item.confidence, "value"):
                    conf_val = item.confidence.value
                    # Map string confidence levels to numeric values
                    conf_map = {
                        "verified": 0.95,
                        "high": 0.85,
                        "medium": 0.7,
                        "low": 0.4,
                        "unverified": 0.2,
                    }
                    self.confidence = conf_map.get(conf_val, 0.5)
                elif isinstance(item.confidence, (int, float)):
                    self.confidence = float(item.confidence)
                else:
                    self.confidence = 0.5
                self.node_type = item.metadata.get("node_type", "fact")

        return NodeProxy(item)

    async def add_relationship(
        self,
        from_id: str,
        to_id: str,
        relationship_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Add a relationship between two knowledge nodes.

        Args:
            from_id: Source node ID
            to_id: Target node ID
            relationship_type: Type of relationship (supports, contradicts, derived_from, related_to)
            metadata: Optional relationship metadata

        Returns:
            True if relationship was created successfully
        """
        self._ensure_initialized()
        try:
            await self._save_relationship(from_id, to_id, relationship_type)
            logger.debug("Created relationship: %s --%s--> %s", from_id, relationship_type, to_id)
            return True
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Failed to create relationship: %s", e)
            return False

    async def get_relationships(
        self,
        node_id: str,
        relationship_type: str | None = None,
        direction: str = "outgoing",
    ) -> list[dict[str, Any]]:
        """
        Get relationships for a node.

        Args:
            node_id: The node ID to get relationships for
            relationship_type: Optional filter by relationship type
            direction: 'outgoing', 'incoming', or 'both'

        Returns:
            List of relationship dicts with from_id, to_id, relationship_type
        """
        self._ensure_initialized()

        # Query relationships from graph store if available
        if hasattr(self, "_graph_store") and self._graph_store:
            try:
                links = await self._graph_store.get_links(
                    node_id,
                    link_type=relationship_type,
                    direction=direction,
                )
                return [
                    {
                        "from_id": link.source_id,
                        "to_id": link.target_id,
                        "relationship_type": link.link_type,
                        "metadata": link.metadata,
                    }
                    for link in links
                ]
            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                logger.warning("Failed to get relationships from graph store: %s", e)

        # Fallback to empty list if no graph store
        return []

    async def query_nodes(
        self,
        node_type: str | None = None,
        workspace_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Any]:
        """
        Query nodes with optional filtering.

        Args:
            node_type: Optional filter by node type
            workspace_id: Optional workspace filter
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of knowledge items matching the criteria
        """
        self._ensure_initialized()

        # Call the query method (from QueryOperationsMixin) with simple filter
        if hasattr(self, "query"):
            result = await self.query(
                query="*",  # Match all
                limit=limit,
                offset=offset,
            )
            items = result.items if hasattr(result, "items") else []

            # Apply node_type and workspace_id filters manually
            if node_type:
                items = [
                    i for i in items if getattr(i, "metadata", {}).get("node_type") == node_type
                ]
            if workspace_id:
                items = [i for i in items if getattr(i, "workspace_id", None) == workspace_id]
            return items

        return []

    async def get_access_grants(
        self,
        node_id: str,
    ) -> list[dict[str, Any]]:
        """
        Get access grants for a knowledge node.

        Args:
            node_id: The node ID to get access grants for

        Returns:
            List of access grant dicts with user_id, workspace_id, permission level
        """
        self._ensure_initialized()

        # Query from sharing mixin if available
        if hasattr(self, "_get_access_grants_impl"):
            return await self._get_access_grants_impl(node_id)

        # Return empty list if sharing not configured
        return []

    async def update_confidence(
        self,
        node_id: str,
        new_confidence: float,
    ) -> bool:
        """
        Update the confidence level of a knowledge node.

        This method is used by the confidence decay system to adjust
        confidence levels over time based on age, usage, and validation events.

        Args:
            node_id: The node ID to update
            new_confidence: New confidence level (0.0 to 1.0)

        Returns:
            True if update was successful, False if node not found
        """
        self._ensure_initialized()

        # Validate inputs
        validate_id(node_id, field_name="node_id")
        new_confidence = max(0.0, min(1.0, new_confidence))

        # Update the node
        try:
            await self._update_node(node_id, {"confidence": new_confidence})

            # Invalidate cache
            if self._cache:
                await self._cache.invalidate_node(node_id)

            logger.debug(f"Updated confidence for {node_id} to {new_confidence:.3f}")
            return True
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to update confidence for %s: %s", node_id, e)
            return False
