"""
Weaviate Embedding Service for vector-based semantic search.

Provides hybrid search (vector + BM25) over document chunks
using Weaviate as the vector database.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Any

from aragora.knowledge.search.bm25 import BM25Index, HybridSearcher

logger = logging.getLogger(__name__)

# Optional Weaviate import
WeaviateConnectionError: type[Exception]

try:
    # weaviate's package __init__ calls a bare warnings.simplefilter("default")
    # (and its transitive imports register more filters), globally rewriting the
    # ambient warning policy; the scoped guard confines that to this import.
    with warnings.catch_warnings():
        import weaviate
        from weaviate.classes.config import Configure, Property, DataType
        from weaviate.classes.query import MetadataQuery, Filter
        from weaviate.exceptions import WeaviateConnectionError as _WeaviateConnectionError

    WeaviateConnectionError = _WeaviateConnectionError
    WEAVIATE_AVAILABLE = True
except ImportError:
    WEAVIATE_AVAILABLE = False
    weaviate = None  # type: ignore[assignment]

    class _FallbackWeaviateConnectionError(Exception):
        """Fallback exception when Weaviate is not available."""

    WeaviateConnectionError = _FallbackWeaviateConnectionError


@dataclass
class ChunkMatch:
    """A matching chunk from vector search."""

    chunk_id: str
    document_id: str
    workspace_id: str
    content: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "workspace_id": self.workspace_id,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
        }

    @classmethod
    def from_weaviate(cls, obj: Any, workspace_id: str = "") -> ChunkMatch:
        """Create from Weaviate search result."""
        props = obj.properties
        return cls(
            chunk_id=props.get("chunk_id", ""),
            document_id=props.get("document_id", ""),
            workspace_id=props.get("workspace_id", workspace_id),
            content=props.get("content", ""),
            score=getattr(obj.metadata, "score", 0.0) if obj.metadata else 0.0,
            metadata={
                k: v
                for k, v in props.items()
                if k not in ("chunk_id", "document_id", "workspace_id", "content")
            },
        )


@dataclass
class EmbeddingConfig:
    """Configuration for embedding service."""

    weaviate_url: str = "http://localhost:8080"
    weaviate_api_key: str | None = None
    collection_name: str = "DocumentChunk"
    vectorizer: str = "text2vec-transformers"  # or "text2vec-openai"
    openai_api_key: str | None = None
    batch_size: int = 100


class WeaviateEmbeddingService:
    """Generate and store embeddings using Weaviate.

    Provides hybrid search combining vector similarity with BM25
    keyword matching for document chunks.
    """

    def __init__(self, config: EmbeddingConfig | None = None):
        """Initialize the embedding service.

        Args:
            config: Service configuration

        Raises:
            ImportError: If weaviate-client is not installed
            ConnectionError: If cannot connect to Weaviate
        """
        if not WEAVIATE_AVAILABLE:
            raise ImportError(
                "weaviate-client is required for WeaviateEmbeddingService. "
                "Install with: pip install weaviate-client>=4.0.0"
            )

        self.config = config or EmbeddingConfig()
        self._client: Any | None = None
        self._connected = False

    def connect(self) -> None:
        """Connect to Weaviate server.

        Raises:
            ConnectionError: If cannot connect
        """
        if self._connected:
            return

        try:
            if self.config.weaviate_api_key:
                # Connect to Weaviate Cloud
                self._client = weaviate.connect_to_wcs(
                    cluster_url=self.config.weaviate_url,
                    auth_credentials=weaviate.auth.AuthApiKey(self.config.weaviate_api_key),
                )
            else:
                # Connect to local Weaviate
                self._client = weaviate.connect_to_local(
                    host=self.config.weaviate_url.replace("http://", "")
                    .replace("https://", "")
                    .split(":")[0],
                    port=(
                        int(self.config.weaviate_url.split(":")[-1])
                        if ":" in self.config.weaviate_url
                        else 8080
                    ),
                )

            self._connected = True
            self._ensure_schema()
            logger.info("Connected to Weaviate at %s", self.config.weaviate_url)

        except WeaviateConnectionError as e:
            raise ConnectionError(f"Failed to connect to Weaviate: {e}") from e

    def _ensure_schema(self) -> None:
        """Create Weaviate collection if it doesn't exist."""
        if not self._client:
            return

        collection_name = self.config.collection_name

        # Check if collection exists
        if self._client.collections.exists(collection_name):
            logger.debug("Collection %s already exists", collection_name)
            return

        # Create collection with properties
        logger.info("Creating collection %s", collection_name)

        # Configure vectorizer based on config
        if self.config.vectorizer == "text2vec-openai" and self.config.openai_api_key:
            vectorizer_config = Configure.Vectorizer.text2vec_openai(
                model="text-embedding-3-small",
            )
        else:
            # Default to transformers (requires t2v-transformers module)
            vectorizer_config = Configure.Vectorizer.text2vec_transformers()

        self._client.collections.create(
            name=collection_name,
            vectorizer_config=vectorizer_config,
            properties=[
                Property(name="chunk_id", data_type=DataType.TEXT),
                Property(name="document_id", data_type=DataType.TEXT),
                Property(name="workspace_id", data_type=DataType.TEXT),
                Property(name="content", data_type=DataType.TEXT),
                Property(name="chunk_index", data_type=DataType.INT),
                Property(name="file_path", data_type=DataType.TEXT),
                Property(name="file_type", data_type=DataType.TEXT),
                Property(name="topics", data_type=DataType.TEXT_ARRAY),
            ],
        )

    def close(self) -> None:
        """Close Weaviate connection."""
        if self._client:
            self._client.close()
            self._client = None
            self._connected = False

    def __enter__(self) -> WeaviateEmbeddingService:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

    async def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        workspace_id: str,
    ) -> int:
        """Batch upload chunks to Weaviate with embeddings.

        Args:
            chunks: List of chunk dictionaries with:
                - chunk_id: Unique chunk ID
                - document_id: Parent document ID
                - content: Text content
                - chunk_index: Position in document
                - file_path: Source file path
                - file_type: File type/extension
                - topics: Optional list of topics
            workspace_id: Workspace ID for isolation

        Returns:
            Number of chunks embedded
        """
        if not self._connected:
            self.connect()

        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        collection = self._client.collections.get(self.config.collection_name)
        count = 0

        # Batch insert
        with collection.batch.dynamic() as batch:
            for chunk in chunks:
                batch.add_object(
                    properties={
                        "chunk_id": chunk.get("chunk_id", ""),
                        "document_id": chunk.get("document_id", ""),
                        "workspace_id": workspace_id,
                        "content": chunk.get("content", ""),
                        "chunk_index": chunk.get("chunk_index", 0),
                        "file_path": chunk.get("file_path", ""),
                        "file_type": chunk.get("file_type", ""),
                        "topics": chunk.get("topics", []),
                    }
                )
                count += 1

        logger.info("Embedded %s chunks for workspace %s", count, workspace_id)
        return count

    async def hybrid_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 10,
        alpha: float = 0.5,
        min_score: float = 0.0,
    ) -> list[ChunkMatch]:
        """Hybrid search combining vector similarity and BM25.

        Args:
            query: Search query
            workspace_id: Workspace to search in
            limit: Maximum results
            alpha: Balance between vector (0) and keyword (1)
            min_score: Minimum score threshold

        Returns:
            List of matching chunks
        """
        if not self._connected:
            self.connect()

        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        collection = self._client.collections.get(self.config.collection_name)

        # Build filter for workspace isolation
        workspace_filter = Filter.by_property("workspace_id").equal(workspace_id)

        # Hybrid search
        response = collection.query.hybrid(
            query=query,
            alpha=alpha,
            limit=limit,
            filters=workspace_filter,
            return_metadata=MetadataQuery(score=True),
        )

        results = []
        for obj in response.objects:
            match = ChunkMatch.from_weaviate(obj, workspace_id)
            if match.score >= min_score:
                results.append(match)

        return results

    async def vector_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[ChunkMatch]:
        """Pure vector similarity search.

        Args:
            query: Search query
            workspace_id: Workspace to search in
            limit: Maximum results
            min_score: Minimum score threshold

        Returns:
            List of matching chunks
        """
        if not self._connected:
            self.connect()

        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        collection = self._client.collections.get(self.config.collection_name)
        workspace_filter = Filter.by_property("workspace_id").equal(workspace_id)

        response = collection.query.near_text(
            query=query,
            limit=limit,
            filters=workspace_filter,
            return_metadata=MetadataQuery(score=True, distance=True),
        )

        results = []
        for obj in response.objects:
            match = ChunkMatch.from_weaviate(obj, workspace_id)
            if match.score >= min_score:
                results.append(match)

        return results

    async def keyword_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 10,
    ) -> list[ChunkMatch]:
        """BM25 keyword search.

        Args:
            query: Search query
            workspace_id: Workspace to search in
            limit: Maximum results

        Returns:
            List of matching chunks
        """
        if not self._connected:
            self.connect()

        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        collection = self._client.collections.get(self.config.collection_name)
        workspace_filter = Filter.by_property("workspace_id").equal(workspace_id)

        response = collection.query.bm25(
            query=query,
            limit=limit,
            filters=workspace_filter,
            return_metadata=MetadataQuery(score=True),
        )

        return [ChunkMatch.from_weaviate(obj, workspace_id) for obj in response.objects]

    async def delete_workspace_chunks(self, workspace_id: str) -> int:
        """Delete all chunks for a workspace.

        Args:
            workspace_id: Workspace to delete chunks from

        Returns:
            Number of chunks deleted
        """
        if not self._connected:
            self.connect()

        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        collection = self._client.collections.get(self.config.collection_name)
        workspace_filter = Filter.by_property("workspace_id").equal(workspace_id)

        # Delete matching objects
        result = collection.data.delete_many(where=workspace_filter)
        deleted = result.successful if hasattr(result, "successful") else 0

        logger.info("Deleted %s chunks for workspace %s", deleted, workspace_id)
        return deleted

    async def delete_document_chunks(self, document_id: str) -> int:
        """Delete all chunks for a document.

        Args:
            document_id: Document to delete chunks from

        Returns:
            Number of chunks deleted
        """
        if not self._connected:
            self.connect()

        if not self._client:
            raise ConnectionError("Not connected to Weaviate")

        collection = self._client.collections.get(self.config.collection_name)
        doc_filter = Filter.by_property("document_id").equal(document_id)

        result = collection.data.delete_many(where=doc_filter)
        deleted = result.successful if hasattr(result, "successful") else 0

        logger.info("Deleted %s chunks for document %s", deleted, document_id)
        return deleted

    def get_statistics(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get embedding statistics.

        Args:
            workspace_id: Optional workspace filter

        Returns:
            Statistics dictionary
        """
        if not self._connected:
            try:
                self.connect()
            except ConnectionError:
                return {"error": "Not connected to Weaviate", "total_chunks": 0}

        if not self._client:
            return {"error": "No client", "total_chunks": 0}

        collection = self._client.collections.get(self.config.collection_name)

        # Get aggregate count
        if workspace_id:
            workspace_filter = Filter.by_property("workspace_id").equal(workspace_id)
            response = collection.aggregate.over_all(filters=workspace_filter, total_count=True)
        else:
            response = collection.aggregate.over_all(total_count=True)

        return {
            "total_chunks": response.total_count if response else 0,
            "collection_name": self.config.collection_name,
            "vectorizer": self.config.vectorizer,
            "weaviate_url": self.config.weaviate_url,
        }


class InMemoryEmbeddingService:
    """In-memory embedding service for testing without Weaviate.

    Uses simple keyword matching instead of vector search.
    """

    def __init__(self):
        """Initialize in-memory store."""
        self._chunks: dict[str, dict[str, Any]] = {}  # chunk_id -> chunk data
        self._by_workspace: dict[str, set[str]] = {}  # workspace_id -> chunk_ids
        self._by_document: dict[str, set[str]] = {}  # document_id -> chunk_ids
        self._bm25_indices: dict[str, BM25Index] = {}  # workspace_id -> BM25 index

    def _get_bm25_index(self, workspace_id: str) -> BM25Index:
        """Get or create BM25 index for workspace."""
        if workspace_id not in self._bm25_indices:
            self._bm25_indices[workspace_id] = BM25Index()
        return self._bm25_indices[workspace_id]

    def connect(self) -> None:
        """No-op for in-memory."""
        pass

    def close(self) -> None:
        """No-op for in-memory."""
        pass

    def __enter__(self) -> InMemoryEmbeddingService:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    async def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        workspace_id: str,
    ) -> int:
        """Store chunks in memory and index in BM25."""
        count = 0
        bm25_index = self._get_bm25_index(workspace_id)

        for chunk in chunks:
            chunk_id = chunk.get("chunk_id", "")
            if not chunk_id:
                continue

            self._chunks[chunk_id] = {**chunk, "workspace_id": workspace_id}

            # Index by workspace
            if workspace_id not in self._by_workspace:
                self._by_workspace[workspace_id] = set()
            self._by_workspace[workspace_id].add(chunk_id)

            # Index by document
            doc_id = chunk.get("document_id", "")
            if doc_id:
                if doc_id not in self._by_document:
                    self._by_document[doc_id] = set()
                self._by_document[doc_id].add(chunk_id)

            # Index in BM25
            content = chunk.get("content", "")
            if content:
                bm25_index.add_document(
                    id=chunk_id,
                    content=content,
                    metadata={"document_id": doc_id},
                )

            count += 1

        return count

    async def hybrid_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 10,
        alpha: float = 0.5,
        min_score: float = 0.0,
    ) -> list[ChunkMatch]:
        """Hybrid search using BM25 + keyword matching with score fusion."""
        bm25_index = self._get_bm25_index(workspace_id)

        # Get BM25 results
        bm25_results = bm25_index.search(query, limit=limit * 2)

        # Get keyword match results (as fallback "vector" scores)
        keyword_results = await self._keyword_match(query, workspace_id, limit * 2)

        # Convert keyword results to HybridSearcher format
        vector_formatted = [
            {
                "id": r.chunk_id,
                "score": r.score,
                "content": r.content,
                "metadata": r.metadata,
            }
            for r in keyword_results
        ]

        # Use HybridSearcher to fuse results
        searcher = HybridSearcher(bm25_index, alpha=alpha, fusion_strategy="linear")
        fused = searcher.fuse_results(bm25_results, vector_formatted, limit)

        # Convert back to ChunkMatch format
        results = []
        for item in fused:
            chunk_id = item["id"]
            chunk = self._chunks.get(chunk_id, {})
            if item.get("score", 0) >= min_score:
                results.append(
                    ChunkMatch(
                        chunk_id=chunk_id,
                        document_id=chunk.get("document_id", ""),
                        workspace_id=workspace_id,
                        content=item.get("content", chunk.get("content", "")),
                        score=item["score"],
                        metadata=item.get("metadata", {}),
                    )
                )

        return results

    async def vector_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[ChunkMatch]:
        """Simple keyword search."""
        return await self._keyword_match(query, workspace_id, limit)

    async def keyword_search(
        self,
        query: str,
        workspace_id: str,
        limit: int = 10,
    ) -> list[ChunkMatch]:
        """Simple keyword search."""
        return await self._keyword_match(query, workspace_id, limit)

    async def _keyword_match(
        self,
        query: str,
        workspace_id: str,
        limit: int,
    ) -> list[ChunkMatch]:
        """Match chunks by keyword."""
        query_lower = query.lower()
        query_terms = set(query_lower.split())

        chunk_ids = self._by_workspace.get(workspace_id, set())
        results = []

        for chunk_id in chunk_ids:
            chunk = self._chunks.get(chunk_id)
            if not chunk:
                continue

            content = chunk.get("content", "").lower()
            content_terms = set(content.split())

            # Calculate simple overlap score
            overlap = len(query_terms & content_terms)
            if overlap > 0:
                score = overlap / len(query_terms)
                results.append(
                    ChunkMatch(
                        chunk_id=chunk_id,
                        document_id=chunk.get("document_id", ""),
                        workspace_id=workspace_id,
                        content=chunk.get("content", ""),
                        score=score,
                        metadata={
                            "file_path": chunk.get("file_path", ""),
                            "file_type": chunk.get("file_type", ""),
                            "topics": chunk.get("topics", []),
                        },
                    )
                )

        results.sort(key=lambda x: x.score, reverse=True)
        return results[:limit]

    async def delete_workspace_chunks(self, workspace_id: str) -> int:
        """Delete workspace chunks."""
        chunk_ids = self._by_workspace.pop(workspace_id, set())

        # Remove from BM25 index
        if workspace_id in self._bm25_indices:
            bm25_index = self._bm25_indices[workspace_id]
            for chunk_id in chunk_ids:
                bm25_index.remove_document(chunk_id)
            del self._bm25_indices[workspace_id]

        for chunk_id in chunk_ids:
            chunk = self._chunks.pop(chunk_id, None)
            if chunk:
                doc_id = chunk.get("document_id", "")
                if doc_id in self._by_document:
                    self._by_document[doc_id].discard(chunk_id)
        return len(chunk_ids)

    async def delete_document_chunks(self, document_id: str) -> int:
        """Delete document chunks."""
        chunk_ids = self._by_document.pop(document_id, set())
        for chunk_id in chunk_ids:
            chunk = self._chunks.pop(chunk_id, None)
            if chunk:
                ws_id = chunk.get("workspace_id", "")
                if ws_id in self._by_workspace:
                    self._by_workspace[ws_id].discard(chunk_id)
                # Remove from BM25 index
                if ws_id in self._bm25_indices:
                    self._bm25_indices[ws_id].remove_document(chunk_id)
        return len(chunk_ids)

    def get_statistics(self, workspace_id: str | None = None) -> dict[str, Any]:
        """Get statistics."""
        if workspace_id:
            count = len(self._by_workspace.get(workspace_id, set()))
        else:
            count = len(self._chunks)

        return {
            "total_chunks": count,
            "collection_name": "in_memory",
            "vectorizer": "keyword_match",
            "weaviate_url": "N/A",
        }
