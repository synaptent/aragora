"""
Semantic Index Store for Knowledge Mound.

Provides mandatory semantic grounding for all knowledge items via embeddings.
Supports content hash deduplication and multi-tenant isolation.

Usage:
    from aragora.knowledge.mound.semantic_store import SemanticStore

    store = SemanticStore(db_path="path/to/semantic.db")

    # Index an item with mandatory embedding
    km_id = await store.index_item(
        source_type=KnowledgeSource.FACT,
        source_id="fact_123",
        content="All contracts require 90-day notice periods",
        tenant_id="enterprise_team",
        domain="legal/contracts",
    )

    # Search semantically
    results = await store.search_similar(
        query="contract termination notice",
        tenant_id="enterprise_team",
        limit=10,
    )
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from aragora.knowledge.mound.types import KnowledgeSource
from aragora.knowledge.mound_types import content_dedup_hash
from aragora.memory.embeddings import (
    EmbeddingProvider,
    OpenAIEmbedding,
    GeminiEmbedding,
    OllamaEmbedding,
    cosine_similarity,
    pack_embedding,
    unpack_embedding,
)
from aragora.storage.base_store import SQLiteStore

logger = logging.getLogger(__name__)


@dataclass
class SemanticIndexEntry:
    """A semantically indexed knowledge item."""

    id: str  # km_<uuid> format
    source_type: str
    source_id: str
    content_hash: str
    embedding: list[float]
    embedding_model: str
    tenant_id: str
    domain: str
    importance: float
    created_at: datetime
    updated_at: datetime
    retrieval_count: int = 0
    last_retrieved_at: datetime | None = None
    avg_retrieval_rank: float = 0.0
    metadata: dict = field(default_factory=dict)


@dataclass
class SemanticSearchResult:
    """Result of a semantic search."""

    id: str
    source_type: str
    source_id: str
    content_hash: str
    similarity: float
    domain: str
    importance: float
    tenant_id: str
    metadata: dict = field(default_factory=dict)


class SemanticStore(SQLiteStore):
    """
    Persistent semantic index for Knowledge Mound items.

    Provides mandatory embedding generation and storage for all knowledge,
    enabling semantic similarity search across the entire knowledge base.

    Features:
    - Mandatory embeddings on store (no optional path)
    - Content hash deduplication
    - Multi-tenant isolation via tenant_id
    - Retrieval metrics tracking for meta-learning
    - Domain-based filtering
    """

    SCHEMA_NAME = "semantic_store"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        -- Main semantic index table
        CREATE TABLE IF NOT EXISTS semantic_index (
            id TEXT PRIMARY KEY,                    -- km_<uuid>
            source_type TEXT NOT NULL,              -- continuum|consensus|fact|pattern|document
            source_id TEXT NOT NULL,                -- ID in original store
            content_hash TEXT NOT NULL,             -- SHA256 of content (for dedup)
            embedding BLOB NOT NULL,                -- Packed float32 vector
            embedding_model TEXT NOT NULL,          -- Model used (e.g., text-embedding-3-small)
            embedding_dim INTEGER NOT NULL,         -- Embedding dimension
            tenant_id TEXT NOT NULL DEFAULT 'default', -- Organization isolation
            domain TEXT DEFAULT 'general',          -- Hierarchical domain (e.g., legal/contracts)
            importance REAL DEFAULT 0.5,            -- Inherited from source
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            -- Retrieval metrics for meta-learning
            retrieval_count INTEGER DEFAULT 0,
            last_retrieved_at TEXT,
            avg_retrieval_rank REAL DEFAULT 0.0,
            metadata TEXT DEFAULT '{}'
        );

        -- Indices for efficient queries
        CREATE INDEX IF NOT EXISTS idx_semantic_source
            ON semantic_index(source_type, source_id);
        CREATE INDEX IF NOT EXISTS idx_semantic_tenant
            ON semantic_index(tenant_id);
        CREATE INDEX IF NOT EXISTS idx_semantic_domain
            ON semantic_index(domain);
        CREATE INDEX IF NOT EXISTS idx_semantic_hash
            ON semantic_index(content_hash, tenant_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_semantic_unique_source
            ON semantic_index(source_type, source_id, tenant_id);

        -- Archive table for deleted entries
        CREATE TABLE IF NOT EXISTS semantic_index_archive (
            id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            tenant_id TEXT NOT NULL,
            domain TEXT,
            importance REAL,
            archived_at TEXT NOT NULL,
            archive_reason TEXT
        );
    """

    def __init__(
        self,
        db_path: str | Path,
        embedding_provider: EmbeddingProvider | None = None,
        default_tenant_id: str = "default",
    ):
        """
        Initialize the Semantic Store.

        Args:
            db_path: Path to SQLite database
            embedding_provider: Provider for generating embeddings.
                               Auto-detects if not provided.
            default_tenant_id: Default tenant for operations
        """
        super().__init__(db_path)
        self._provider = embedding_provider or self._auto_detect_provider()
        self._default_tenant_id = default_tenant_id
        self._embedding_model = type(self._provider).__name__

        logger.info(
            "SemanticStore initialized with %s (dim=%s)",
            self._embedding_model,
            self._provider.dimension,
        )

    def _auto_detect_provider(self) -> EmbeddingProvider:
        """Auto-detect best available embedding provider."""
        from aragora.config import get_api_key

        if get_api_key("OPENAI_API_KEY", required=False):
            return OpenAIEmbedding()
        elif get_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY", required=False):
            return GeminiEmbedding()
        else:
            # Try Ollama connectivity check
            try:
                import socket

                ollama = OllamaEmbedding()
                host = ollama.base_url.replace("http://", "").replace("https://", "")
                port = 11434
                if ":" in host:
                    parts = host.rsplit(":", 1)
                    if len(parts) == 2:
                        host = parts[0]
                        try:
                            port = int(parts[1])
                        except ValueError:
                            port = 11434
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(0.5)
                    if sock.connect_ex((host, port)) == 0:
                        return ollama
            except (OSError, ImportError):
                pass  # Ollama not reachable, will use fallback
            # Fall back to hash-based embeddings
            logger.warning(
                "No embedding API available, using hash-based fallback. "
                "Set OPENAI_API_KEY or GEMINI_API_KEY for semantic search."
            )
            return EmbeddingProvider(dimension=256)

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Get the embedding provider."""
        return self._provider

    @property
    def embedding_dimension(self) -> int:
        """Get the embedding dimension."""
        return self._provider.dimension

    # =========================================================================
    # Core Operations
    # =========================================================================

    async def index_item(
        self,
        source_type: KnowledgeSource | str,
        source_id: str,
        content: str,
        tenant_id: str | None = None,
        domain: str = "general",
        importance: float = 0.5,
        metadata: dict | None = None,
    ) -> str:
        """
        Index a knowledge item with mandatory embedding generation.

        If content already exists (by hash), returns existing ID.

        Args:
            source_type: Type of knowledge source
            source_id: ID in the original store
            content: Text content to embed
            tenant_id: Tenant/workspace ID for isolation
            domain: Hierarchical domain (e.g., "legal/contracts")
            importance: Importance score (0-1)
            metadata: Additional metadata

        Returns:
            Knowledge Mound ID (km_<uuid>)
        """
        tenant_id = tenant_id or self._default_tenant_id
        source_type_str = (
            source_type.value if isinstance(source_type, KnowledgeSource) else source_type
        )

        # Check for duplicate content
        content_hash = content_dedup_hash(content, metadata)
        existing_id = await self._find_by_hash(content_hash, tenant_id)
        if existing_id:
            # Update retrieval count as a proxy for importance
            await self._increment_retrieval_count(existing_id)
            logger.debug("Dedup hit: returning existing %s", existing_id)
            return existing_id

        # Generate embedding (mandatory - no fallback to no-embedding)
        embedding = await self._provider.embed(content)

        # Generate unique ID
        km_id = f"km_{uuid.uuid4().hex[:16]}"

        # Store in database
        now = datetime.now().isoformat()
        await asyncio.to_thread(
            self._sync_insert,
            km_id,
            source_type_str,
            source_id,
            content_hash,
            embedding,
            tenant_id,
            domain,
            importance,
            now,
            metadata or {},
        )

        logger.debug("Indexed %s:%s as %s", source_type_str, source_id, km_id)
        return km_id

    def _sync_insert(
        self,
        km_id: str,
        source_type: str,
        source_id: str,
        content_hash: str,
        embedding: list[float],
        tenant_id: str,
        domain: str,
        importance: float,
        timestamp: str,
        metadata: dict,
    ) -> None:
        """Synchronous database insert."""
        import json

        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO semantic_index (
                    id, source_type, source_id, content_hash, embedding,
                    embedding_model, embedding_dim, tenant_id, domain,
                    importance, created_at, updated_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    km_id,
                    source_type,
                    source_id,
                    content_hash,
                    pack_embedding(embedding),
                    self._embedding_model,
                    len(embedding),
                    tenant_id,
                    domain,
                    importance,
                    timestamp,
                    timestamp,
                    json.dumps(metadata),
                ),
            )

    async def _find_by_hash(self, content_hash: str, tenant_id: str) -> str | None:
        """Find existing entry by content hash."""
        return await asyncio.to_thread(self._sync_find_by_hash, content_hash, tenant_id)

    def _sync_find_by_hash(self, content_hash: str, tenant_id: str) -> str | None:
        """Synchronous hash lookup."""
        row = self.fetch_one(
            "SELECT id FROM semantic_index WHERE content_hash = ? AND tenant_id = ?",
            (content_hash, tenant_id),
        )
        return row[0] if row else None

    async def get_entry(self, km_id: str) -> SemanticIndexEntry | None:
        """Get a semantic index entry by ID."""
        return await asyncio.to_thread(self._sync_get_entry, km_id)

    def _sync_get_entry(self, km_id: str) -> SemanticIndexEntry | None:
        """Synchronous entry lookup."""
        import json

        row = self.fetch_one(
            """
            SELECT id, source_type, source_id, content_hash, embedding,
                   embedding_model, tenant_id, domain, importance,
                   created_at, updated_at, retrieval_count,
                   last_retrieved_at, avg_retrieval_rank, metadata
            FROM semantic_index WHERE id = ?
            """,
            (km_id,),
        )
        if not row:
            return None

        return SemanticIndexEntry(
            id=row[0],
            source_type=row[1],
            source_id=row[2],
            content_hash=row[3],
            embedding=unpack_embedding(row[4]),
            embedding_model=row[5],
            tenant_id=row[6],
            domain=row[7],
            importance=row[8],
            created_at=datetime.fromisoformat(row[9]),
            updated_at=datetime.fromisoformat(row[10]),
            retrieval_count=row[11] or 0,
            last_retrieved_at=(datetime.fromisoformat(row[12]) if row[12] else None),
            avg_retrieval_rank=row[13] or 0.0,
            metadata=json.loads(row[14]) if row[14] else {},
        )

    async def update_source_id(self, km_id: str, source_id: str) -> bool:
        """Update the source_id for an entry (used after underlying store assigns ID)."""
        return await asyncio.to_thread(self._sync_update_source_id, km_id, source_id)

    def _sync_update_source_id(self, km_id: str, source_id: str) -> bool:
        """Synchronous source_id update."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE semantic_index
                SET source_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (source_id, datetime.now().isoformat(), km_id),
            )
            return cursor.rowcount > 0

    async def delete_entry(self, km_id: str, archive: bool = True, reason: str = "manual") -> bool:
        """Delete a semantic index entry."""
        return await asyncio.to_thread(self._sync_delete_entry, km_id, archive, reason)

    def _sync_delete_entry(self, km_id: str, archive: bool, reason: str) -> bool:
        """Synchronous delete with optional archiving."""
        with self.connection() as conn:
            if archive:
                # Archive first
                conn.execute(
                    """
                    INSERT INTO semantic_index_archive
                    (id, source_type, source_id, content_hash, tenant_id,
                     domain, importance, archived_at, archive_reason)
                    SELECT id, source_type, source_id, content_hash, tenant_id,
                           domain, importance, ?, ?
                    FROM semantic_index WHERE id = ?
                    """,
                    (datetime.now().isoformat(), reason, km_id),
                )
            cursor = conn.execute("DELETE FROM semantic_index WHERE id = ?", (km_id,))
            return cursor.rowcount > 0

    # =========================================================================
    # Semantic Search
    # =========================================================================

    async def search_similar(
        self,
        query: str,
        tenant_id: str | None = None,
        limit: int = 10,
        domain_filter: str | None = None,
        min_similarity: float = 0.3,
        source_types: list[str] | None = None,
    ) -> list[SemanticSearchResult]:
        """
        Search for semantically similar items.

        Args:
            query: Natural language query
            tenant_id: Filter by tenant (required for isolation)
            limit: Maximum results
            domain_filter: Filter by domain prefix (e.g., "legal" matches "legal/contracts")
            min_similarity: Minimum cosine similarity threshold
            source_types: Filter by source types

        Returns:
            List of search results sorted by similarity (descending)
        """
        tenant_id = tenant_id or self._default_tenant_id

        # Generate query embedding
        query_embedding = await self._provider.embed(query)

        # Fetch candidates and compute similarities
        results = await asyncio.to_thread(
            self._sync_search_similar,
            query_embedding,
            tenant_id,
            limit * 3,  # Oversample for filtering
            domain_filter,
            source_types,
        )

        # Filter by similarity and limit
        filtered = [r for r in results if r.similarity >= min_similarity]
        filtered.sort(key=lambda x: x.similarity, reverse=True)
        return filtered[:limit]

    def _sync_search_similar(
        self,
        query_embedding: list[float],
        tenant_id: str,
        candidate_limit: int,
        domain_filter: str | None,
        source_types: list[str] | None,
    ) -> list[SemanticSearchResult]:
        """Synchronous similarity search with candidate filtering."""
        import json

        # Build query with filters
        sql = """
            SELECT id, source_type, source_id, content_hash, embedding,
                   domain, importance, tenant_id, metadata
            FROM semantic_index
            WHERE tenant_id = ?
              AND embedding_dim = ?
        """
        params: list = [tenant_id, len(query_embedding)]

        if domain_filter:
            sql += " AND (domain = ? OR domain LIKE ?)"
            params.extend([domain_filter, f"{domain_filter}/%"])

        if source_types:
            placeholders = ",".join("?" * len(source_types))
            sql += f" AND source_type IN ({placeholders})"
            params.extend(source_types)

        # Order by importance for initial ranking, then rerank by similarity
        sql += " ORDER BY importance DESC LIMIT ?"
        params.append(candidate_limit)

        rows = self.fetch_all(sql, tuple(params))

        results = []
        for row in rows:
            stored_embedding = unpack_embedding(row[4])
            similarity = cosine_similarity(query_embedding, stored_embedding)

            results.append(
                SemanticSearchResult(
                    id=row[0],
                    source_type=row[1],
                    source_id=row[2],
                    content_hash=row[3],
                    similarity=similarity,
                    domain=row[5],
                    importance=row[6],
                    tenant_id=row[7],
                    metadata=json.loads(row[8]) if row[8] else {},
                )
            )

        return results

    # =========================================================================
    # Retrieval Metrics (for Meta-Learning)
    # =========================================================================

    async def record_retrieval(
        self,
        km_id: str,
        rank_position: int,
        was_useful: bool | None = None,
    ) -> None:
        """
        Record a retrieval event for meta-learning optimization.

        Args:
            km_id: Knowledge Mound ID that was retrieved
            rank_position: Position in search results (0 = top)
            was_useful: Optional feedback on whether retrieval was useful
        """
        await asyncio.to_thread(self._sync_record_retrieval, km_id, rank_position)

    def _sync_record_retrieval(self, km_id: str, rank_position: int) -> None:
        """Synchronous retrieval recording."""
        with self.connection() as conn:
            # Get current stats
            row = self.fetch_one(
                "SELECT retrieval_count, avg_retrieval_rank FROM semantic_index WHERE id = ?",
                (km_id,),
            )
            if not row:
                return

            count, avg_rank = row
            count = count or 0
            avg_rank = avg_rank or 0.0

            # Update running average of rank position
            new_count = count + 1
            new_avg_rank = ((avg_rank * count) + rank_position) / new_count

            conn.execute(
                """
                UPDATE semantic_index
                SET retrieval_count = ?,
                    last_retrieved_at = ?,
                    avg_retrieval_rank = ?
                WHERE id = ?
                """,
                (new_count, datetime.now().isoformat(), new_avg_rank, km_id),
            )

    async def _increment_retrieval_count(self, km_id: str) -> None:
        """Increment retrieval count (for dedup hits)."""
        await asyncio.to_thread(self._sync_increment_count, km_id)

    def _sync_increment_count(self, km_id: str) -> None:
        """Synchronous count increment."""
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE semantic_index
                SET retrieval_count = retrieval_count + 1,
                    last_retrieved_at = ?
                WHERE id = ?
                """,
                (datetime.now().isoformat(), km_id),
            )

    async def get_retrieval_patterns(
        self,
        tenant_id: str | None = None,
        min_retrievals: int = 5,
    ) -> dict:
        """
        Get retrieval patterns for meta-learning analysis.

        Returns statistics on what's being retrieved frequently/rarely.
        """
        return await asyncio.to_thread(
            self._sync_get_retrieval_patterns,
            tenant_id or self._default_tenant_id,
            min_retrievals,
        )

    def _sync_get_retrieval_patterns(self, tenant_id: str, min_retrievals: int) -> dict:
        """Synchronous pattern analysis."""
        # High retrieval items
        high_rows = self.fetch_all(
            """
            SELECT domain, COUNT(*) as count, AVG(avg_retrieval_rank) as avg_rank
            FROM semantic_index
            WHERE tenant_id = ? AND retrieval_count >= ?
            GROUP BY domain
            ORDER BY count DESC
            """,
            (tenant_id, min_retrievals),
        )

        # Low retrieval items (potentially stale)
        low_rows = self.fetch_all(
            """
            SELECT domain, COUNT(*) as count
            FROM semantic_index
            WHERE tenant_id = ? AND retrieval_count < ?
            GROUP BY domain
            ORDER BY count DESC
            """,
            (tenant_id, min_retrievals),
        )

        return {
            "high_retrieval_domains": [
                {"domain": r[0], "count": r[1], "avg_rank": r[2]} for r in high_rows
            ],
            "low_retrieval_domains": [{"domain": r[0], "count": r[1]} for r in low_rows],
        }

    # =========================================================================
    # Bulk Operations
    # =========================================================================

    async def index_batch(
        self,
        items: list[tuple[str, str, str]],  # (source_type, source_id, content)
        tenant_id: str | None = None,
        domain: str = "general",
    ) -> list[str]:
        """
        Index multiple items in batch (more efficient for bulk imports).

        Args:
            items: List of (source_type, source_id, content) tuples
            tenant_id: Tenant ID for all items
            domain: Default domain for all items

        Returns:
            List of Knowledge Mound IDs
        """
        tenant_id = tenant_id or self._default_tenant_id

        # Extract just the content for batch embedding
        contents = [item[2] for item in items]

        # Batch embed
        embeddings = await self._provider.embed_batch(contents)

        # Store each item
        km_ids = []
        now = datetime.now().isoformat()

        for (source_type, source_id, content), embedding in zip(items, embeddings):
            content_hash = hashlib.sha256(content.encode()).hexdigest()

            # Check for duplicate
            existing_id = self._sync_find_by_hash(content_hash, tenant_id)
            if existing_id:
                km_ids.append(existing_id)
                continue

            km_id = f"km_{uuid.uuid4().hex[:16]}"
            self._sync_insert(
                km_id,
                source_type,
                source_id,
                content_hash,
                embedding,
                tenant_id,
                domain,
                0.5,
                now,
                {},
            )
            km_ids.append(km_id)

        logger.info("Batch indexed %s items", len(km_ids))
        return km_ids

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self, tenant_id: str | None = None) -> dict:
        """Get statistics about the semantic index."""
        return await asyncio.to_thread(self._sync_get_stats, tenant_id or self._default_tenant_id)

    def _sync_get_stats(self, tenant_id: str) -> dict:
        """Synchronous stats retrieval."""
        total = self.fetch_one(
            "SELECT COUNT(*) FROM semantic_index WHERE tenant_id = ?",
            (tenant_id,),
        )

        by_source = self.fetch_all(
            """
            SELECT source_type, COUNT(*) FROM semantic_index
            WHERE tenant_id = ?
            GROUP BY source_type
            """,
            (tenant_id,),
        )

        by_domain = self.fetch_all(
            """
            SELECT domain, COUNT(*) FROM semantic_index
            WHERE tenant_id = ?
            GROUP BY domain
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """,
            (tenant_id,),
        )

        avg_importance = self.fetch_one(
            "SELECT AVG(importance) FROM semantic_index WHERE tenant_id = ?",
            (tenant_id,),
        )

        return {
            "total_entries": total[0] if total else 0,
            "by_source_type": dict(by_source),
            "top_domains": dict(by_domain),
            "average_importance": avg_importance[0] if avg_importance else 0.0,
            "embedding_model": self._embedding_model,
            "embedding_dimension": self._provider.dimension,
            "tenant_id": tenant_id,
        }

    def has_source(self, source_type: str, source_id: str, tenant_id: str | None = None) -> bool:
        """Check if a source is already indexed."""
        tenant_id = tenant_id or self._default_tenant_id
        row = self.fetch_one(
            "SELECT 1 FROM semantic_index WHERE source_type = ? AND source_id = ? AND tenant_id = ?",
            (source_type, source_id, tenant_id),
        )
        return row is not None


__all__ = [
    "SemanticStore",
    "SemanticIndexEntry",
    "SemanticSearchResult",
]
