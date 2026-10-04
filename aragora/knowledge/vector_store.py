"""
Vector storage adapter for KnowledgeNodes.

Extends WeaviateStore capabilities to handle KnowledgeNode objects
with support for:
- Multi-type node storage (fact, claim, memory, evidence, consensus)
- Semantic search across knowledge types
- Confidence-filtered queries
- Workspace-scoped multi-tenancy
- Graph relationship filtering

Usage:
    from aragora.knowledge.vector_store import KnowledgeVectorStore

    store = KnowledgeVectorStore(workspace_id="default")
    await store.connect()
    await store.index_node(node, embedding)
    results = await store.search_semantic("query", limit=10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Callable

from aragora.observability.server_metrics import (
    track_vector_index_batch,
    track_vector_operation,
    track_vector_search_results,
)

if TYPE_CHECKING:
    from aragora.knowledge.mound import KnowledgeNode

logger = logging.getLogger(__name__)

# Check for weaviate library
try:
    # weaviate's package __init__ calls a bare warnings.simplefilter("default")
    # (and its transitive imports register more filters), globally rewriting the
    # ambient warning policy; the scoped guard confines that to this import.
    with warnings.catch_warnings():
        import weaviate  # noqa: F401
        from weaviate.classes.config import Configure, DataType, Property  # noqa: F401
        from weaviate.classes.data import DataObject  # noqa: F401
        from weaviate.classes.query import Filter, MetadataQuery  # noqa: F401

    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False
    logger.info("weaviate-client not available - install with: pip install weaviate-client")

__all__ = [
    "KnowledgeVectorStore",
    "KnowledgeVectorConfig",
    "KnowledgeSearchResult",
    "WEAVIATE_AVAILABLE",
]


@dataclass
class KnowledgeSearchResult:
    """A single search result for a KnowledgeNode."""

    node_id: str
    workspace_id: str
    node_type: str
    content: str
    confidence: float
    score: float  # Similarity/relevance score
    tier: str = "slow"
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "node_id": self.node_id,
            "workspace_id": self.workspace_id,
            "node_type": self.node_type,
            "content": self.content,
            "confidence": self.confidence,
            "score": self.score,
            "tier": self.tier,
            "supports": self.supports,
            "contradicts": self.contradicts,
            "derived_from": self.derived_from,
            "metadata": self.metadata,
        }


@dataclass
class KnowledgeVectorConfig:
    """Configuration for knowledge vector storage."""

    url: str = "http://localhost:8080"
    api_key: str | None = None
    collection_name: str = "KnowledgeNodes"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    batch_size: int = 100
    timeout: int = 30

    # Knowledge-specific settings
    default_workspace: str = "default"
    index_relationships: bool = True

    @classmethod
    def from_env(cls, workspace_id: str | None = None) -> KnowledgeVectorConfig:
        """Create config from environment variables."""
        return cls(
            url=os.getenv("WEAVIATE_URL", "http://localhost:8080"),
            api_key=os.getenv("WEAVIATE_API_KEY"),
            collection_name=os.getenv("WEAVIATE_KNOWLEDGE_COLLECTION", "KnowledgeNodes"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
            default_workspace=(
                workspace_id if workspace_id else os.getenv("ARAGORA_WORKSPACE", "default")
            ),
        )


class KnowledgeVectorStore:
    """
    Vector store for KnowledgeNodes.

    Provides semantic search and retrieval for knowledge nodes with
    support for filtering by type, confidence, workspace, and relationships.
    """

    # Node type values for validation
    VALID_NODE_TYPES = {"fact", "claim", "memory", "evidence", "consensus", "insight", "pattern"}

    def __init__(
        self,
        workspace_id: str | None = None,
        config: KnowledgeVectorConfig | None = None,
    ):
        """
        Initialize knowledge vector store.

        Args:
            workspace_id: Workspace for multi-tenant isolation
            config: Vector store configuration
        """
        self.config = config or KnowledgeVectorConfig.from_env(workspace_id)
        self.workspace_id = workspace_id or self.config.default_workspace
        self._client: Any | None = None
        # Typed Any (not Any | None): connect() must run before use, and the
        # unconnected AttributeError is part of the existing error contract.
        self._collection: Any = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to Weaviate."""
        return self._connected and self._client is not None

    async def connect(self) -> bool:
        """
        Connect to Weaviate and ensure collection exists.

        Returns:
            True if connection successful
        """
        if not WEAVIATE_AVAILABLE:
            raise RuntimeError(
                "Weaviate client not installed. Install with: pip install weaviate-client"
            )

        try:
            # Create client
            if self.config.api_key:
                _connect = cast(Any, weaviate).connect_to_custom
                self._client = _connect(
                    http_host=self.config.url.replace("http://", "").replace("https://", ""),
                    http_port=8080,
                    http_secure=self.config.url.startswith("https"),
                    grpc_port=50051,
                    grpc_secure=self.config.url.startswith("https"),
                    auth_credentials=weaviate.auth.AuthApiKey(self.config.api_key),
                )
            else:
                self._client = weaviate.connect_to_local()

            # Ensure collection exists
            await self._ensure_collection()
            self._connected = True
            logger.info(
                "Connected to Weaviate at %s for workspace %s", self.config.url, self.workspace_id
            )
            return True

        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error("Failed to connect to Weaviate: %s", e)
            self._connected = False
            raise

    async def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        if self._client is None:
            raise RuntimeError("Not connected to Weaviate")

        collections = self._client.collections

        if not collections.exists(self.config.collection_name):
            logger.info("Creating knowledge collection: %s", self.config.collection_name)

            collections.create(
                name=self.config.collection_name,
                vectorizer_config=Configure.Vectorizer.none(),  # We provide embeddings
                properties=[
                    # Core properties
                    Property(name="node_id", data_type=DataType.TEXT),
                    Property(name="workspace_id", data_type=DataType.TEXT),
                    Property(name="node_type", data_type=DataType.TEXT),
                    Property(name="content", data_type=DataType.TEXT),
                    Property(name="confidence", data_type=DataType.NUMBER),
                    Property(name="tier", data_type=DataType.TEXT),
                    # Relationships (stored as comma-separated IDs for filtering)
                    Property(name="supports_ids", data_type=DataType.TEXT),
                    Property(name="contradicts_ids", data_type=DataType.TEXT),
                    Property(name="derived_from_ids", data_type=DataType.TEXT),
                    # Metadata
                    Property(name="surprise_score", data_type=DataType.NUMBER),
                    Property(name="update_count", data_type=DataType.INT),
                    Property(name="validation_status", data_type=DataType.TEXT),
                    Property(name="created_at", data_type=DataType.TEXT),
                ],
            )

        self._collection = collections.get(self.config.collection_name)

    async def disconnect(self) -> None:
        """Disconnect from Weaviate."""
        if self._client:
            self._client.close()
            self._client = None
            self._collection = None
            self._connected = False
            logger.info("Disconnected from Weaviate")

    async def index_node(
        self,
        node: KnowledgeNode,
        embedding: list[float],
    ) -> str:
        """
        Index a single knowledge node.

        Args:
            node: KnowledgeNode to index
            embedding: Vector embedding for the node content

        Returns:
            Weaviate object UUID
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        # Serialize relationships as comma-separated IDs
        properties = {
            "node_id": node.id,
            "workspace_id": node.workspace_id or self.workspace_id,
            "node_type": (
                node.node_type
                if isinstance(node.node_type, str)
                else (
                    node.node_type.value
                    if hasattr(node.node_type, "value")
                    else str(node.node_type)
                )
            ),
            "content": node.content,
            "confidence": node.confidence,
            "tier": node.tier.value if hasattr(node.tier, "value") else str(node.tier),
            "supports_ids": ",".join(node.supports) if node.supports else "",
            "contradicts_ids": ",".join(node.contradicts) if node.contradicts else "",
            "derived_from_ids": ",".join(node.derived_from) if node.derived_from else "",
            "surprise_score": node.surprise_score,
            "update_count": node.update_count,
            "validation_status": (
                node.validation_status.value
                if hasattr(node.validation_status, "value")
                else str(node.validation_status)
            ),
            "created_at": node.created_at if hasattr(node, "created_at") else "",
        }

        uuid = self._collection.data.insert(
            properties=properties,
            vector=embedding,
        )

        return str(uuid)

    async def index_nodes(
        self,
        nodes: list[KnowledgeNode],
        embeddings: list[list[float]],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        """
        Batch index multiple knowledge nodes.

        Args:
            nodes: List of KnowledgeNodes
            embeddings: Corresponding vector embeddings
            on_progress: Optional callback(indexed, total)

        Returns:
            List of Weaviate object UUIDs
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        if len(nodes) != len(embeddings):
            raise ValueError("Number of nodes must match number of embeddings")

        # Track total batch size
        track_vector_index_batch(len(nodes), "weaviate")

        uuids = []
        total = len(nodes)

        # Process in batches
        for i in range(0, total, self.config.batch_size):
            batch_nodes = nodes[i : i + self.config.batch_size]
            batch_embeddings = embeddings[i : i + self.config.batch_size]

            with (
                track_vector_operation("index_batch", "weaviate"),
                self._collection.batch.dynamic() as batch,
            ):
                for node, embedding in zip(batch_nodes, batch_embeddings):
                    properties = {
                        "node_id": node.id,
                        "workspace_id": node.workspace_id or self.workspace_id,
                        "node_type": (
                            node.node_type
                            if isinstance(node.node_type, str)
                            else (
                                node.node_type.value
                                if hasattr(node.node_type, "value")
                                else str(node.node_type)
                            )
                        ),
                        "content": node.content,
                        "confidence": node.confidence,
                        "tier": node.tier.value if hasattr(node.tier, "value") else str(node.tier),
                        "supports_ids": ",".join(node.supports) if node.supports else "",
                        "contradicts_ids": ",".join(node.contradicts) if node.contradicts else "",
                        "derived_from_ids": (
                            ",".join(node.derived_from) if node.derived_from else ""
                        ),
                        "surprise_score": node.surprise_score,
                        "update_count": node.update_count,
                        "validation_status": (
                            node.validation_status.value
                            if hasattr(node.validation_status, "value")
                            else str(node.validation_status)
                        ),
                        "created_at": node.created_at if hasattr(node, "created_at") else "",
                    }

                    uuid = batch.add_object(
                        properties=properties,
                        vector=embedding,
                    )
                    uuids.append(str(uuid))

            if on_progress is not None:
                on_progress(min(i + self.config.batch_size, total), total)

            # Small delay between batches
            await asyncio.sleep(0.01)

        logger.info("Indexed %s knowledge nodes to Weaviate", len(uuids))
        return uuids

    async def search_semantic(
        self,
        embedding: list[float],
        limit: int = 10,
        node_types: list[str] | None = None,
        min_confidence: float = 0.0,
        min_score: float = 0.0,
        workspace_id: str | None = None,
    ) -> list[KnowledgeSearchResult]:
        """
        Search for similar knowledge nodes using vector similarity.

        Args:
            embedding: Query vector embedding
            limit: Maximum results to return
            node_types: Optional filter to specific node types
            min_confidence: Minimum confidence threshold
            min_score: Minimum similarity score (0-1)
            workspace_id: Optional workspace filter (defaults to store's workspace)

        Returns:
            List of search results
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        with track_vector_operation("search_semantic", "weaviate"):
            results = await self._search_semantic_impl(
                embedding, limit, node_types, min_confidence, min_score, workspace_id
            )
            track_vector_search_results(len(results), "weaviate", "semantic")
            return results

    async def _search_semantic_impl(
        self,
        embedding: list[float],
        limit: int,
        node_types: list[str] | None,
        min_confidence: float,
        min_score: float,
        workspace_id: str | None,
    ) -> list[KnowledgeSearchResult]:
        """Internal implementation of semantic search."""
        # Build filters
        filters = []
        ws = workspace_id or self.workspace_id
        filters.append(Filter.by_property("workspace_id").equal(ws))

        if node_types:
            filters.append(Filter.by_property("node_type").contains_any(node_types))

        if min_confidence > 0:
            filters.append(Filter.by_property("confidence").greater_or_equal(min_confidence))

        # Combine filters
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f

        response = self._collection.query.near_vector(
            near_vector=embedding,
            limit=limit,
            filters=combined_filter,
            return_metadata=MetadataQuery(distance=True),
        )

        results = []
        for obj in response.objects:
            # Convert distance to similarity score
            distance = obj.metadata.distance or 0.0
            score = 1.0 - distance

            if score >= min_score:
                # Parse relationship IDs
                supports = self._parse_ids(obj.properties.get("supports_ids", ""))
                contradicts = self._parse_ids(obj.properties.get("contradicts_ids", ""))
                derived_from = self._parse_ids(obj.properties.get("derived_from_ids", ""))

                results.append(
                    KnowledgeSearchResult(
                        node_id=obj.properties.get("node_id", ""),
                        workspace_id=obj.properties.get("workspace_id", ""),
                        node_type=obj.properties.get("node_type", "fact"),
                        content=obj.properties.get("content", ""),
                        confidence=obj.properties.get("confidence", 0.5),
                        score=score,
                        tier=obj.properties.get("tier", "slow"),
                        supports=supports,
                        contradicts=contradicts,
                        derived_from=derived_from,
                        metadata={
                            "surprise_score": obj.properties.get("surprise_score", 0.0),
                            "update_count": obj.properties.get("update_count", 1),
                            "validation_status": obj.properties.get(
                                "validation_status", "unverified"
                            ),
                        },
                    )
                )

        return results

    async def search_keyword(
        self,
        query: str,
        limit: int = 10,
        node_types: list[str] | None = None,
        min_confidence: float = 0.0,
        workspace_id: str | None = None,
    ) -> list[KnowledgeSearchResult]:
        """
        Search for knowledge nodes using BM25 keyword matching.

        Args:
            query: Search query text
            limit: Maximum results to return
            node_types: Optional filter to specific node types
            min_confidence: Minimum confidence threshold
            workspace_id: Optional workspace filter

        Returns:
            List of search results
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        with track_vector_operation("search_keyword", "weaviate"):
            results = await self._search_keyword_impl(
                query, limit, node_types, min_confidence, workspace_id
            )
            track_vector_search_results(len(results), "weaviate", "keyword")
            return results

    async def _search_keyword_impl(
        self,
        query: str,
        limit: int,
        node_types: list[str] | None,
        min_confidence: float,
        workspace_id: str | None,
    ) -> list[KnowledgeSearchResult]:
        """Internal implementation of keyword search."""
        # Build filters
        filters = []
        ws = workspace_id or self.workspace_id
        filters.append(Filter.by_property("workspace_id").equal(ws))

        if node_types:
            filters.append(Filter.by_property("node_type").contains_any(node_types))

        if min_confidence > 0:
            filters.append(Filter.by_property("confidence").greater_or_equal(min_confidence))

        # Combine filters
        combined_filter = filters[0]
        for f in filters[1:]:
            combined_filter = combined_filter & f

        response = self._collection.query.bm25(
            query=query,
            limit=limit,
            filters=combined_filter,
            return_metadata=MetadataQuery(score=True),
        )

        results = []
        for obj in response.objects:
            score = obj.metadata.score or 0.0

            supports = self._parse_ids(obj.properties.get("supports_ids", ""))
            contradicts = self._parse_ids(obj.properties.get("contradicts_ids", ""))
            derived_from = self._parse_ids(obj.properties.get("derived_from_ids", ""))

            results.append(
                KnowledgeSearchResult(
                    node_id=obj.properties.get("node_id", ""),
                    workspace_id=obj.properties.get("workspace_id", ""),
                    node_type=obj.properties.get("node_type", "fact"),
                    content=obj.properties.get("content", ""),
                    confidence=obj.properties.get("confidence", 0.5),
                    score=score,
                    tier=obj.properties.get("tier", "slow"),
                    supports=supports,
                    contradicts=contradicts,
                    derived_from=derived_from,
                )
            )

        return results

    async def search_by_relationship(
        self,
        node_id: str,
        relationship_type: str,  # "supports", "contradicts", "derived_from"
        limit: int = 10,
        workspace_id: str | None = None,
    ) -> list[KnowledgeSearchResult]:
        """
        Search for nodes related to a specific node.

        Args:
            node_id: ID of the source node
            relationship_type: Type of relationship to search
            limit: Maximum results to return
            workspace_id: Optional workspace filter

        Returns:
            List of related nodes
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        if relationship_type not in ("supports", "contradicts", "derived_from"):
            raise ValueError(f"Invalid relationship type: {relationship_type}")

        # Build filter for the relationship
        ws = workspace_id or self.workspace_id
        property_name = f"{relationship_type}_ids"

        filters = Filter.by_property("workspace_id").equal(ws) & Filter.by_property(
            property_name
        ).like(f"*{node_id}*")

        response = self._collection.query.fetch_objects(
            filters=filters,
            limit=limit,
        )

        results = []
        for obj in response.objects:
            supports = self._parse_ids(obj.properties.get("supports_ids", ""))
            contradicts = self._parse_ids(obj.properties.get("contradicts_ids", ""))
            derived_from = self._parse_ids(obj.properties.get("derived_from_ids", ""))

            results.append(
                KnowledgeSearchResult(
                    node_id=obj.properties.get("node_id", ""),
                    workspace_id=obj.properties.get("workspace_id", ""),
                    node_type=obj.properties.get("node_type", "fact"),
                    content=obj.properties.get("content", ""),
                    confidence=obj.properties.get("confidence", 0.5),
                    score=1.0,  # No relevance score for relationship queries
                    tier=obj.properties.get("tier", "slow"),
                    supports=supports,
                    contradicts=contradicts,
                    derived_from=derived_from,
                )
            )

        return results

    async def get_node(
        self, node_id: str, workspace_id: str | None = None
    ) -> KnowledgeSearchResult | None:
        """
        Get a specific node by ID.

        Args:
            node_id: Node ID to retrieve
            workspace_id: Optional workspace filter

        Returns:
            Node if found, None otherwise
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        ws = workspace_id or self.workspace_id
        filters = Filter.by_property("workspace_id").equal(ws) & Filter.by_property(
            "node_id"
        ).equal(node_id)

        response = self._collection.query.fetch_objects(
            filters=filters,
            limit=1,
        )

        if not response.objects:
            return None

        obj = response.objects[0]
        supports = self._parse_ids(obj.properties.get("supports_ids", ""))
        contradicts = self._parse_ids(obj.properties.get("contradicts_ids", ""))
        derived_from = self._parse_ids(obj.properties.get("derived_from_ids", ""))

        return KnowledgeSearchResult(
            node_id=obj.properties.get("node_id", ""),
            workspace_id=obj.properties.get("workspace_id", ""),
            node_type=obj.properties.get("node_type", "fact"),
            content=obj.properties.get("content", ""),
            confidence=obj.properties.get("confidence", 0.5),
            score=1.0,
            tier=obj.properties.get("tier", "slow"),
            supports=supports,
            contradicts=contradicts,
            derived_from=derived_from,
        )

    async def delete_node(self, node_id: str, workspace_id: str | None = None) -> bool:
        """
        Delete a specific node.

        Args:
            node_id: Node ID to delete
            workspace_id: Optional workspace filter

        Returns:
            True if deleted, False if not found
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        ws = workspace_id or self.workspace_id
        filters = Filter.by_property("workspace_id").equal(ws) & Filter.by_property(
            "node_id"
        ).equal(node_id)

        result = self._collection.data.delete_many(where=filters)
        deleted = result.successful if hasattr(result, "successful") else 0
        return deleted > 0

    async def delete_workspace(self, workspace_id: str | None = None) -> int:
        """
        Delete all nodes in a workspace.

        Args:
            workspace_id: Workspace to clear (defaults to store's workspace)

        Returns:
            Number of nodes deleted
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        ws = workspace_id or self.workspace_id
        result = self._collection.data.delete_many(
            where=Filter.by_property("workspace_id").equal(ws)
        )

        deleted = result.successful if hasattr(result, "successful") else 0
        logger.info("Deleted %s nodes from workspace %s", deleted, ws)
        return deleted

    async def count_nodes(
        self,
        node_type: str | None = None,
        workspace_id: str | None = None,
    ) -> int:
        """
        Count nodes in the collection.

        Args:
            node_type: Optional filter to specific type
            workspace_id: Optional workspace filter

        Returns:
            Number of nodes
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")

        ws = workspace_id or self.workspace_id
        filters = Filter.by_property("workspace_id").equal(ws)

        if node_type:
            filters = filters & Filter.by_property("node_type").equal(node_type)

        response = self._collection.aggregate.over_all(
            filters=filters,
            total_count=True,
        )

        return response.total_count or 0

    async def get_type_distribution(self, workspace_id: str | None = None) -> dict[str, int]:
        """
        Get distribution of node types in a workspace.

        Args:
            workspace_id: Optional workspace filter

        Returns:
            Dict mapping node type to count
        """
        distribution = {}
        for node_type in self.VALID_NODE_TYPES:
            count = await self.count_nodes(node_type=node_type, workspace_id=workspace_id)
            if count > 0:
                distribution[node_type] = count
        return distribution

    async def health_check(self) -> dict[str, Any]:
        """
        Check vector store connection health.

        Returns:
            Health status dictionary
        """
        if not self._client:
            return {"healthy": False, "error": "Not connected"}

        try:
            is_ready = self._client.is_ready()
            node_count = await self.count_nodes() if is_ready else 0
            return {
                "healthy": is_ready,
                "url": self.config.url,
                "collection": self.config.collection_name,
                "workspace": self.workspace_id,
                "node_count": node_count,
            }
        except (RuntimeError, ConnectionError, TimeoutError) as e:
            logger.warning("Health check failed: %s", e)
            return {"healthy": False, "error": "Health check failed"}
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            logger.exception("Unexpected error in health check: %s", e)
            return {"healthy": False, "error": "Health check failed"}

    @staticmethod
    def _parse_ids(ids_string: str) -> list[str]:
        """Parse comma-separated IDs string into list."""
        if not ids_string:
            return []
        return [id.strip() for id in ids_string.split(",") if id.strip()]


# Global store instances per workspace (singleton pattern)
_stores: dict[str, KnowledgeVectorStore] = {}


def get_knowledge_vector_store(
    workspace_id: str = "default",
    config: KnowledgeVectorConfig | None = None,
) -> KnowledgeVectorStore:
    """Get or create knowledge vector store instance for a workspace."""
    global _stores
    if workspace_id not in _stores:
        _stores[workspace_id] = KnowledgeVectorStore(workspace_id, config)
    return _stores[workspace_id]
