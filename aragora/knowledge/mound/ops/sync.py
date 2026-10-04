"""
Sync Operations Mixin for Knowledge Mound.

Provides cross-system synchronization:
- sync_from_continuum: Sync from ContinuumMemory
- sync_from_consensus: Sync from ConsensusMemory
- sync_from_facts: Sync from FactStore
- sync_from_evidence: Sync from EvidenceStore
- sync_from_critique: Sync from CritiqueStore
- sync_all: Sync from all connected systems

Performance optimizations:
- Batched store operations to avoid N+1 query pattern
- Concurrent processing with configurable batch sizes
- Retry logic with exponential backoff for transient failures

NOTE: This is a mixin class designed to be composed with KnowledgeMound.
Attribute accesses like self._ensure_initialized, self.workspace_id, self.store, etc.
are provided by the composed class. The mixin uses a conditional Protocol base class
pattern for proper type checking without runtime overhead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol

from aragora.resilience.retry import (
    PROVIDER_RETRY_POLICIES,
    with_retry,
)

if TYPE_CHECKING:
    from aragora.knowledge.mound.types import (
        IngestionRequest,
        MoundConfig,
        SyncResult,
    )
    from aragora.memory.continuum import ContinuumMemory
    from aragora.memory.consensus import ConsensusMemory
    from aragora.knowledge.fact_store import FactStore
    from aragora.evidence.store import EvidenceStore
    from aragora.memory.store import CritiqueStore

logger = logging.getLogger(__name__)


class SyncProtocol(Protocol):
    """Protocol defining expected interface for Sync mixin."""

    config: MoundConfig
    workspace_id: str
    _continuum: ContinuumMemory | None
    _consensus: ConsensusMemory | None
    _facts: FactStore | None
    _evidence: EvidenceStore | None
    _critique: CritiqueStore | None
    _batch_store: Any
    _initialized: bool

    def _ensure_initialized(self) -> None: ...
    async def store(self, request: IngestionRequest) -> Any: ...

    async def sync_from_continuum(
        self,
        continuum: ContinuumMemory,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult: ...

    async def sync_from_consensus(
        self,
        consensus: ConsensusMemory,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult: ...

    async def sync_from_facts(
        self,
        facts: FactStore,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult: ...

    async def sync_from_evidence(
        self,
        evidence: EvidenceStore,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult: ...

    async def sync_from_critique(
        self,
        critique: CritiqueStore,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult: ...


# Retry configuration for sync operations
_SYNC_RETRY_CONFIG = PROVIDER_RETRY_POLICIES["knowledge_mound"]


# Use Protocol as base class only for type checking
if TYPE_CHECKING:
    _SyncMixinBase = SyncProtocol
else:
    _SyncMixinBase = object


class SyncOperationsMixin(_SyncMixinBase):
    """Mixin providing sync operations for KnowledgeMound."""

    @with_retry(_SYNC_RETRY_CONFIG)
    async def _batch_store(
        self,
        requests: list[IngestionRequest],
        batch_size: int = 50,
    ) -> tuple[int, int, int, int, list[str]]:
        """
        Store multiple ingestion requests in batches with concurrency control.

        This method addresses the N+1 query pattern by processing requests
        concurrently in batches rather than one at a time.

        Args:
            requests: List of IngestionRequest objects to store
            batch_size: Number of concurrent store operations per batch

        Returns:
            Tuple of (nodes_synced, nodes_updated, nodes_skipped,
                     relationships_created, errors)
        """
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        relationships_created = 0
        errors: list[str] = []

        # Process in batches to control concurrency
        for i in range(0, len(requests), batch_size):
            batch = requests[i : i + batch_size]

            # Create coroutines for the batch
            async def store_single(
                req: IngestionRequest,
            ) -> tuple[bool, bool, int, str | None]:
                """Store a single request and return status."""
                try:
                    result = await self.store(req)
                    return (
                        not result.deduplicated,  # is_new
                        result.deduplicated,  # is_update
                        result.relationships_created,
                        None,  # no error
                    )
                except (RuntimeError, ValueError, OSError, KeyError):  # noqa: BLE001 - adapter isolation
                    # Extract identifier for error message
                    item_id = (
                        req.metadata.get("continuum_id")
                        or req.metadata.get("consensus_id")
                        or req.metadata.get("fact_id")
                        or req.metadata.get("evidence_id")
                        or req.metadata.get("pattern_id")
                        or "unknown"
                    )
                    return (False, False, 0, f"{item_id}: ingestion failed")

            # Execute batch concurrently
            results = await asyncio.gather(
                *[store_single(req) for req in batch],
                return_exceptions=False,
            )

            # Aggregate results
            for is_new, is_update, rels, error in results:
                if error:
                    nodes_skipped += 1
                    errors.append(error)
                elif is_update:
                    nodes_updated += 1
                    relationships_created += rels
                else:
                    nodes_synced += 1
                    relationships_created += rels

        return nodes_synced, nodes_updated, nodes_skipped, relationships_created, errors

    async def sync_from_continuum(
        self,
        continuum: ContinuumMemory,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult:
        """
        Sync knowledge from ContinuumMemory.

        Iterates through memory entries and stores them as knowledge nodes.
        Uses content hash deduplication to avoid duplicates.

        Args:
            continuum: ContinuumMemory instance to sync from
            incremental: If True, only sync entries updated since last sync
            batch_size: Number of entries to process per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        start_time = time.time()
        self._continuum = continuum
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        errors: list[str] = []

        try:
            # Retrieve all entries from continuum (using high limit for full sync)
            entries = continuum.retrieve(
                query=None,
                tiers=None,
                limit=10000,  # High limit for sync
                min_importance=0.0,
                include_glacial=True,
            )

            # Collect all requests for batch processing
            requests: list[IngestionRequest] = []
            for entry in entries:
                try:
                    # Create ingestion request from continuum entry
                    request = IngestionRequest(
                        content=entry.content,
                        workspace_id=self.workspace_id,
                        source_type=KnowledgeSource.CONTINUUM,
                        node_type="memory",
                        confidence=entry.importance,
                        tier=entry.tier.value,
                        metadata={
                            "continuum_id": entry.id,
                            "surprise_score": entry.surprise_score,
                            "consolidation_score": entry.consolidation_score,
                            "update_count": entry.update_count,
                            "success_rate": entry.success_rate,
                            "original_metadata": entry.metadata,
                        },
                    )
                    requests.append(request)

                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    nodes_skipped += 1
                    logger.warning(
                        "Failed to create request for continuum entry %s: %s", entry.id, e
                    )
                    errors.append(f"continuum:{entry.id}: request creation failed")

            # Batch store all requests
            if requests:
                synced, updated, skipped, _, batch_errors = await self._batch_store(
                    requests, batch_size=batch_size
                )
                nodes_synced += synced
                nodes_updated += updated
                nodes_skipped += skipped
                errors.extend(batch_errors)

        except (RuntimeError, ValueError, AttributeError, OSError) as e:
            logger.warning("Failed to retrieve continuum entries: %s", e)
            errors.append("continuum:retrieve: retrieval failed")

        return SyncResult(
            source="continuum",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=0,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_from_consensus(
        self,
        consensus: ConsensusMemory,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult:
        """
        Sync knowledge from ConsensusMemory.

        Stores consensus records as high-confidence knowledge nodes.

        Args:
            consensus: ConsensusMemory instance to sync from
            incremental: If True, only sync entries since last sync
            batch_size: Number of entries to process per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        start_time = time.time()
        self._consensus = consensus
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        relationships_created = 0
        errors: list[str] = []

        try:
            # Get recent consensus records from the store
            # ConsensusMemory stores records in SQLite, we query directly
            if hasattr(consensus, "_store") and consensus._store:
                with consensus._store.connection() as conn:
                    cursor = conn.execute(
                        """
                        SELECT id, topic, conclusion, strength, confidence,
                               participating_agents, agreeing_agents, domain, tags,
                               timestamp, supersedes, metadata
                        FROM consensus_records
                        ORDER BY timestamp DESC
                        LIMIT ?
                        """,
                        (10000,),
                    )
                    rows = cursor.fetchall()

                # Parse JSON helper
                from aragora.utils.json_helpers import safe_json_loads

                # Collect all requests for batch processing
                requests: list[IngestionRequest] = []
                for row in rows:
                    try:
                        record_id = row[0]
                        topic = row[1]
                        conclusion = row[2]
                        strength = row[3]
                        confidence = row[4]
                        domain = row[7]
                        tags_json = row[8]
                        supersedes = row[10]
                        metadata_json = row[11]

                        tags: list[str] = safe_json_loads(tags_json, [])
                        metadata: dict[str, Any] = safe_json_loads(metadata_json, {})

                        # Create ingestion request
                        request = IngestionRequest(
                            content=f"{topic}: {conclusion}",
                            workspace_id=self.workspace_id,
                            source_type=KnowledgeSource.CONSENSUS,
                            debate_id=record_id,
                            node_type="consensus",
                            confidence=confidence,
                            tier="slow",  # Consensus is stable knowledge
                            topics=tags,
                            metadata={
                                "consensus_id": record_id,
                                "strength": strength,
                                "domain": domain,
                                "original_metadata": metadata,
                            },
                        )

                        # Add supersession relationship
                        if supersedes:
                            request.derived_from = [f"cs_{supersedes}"]

                        requests.append(request)

                    except (
                        RuntimeError,
                        ValueError,
                        KeyError,
                        IndexError,
                        json.JSONDecodeError,
                    ) as e:  # noqa: BLE001 - adapter isolation
                        nodes_skipped += 1
                        logger.warning(
                            "Failed to create request for consensus record %s: %s", row[0], e
                        )
                        errors.append(f"consensus:{row[0]}: request creation failed")

                # Batch store all requests
                if requests:
                    synced, updated, skipped, rels, batch_errors = await self._batch_store(
                        requests, batch_size=batch_size
                    )
                    nodes_synced += synced
                    nodes_updated += updated
                    nodes_skipped += skipped
                    relationships_created += rels
                    errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to query consensus records: %s", e)
            errors.append("consensus:query: query failed")

        return SyncResult(
            source="consensus",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=relationships_created,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_from_facts(
        self,
        facts: FactStore,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult:
        """
        Sync knowledge from FactStore.

        Stores facts as knowledge nodes with evidence relationships.

        Args:
            facts: FactStore instance to sync from
            incremental: If True, only sync since last sync
            batch_size: Number of entries to process per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        start_time = time.time()
        self._facts = facts
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        relationships_created = 0
        errors: list[str] = []

        try:
            # FactStore has query_facts method
            if hasattr(facts, "query_facts"):
                from aragora.knowledge.types import FactFilters

                filters = FactFilters(
                    workspace_id=self.workspace_id,
                    limit=10000,
                )
                all_facts = facts.query_facts(query="", filters=filters)

                # Collect all requests for batch processing
                requests: list[IngestionRequest] = []
                for fact in all_facts:
                    try:
                        request = IngestionRequest(
                            content=fact.statement,
                            workspace_id=self.workspace_id,
                            source_type=KnowledgeSource.FACT,
                            document_id=fact.source_documents[0] if fact.source_documents else None,
                            node_type="fact",
                            confidence=fact.confidence,
                            tier="slow",
                            topics=fact.topics,
                            metadata={
                                "fact_id": fact.id,
                                "validation_status": (
                                    fact.validation_status.value
                                    if hasattr(fact.validation_status, "value")
                                    else str(fact.validation_status)
                                ),
                                "evidence_ids": fact.evidence_ids,
                                "source_documents": fact.source_documents,
                            },
                        )
                        requests.append(request)

                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                        nodes_skipped += 1
                        logger.warning("Failed to create request for fact %s: %s", fact.id, e)
                        errors.append(f"facts:{fact.id}: request creation failed")

                # Batch store all requests
                if requests:
                    synced, updated, skipped, rels, batch_errors = await self._batch_store(
                        requests, batch_size=batch_size
                    )
                    nodes_synced += synced
                    nodes_updated += updated
                    nodes_skipped += skipped
                    relationships_created += rels
                    errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to query facts: %s", e)
            errors.append("facts:query: query failed")

        return SyncResult(
            source="facts",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=relationships_created,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_from_evidence(
        self,
        evidence: EvidenceStore,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult:
        """
        Sync knowledge from EvidenceStore.

        Stores evidence snippets as knowledge nodes.

        Args:
            evidence: EvidenceStore instance to sync from
            incremental: If True, only sync since last sync
            batch_size: Number of entries to process per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        start_time = time.time()
        self._evidence = evidence
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        errors: list[str] = []

        relationships_created = 0

        try:
            # EvidenceStore has search method
            if hasattr(evidence, "search"):
                all_evidence = evidence.search("", limit=10000)

                # Collect all requests for batch processing
                requests: list[IngestionRequest] = []
                for ev in all_evidence:
                    try:
                        request = IngestionRequest(
                            content=ev.content,
                            workspace_id=self.workspace_id,
                            source_type=KnowledgeSource.EVIDENCE,
                            debate_id=getattr(ev, "debate_id", None),
                            agent_id=getattr(ev, "agent_id", None),
                            node_type="evidence",
                            confidence=getattr(ev, "quality_score", 0.5),
                            tier="medium",
                            metadata={
                                "evidence_id": ev.id,
                                "source_url": getattr(ev, "source_url", None),
                            },
                        )
                        requests.append(request)

                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                        nodes_skipped += 1
                        logger.warning("Failed to create request for evidence %s: %s", ev.id, e)
                        errors.append(f"evidence:{ev.id}: request creation failed")

                # Batch store all requests
                if requests:
                    synced, updated, skipped, rels, batch_errors = await self._batch_store(
                        requests, batch_size=batch_size
                    )
                    nodes_synced += synced
                    nodes_updated += updated
                    nodes_skipped += skipped
                    relationships_created += rels
                    errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to search evidence: %s", e)
            errors.append("evidence:search: search failed")

        return SyncResult(
            source="evidence",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=relationships_created,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_from_critique(
        self,
        critique: CritiqueStore,
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncResult:
        """
        Sync knowledge from CritiqueStore (critique patterns).

        Stores successful critique patterns as knowledge nodes.

        Args:
            critique: CritiqueStore instance to sync from
            incremental: If True, only sync since last sync
            batch_size: Number of entries to process per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        start_time = time.time()
        self._critique = critique
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        errors: list[str] = []

        relationships_created = 0

        try:
            # CritiqueStore has search_patterns method
            if hasattr(critique, "search_patterns"):
                patterns = critique.search_patterns("", limit=10000)

                # Collect all requests for batch processing
                requests: list[IngestionRequest] = []
                for pattern in patterns:
                    try:
                        content = getattr(pattern, "pattern", "") or getattr(pattern, "content", "")
                        if not content:
                            nodes_skipped += 1
                            continue

                        request = IngestionRequest(
                            content=content,
                            workspace_id=self.workspace_id,
                            source_type=KnowledgeSource.CRITIQUE,
                            agent_id=getattr(pattern, "agent_name", None),
                            node_type="critique",
                            confidence=getattr(pattern, "success_rate", 0.5),
                            tier="slow",
                            metadata={
                                "pattern_id": pattern.id,
                                "success_count": getattr(pattern, "success_count", 0),
                            },
                        )
                        requests.append(request)

                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                        nodes_skipped += 1
                        logger.warning(
                            "Failed to create request for critique pattern %s: %s", pattern.id, e
                        )
                        errors.append(f"critique:{pattern.id}: request creation failed")

                # Batch store all requests
                if requests:
                    synced, updated, skipped, rels, batch_errors = await self._batch_store(
                        requests, batch_size=batch_size
                    )
                    nodes_synced += synced
                    nodes_updated += updated
                    nodes_skipped += skipped
                    relationships_created += rels
                    errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to search critique patterns: %s", e)
            errors.append("critique:search: search failed")

        return SyncResult(
            source="critique",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=relationships_created,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_all(self) -> dict[str, SyncResult]:
        """
        Sync from all connected memory systems.

        Returns a dict mapping source name to SyncResult.
        Only syncs from sources that have been connected.
        """

        self._ensure_initialized()
        results: dict[str, SyncResult] = {}

        continuum = self._continuum
        if continuum is not None:
            results["continuum"] = await self.sync_from_continuum(continuum)

        consensus = self._consensus
        if consensus is not None:
            results["consensus"] = await self.sync_from_consensus(consensus)

        evidence = self._evidence
        if evidence is not None:
            results["evidence"] = await self.sync_from_evidence(evidence)

        critique = self._critique
        if critique is not None:
            results["critique"] = await self.sync_from_critique(critique)

        # Last: an unscoped fact store raises, and must not cost the other sources their sync.
        facts = self._facts
        if facts is not None:
            results["facts"] = await self.sync_from_facts(facts)

        logger.info(
            "Sync complete: %d sources, %d total nodes synced",
            len(results),
            sum(r.nodes_synced for r in results.values()),
        )

        return results

    # =========================================================================
    # Handler-Compatible Sync Methods
    # These methods use internally connected stores and support incremental sync
    # with `since` parameter for API handler integration.
    # =========================================================================

    async def sync_continuum_incremental(
        self,
        workspace_id: str | None = None,
        since: str | None = None,
        limit: int = 1000,
        batch_size: int = 50,
    ) -> SyncResult:
        """
        Handler-compatible incremental sync from ContinuumMemory.

        Uses the internally connected _continuum store. Supports incremental
        sync via the `since` parameter (ISO timestamp or entry ID).

        Args:
            workspace_id: Override workspace ID for this sync
            since: ISO timestamp or entry ID to sync from (incremental)
            limit: Maximum entries to sync in this batch
            batch_size: Number of concurrent store operations per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from datetime import datetime
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        if not self._continuum:
            return SyncResult(
                source="continuum",
                nodes_synced=0,
                nodes_updated=0,
                nodes_skipped=0,
                relationships_created=0,
                duration_ms=0,
                errors=["ContinuumMemory not connected"],
            )

        start_time = time.time()
        ws_id = workspace_id or self.workspace_id
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        errors: list[str] = []

        try:
            # Parse since timestamp if provided
            since_dt = None
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                except ValueError:
                    pass  # Not a timestamp, could be an ID

            # Retrieve entries from continuum
            entries = self._continuum.retrieve(
                query=None,
                tiers=None,
                limit=limit,
                min_importance=0.0,
                include_glacial=True,
            )

            # Filter by since if provided
            if since_dt:
                entries = [
                    e
                    for e in entries
                    if hasattr(e, "updated_at") and e.updated_at >= since_dt.isoformat()
                ]

            # Collect all requests for batch processing (avoids N+1 pattern)
            requests: list[IngestionRequest] = []
            for entry in entries:
                try:
                    request = IngestionRequest(
                        content=entry.content,
                        workspace_id=ws_id,
                        source_type=KnowledgeSource.CONTINUUM,
                        node_type="memory",
                        confidence=entry.importance,
                        tier=entry.tier.value,
                        metadata={
                            "continuum_id": entry.id,
                            "surprise_score": entry.surprise_score,
                            "consolidation_score": entry.consolidation_score,
                            "update_count": entry.update_count,
                            "success_rate": entry.success_rate,
                            "original_metadata": entry.metadata,
                        },
                    )
                    requests.append(request)

                except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                    nodes_skipped += 1
                    logger.warning(
                        "Failed to create request for continuum entry %s: %s", entry.id, e
                    )
                    errors.append(f"continuum:{entry.id}: request creation failed")

            # Batch store all requests using concurrent processing
            if requests:
                synced, updated, skipped, _, batch_errors = await self._batch_store(
                    requests, batch_size=batch_size
                )
                nodes_synced += synced
                nodes_updated += updated
                nodes_skipped += skipped
                errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to retrieve continuum entries: %s", e)
            errors.append("continuum:retrieve: retrieval failed")

        return SyncResult(
            source="continuum",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=0,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_consensus_incremental(
        self,
        workspace_id: str | None = None,
        since: str | None = None,
        limit: int = 1000,
        batch_size: int = 50,
    ) -> SyncResult:
        """
        Handler-compatible incremental sync from ConsensusMemory.

        Uses the internally connected _consensus store. Supports incremental
        sync via the `since` parameter (ISO timestamp).

        Args:
            workspace_id: Override workspace ID for this sync
            since: ISO timestamp to sync from (incremental)
            limit: Maximum entries to sync in this batch
            batch_size: Number of concurrent store operations per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        if not self._consensus:
            return SyncResult(
                source="consensus",
                nodes_synced=0,
                nodes_updated=0,
                nodes_skipped=0,
                relationships_created=0,
                duration_ms=0,
                errors=["ConsensusMemory not connected"],
            )

        start_time = time.time()
        ws_id = workspace_id or self.workspace_id
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        relationships_created = 0
        errors: list[str] = []

        try:
            # Build query with since filter
            query = """
                SELECT id, topic, conclusion, strength, confidence,
                       participating_agents, agreeing_agents, domain, tags,
                       timestamp, supersedes, metadata
                FROM consensus_records
            """
            params: list[Any] = []

            if since:
                query += " WHERE timestamp >= ?"
                params.append(since)

            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)

            if hasattr(self._consensus, "_store") and self._consensus._store:
                with self._consensus._store.connection() as conn:
                    cursor = conn.execute(query, params)
                    rows = cursor.fetchall()

                from aragora.utils.json_helpers import safe_json_loads

                # Collect all requests for batch processing (avoids N+1 pattern)
                requests: list[IngestionRequest] = []
                for row in rows:
                    try:
                        record_id = row[0]
                        topic = row[1]
                        conclusion = row[2]
                        strength = row[3]
                        confidence = row[4]
                        domain = row[7]
                        tags_json = row[8]
                        supersedes = row[10]
                        metadata_json = row[11]

                        tags: list[str] = safe_json_loads(tags_json, [])
                        metadata: dict[str, Any] = safe_json_loads(metadata_json, {})

                        request = IngestionRequest(
                            content=f"{topic}: {conclusion}",
                            workspace_id=ws_id,
                            source_type=KnowledgeSource.CONSENSUS,
                            debate_id=record_id,
                            node_type="consensus",
                            confidence=confidence,
                            tier="slow",
                            topics=tags,
                            metadata={
                                "consensus_id": record_id,
                                "strength": strength,
                                "domain": domain,
                                "original_metadata": metadata,
                            },
                        )

                        if supersedes:
                            request.derived_from = [f"cs_{supersedes}"]

                        requests.append(request)

                    except (
                        RuntimeError,
                        ValueError,
                        KeyError,
                        IndexError,
                        json.JSONDecodeError,
                    ) as e:  # noqa: BLE001 - adapter isolation
                        nodes_skipped += 1
                        logger.warning(
                            "Failed to create request for consensus record %s: %s", row[0], e
                        )
                        errors.append(f"consensus:{row[0]}: request creation failed")

                # Batch store all requests using concurrent processing
                if requests:
                    synced, updated, skipped, rels, batch_errors = await self._batch_store(
                        requests, batch_size=batch_size
                    )
                    nodes_synced += synced
                    nodes_updated += updated
                    nodes_skipped += skipped
                    relationships_created += rels
                    errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to query consensus records: %s", e)
            errors.append("consensus:query: query failed")

        return SyncResult(
            source="consensus",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=relationships_created,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def sync_facts_incremental(
        self,
        workspace_id: str | None = None,
        since: str | None = None,
        limit: int = 1000,
        batch_size: int = 50,
    ) -> SyncResult:
        """
        Handler-compatible incremental sync from FactStore.

        Uses the internally connected _facts store. Supports incremental
        sync via the `since` parameter.

        Args:
            workspace_id: Override workspace ID for this sync
            since: ISO timestamp to sync from (incremental)
            limit: Maximum entries to sync in this batch
            batch_size: Number of concurrent store operations per batch

        Returns:
            SyncResult with counts of synced/updated/skipped nodes
        """
        from aragora.knowledge.mound.types import (
            IngestionRequest,
            KnowledgeSource,
            SyncResult,
        )

        self._ensure_initialized()

        if not self._facts:
            return SyncResult(
                source="facts",
                nodes_synced=0,
                nodes_updated=0,
                nodes_skipped=0,
                relationships_created=0,
                duration_ms=0,
                errors=["FactStore not connected"],
            )

        start_time = time.time()
        ws_id = workspace_id or self.workspace_id
        nodes_synced = 0
        nodes_updated = 0
        nodes_skipped = 0
        relationships_created = 0
        errors: list[str] = []

        try:
            if hasattr(self._facts, "query_facts"):
                from datetime import datetime as dt
                from aragora.knowledge.types import FactFilters

                # Parse since timestamp for incremental sync
                created_after = None
                if since:
                    try:
                        created_after = dt.fromisoformat(since.replace("Z", "+00:00"))
                    except ValueError:
                        pass  # Not a valid timestamp

                filters = FactFilters(
                    workspace_id=ws_id,
                    limit=limit,
                    created_after=created_after,
                )
                all_facts = self._facts.query_facts(query="", filters=filters)

                # Collect all requests for batch processing (avoids N+1 pattern)
                requests: list[IngestionRequest] = []
                for fact in all_facts:
                    try:
                        request = IngestionRequest(
                            content=fact.statement,
                            workspace_id=ws_id,
                            source_type=KnowledgeSource.FACT,
                            document_id=fact.source_documents[0] if fact.source_documents else None,
                            node_type="fact",
                            confidence=fact.confidence,
                            tier="slow",
                            topics=fact.topics,
                            metadata={
                                "fact_id": fact.id,
                                "validation_status": (
                                    fact.validation_status.value
                                    if hasattr(fact.validation_status, "value")
                                    else str(fact.validation_status)
                                ),
                                "evidence_ids": fact.evidence_ids,
                                "source_documents": fact.source_documents,
                            },
                        )
                        requests.append(request)

                    except (RuntimeError, ValueError, AttributeError, KeyError) as e:  # noqa: BLE001 - adapter isolation
                        nodes_skipped += 1
                        logger.warning("Failed to create request for fact %s: %s", fact.id, e)
                        errors.append(f"facts:{fact.id}: request creation failed")

                # Batch store all requests using concurrent processing
                if requests:
                    synced, updated, skipped, rels, batch_errors = await self._batch_store(
                        requests, batch_size=batch_size
                    )
                    nodes_synced += synced
                    nodes_updated += updated
                    nodes_skipped += skipped
                    relationships_created += rels
                    errors.extend(batch_errors)

        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to query facts: %s", e)
            errors.append("facts:query: query failed")

        return SyncResult(
            source="facts",
            nodes_synced=nodes_synced,
            nodes_updated=nodes_updated,
            nodes_skipped=nodes_skipped,
            relationships_created=relationships_created,
            duration_ms=int((time.time() - start_time) * 1000),
            errors=errors,
        )

    async def connect_memory_stores(
        self,
        continuum: ContinuumMemory | None = None,
        consensus: ConsensusMemory | None = None,
        facts: FactStore | None = None,
        evidence: EvidenceStore | None = None,
        critique: CritiqueStore | None = None,
    ) -> dict[str, bool]:
        """
        Connect memory stores for use with incremental sync methods.

        Args:
            continuum: ContinuumMemory instance
            consensus: ConsensusMemory instance
            facts: FactStore instance
            evidence: EvidenceStore instance
            critique: CritiqueStore instance

        Returns:
            Dict mapping store name to connection status
        """
        status = {}

        if continuum:
            self._continuum = continuum
            status["continuum"] = True

        if consensus:
            self._consensus = consensus
            status["consensus"] = True

        if facts:
            self._facts = facts
            status["facts"] = True

        if evidence:
            self._evidence = evidence
            status["evidence"] = True

        if critique:
            self._critique = critique
            status["critique"] = True

        logger.info(
            "Connected %d memory stores to Knowledge Mound",
            len(status),
        )

        return status

    def get_connected_stores(self) -> list[str]:
        """Get list of connected memory store names."""
        connected = []
        if self._continuum:
            connected.append("continuum")
        if self._consensus:
            connected.append("consensus")
        if self._facts:
            connected.append("facts")
        if self._evidence:
            connected.append("evidence")
        if self._critique:
            connected.append("critique")
        return connected
