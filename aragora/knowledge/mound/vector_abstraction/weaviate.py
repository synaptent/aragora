"""
Weaviate vector store adapter.

Wraps the Weaviate client to provide the BaseVectorStore interface,
enabling seamless use of Weaviate within the Knowledge Mound.

Requirements:
    pip install weaviate-client>=4.0
"""

from __future__ import annotations

import logging
import warnings
from typing import Any, cast
from collections.abc import Sequence

from aragora.knowledge.mound.vector_abstraction.base import (
    BaseVectorStore,
    VectorBackend,
    VectorSearchResult,
    VectorStoreConfig,
)

logger = logging.getLogger(__name__)

# Check for weaviate library
try:
    # weaviate's package __init__ calls a bare warnings.simplefilter("default")
    # (and its transitive imports register more filters), globally rewriting the
    # ambient warning policy; the scoped guard confines that to this import.
    with warnings.catch_warnings():
        import weaviate
        from weaviate.classes.config import Configure, DataType, Property
        from weaviate.classes.data import DataObject  # noqa: F401
        from weaviate.classes.query import Filter, MetadataQuery

    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False
    logger.debug("weaviate-client not available - install with: pip install weaviate-client")


class WeaviateVectorStore(BaseVectorStore):
    """
    Weaviate vector store adapter.

    Provides enterprise-grade vector storage with:
    - Multi-tenant isolation via namespaces
    - Hybrid search (BM25 + vector)
    - Automatic schema management
    - Batch operations

    Usage:
        config = VectorStoreConfig(
            backend=VectorBackend.WEAVIATE,
            url="http://localhost:8080",
            collection_name="knowledge_mound",
        )
        store = WeaviateVectorStore(config)
        await store.connect()
    """

    # Initialized by BaseVectorStore.__init__; annotated here because the
    # changed-file mypy hook runs with --follow-imports=skip and cannot see it.
    _connected: bool

    def __init__(self, config: VectorStoreConfig):
        """Initialize Weaviate store."""
        if not WEAVIATE_AVAILABLE:
            raise ImportError(
                "Weaviate client not installed. Install with: pip install weaviate-client"
            )

        # Ensure backend is WEAVIATE
        config.backend = VectorBackend.WEAVIATE
        super().__init__(config)

        self._client: Any | None = None
        self._collections: dict[str, Any] = {}  # Cache for collection references

    # -------------------------------------------------------------------------
    # Connection Management
    # -------------------------------------------------------------------------

    async def connect(self) -> None:
        """Establish connection to Weaviate."""
        if self._connected:
            return

        try:
            url = self.config.url or "http://localhost:8080"

            # Parse URL for connection
            if self.config.api_key:
                # Cloud or authenticated connection
                # weaviate v4 connect_to_custom signature varies across versions;
                # cast to Any to avoid call-arg mismatches with type stubs
                _connect = cast(Any, weaviate.connect_to_custom)
                self._client = _connect(
                    http_host=url.replace("http://", "").replace("https://", "").split(":")[0],
                    http_port=int(url.split(":")[-1]) if ":" in url.split("/")[-1] else 8080,
                    http_secure=url.startswith("https"),
                    grpc_port=self.config.extra.get("grpc_port", 50051),
                    grpc_secure=url.startswith("https"),
                    auth_credentials=weaviate.auth.AuthApiKey(self.config.api_key),
                )
            else:
                # Local connection
                self._client = weaviate.connect_to_local()

            self._connected = True

            # Ensure default collection exists
            if not await self.collection_exists(self.config.collection_name):
                await self.create_collection(self.config.collection_name)

            logger.info("Connected to Weaviate at %s", url)

        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            self._connected = False
            raise ConnectionError(f"Failed to connect to Weaviate: {e}") from e

    async def disconnect(self) -> None:
        """Close connection to Weaviate."""
        if self._client:
            try:
                self._client.close()
            except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                logger.warning("Error closing Weaviate connection: %s", e)
            finally:
                self._client = None
                self._collections.clear()
                self._connected = False

    # -------------------------------------------------------------------------
    # Collection Management
    # -------------------------------------------------------------------------

    async def create_collection(
        self,
        name: str,
        schema: dict[str, Any] | None = None,
    ) -> None:
        """Create a new collection with schema."""
        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        if self._client.collections.exists(name):
            return

        # Default properties
        properties = [
            Property(name="content", data_type=DataType.TEXT),
            Property(name="namespace", data_type=DataType.TEXT),
        ]

        # Add custom schema properties
        if schema:
            for prop_name, prop_type in schema.items():
                if prop_name not in ["content", "namespace"]:
                    data_type = self._map_data_type(prop_type)
                    properties.append(Property(name=prop_name, data_type=data_type))

        # Create collection with vectorizer config
        self._client.collections.create(
            name=name,
            properties=properties,
            vectorizer_config=Configure.Vectorizer.none(),  # We provide our own embeddings
        )

        logger.info("Created Weaviate collection: %s", name)

    async def delete_collection(self, name: str) -> bool:
        """Delete a collection."""
        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        if not self._client.collections.exists(name):
            return False

        self._client.collections.delete(name)
        self._collections.pop(name, None)
        return True

    async def collection_exists(self, name: str) -> bool:
        """Check if collection exists."""
        if not self._client:
            raise ConnectionError("Not connected to Weaviate")
        return self._client.collections.exists(name)

    async def list_collections(self) -> list[str]:
        """List all collections."""
        if not self._client:
            raise ConnectionError("Not connected to Weaviate")
        return [c.name for c in self._client.collections.list_all()]

    # -------------------------------------------------------------------------
    # Data Operations
    # -------------------------------------------------------------------------

    async def upsert(
        self,
        id: str,
        embedding: list[float],
        content: str,
        metadata: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> str:
        """Insert or update a vector."""
        collection = self._get_collection()

        properties = {
            "content": content,
            "namespace": namespace or "",
            **(metadata or {}),
        }

        # Check if exists first for upsert
        try:
            existing = collection.query.fetch_object_by_id(id)
            if existing:
                collection.data.update(
                    uuid=id,
                    properties=properties,
                    vector=embedding,
                )
            else:
                collection.data.insert(
                    uuid=id,
                    properties=properties,
                    vector=embedding,
                )
        except (KeyError, RuntimeError) as e:
            # Insert if fetch failed
            logger.debug("Vector fetch failed, inserting new: %s", e)
            collection.data.insert(
                uuid=id,
                properties=properties,
                vector=embedding,
            )

        return id

    async def upsert_batch(
        self,
        items: Sequence[dict[str, Any]],
        namespace: str | None = None,
    ) -> list[str]:
        """Batch upsert multiple vectors."""
        collection = self._get_collection()
        ids = []

        with collection.batch.dynamic() as batch:
            for item in items:
                item_id = item.get("id")
                properties = {
                    "content": item["content"],
                    "namespace": namespace or "",
                    **(item.get("metadata") or {}),
                }
                batch.add_object(
                    properties=properties,
                    vector=item["embedding"],
                    uuid=item_id,
                )
                ids.append(item_id)

        # Items without an explicit "id" append None here; preserved as-is, the
        # cast only records the declared contract.
        return cast("list[str]", ids)

    async def delete(
        self,
        ids: Sequence[str],
        namespace: str | None = None,
    ) -> int:
        """Delete vectors by ID."""
        collection = self._get_collection()
        deleted = 0

        for id in ids:
            try:
                collection.data.delete_by_id(id)
                deleted += 1
            except (KeyError, RuntimeError, ValueError) as e:
                logger.debug("Error deleting vector %s: %s", id, e)

        return deleted

    async def delete_by_filter(
        self,
        filters: dict[str, Any],
        namespace: str | None = None,
    ) -> int:
        """Delete vectors matching filter criteria."""
        collection = self._get_collection()

        # Build filter
        weaviate_filter = self._build_filter(filters, namespace)

        # Count before delete
        count_before = collection.aggregate.over_all(total_count=True).total_count

        # Delete with filter
        collection.data.delete_many(where=weaviate_filter)

        # Count after delete
        count_after = collection.aggregate.over_all(total_count=True).total_count

        return count_before - count_after

    # -------------------------------------------------------------------------
    # Search Operations
    # -------------------------------------------------------------------------

    async def search(
        self,
        embedding: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        namespace: str | None = None,
        min_score: float = 0.0,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors."""
        collection = self._get_collection()

        # Build filter
        weaviate_filter = self._build_filter(filters, namespace)

        # Perform search
        response = collection.query.near_vector(
            near_vector=embedding,
            limit=limit,
            filters=weaviate_filter,
            return_metadata=MetadataQuery(distance=True),
        )

        results = []
        for obj in response.objects:
            # Convert distance to similarity score (cosine)
            distance = obj.metadata.distance or 0
            score = 1 - distance  # Weaviate returns distance, not similarity

            if score >= min_score:
                results.append(
                    VectorSearchResult(
                        id=str(obj.uuid),
                        content=obj.properties.get("content", ""),
                        score=score,
                        metadata={
                            k: v
                            for k, v in obj.properties.items()
                            if k not in ["content", "namespace"]
                        },
                        embedding=obj.vector.get("default") if obj.vector else None,
                    )
                )

        return results

    async def hybrid_search(
        self,
        query: str,
        embedding: list[float],
        limit: int = 10,
        alpha: float = 0.5,
        filters: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> list[VectorSearchResult]:
        """Hybrid search combining vector and BM25 keyword matching."""
        collection = self._get_collection()

        # Build filter
        weaviate_filter = self._build_filter(filters, namespace)

        # Perform hybrid search
        response = collection.query.hybrid(
            query=query,
            vector=embedding,
            alpha=alpha,  # 0 = pure BM25, 1 = pure vector
            limit=limit,
            filters=weaviate_filter,
            return_metadata=MetadataQuery(score=True),
        )

        results = []
        for obj in response.objects:
            score = obj.metadata.score or 0

            results.append(
                VectorSearchResult(
                    id=str(obj.uuid),
                    content=obj.properties.get("content", ""),
                    score=score,
                    metadata={
                        k: v for k, v in obj.properties.items() if k not in ["content", "namespace"]
                    },
                    embedding=obj.vector.get("default") if obj.vector else None,
                )
            )

        return results

    # -------------------------------------------------------------------------
    # Retrieval Operations
    # -------------------------------------------------------------------------

    async def get_by_id(
        self,
        id: str,
        namespace: str | None = None,
    ) -> VectorSearchResult | None:
        """Get a specific vector by ID."""
        collection = self._get_collection()

        try:
            obj = collection.query.fetch_object_by_id(
                id,
                include_vector=True,
            )
            if obj:
                return VectorSearchResult(
                    id=str(obj.uuid),
                    content=obj.properties.get("content", ""),
                    score=1.0,
                    metadata={
                        k: v for k, v in obj.properties.items() if k not in ["content", "namespace"]
                    },
                    embedding=obj.vector.get("default") if obj.vector else None,
                )
        except (OSError, ConnectionError, RuntimeError) as e:
            logger.debug("Error retrieving vector by ID: %s", e)

        return None

    async def get_by_ids(
        self,
        ids: Sequence[str],
        namespace: str | None = None,
    ) -> list[VectorSearchResult]:
        """Get multiple vectors by ID."""
        results = []
        for id in ids:
            result = await self.get_by_id(id, namespace)
            if result:
                results.append(result)
        return results

    async def count(
        self,
        filters: dict[str, Any] | None = None,
        namespace: str | None = None,
    ) -> int:
        """Count vectors matching optional filters."""
        collection = self._get_collection()

        weaviate_filter = self._build_filter(filters, namespace)

        if weaviate_filter:
            result = collection.aggregate.over_all(
                filters=weaviate_filter,
                total_count=True,
            )
        else:
            result = collection.aggregate.over_all(total_count=True)

        return result.total_count or 0

    # -------------------------------------------------------------------------
    # Health & Diagnostics
    # -------------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Check health and return diagnostics."""
        if not self._client:
            return {"status": "disconnected", "backend": "weaviate"}

        try:
            meta = self._client.get_meta()
            return {
                "status": "healthy",
                "backend": "weaviate",
                "version": meta.get("version", "unknown"),
                "modules": list(meta.get("modules", {}).keys()),
            }
        except (OSError, ConnectionError, RuntimeError, ValueError):
            return {
                "status": "unhealthy",
                "backend": "weaviate",
                "error": "Health check failed",
            }

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_collection(self) -> Any:
        """Get collection reference."""
        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        name = self.config.collection_name
        if name not in self._collections:
            self._collections[name] = self._client.collections.get(name)
        return self._collections[name]

    def _build_filter(
        self,
        filters: dict[str, Any] | None,
        namespace: str | None,
    ) -> Any | None:
        """Build Weaviate filter from dict."""
        conditions = []

        if namespace:
            conditions.append(Filter.by_property("namespace").equal(namespace))

        if filters:
            for key, value in filters.items():
                conditions.append(Filter.by_property(key).equal(value))

        if not conditions:
            return None

        if len(conditions) == 1:
            return conditions[0]

        # Combine with AND
        result = conditions[0]
        for cond in conditions[1:]:
            result = result & cond
        return result

    def _map_data_type(self, type_str: str) -> DataType:
        """Map string type to Weaviate DataType."""
        mapping = {
            "string": DataType.TEXT,
            "text": DataType.TEXT,
            "int": DataType.INT,
            "integer": DataType.INT,
            "float": DataType.NUMBER,
            "number": DataType.NUMBER,
            "bool": DataType.BOOL,
            "boolean": DataType.BOOL,
            "date": DataType.DATE,
        }
        return mapping.get(type_str.lower(), DataType.TEXT)
