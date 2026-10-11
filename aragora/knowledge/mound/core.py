"""
Knowledge Mound Core - Base class with initialization and storage adapters.

Provides the foundation for KnowledgeMound:
- Constructor and initialization
- Storage backend initialization (SQLite, PostgreSQL, Redis, Weaviate)
- Private storage adapter methods
- Query helper methods for connected stores
- Lifecycle management (close, session)
- Statistics methods
- Converter wrappers
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import inspect
from typing import TYPE_CHECKING, Any
from collections.abc import AsyncIterator

from aragora.config import DB_KNOWLEDGE_PATH
from aragora.knowledge.mound.types import (
    KnowledgeItem,
    KnowledgeLink,
    MoundBackend,
    MoundConfig,
    MoundStats,
    QueryFilters,
    RelationshipType,
)
from aragora.knowledge.mound.converters import (
    node_to_item,
    relationship_to_link,
    continuum_to_item,
    consensus_to_item,
    fact_to_item,
    vector_result_to_item,
    evidence_to_item,
    critique_to_item,
)

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.consensus import ConsensusMemory
    from aragora.knowledge.fact_store import FactStore
    from aragora.evidence.store import EvidenceStore
    from aragora.memory.store import CritiqueStore
    from aragora.protocols import LegacyEventEmitterProtocol

logger = logging.getLogger(__name__)


def _to_iso_string(value: Any) -> str | None:
    """Safely convert datetime or string to ISO format string.

    Handles both datetime objects and ISO format strings to ensure
    consistent serialization regardless of how the value was stored.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value  # Already an ISO string
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_enum_value(value: Any) -> Any:
    """Safely extract value from enum or return string as-is.

    Handles both enum instances and raw string values to ensure
    consistent serialization regardless of how the value was stored.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value  # Already a string value
    if hasattr(value, "value"):
        return value.value
    return str(value)


class KnowledgeMoundCore:
    """
    Core foundation for the Knowledge Mound facade.

    Provides initialization, storage adapters, and utility methods
    that are used by the operation mixins.
    """

    def __init__(
        self,
        config: MoundConfig | None = None,
        workspace_id: str | None = None,
        event_emitter: LegacyEventEmitterProtocol | None = None,
    ) -> None:
        """
        Initialize the Knowledge Mound core.

        Args:
            config: Mound configuration. Defaults to SQLite backend.
            workspace_id: Default workspace for queries. Overrides config.
            event_emitter: Optional event emitter for cross-subsystem events.
        """
        self.config = config or MoundConfig()
        self.workspace_id = workspace_id or self.config.default_workspace_id
        self.event_emitter = event_emitter

        # Storage backends (initialized lazily)
        self._meta_store: Any | None = None  # SQLite or Postgres
        self._store: Any | None = None  # Alias for mixin compatibility
        self._cache: Any | None = None  # Redis cache
        self._vector_store: Any | None = None  # Weaviate
        self._semantic_store: Any | None = None  # Local semantic index

        # Connected memory systems
        self._continuum: ContinuumMemory | None = None
        self._consensus: ConsensusMemory | None = None
        self._facts: FactStore | None = None
        self._evidence: EvidenceStore | None = None
        self._critique: CritiqueStore | None = None

        # Staleness detector and culture accumulator
        self._staleness_detector: Any | None = None
        self._culture_accumulator: Any | None = None
        self._org_culture_manager: Any | None = None

        # State
        self._initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the mound is initialized."""
        return self._initialized

    # =========================================================================
    # Initialization
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize storage backends and connections."""
        if self._initialized:
            return

        logger.info("Initializing Knowledge Mound (backend=%s)", self.config.backend.value)

        # Initialize primary storage based on backend
        if self.config.backend == MoundBackend.SQLITE:
            await self._init_sqlite()
        elif self.config.backend == MoundBackend.POSTGRES:
            await self._init_postgres()
        elif self.config.backend == MoundBackend.HYBRID:
            await self._init_postgres()
            await self._init_redis()

        # Initialize Redis cache if configured
        if self.config.redis_url and self.config.backend != MoundBackend.HYBRID:
            await self._init_redis()

        # Initialize vector store if configured
        if self.config.weaviate_url:
            await self._init_weaviate()

        # Initialize staleness detector
        if self.config.enable_staleness_detection:
            from aragora.knowledge.mound.staleness import StalenessDetector

            # StalenessDetector expects the full KnowledgeMound (with mixins), which self
            # becomes via composition. Cast to Any to satisfy the type checker.
            mound_ref: Any = self
            self._staleness_detector = StalenessDetector(
                mound=mound_ref,
                age_threshold=self.config.staleness_age_threshold,
            )

        # Initialize culture accumulator
        if self.config.enable_culture_accumulator:
            from aragora.knowledge.mound.culture import CultureAccumulator

            mound_ref = self
            self._culture_accumulator = CultureAccumulator(mound=mound_ref)

        # Initialize semantic store for local embeddings
        await self._init_semantic_store()

        self._initialized = True
        logger.info("Knowledge Mound initialized successfully")

    async def _init_sqlite(self) -> None:
        """Initialize SQLite backend."""
        from aragora.knowledge.mound import KnowledgeMoundMetaStore

        db_path = self.config.sqlite_path or str(Path(DB_KNOWLEDGE_PATH) / "mound.db")
        self._meta_store = KnowledgeMoundMetaStore(db_path)
        logger.debug("SQLite backend initialized at %s", db_path)

    async def _init_postgres(self) -> None:
        """Initialize PostgreSQL backend with optional resilience hardening."""
        if not self.config.postgres_url:
            logger.warning("PostgreSQL URL not configured, falling back to SQLite")
            await self._init_sqlite()
            return

        try:
            from aragora.knowledge.mound.postgres_store import PostgresStore

            base_store = PostgresStore(
                url=self.config.postgres_url,
                pool_size=self.config.postgres_pool_size,
                max_overflow=self.config.postgres_pool_max_overflow,
            )

            # Wrap with resilience features if enabled
            if self.config.enable_resilience:
                from aragora.knowledge.mound.resilience import (
                    ResilientPostgresStore,
                    RetryConfig,
                    TransactionConfig,
                )

                retry_config = RetryConfig(
                    max_retries=self.config.retry_max_attempts,
                    base_delay=self.config.retry_base_delay,
                )
                tx_config = TransactionConfig(
                    timeout_seconds=self.config.transaction_timeout,
                )

                self._meta_store = ResilientPostgresStore(
                    store=base_store,
                    retry_config=retry_config,
                    transaction_config=tx_config,
                )

                # Initialize with integrity checks
                integrity_result = await self._meta_store.initialize()
                if self.config.enable_integrity_checks and not integrity_result.passed:
                    logger.warning(
                        "Integrity check found issues: %s", integrity_result.issues_found
                    )
                logger.debug(
                    "PostgreSQL backend initialized with resilience (integrity: %s checks, %s)",
                    integrity_result.checks_performed,
                    "passed" if integrity_result.passed else "issues found",
                )
            else:
                self._meta_store = base_store
                await self._meta_store.initialize()
                logger.debug("PostgreSQL backend initialized (resilience disabled)")

        except ImportError as e:
            logger.warning("asyncpg not available (%s), falling back to SQLite", e)
            await self._init_sqlite()
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("PostgreSQL init failed: %s, falling back to SQLite", e)
            await self._init_sqlite()
        except (RuntimeError, ValueError) as e:
            logger.exception("Unexpected PostgreSQL init error: %s, falling back to SQLite", e)
            await self._init_sqlite()

    async def _init_redis(self) -> None:
        """Initialize Redis cache with optional invalidation bus subscription."""
        if not self.config.redis_url:
            return

        try:
            from aragora.knowledge.mound.redis_cache import RedisCache

            self._cache = RedisCache(
                url=self.config.redis_url,
                default_ttl=self.config.redis_cache_ttl,
                culture_ttl=self.config.redis_culture_ttl,
            )
            await self._cache.connect()

            # Subscribe to invalidation bus for event-driven cache updates
            if self.config.enable_cache_invalidation_events:
                await self._cache.subscribe_to_invalidation_bus()
                logger.debug("Redis cache initialized with invalidation bus subscription")
            else:
                logger.debug("Redis cache initialized")

        except ImportError:
            logger.warning("redis not available, caching disabled")
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis init failed: %s, caching disabled", e)

    async def _init_weaviate(self) -> None:
        """Initialize Weaviate vector store.

        Prefers KnowledgeVectorStore (KnowledgeNode-aware) over raw WeaviateStore.
        """
        weaviate_url = self.config.weaviate_url
        if not weaviate_url:
            logger.debug("Weaviate URL not configured; skipping vector store init")
            return

        # Try KnowledgeVectorStore first (higher-level, KnowledgeNode-aware)
        try:
            from aragora.knowledge.vector_store import KnowledgeVectorStore, KnowledgeVectorConfig

            _vec_config = KnowledgeVectorConfig(
                url=weaviate_url,
                api_key=self.config.weaviate_api_key,
            )
            self._vector_store = KnowledgeVectorStore(  # type: ignore[call-arg]
                workspace_id=self.workspace_id,
                config=_vec_config,
            )
            await self._vector_store.connect()
            logger.debug("KnowledgeVectorStore initialized (KnowledgeNode-aware)")
            return
        except (ImportError, Exception) as e:
            logger.debug("KnowledgeVectorStore unavailable, falling back to WeaviateStore: %s", e)

        # Fallback to raw WeaviateStore
        try:
            from aragora.documents.indexing.weaviate_store import WeaviateStore, WeaviateConfig

            config = WeaviateConfig(
                url=weaviate_url,
                api_key=self.config.weaviate_api_key,
                collection_name=self.config.weaviate_collection,
            )
            self._vector_store = WeaviateStore(config)
            await self._vector_store.connect()
            logger.debug("Weaviate vector store initialized")
        except ImportError:
            logger.warning("Weaviate not available")
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.warning("Weaviate init failed: %s", e)

    async def _init_semantic_store(self) -> None:
        """Initialize local semantic store for embeddings."""
        try:
            from aragora.knowledge.mound.semantic_store import SemanticStore

            db_path = (
                str(self.config.sqlite_path)
                if self.config.sqlite_path
                else str(Path(DB_KNOWLEDGE_PATH) / "mound.db")
            )
            # Use a separate database for semantic index
            semantic_db_path = db_path.replace(".db", "_semantic.db")
            self._semantic_store = SemanticStore(
                db_path=semantic_db_path,
                default_tenant_id=self.workspace_id,
            )
            logger.debug("Semantic store initialized at %s", semantic_db_path)
        except ImportError:
            logger.warning("Semantic store dependencies not available")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Semantic store init failed: %s", e)

    def _ensure_initialized(self) -> None:
        """Ensure the mound is initialized."""
        if not self._initialized:
            raise RuntimeError("KnowledgeMound not initialized. Call initialize() first.")

    def _require_meta_store(self) -> Any:
        """Return the meta store, raising if it is not connected.

        Internal narrowing helper: after :meth:`initialize` runs, the meta store
        is non-None for the rest of the instance's lifetime. Routing every
        meta-store access through this helper gives mypy a non-optional type
        without losing the runtime assertion that tells callers they forgot
        to call :meth:`initialize`.
        """
        if self._meta_store is None:
            raise RuntimeError("KnowledgeMound meta store not connected. Call initialize() first.")
        return self._meta_store

    # =========================================================================
    # Lifecycle
    # =========================================================================

    async def close(self) -> None:
        """Close all connections."""
        if self._cache is not None:
            await self._cache.close()
        if self._vector_store is not None:
            try:
                await self._vector_store.close()
            except (RuntimeError, ConnectionError, OSError) as e:
                logger.debug("Error closing vector store: %s", e)
        store = self._meta_store
        if store is not None and hasattr(store, "close"):
            close_result = store.close()
            if inspect.isawaitable(close_result):
                await close_result

        self._initialized = False
        logger.info("Knowledge Mound closed")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[KnowledgeMoundCore]:
        """Context manager for managed lifecycle."""
        await self.initialize()
        try:
            yield self
        finally:
            await self.close()

    # =========================================================================
    # Statistics
    # =========================================================================

    async def get_stats(self, workspace_id: str | None = None) -> MoundStats:
        """Get statistics about the Knowledge Mound."""
        self._ensure_initialized()

        ws_id = workspace_id or self.workspace_id
        return await self._get_stats(ws_id)

    async def _get_stats(self, workspace_id: str) -> MoundStats:
        """Get statistics from storage."""
        store = self._require_meta_store()
        if hasattr(store, "get_stats_async"):
            return await store.get_stats_async(workspace_id)
        else:
            stats = store.get_stats(workspace_id)
            return MoundStats(
                total_nodes=stats.get("total_nodes", 0),
                nodes_by_type=stats.get("by_type", {}),
                nodes_by_tier=stats.get("by_tier", {}),
                nodes_by_validation=stats.get("by_validation_status", {}),
                total_relationships=stats.get("total_relationships", 0),
                relationships_by_type={},
                average_confidence=stats.get("average_confidence", 0.0),
                stale_nodes_count=0,
                workspace_id=workspace_id,
            )

    # =========================================================================
    # Private Storage Adapter Methods
    # =========================================================================

    async def _save_node(self, node_data: dict[str, Any]) -> None:
        """Save node to storage."""
        store = self._require_meta_store()
        if hasattr(store, "save_node_async"):
            await store.save_node_async(node_data)
        else:
            # SQLite sync fallback
            from aragora.knowledge.mound import KnowledgeNode, ProvenanceChain, ProvenanceType

            # Map KnowledgeSource values to valid ProvenanceType values
            source_to_provenance = {
                "document": ProvenanceType.DOCUMENT,
                "debate": ProvenanceType.DEBATE,
                "consensus": ProvenanceType.DEBATE,  # Consensus comes from debates
                "user": ProvenanceType.USER,
                "fact": ProvenanceType.AGENT,  # Facts are agent-derived
                "continuum": ProvenanceType.INFERENCE,  # Memory-derived
                "vector": ProvenanceType.DOCUMENT,  # Vector embeddings from documents
                "external": ProvenanceType.MIGRATION,  # External sources
                "extraction": ProvenanceType.AGENT,  # Agent extraction
            }

            node = KnowledgeNode(
                id=node_data["id"],
                node_type=node_data["node_type"],
                content=node_data["content"],
                confidence=node_data["confidence"],
                workspace_id=node_data["workspace_id"],
                metadata=node_data.get("metadata", {}),
                topics=node_data.get("topics", []),
            )
            if node_data.get("source_type"):
                source_type_str = node_data["source_type"]
                provenance_type = source_to_provenance.get(source_type_str, ProvenanceType.DOCUMENT)
                node.provenance = ProvenanceChain(
                    source_type=provenance_type,
                    source_id=node_data.get("debate_id") or node_data.get("document_id") or "",
                    debate_id=node_data.get("debate_id"),
                    document_id=node_data.get("document_id"),
                    agent_id=node_data.get("agent_id"),
                    user_id=node_data.get("user_id"),
                )
            store.save_node(node)

    async def _get_node(self, node_id: str) -> KnowledgeItem | None:
        """Get node from storage."""
        store = self._require_meta_store()
        if hasattr(store, "get_node_async"):
            return await store.get_node_async(node_id)
        else:
            node = store.get_node(node_id)
            if node:
                return self._node_to_item(node)
            return None

    async def _update_node(self, node_id: str, updates: dict[str, Any]) -> None:
        """Update node in storage."""
        # For SQLite, get then save
        store = self._require_meta_store()
        if hasattr(store, "update_node_async"):
            await store.update_node_async(node_id, updates)
        else:
            node = store.get_node(node_id)
            if node:
                for key, value in updates.items():
                    if hasattr(node, key):
                        setattr(node, key, value)
                store.save_node(node)

    async def _delete_node(self, node_id: str) -> bool:
        """Delete node from storage."""
        store = self._require_meta_store()
        if hasattr(store, "delete_node_async"):
            return bool(await store.delete_node_async(node_id))
        else:
            # SQLite doesn't have delete, use raw SQL
            with store.connection() as conn:
                cursor = conn.execute("DELETE FROM knowledge_nodes WHERE id = ?", (node_id,))
                return bool(cursor.rowcount > 0)

    async def _archive_node(self, node_id: str) -> None:
        """
        Archive node before deletion.

        Saves the node to an archive table/collection for audit trail
        and potential recovery. The archive includes full node data
        plus deletion metadata.
        """
        # Import get method from mixin - will be available via composition
        # Use getattr to access method that comes from mixin
        get_method = getattr(self, "get", None)
        if get_method is None:
            logger.debug("Node %s cannot be archived - get method not available", node_id)
            return
        node = await get_method(node_id)
        if not node:
            logger.debug("Node %s not found, skipping archive", node_id)
            return

        archive_record = {
            "id": f"arch_{node_id}_{uuid.uuid4().hex[:8]}",
            "original_id": node_id,
            "content": node.content,
            "source": node.source.value if hasattr(node.source, "value") else str(node.source),
            "source_id": node.source_id,
            "confidence": (
                node.confidence.value if hasattr(node.confidence, "value") else str(node.confidence)
            ),
            "importance": node.importance,
            "metadata": node.metadata,
            "created_at": _to_iso_string(node.created_at),
            "updated_at": _to_iso_string(node.updated_at),
            "archived_at": datetime.now().isoformat(),
            "workspace_id": self.workspace_id,
        }

        # Save to archive store
        store = self._require_meta_store()
        if hasattr(store, "archive_node_async"):
            await store.archive_node_async(archive_record)
        elif hasattr(store, "archive_node"):
            store.archive_node(archive_record)
        else:
            # Fallback: store in SQLite archive table
            try:
                with store.connection() as conn:
                    # Create archive table if it doesn't exist
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS knowledge_archive (
                            id TEXT PRIMARY KEY,
                            original_id TEXT NOT NULL,
                            content TEXT NOT NULL,
                            source TEXT,
                            source_id TEXT,
                            confidence TEXT,
                            importance REAL,
                            metadata TEXT,
                            created_at TEXT,
                            updated_at TEXT,
                            archived_at TEXT NOT NULL,
                            workspace_id TEXT
                        )
                    """)
                    conn.execute(
                        """
                        INSERT INTO knowledge_archive
                        (id, original_id, content, source, source_id, confidence,
                         importance, metadata, created_at, updated_at, archived_at, workspace_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            archive_record["id"],
                            archive_record["original_id"],
                            archive_record["content"],
                            archive_record["source"],
                            archive_record["source_id"],
                            archive_record["confidence"],
                            archive_record["importance"],
                            (
                                json.dumps(archive_record["metadata"])
                                if archive_record["metadata"]
                                else "{}"
                            ),
                            archive_record["created_at"],
                            archive_record["updated_at"],
                            archive_record["archived_at"],
                            archive_record["workspace_id"],
                        ),
                    )
                    conn.commit()
                logger.debug("Archived node %s to knowledge_archive table", node_id)
            except (RuntimeError, OSError, sqlite3.Error) as e:
                logger.warning("Failed to archive node %s: %s", node_id, e)
                # Don't block deletion on archive failure
            except (ValueError, KeyError, AttributeError) as e:
                logger.exception("Unexpected archive error for node %s: %s", node_id, e)
                # Don't block deletion on archive failure

    async def _save_relationship(self, from_id: str, to_id: str, rel_type: str) -> None:
        """Save relationship to storage."""
        store = self._require_meta_store()
        if hasattr(store, "save_relationship_async"):
            await store.save_relationship_async(from_id, to_id, rel_type)
        else:
            from typing import cast
            from aragora.knowledge.mound import KnowledgeRelationship
            from aragora.knowledge.mound_core import RelationshipType as LegacyRelationshipType

            # rel_type may be str or RelationshipType enum; KnowledgeRelationship
            # expects a Literal string type (LegacyRelationshipType)
            # Extract the string value for the constructor
            rel_type_str = rel_type.value if hasattr(rel_type, "value") else rel_type

            # KnowledgeRelationship expects LegacyRelationshipType (Literal string)
            # Cast to the expected literal type for type safety
            rel = KnowledgeRelationship(
                from_node_id=from_id,
                to_node_id=to_id,
                relationship_type=cast(LegacyRelationshipType, rel_type_str),
            )
            store.save_relationship(rel)

    async def _get_relationships(
        self, node_id: str, types: list[RelationshipType] | None = None
    ) -> list[KnowledgeLink]:
        """Get relationships for a node."""
        store = self._require_meta_store()
        if hasattr(store, "get_relationships_async"):
            return list(await store.get_relationships_async(node_id, types))
        else:
            rels = store.get_relationships(node_id)
            return [self._rel_to_link(r) for r in rels]

    async def _get_relationships_batch(
        self, node_ids: list[str], types: list[RelationshipType] | None = None
    ) -> dict[str, list[KnowledgeLink]]:
        """Get relationships for multiple nodes in a single batch operation.

        This method reduces N+1 query patterns by fetching relationships
        for all requested nodes in a single database query when supported,
        or falls back to parallel fetching via asyncio.gather.

        Args:
            node_ids: List of node IDs to fetch relationships for
            types: Optional filter for specific relationship types

        Returns:
            Dictionary mapping node_id to list of relationships for that node
        """
        import asyncio

        if not node_ids:
            return {}

        # Try batch method on meta_store first (most efficient - single query)
        store = self._require_meta_store()
        if hasattr(store, "get_relationships_batch_async"):
            result_dict: dict[str, list[KnowledgeLink]] = await store.get_relationships_batch_async(
                node_ids, types
            )
            return result_dict

        # Fall back to parallel fetching via asyncio.gather
        # This is still better than sequential N queries
        results = await asyncio.gather(
            *[self._get_relationships(node_id, types) for node_id in node_ids],
            return_exceptions=True,
        )

        # Build result dictionary, handling any errors gracefully
        batch_result: dict[str, list[KnowledgeLink]] = {}
        for node_id, result in zip(node_ids, results):
            if isinstance(result, BaseException):
                # Log error but don't fail the whole batch
                batch_result[node_id] = []
            else:
                batch_result[node_id] = result

        return batch_result

    async def _find_by_content_hash(self, content_hash: str, workspace_id: str) -> str | None:
        """Find node by content hash."""
        store = self._require_meta_store()
        if hasattr(store, "find_by_content_hash_async"):
            hit: str | None = await store.find_by_content_hash_async(content_hash, workspace_id)
            return hit
        else:
            node = store.find_by_content_hash(content_hash, workspace_id)
            return node.id if node else None

    async def _increment_update_count(self, node_id: str) -> None:
        """Increment update count for a node."""
        await self._update_node(node_id, {"update_count": "update_count + 1"})

    # =========================================================================
    # Ops Mixin Adapter Methods (for dedup/pruning operations)
    # =========================================================================

    async def _get_nodes_for_workspace(self, workspace_id: str, limit: int = 1000) -> list[Any]:
        """Get all nodes for a workspace (used by dedup/pruning)."""
        store = self._require_meta_store()
        if hasattr(store, "get_nodes_for_workspace_async"):
            return list(await store.get_nodes_for_workspace_async(workspace_id, limit))
        elif hasattr(store, "query_nodes"):
            nodes = store.query_nodes(workspace_id=workspace_id, limit=limit)
            return [self._node_to_item(n) for n in nodes]
        return []

    async def _search_similar(
        self,
        workspace_id: str,
        embedding: list[float] | None = None,
        query: str | None = None,
        top_k: int = 20,
        min_score: float = 0.8,
    ) -> list[Any]:
        """Search for similar nodes by embedding or content (used by dedup)."""
        store = self._require_meta_store()
        if hasattr(store, "search_similar_async"):
            return list(
                await store.search_similar_async(workspace_id, embedding, query, top_k, min_score)
            )
        elif self._semantic_store and query:
            # Use semantic store for similarity search
            try:
                results = await self._semantic_store.search(query, limit=top_k)
                return [r for r in results if getattr(r, "score", 1.0) >= min_score]
            except (AttributeError, TypeError) as e:
                logger.warning("search similar encountered an error: %s", e)
        # Fallback: simple content-based similarity using query_local
        if query:
            items = await self._query_local(query, None, top_k, workspace_id)
            # Add mock score attribute using setattr for dynamic attribute
            for item in items:
                setattr(item, "score", 0.9)
            return items
        return []

    async def _count_nodes(self, workspace_id: str) -> int:
        """Count nodes in workspace (used by dedup report)."""
        store = self._require_meta_store()
        if hasattr(store, "count_nodes_async"):
            return int(await store.count_nodes_async(workspace_id))
        elif hasattr(store, "get_stats"):
            stats = store.get_stats(workspace_id)
            return int(stats.get("total_nodes", 0))
        elif hasattr(store, "query_nodes"):
            nodes = store.query_nodes(workspace_id=workspace_id, limit=100000)
            return len(nodes)
        return 0

    async def _get_node_relationships_for_ops(self, node_id: str, workspace_id: str) -> list[Any]:
        """Get relationships for node (used by dedup merge)."""
        return await self._get_relationships(node_id)

    async def _create_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        workspace_id: str,
    ) -> None:
        """Create a relationship (used by dedup merge)."""
        await self._save_relationship(source_id, target_id, relationship_type)

    async def _archive_node_with_reason(self, node_id: str, workspace_id: str, reason: str) -> None:
        """Archive node with reason (used by dedup/pruning)."""
        # Get node data first
        node = await self._get_node(node_id)
        if not node:
            logger.debug("Node %s not found, skipping archive", node_id)
            return

        archive_record = {
            "id": f"arch_{node_id}_{uuid.uuid4().hex[:8]}",
            "original_id": node_id,
            "content": node.content,
            "source": node.source.value if hasattr(node.source, "value") else str(node.source),
            "source_id": node.source_id,
            "confidence": (
                node.confidence.value if hasattr(node.confidence, "value") else str(node.confidence)
            ),
            "importance": node.importance,
            "metadata": node.metadata,
            "created_at": _to_iso_string(node.created_at),
            "updated_at": _to_iso_string(node.updated_at),
            "archived_at": datetime.now().isoformat(),
            "archived_by": reason,
            "workspace_id": workspace_id,
        }

        # Save to archive
        store = self._require_meta_store()
        try:
            with store.connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS knowledge_archive (
                        id TEXT PRIMARY KEY,
                        original_id TEXT NOT NULL,
                        content TEXT NOT NULL,
                        source TEXT,
                        source_id TEXT,
                        confidence TEXT,
                        importance REAL,
                        metadata TEXT,
                        created_at TEXT,
                        updated_at TEXT,
                        archived_at TEXT NOT NULL,
                        archived_by TEXT,
                        workspace_id TEXT
                    )
                    """)
                conn.execute(
                    """
                    INSERT INTO knowledge_archive
                    (id, original_id, content, source, source_id, confidence,
                     importance, metadata, created_at, updated_at, archived_at, archived_by, workspace_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        archive_record["id"],
                        archive_record["original_id"],
                        archive_record["content"],
                        archive_record["source"],
                        archive_record["source_id"],
                        archive_record["confidence"],
                        archive_record["importance"],
                        (
                            json.dumps(archive_record["metadata"])
                            if archive_record["metadata"]
                            else "{}"
                        ),
                        archive_record["created_at"],
                        archive_record["updated_at"],
                        archive_record["archived_at"],
                        archive_record["archived_by"],
                        archive_record["workspace_id"],
                    ),
                )
                conn.commit()
            # Delete the original node
            await self._delete_node(node_id)
            logger.debug("Archived node %s with reason: %s", node_id, reason)
        except (RuntimeError, OSError) as e:
            logger.warning("Failed to archive node %s: %s", node_id, e)

    async def _restore_archived_node(self, node_id: str, workspace_id: str) -> bool:
        """Restore an archived node (used by pruning restore)."""
        store = self._require_meta_store()
        try:
            with store.connection() as conn:
                row = conn.execute(
                    "SELECT * FROM knowledge_archive WHERE original_id = ? AND workspace_id = ? ORDER BY archived_at DESC LIMIT 1",
                    (node_id, workspace_id),
                ).fetchone()
                if not row:
                    return False

                # Recreate the node from archive
                node_data = {
                    "id": row["original_id"],
                    "workspace_id": row["workspace_id"],
                    "content": row["content"],
                    "source_type": row["source"],
                    "confidence": float(row["confidence"]) if row["confidence"] else 0.5,
                    "metadata": json.loads(row["metadata"]) if row["metadata"] else {},
                }
                await self._save_node(node_data)

                # Remove from archive
                conn.execute("DELETE FROM knowledge_archive WHERE id = ?", (row["id"],))
                conn.commit()
                return True
        except (RuntimeError, OSError, KeyError) as e:
            logger.warning("Failed to restore node %s: %s", node_id, e)
            return False

    async def _get_nodes_by_content_hash(self, workspace_id: str) -> dict[str, list[str]]:
        """Get nodes grouped by content hash (used by dedup auto-merge)."""
        result: dict[str, list[str]] = {}
        store = self._require_meta_store()
        if hasattr(store, "get_nodes_by_content_hash_async"):
            grouped: dict[str, list[str]] = await store.get_nodes_by_content_hash_async(
                workspace_id
            )
            return grouped
        elif hasattr(store, "query_nodes"):
            nodes = store.query_nodes(workspace_id=workspace_id, limit=100000)
            for node in nodes:
                content_hash = node.content_hash
                if content_hash not in result:
                    result[content_hash] = []
                result[content_hash].append(node.id)
        return result

    async def _get_prune_history(
        self,
        workspace_id: str,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[Any]:
        """Get pruning history (used by pruning operations)."""
        from aragora.knowledge.mound.ops.pruning import PruneHistory, PruningAction

        store = self._require_meta_store()
        try:
            with store.connection() as conn:
                # Create table if needed
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS prune_history (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        executed_at TEXT NOT NULL,
                        policy_id TEXT,
                        action TEXT NOT NULL,
                        items_pruned INTEGER NOT NULL,
                        pruned_item_ids TEXT NOT NULL,
                        reason TEXT,
                        executed_by TEXT
                    )
                    """)
                if since:
                    rows = conn.execute(
                        "SELECT * FROM prune_history WHERE workspace_id = ? AND executed_at > ? ORDER BY executed_at DESC LIMIT ?",
                        (workspace_id, since.isoformat(), limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM prune_history WHERE workspace_id = ? ORDER BY executed_at DESC LIMIT ?",
                        (workspace_id, limit),
                    ).fetchall()

                return [
                    PruneHistory(
                        history_id=row["id"],
                        workspace_id=row["workspace_id"],
                        executed_at=datetime.fromisoformat(row["executed_at"]),
                        policy_id=row["policy_id"],
                        action=PruningAction(row["action"]),
                        items_pruned=row["items_pruned"],
                        pruned_item_ids=json.loads(row["pruned_item_ids"]),
                        reason=row["reason"],
                        executed_by=row["executed_by"],
                    )
                    for row in rows
                ]
        except (RuntimeError, OSError) as e:
            logger.warning("Failed to get prune history: %s", e)
            return []

    async def _save_prune_history(self, history: Any) -> None:
        """Save pruning history (used by pruning operations)."""
        store = self._require_meta_store()
        try:
            with store.connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS prune_history (
                        id TEXT PRIMARY KEY,
                        workspace_id TEXT NOT NULL,
                        executed_at TEXT NOT NULL,
                        policy_id TEXT,
                        action TEXT NOT NULL,
                        items_pruned INTEGER NOT NULL,
                        pruned_item_ids TEXT NOT NULL,
                        reason TEXT,
                        executed_by TEXT
                    )
                    """)
                conn.execute(
                    """
                    INSERT INTO prune_history
                    (id, workspace_id, executed_at, policy_id, action, items_pruned, pruned_item_ids, reason, executed_by)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        history.history_id,
                        history.workspace_id,
                        _to_iso_string(history.executed_at),
                        history.policy_id,
                        _to_enum_value(history.action),
                        history.items_pruned,
                        json.dumps(history.pruned_item_ids),
                        history.reason,
                        history.executed_by,
                    ),
                )
                conn.commit()
        except (RuntimeError, OSError) as e:
            logger.warning("Failed to save prune history: %s", e)

    # =========================================================================
    # Query Helper Methods (for connected stores)
    # =========================================================================

    async def _query_local(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
        workspace_id: str,
    ) -> list[KnowledgeItem]:
        """Query local mound storage."""
        store = self._require_meta_store()
        if hasattr(store, "query_async"):
            return list(await store.query_async(query, filters, limit, workspace_id))
        else:
            nodes = store.query_nodes(
                workspace_id=workspace_id,
                limit=limit,
            )
            # Simple keyword matching
            query_words = set(query.lower().split())
            scored = []
            for node in nodes:
                content_words = set(node.content.lower().split())
                score = len(query_words & content_words) / max(len(query_words), 1)
                scored.append((score, node))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [self._node_to_item(n) for _, n in scored[:limit]]

    async def _query_continuum(
        self, query: str, filters: QueryFilters | None, limit: int
    ) -> list[KnowledgeItem]:
        """Query ContinuumMemory."""
        if not self._continuum:
            return []
        try:
            search_fn = getattr(self._continuum, "search_by_keyword", None)
            if search_fn is None:
                return []
            entries = search_fn(query, limit=limit)
            return [self._continuum_to_item(e) for e in entries]
        except (KeyError, ValueError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Continuum query failed: %s", e)
            return []

    async def _query_consensus(
        self, query: str, filters: QueryFilters | None, limit: int
    ) -> list[KnowledgeItem]:
        """Query ConsensusMemory."""
        if not self._consensus:
            return []
        try:
            search_fn = getattr(self._consensus, "search_by_topic", None)
            if search_fn is None:
                return []
            entries = await search_fn(query, limit=limit)
            return [self._consensus_to_item(e) for e in entries]
        except (KeyError, ValueError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Consensus query failed: %s", e)
            return []

    async def _query_facts(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
        workspace_id: str,
    ) -> list[KnowledgeItem]:
        """Query FactStore."""
        if not self._facts:
            return []
        try:
            query_fn = getattr(self._facts, "query_facts", None)
            if query_fn is None:
                return []
            facts = query_fn(query, workspace_id=workspace_id, limit=limit)
            return [self._fact_to_item(f) for f in facts]
        except (KeyError, ValueError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Facts query failed: %s", e)
            return []

    async def _query_evidence(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
        workspace_id: str,
    ) -> list[KnowledgeItem]:
        """Query EvidenceStore."""
        if not self._evidence:
            return []
        try:
            # EvidenceStore.search returns evidence snippets
            search_fn = getattr(self._evidence, "search", None)
            if search_fn is None:
                return []
            evidence_list = search_fn(query, limit=limit)
            return [self._evidence_to_item(e) for e in evidence_list]
        except (KeyError, ValueError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Evidence query failed: %s", e)
            return []

    async def _query_critique(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
    ) -> list[KnowledgeItem]:
        """Query CritiqueStore for successful patterns."""
        if not self._critique:
            return []
        try:
            # CritiqueStore.search_patterns returns critique patterns
            search_fn = getattr(self._critique, "search_patterns", None)
            if search_fn is None:
                return []
            patterns = search_fn(query, limit=limit)
            return [self._critique_to_item(p) for p in patterns]
        except (KeyError, ValueError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Critique query failed: %s", e)
            return []

    # =========================================================================
    # Conversion Helpers (delegated to converters module)
    # =========================================================================

    def _node_to_item(self, node: Any) -> KnowledgeItem:
        """Convert KnowledgeNode to KnowledgeItem."""
        return node_to_item(node)

    def _rel_to_link(self, rel: Any) -> KnowledgeLink:
        """Convert KnowledgeRelationship to KnowledgeLink."""
        return relationship_to_link(rel)

    def _continuum_to_item(self, entry: Any) -> KnowledgeItem:
        """Convert ContinuumMemory entry to KnowledgeItem."""
        return continuum_to_item(entry)

    def _consensus_to_item(self, entry: Any) -> KnowledgeItem:
        """Convert ConsensusMemory entry to KnowledgeItem."""
        return consensus_to_item(entry)

    def _fact_to_item(self, fact: Any) -> KnowledgeItem:
        """Convert Fact to KnowledgeItem."""
        return fact_to_item(fact)

    def _vector_result_to_item(self, result: Any) -> KnowledgeItem:
        """Convert vector search result to KnowledgeItem."""
        return vector_result_to_item(result)

    def _evidence_to_item(self, evidence: Any) -> KnowledgeItem:
        """Convert EvidenceSnippet to KnowledgeItem."""
        return evidence_to_item(evidence)

    def _critique_to_item(self, pattern: Any) -> KnowledgeItem:
        """Convert CritiquePattern to KnowledgeItem."""
        return critique_to_item(pattern)


# Re-export KnowledgeMound facade from here for backward compatibility
# Many modules import from .core expecting KnowledgeMound
def __getattr__(name: str) -> Any:
    """Lazy import for KnowledgeMound to avoid circular import."""
    if name == "KnowledgeMound":
        from aragora.knowledge.mound.facade import KnowledgeMound

        return KnowledgeMound
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
