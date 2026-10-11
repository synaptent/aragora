"""
Knowledge Mound Unified Store.

Provides a federated query interface across all Aragora knowledge systems:
- ContinuumMemory: Multi-tier temporal learning
- ConsensusMemory: Debate outcomes and agreements
- FactStore: Verified facts from document analysis
- WeaviateStore: Semantic embeddings for similarity search

The Knowledge Mound enables cross-system queries and knowledge linking,
implementing the "termite mound" architecture where all agents contribute
to and query from a shared knowledge superstructure.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Sequence

from aragora.knowledge.fact_store import OrgScopeRequiredError
from aragora.knowledge.unified.types import (
    ConfidenceLevel,
    KnowledgeItem,
    KnowledgeLink,
    KnowledgeSource,
    LinkResult,
    QueryFilters,
    QueryResult,
    RelationshipType,
    SourceFilter,
    StoreResult,
)

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.consensus import ConsensusMemory
    from aragora.knowledge.fact_store import FactStore
    from aragora.documents.indexing.weaviate_store import WeaviateStore

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeMoundConfig:
    """Configuration for the Knowledge Mound."""

    # Optional store references (will use defaults if not provided)
    continuum_memory: ContinuumMemory | None = None
    consensus_memory: ConsensusMemory | None = None
    fact_store: FactStore | None = None
    vector_store: WeaviateStore | None = None

    # Feature flags
    enable_cross_references: bool = True
    enable_vector_search: bool = True
    enable_link_inference: bool = False  # Experimental: auto-infer links

    # Query settings
    default_limit: int = 20
    max_limit: int = 100
    parallel_queries: bool = True  # Query sources in parallel

    # Cross-reference settings
    auto_link_threshold: float = 0.85  # Similarity threshold for auto-linking


class KnowledgeMound:
    """
    Unified knowledge retrieval and storage across all memory systems.

    The Knowledge Mound provides:
    1. Federated queries across ContinuumMemory, ConsensusMemory, FactStore, and VectorStore
    2. Cross-referencing between knowledge items
    3. Knowledge graph traversal via links
    4. Unified storage with automatic routing to appropriate stores

    Usage:
        mound = KnowledgeMound(config)
        await mound.initialize()

        # Query across all sources
        result = await mound.query("contract expiration dates")

        # Store new knowledge
        item_id = await mound.store(
            content="Contract expires 2025-12-31",
            source_type=KnowledgeSource.FACT,
            metadata={"document_id": "doc_123"},
        )

        # Link related items
        await mound.link(
            source_id="fact_123",
            target_id="consensus_456",
            relationship=RelationshipType.SUPPORTS,
        )
    """

    def __init__(self, config: KnowledgeMoundConfig | None = None):
        self.config = config or KnowledgeMoundConfig()
        self._initialized = False

        # Store references (lazy-loaded)
        self._continuum: ContinuumMemory | None = config.continuum_memory if config else None
        self._consensus: ConsensusMemory | None = config.consensus_memory if config else None
        self._facts: FactStore | None = config.fact_store if config else None
        self._vectors: WeaviateStore | None = config.vector_store if config else None

        # In-memory link storage (will be persisted in Phase 1.2)
        self._links: dict[str, KnowledgeLink] = {}
        self._source_links: dict[str, list[str]] = {}  # source_id -> [link_ids]
        self._target_links: dict[str, list[str]] = {}  # target_id -> [link_ids]

    async def initialize(self) -> None:
        """Initialize connections to all knowledge stores."""
        if self._initialized:
            return

        logger.info("Initializing Knowledge Mound...")

        # Initialize stores that weren't provided
        if self._continuum is None:
            try:
                from aragora.memory.continuum import ContinuumMemory

                self._continuum = ContinuumMemory()
                # ContinuumMemory initializes in __init__, no async initialize needed
            except ImportError:
                logger.warning("ContinuumMemory not available")

        if self._consensus is None:
            try:
                from aragora.memory.consensus import ConsensusMemory

                self._consensus = ConsensusMemory()
            except ImportError:
                logger.warning("ConsensusMemory not available")

        if self._facts is None:
            try:
                from aragora.knowledge.fact_store import FactStore

                self._facts = FactStore()
            except ImportError:
                logger.warning("FactStore not available")

        if self._vectors is None and self.config.enable_vector_search:
            try:
                from aragora.documents.indexing.weaviate_store import WeaviateStore

                self._vectors = WeaviateStore()
            except ImportError:
                logger.warning("WeaviateStore not available")

        self._initialized = True
        logger.info("Knowledge Mound initialized")

    async def query(
        self,
        query: str,
        sources: Sequence[SourceFilter] = ("all",),
        filters: QueryFilters | None = None,
        limit: int = 20,
        include_links: bool = False,
    ) -> QueryResult:
        """
        Query across all configured knowledge stores.

        Args:
            query: Natural language query string
            sources: Which sources to query ("all" or specific sources)
            filters: Optional filters to apply
            limit: Maximum number of results
            include_links: Whether to include linked items in results

        Returns:
            QueryResult with items from all queried sources
        """
        if not self._initialized:
            await self.initialize()

        start_time = time.time()
        limit = min(limit, self.config.max_limit)

        # Determine which sources to query
        source_list = self._resolve_sources(sources)

        # Query each source
        # Results can be list[KnowledgeItem] or BaseException when return_exceptions=True
        results: list[list[KnowledgeItem] | BaseException]
        if self.config.parallel_queries:
            tasks = []
            for source in source_list:
                tasks.append(self._query_source(source, query, filters, limit))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            results = []
            for source in source_list:
                try:
                    result = await self._query_source(source, query, filters, limit)
                    results.append(result)
                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    results.append(e)

        # Combine results
        all_items: list[KnowledgeItem] = []
        for i, query_result in enumerate(results):
            if isinstance(query_result, OrgScopeRequiredError):
                raise query_result
            if isinstance(query_result, BaseException):
                logger.warning("Query to %s failed: %s", source_list[i], query_result)
            elif query_result:
                all_items.extend(query_result)

        # Sort by importance/relevance and limit
        def _importance(item: KnowledgeItem) -> float:
            value = getattr(item, "importance", None)
            if value is None:
                return 0.0
            if isinstance(value, (int, float)):
                return float(value)
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        all_items.sort(key=_importance, reverse=True)
        all_items = all_items[:limit]

        # Optionally include linked items
        if include_links and all_items:
            linked_items = await self._get_linked_items([item.id for item in all_items])
            # Add linked items that aren't already in results
            existing_ids = {item.id for item in all_items}
            for linked in linked_items:
                if linked.id not in existing_ids:
                    all_items.append(linked)

        execution_time = (time.time() - start_time) * 1000

        return QueryResult(
            items=all_items,
            total_count=len(all_items),
            query=query,
            filters=filters,
            execution_time_ms=execution_time,
            sources_queried=source_list,
        )

    async def store(
        self,
        content: str,
        source_type: KnowledgeSource,
        metadata: dict[str, Any] | None = None,
        cross_references: list[str] | None = None,
        importance: float = 0.5,
    ) -> StoreResult:
        """
        Store a new knowledge item with automatic routing to the appropriate store.

        Args:
            content: The knowledge content to store
            source_type: Which store to use
            metadata: Optional metadata to attach
            cross_references: Optional list of item IDs to link to
            importance: Importance score (0-1)

        Returns:
            StoreResult with the new item ID
        """
        if not self._initialized:
            await self.initialize()

        metadata = metadata or {}
        item_id = f"km_{uuid.uuid4().hex[:12]}"

        try:
            if source_type == KnowledgeSource.CONTINUUM:
                await self._store_to_continuum(item_id, content, metadata, importance)
            elif source_type == KnowledgeSource.FACT:
                await self._store_to_facts(item_id, content, metadata)
            elif source_type == KnowledgeSource.CONSENSUS:
                # Consensus entries are typically created by debates, not directly
                logger.warning("Direct storage to consensus memory not recommended")
                return StoreResult(
                    id=item_id,
                    source=source_type,
                    success=False,
                    message="Use debate system to create consensus entries",
                )
            else:
                return StoreResult(
                    id=item_id,
                    source=source_type,
                    success=False,
                    message=f"Storage not supported for source type: {source_type}",
                )

            # Create cross-references if enabled
            refs_created = 0
            if self.config.enable_cross_references and cross_references:
                for ref_id in cross_references:
                    result = await self.link(
                        source_id=item_id,
                        target_id=ref_id,
                        relationship=RelationshipType.RELATED_TO,
                    )
                    if result.success:
                        refs_created += 1

            return StoreResult(
                id=item_id,
                source=source_type,
                success=True,
                cross_references_created=refs_created,
            )

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to store knowledge item: %s", e)
            return StoreResult(
                id=item_id,
                source=source_type,
                success=False,
                message="Failed to store knowledge item",
            )

    async def link(
        self,
        source_id: str,
        target_id: str,
        relationship: RelationshipType,
        confidence: float = 1.0,
        created_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LinkResult:
        """
        Create a link between two knowledge items.

        Args:
            source_id: ID of the source knowledge item
            target_id: ID of the target knowledge item
            relationship: Type of relationship
            confidence: Confidence in the relationship (0-1)
            created_by: Agent or user that created the link
            metadata: Optional metadata for the link

        Returns:
            LinkResult indicating success or failure
        """
        link_id = f"link_{uuid.uuid4().hex[:12]}"

        try:
            link = KnowledgeLink(
                id=link_id,
                source_id=source_id,
                target_id=target_id,
                relationship=relationship,
                confidence=confidence,
                created_at=datetime.now(timezone.utc),
                created_by=created_by,
                metadata=metadata or {},
            )

            # Store link
            self._links[link_id] = link

            # Update indexes
            if source_id not in self._source_links:
                self._source_links[source_id] = []
            self._source_links[source_id].append(link_id)

            if target_id not in self._target_links:
                self._target_links[target_id] = []
            self._target_links[target_id].append(link_id)

            logger.debug(
                "Created link %s: %s -> %s (%s)", link_id, source_id, target_id, relationship
            )

            return LinkResult(id=link_id, success=True)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to create link: %s", e)
            return LinkResult(id=link_id, success=False, message="Failed to create link")

    async def get_links(
        self,
        item_id: str,
        direction: str = "both",  # "outgoing", "incoming", "both"
        relationship: RelationshipType | None = None,
    ) -> list[KnowledgeLink]:
        """
        Get all links for a knowledge item.

        Args:
            item_id: ID of the knowledge item
            direction: Which links to return
            relationship: Optional filter by relationship type

        Returns:
            List of matching links
        """
        links: list[KnowledgeLink] = []

        if direction in ("outgoing", "both"):
            for link_id in self._source_links.get(item_id, []):
                link = self._links.get(link_id)
                if link and (relationship is None or link.relationship == relationship):
                    links.append(link)

        if direction in ("incoming", "both"):
            for link_id in self._target_links.get(item_id, []):
                link = self._links.get(link_id)
                if link and (relationship is None or link.relationship == relationship):
                    links.append(link)

        return links

    async def get_graph(
        self,
        root_id: str,
        depth: int = 2,
        max_nodes: int = 50,
    ) -> dict[str, Any]:
        """
        Get a knowledge subgraph starting from a root item.

        Args:
            root_id: ID of the root knowledge item
            depth: Maximum depth to traverse
            max_nodes: Maximum number of nodes to return

        Returns:
            Dictionary with nodes and edges for visualization
        """
        nodes: dict[str, KnowledgeItem] = {}
        edges: list[dict[str, Any]] = []
        visited: set = set()
        queue: list[tuple] = [(root_id, 0)]

        while queue and len(nodes) < max_nodes:
            current_id, current_depth = queue.pop(0)

            if current_id in visited or current_depth > depth:
                continue
            visited.add(current_id)

            # Get the item
            item = await self._get_item_by_id(current_id)
            if item:
                nodes[current_id] = item

                # Get outgoing links
                if current_depth < depth:
                    links = await self.get_links(current_id, direction="outgoing")
                    for link in links:
                        edges.append(
                            {
                                "source": link.source_id,
                                "target": link.target_id,
                                "relationship": link.relationship.value,
                                "confidence": link.confidence,
                            }
                        )
                        if link.target_id not in visited:
                            queue.append((link.target_id, current_depth + 1))

        return {
            "nodes": [node.to_dict() for node in nodes.values()],
            "edges": edges,
            "root_id": root_id,
            "depth": depth,
        }

    # Private helper methods

    def _resolve_sources(self, sources: Sequence[SourceFilter]) -> list[KnowledgeSource]:
        """Resolve source filter to list of KnowledgeSource."""
        if "all" in sources:
            return [
                KnowledgeSource.CONTINUUM,
                KnowledgeSource.CONSENSUS,
                KnowledgeSource.FACT,
                KnowledgeSource.VECTOR,
            ]

        result = []
        for s in sources:
            if s != "all":
                result.append(KnowledgeSource(s))
        return result

    async def _query_source(
        self,
        source: KnowledgeSource,
        query: str,
        filters: QueryFilters | None,
        limit: int,
    ) -> list[KnowledgeItem]:
        """Query a specific knowledge source."""
        if source == KnowledgeSource.CONTINUUM:
            return await self._query_continuum(query, filters, limit)
        elif source == KnowledgeSource.CONSENSUS:
            return await self._query_consensus(query, filters, limit)
        elif source == KnowledgeSource.FACT:
            return await self._query_facts(query, filters, limit)
        elif source == KnowledgeSource.VECTOR:
            return await self._query_vectors(query, filters, limit)
        return []

    async def _query_continuum(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
    ) -> list[KnowledgeItem]:
        """Query ContinuumMemory."""
        if not self._continuum:
            return []

        try:
            # Use retrieve() for keyword matching (semantic search in Phase 1.2)
            entries = self._continuum.retrieve(query=query, limit=limit)
            items = []
            for entry in entries:
                items.append(
                    KnowledgeItem(
                        id=f"cm_{entry.id}",
                        content=entry.content,
                        source=KnowledgeSource.CONTINUUM,
                        source_id=entry.id,
                        confidence=self._tier_to_confidence(entry.tier.value),
                        created_at=datetime.fromisoformat(entry.created_at),
                        updated_at=datetime.fromisoformat(entry.last_updated),
                        metadata={"tier": entry.tier.value, "tags": entry.tags},
                        importance=entry.importance,
                    )
                )
            return items
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Continuum query failed: %s", e)
            return []

    async def _query_consensus(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
    ) -> list[KnowledgeItem]:
        """Query ConsensusMemory."""
        if not self._consensus:
            return []

        try:
            # Search by topic similarity using find_similar_debates
            similar_debates = self._consensus.find_similar_debates(topic=query, limit=limit)
            items = []
            for similar in similar_debates:
                consensus = similar.consensus
                items.append(
                    KnowledgeItem(
                        id=f"cs_{consensus.id}",
                        content=consensus.conclusion or consensus.topic,
                        source=KnowledgeSource.CONSENSUS,
                        source_id=consensus.id,
                        confidence=self._strength_to_confidence(consensus.strength.value),
                        created_at=consensus.timestamp,
                        updated_at=consensus.timestamp,
                        metadata={
                            "debate_id": consensus.id,
                            "supporting_agents": consensus.agreeing_agents,
                            "similarity": similar.similarity_score,
                        },
                        importance=consensus.confidence,
                    )
                )
            return items
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Consensus query failed: %s", e)
            return []

    async def _query_facts(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
    ) -> list[KnowledgeItem]:
        """Query FactStore."""
        if not self._facts:
            return []

        try:
            from aragora.knowledge.types import FactFilters

            # Build FactFilters from QueryFilters
            fact_filters = FactFilters(
                workspace_id=filters.workspace_id if filters else None,
                limit=limit,
            )
            # query_facts is sync, not async
            facts = self._facts.query_facts(query=query, filters=fact_filters)
            items = []
            for fact in facts:
                items.append(
                    KnowledgeItem(
                        id=f"fc_{fact.id}",
                        content=fact.statement,
                        source=KnowledgeSource.FACT,
                        source_id=fact.id,
                        confidence=self._validation_to_confidence(fact.validation_status.value),
                        created_at=fact.created_at,
                        updated_at=fact.updated_at or fact.created_at,
                        metadata={
                            "evidence_ids": fact.evidence_ids,
                            "source_documents": fact.source_documents,
                            "tags": fact.topics,
                        },
                        importance=fact.confidence,
                    )
                )
            return items
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Facts query failed: %s", e)
            return []

    async def _query_vectors(
        self,
        query: str,
        filters: QueryFilters | None,
        limit: int,
    ) -> list[KnowledgeItem]:
        """Query VectorStore for semantic similarity."""
        if not self._vectors:
            return []

        try:
            # WeaviateStore uses search_keyword for BM25 text search
            # (search_vector requires an embedding, which we don't have here)
            document_ids = None
            if filters and filters.workspace_id:
                # workspace_id doesn't directly map to document_ids
                # but we can pass None and filter results if needed
                pass
            results = await self._vectors.search_keyword(
                query=query,
                limit=limit,
                document_ids=document_ids,
            )
            items = []
            for result in results:
                items.append(
                    KnowledgeItem(
                        id=f"vc_{result.chunk_id}",
                        content=result.content,
                        source=KnowledgeSource.VECTOR,
                        source_id=result.chunk_id,
                        confidence=ConfidenceLevel.MEDIUM,
                        created_at=datetime.now(
                            timezone.utc
                        ),  # Vector store may not have timestamps
                        updated_at=datetime.now(timezone.utc),
                        metadata=result.metadata or {},
                        importance=result.score,
                    )
                )
            return items
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.error("Vector query failed: %s", e)
            return []

    async def _store_to_continuum(
        self,
        item_id: str,
        content: str,
        metadata: dict[str, Any],
        importance: float,
    ) -> None:
        """Store to ContinuumMemory."""
        if not self._continuum:
            raise RuntimeError("ContinuumMemory not available")

        # ContinuumMemory.store() takes key, content, tier, importance, metadata
        await self._continuum.store(
            key=item_id,
            content=content,
            importance=importance,
            metadata={
                "tags": metadata.get("tags", []),
                "source_type": metadata.get("source_type", "knowledge_mound"),
            },
        )

    async def _store_to_facts(
        self,
        item_id: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        """Store to FactStore."""
        if not self._facts:
            raise RuntimeError("FactStore not available")

        # add_fact is synchronous
        self._facts.add_fact(
            statement=content,
            evidence_ids=metadata.get("evidence_ids", []),
            source_documents=metadata.get("source_documents", []),
            workspace_id=metadata.get("workspace_id", "default"),
            confidence=metadata.get("confidence", 0.5),
            topics=metadata.get("topics", []),
        )

    async def _get_item_by_id(self, item_id: str) -> KnowledgeItem | None:
        """Get a knowledge item by its Knowledge Mound ID."""
        # Parse the ID prefix to determine source
        if item_id.startswith("cm_"):
            return await self._get_continuum_item(item_id[3:])
        elif item_id.startswith("cs_"):
            return await self._get_consensus_item(item_id[3:])
        elif item_id.startswith("fc_"):
            return await self._get_fact_item(item_id[3:])
        elif item_id.startswith("vc_"):
            return await self._get_vector_item(item_id[3:])
        return None

    async def _get_continuum_item(self, source_id: str) -> KnowledgeItem | None:
        """Get a ContinuumMemory item by source ID."""
        if not self._continuum:
            return None
        entry = self._continuum.get_entry(source_id)
        if entry:
            return KnowledgeItem(
                id=f"cm_{entry.id}",
                content=entry.content,
                source=KnowledgeSource.CONTINUUM,
                source_id=entry.id,
                confidence=self._tier_to_confidence(entry.tier.value),
                created_at=datetime.fromisoformat(entry.created_at),
                updated_at=datetime.fromisoformat(entry.last_updated),
                metadata={"tier": entry.tier.value},
                importance=entry.importance,
            )
        return None

    async def _get_consensus_item(self, source_id: str) -> KnowledgeItem | None:
        """Get a ConsensusMemory item by source ID."""
        # Implementation depends on ConsensusMemory.get() method
        return None

    async def _get_fact_item(self, source_id: str) -> KnowledgeItem | None:
        """Get a FactStore item by source ID."""
        if not self._facts:
            return None
        # get_fact is sync, not async
        fact = self._facts.get_fact(source_id)
        if fact:
            return KnowledgeItem(
                id=f"fc_{fact.id}",
                content=fact.statement,
                source=KnowledgeSource.FACT,
                source_id=fact.id,
                confidence=self._validation_to_confidence(fact.validation_status.value),
                created_at=fact.created_at,
                updated_at=fact.updated_at or fact.created_at,
                metadata={
                    "evidence_ids": fact.evidence_ids,
                    "source_documents": fact.source_documents,
                },
                importance=fact.confidence,
            )
        return None

    async def _get_vector_item(self, source_id: str) -> KnowledgeItem | None:
        """Get a VectorStore item by source ID."""
        # Implementation depends on WeaviateStore.get() method
        return None

    async def _get_linked_items(self, item_ids: list[str]) -> list[KnowledgeItem]:
        """Get all items linked to the given item IDs."""
        linked_items = []
        seen_ids = set(item_ids)

        for item_id in item_ids:
            links = await self.get_links(item_id, direction="both")
            for link in links:
                target_id = link.target_id if link.source_id == item_id else link.source_id
                if target_id not in seen_ids:
                    seen_ids.add(target_id)
                    item = await self._get_item_by_id(target_id)
                    if item:
                        linked_items.append(item)

        return linked_items

    # Confidence level mapping helpers

    def _tier_to_confidence(self, tier: str) -> ConfidenceLevel:
        """Map ContinuumMemory tier to confidence level."""
        mapping = {
            "glacial": ConfidenceLevel.VERIFIED,
            "slow": ConfidenceLevel.HIGH,
            "medium": ConfidenceLevel.MEDIUM,
            "fast": ConfidenceLevel.LOW,
        }
        return mapping.get(tier, ConfidenceLevel.MEDIUM)

    def _strength_to_confidence(self, strength: str) -> ConfidenceLevel:
        """Map ConsensusMemory strength to confidence level."""
        mapping = {
            "unanimous": ConfidenceLevel.VERIFIED,
            "strong": ConfidenceLevel.HIGH,
            "moderate": ConfidenceLevel.MEDIUM,
            "weak": ConfidenceLevel.LOW,
            "split": ConfidenceLevel.LOW,
            "contested": ConfidenceLevel.UNVERIFIED,
        }
        return mapping.get(strength.lower(), ConfidenceLevel.MEDIUM)

    def _validation_to_confidence(self, status: str) -> ConfidenceLevel:
        """Map FactStore validation status to confidence level."""
        mapping = {
            "verified": ConfidenceLevel.VERIFIED,
            "unverified": ConfidenceLevel.MEDIUM,
            "contradicted": ConfidenceLevel.LOW,
        }
        return mapping.get(status.lower(), ConfidenceLevel.MEDIUM)
