"""
Weaviate vector database adapter for document indexing.

Provides enterprise-grade vector storage with:
- Multi-tenant isolation
- Hybrid search (BM25 + vector)
- Automatic schema management
- Batch import with streaming

Requirements:
    pip install weaviate-client

Usage:
    from aragora.documents.indexing.weaviate_store import WeaviateStore

    store = WeaviateStore()
    await store.connect()
    await store.index_chunks(document_id, chunks)
    results = await store.search("query", limit=10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import warnings
from dataclasses import dataclass, field
from typing import Any, cast
from collections.abc import Callable

from aragora.documents.models import DocumentChunk

logger = logging.getLogger(__name__)

try:
    # weaviate's package __init__ calls a bare warnings.simplefilter("default")
    # (and its transitive imports register more filters), globally rewriting the
    # ambient warning policy; the scoped guard confines that to this import.
    with warnings.catch_warnings():
        import weaviate
        from weaviate.classes.config import Configure, Property, DataType
        from weaviate.classes.query import MetadataQuery, Filter
        from weaviate.classes.data import DataObject  # noqa: F401

    WEAVIATE_AVAILABLE = True
except ImportError:
    weaviate = None  # type: ignore[assignment]
    Configure = None  # type: ignore[assignment,misc]
    Property = None  # type: ignore[assignment,misc]
    DataType = None  # type: ignore[assignment,misc]
    MetadataQuery = None  # type: ignore[assignment,misc]
    Filter = None  # type: ignore[assignment,misc]
    DataObject = None  # type: ignore[assignment,misc]

    WEAVIATE_AVAILABLE = False


@dataclass
class SearchResult:
    """A single search result from Weaviate."""

    chunk_id: str
    document_id: str
    content: str
    score: float
    chunk_type: str = "text"
    heading_context: str = ""
    start_page: int = 0
    end_page: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "content": self.content,
            "score": self.score,
            "chunk_type": self.chunk_type,
            "heading_context": self.heading_context,
            "start_page": self.start_page,
            "end_page": self.end_page,
            "metadata": self.metadata,
        }


@dataclass
class WeaviateConfig:
    """Configuration for Weaviate connection."""

    url: str = "http://localhost:8080"
    api_key: str | None = None
    collection_name: str = "DocumentChunks"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    batch_size: int = 100
    timeout: int = 30

    @classmethod
    def from_env(cls) -> WeaviateConfig:
        """Create config from environment variables."""
        return cls(
            url=os.getenv("WEAVIATE_URL", "http://localhost:8080"),
            api_key=os.getenv("WEAVIATE_API_KEY"),
            collection_name=os.getenv("WEAVIATE_COLLECTION", "DocumentChunks"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        )


class WeaviateStore:
    """
    Weaviate vector store for document chunks.

    Provides indexing and retrieval of document chunks with
    support for hybrid search combining BM25 and vector similarity.
    """

    def __init__(self, config: WeaviateConfig | None = None):
        """
        Initialize Weaviate store.

        Args:
            config: Weaviate connection configuration
        """
        self.config = config or WeaviateConfig.from_env()
        self._client: Any | None = None
        self._collection: Any | None = None
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
            logger.info("Connected to Weaviate at %s", self.config.url)
            return True

        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            logger.error("Failed to connect to Weaviate: %s", e)
            self._connected = False
            raise

    async def _ensure_collection(self) -> None:
        """Create collection if it doesn't exist."""
        if self._client is None:
            raise RuntimeError("Not connected to Weaviate")

        collections = self._client.collections

        if not collections.exists(self.config.collection_name):
            logger.info("Creating collection: %s", self.config.collection_name)

            collections.create(
                name=self.config.collection_name,
                vectorizer_config=Configure.Vectorizer.none(),  # We provide embeddings
                properties=[
                    Property(name="chunk_id", data_type=DataType.TEXT),
                    Property(name="document_id", data_type=DataType.TEXT),
                    Property(name="content", data_type=DataType.TEXT),
                    Property(name="chunk_type", data_type=DataType.TEXT),
                    Property(name="heading_context", data_type=DataType.TEXT),
                    Property(name="start_page", data_type=DataType.INT),
                    Property(name="end_page", data_type=DataType.INT),
                    Property(name="sequence", data_type=DataType.INT),
                    Property(name="token_count", data_type=DataType.INT),
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

    async def index_chunk(
        self,
        chunk: DocumentChunk,
        embedding: list[float],
    ) -> str:
        """
        Index a single document chunk.

        Args:
            chunk: Document chunk to index
            embedding: Vector embedding for the chunk

        Returns:
            Weaviate object UUID
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        properties = {
            "chunk_id": chunk.id,
            "document_id": chunk.document_id,
            "content": chunk.content,
            "chunk_type": (
                chunk.chunk_type.value
                if hasattr(chunk.chunk_type, "value")
                else str(chunk.chunk_type)
            ),
            "heading_context": chunk.heading_context or "",
            "start_page": chunk.start_page,
            "end_page": chunk.end_page,
            "sequence": chunk.sequence,
            "token_count": chunk.token_count,
        }

        uuid = collection.data.insert(
            properties=properties,
            vector=embedding,
        )

        return str(uuid)

    async def index_chunks(
        self,
        chunks: list[DocumentChunk],
        embeddings: list[list[float]],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        """
        Batch index multiple document chunks.

        Args:
            chunks: List of document chunks
            embeddings: Corresponding vector embeddings
            on_progress: Optional callback(indexed, total)

        Returns:
            List of Weaviate object UUIDs
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        if len(chunks) != len(embeddings):
            raise ValueError("Number of chunks must match number of embeddings")

        uuids = []
        total = len(chunks)

        # Process in batches
        for i in range(0, total, self.config.batch_size):
            batch_chunks = chunks[i : i + self.config.batch_size]
            batch_embeddings = embeddings[i : i + self.config.batch_size]

            with collection.batch.dynamic() as batch:
                for chunk, embedding in zip(batch_chunks, batch_embeddings):
                    properties = {
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "content": chunk.content,
                        "chunk_type": (
                            chunk.chunk_type.value
                            if hasattr(chunk.chunk_type, "value")
                            else str(chunk.chunk_type)
                        ),
                        "heading_context": chunk.heading_context or "",
                        "start_page": chunk.start_page,
                        "end_page": chunk.end_page,
                        "sequence": chunk.sequence,
                        "token_count": chunk.token_count,
                    }

                    uuid = batch.add_object(
                        properties=properties,
                        vector=embedding,
                    )
                    uuids.append(str(uuid))

            if on_progress is not None:
                on_progress(min(i + self.config.batch_size, total), total)

            # Small delay between batches to avoid overwhelming the server
            await asyncio.sleep(0.01)

        logger.info("Indexed %s chunks to Weaviate", len(uuids))
        return uuids

    async def search_vector(
        self,
        embedding: list[float],
        limit: int = 10,
        document_ids: list[str] | None = None,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """
        Search for similar chunks using vector similarity.

        Args:
            embedding: Query vector embedding
            limit: Maximum results to return
            document_ids: Optional filter to specific documents
            min_score: Minimum similarity score (0-1)

        Returns:
            List of search results
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        # Build filter if document_ids specified
        filters = None
        if document_ids:
            filters = Filter.by_property("document_id").contains_any(document_ids)

        response = collection.query.near_vector(
            near_vector=embedding,
            limit=limit,
            filters=filters,
            return_metadata=MetadataQuery(distance=True),
        )

        results = []
        for obj in response.objects:
            # Convert distance to similarity score (Weaviate uses cosine distance)
            distance = obj.metadata.distance or 0.0
            score = 1.0 - distance  # Convert distance to similarity

            if score >= min_score:
                results.append(
                    SearchResult(
                        chunk_id=obj.properties.get("chunk_id", ""),
                        document_id=obj.properties.get("document_id", ""),
                        content=obj.properties.get("content", ""),
                        score=score,
                        chunk_type=obj.properties.get("chunk_type", "text"),
                        heading_context=obj.properties.get("heading_context", ""),
                        start_page=obj.properties.get("start_page", 0),
                        end_page=obj.properties.get("end_page", 0),
                    )
                )

        return results

    async def search_keyword(
        self,
        query: str,
        limit: int = 10,
        document_ids: list[str] | None = None,
    ) -> list[SearchResult]:
        """
        Search for chunks using BM25 keyword matching.

        Args:
            query: Search query text
            limit: Maximum results to return
            document_ids: Optional filter to specific documents

        Returns:
            List of search results
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        # Build filter if document_ids specified
        filters = None
        if document_ids:
            filters = Filter.by_property("document_id").contains_any(document_ids)

        response = collection.query.bm25(
            query=query,
            limit=limit,
            filters=filters,
            return_metadata=MetadataQuery(score=True),
        )

        results = []
        for obj in response.objects:
            score = obj.metadata.score or 0.0

            results.append(
                SearchResult(
                    chunk_id=obj.properties.get("chunk_id", ""),
                    document_id=obj.properties.get("document_id", ""),
                    content=obj.properties.get("content", ""),
                    score=score,
                    chunk_type=obj.properties.get("chunk_type", "text"),
                    heading_context=obj.properties.get("heading_context", ""),
                    start_page=obj.properties.get("start_page", 0),
                    end_page=obj.properties.get("end_page", 0),
                )
            )

        return results

    async def delete_document(self, document_id: str) -> int:
        """
        Delete all chunks for a document.

        Args:
            document_id: Document ID to delete

        Returns:
            Number of chunks deleted
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        result = collection.data.delete_many(
            where=Filter.by_property("document_id").equal(document_id)
        )

        deleted = result.successful if hasattr(result, "successful") else 0
        logger.info("Deleted %s chunks for document %s", deleted, document_id)
        return deleted

    async def get_document_chunks(
        self,
        document_id: str,
        limit: int = 1000,
    ) -> list[SearchResult]:
        """
        Get all chunks for a specific document.

        Args:
            document_id: Document ID to retrieve
            limit: Maximum chunks to return

        Returns:
            List of chunks as SearchResult objects
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        response = collection.query.fetch_objects(
            filters=Filter.by_property("document_id").equal(document_id),
            limit=limit,
        )

        results = []
        for obj in response.objects:
            results.append(
                SearchResult(
                    chunk_id=obj.properties.get("chunk_id", ""),
                    document_id=obj.properties.get("document_id", ""),
                    content=obj.properties.get("content", ""),
                    score=1.0,  # No score for direct fetch
                    chunk_type=obj.properties.get("chunk_type", "text"),
                    heading_context=obj.properties.get("heading_context", ""),
                    start_page=obj.properties.get("start_page", 0),
                    end_page=obj.properties.get("end_page", 0),
                )
            )

        # Sort by sequence
        results.sort(key=lambda r: r.metadata.get("sequence", 0) if r.metadata else 0)
        return results

    async def count_chunks(self, document_id: str | None = None) -> int:
        """
        Count chunks in the collection.

        Args:
            document_id: Optional filter to specific document

        Returns:
            Number of chunks
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to Weaviate")
        collection = cast(Any, self._collection)

        if document_id:
            response = collection.aggregate.over_all(
                filters=Filter.by_property("document_id").equal(document_id),
                total_count=True,
            )
        else:
            response = collection.aggregate.over_all(total_count=True)

        return response.total_count or 0

    async def health_check(self) -> dict[str, Any]:
        """
        Check Weaviate connection health.

        Returns:
            Health status dictionary
        """
        if not self._client:
            return {"healthy": False, "error": "Not connected"}

        try:
            is_ready = self._client.is_ready()
            return {
                "healthy": is_ready,
                "url": self.config.url,
                "collection": self.config.collection_name,
            }
        except (ConnectionError, TimeoutError, OSError, RuntimeError) as e:
            return {"healthy": False, "error": str(e)}


# Global store instance (singleton pattern)
_store: WeaviateStore | None = None


def get_weaviate_store(config: WeaviateConfig | None = None) -> WeaviateStore:
    """Get or create global Weaviate store instance."""
    global _store
    if _store is None:
        _store = WeaviateStore(config)
    return _store


__all__ = [
    "WeaviateStore",
    "WeaviateConfig",
    "SearchResult",
    "get_weaviate_store",
    "WEAVIATE_AVAILABLE",
]
