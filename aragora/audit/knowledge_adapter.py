"""
Knowledge Pipeline Integration for Document Auditor.

Connects the audit system with the knowledge pipeline:
- Loads facts from knowledge base to inform audits
- Stores audit findings as verified facts
- Uses knowledge queries to cross-reference findings
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.audit.document_auditor import AuditFinding, AuditSession
    from aragora.knowledge import InMemoryEmbeddingService, InMemoryFactStore

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeAuditConfig:
    """Configuration for knowledge-audit integration."""

    # Enable knowledge base enrichment
    enrich_with_facts: bool = True

    # Store findings as facts
    store_findings_as_facts: bool = True

    # Fact confidence threshold for findings
    min_finding_confidence: float = 0.7

    # Query knowledge base for cross-references
    enable_cross_reference: bool = True

    # Workspace isolation
    workspace_id: str = "default"


@dataclass
class EnrichedChunk:
    """Document chunk enriched with knowledge base facts."""

    chunk_id: str
    document_id: str
    content: str
    sequence: int

    # Knowledge enrichment
    related_facts: list[dict[str, Any]] = field(default_factory=list)
    fact_count: int = 0
    relevance_score: float = 0.0


class AuditKnowledgeAdapter:
    """
    Adapts the audit system to use the knowledge pipeline.

    Responsibilities:
    1. Enrich document chunks with related facts before audit
    2. Convert audit findings to facts for storage
    3. Query knowledge base for cross-document validation
    """

    def __init__(self, config: KnowledgeAuditConfig | None = None):
        self.config = config or KnowledgeAuditConfig()
        self._initialized = False
        self._fact_store: InMemoryFactStore | None = None
        self._embedding_service: InMemoryEmbeddingService | None = None

    async def initialize(self) -> bool:
        """Initialize knowledge pipeline connection."""
        try:
            from aragora.knowledge import (
                InMemoryEmbeddingService,
                InMemoryFactStore,
            )

            self._fact_store = InMemoryFactStore()
            self._embedding_service = InMemoryEmbeddingService()
            self._initialized = True
            logger.info("Audit knowledge adapter initialized")
            return True

        except ImportError as e:
            logger.warning("Knowledge pipeline not available: %s", e)
            self._initialized = False
            return False

    async def enrich_chunks(
        self,
        chunks: list[dict[str, Any]],
        workspace_id: str | None = None,
        *,
        org_id: str | None = None,
    ) -> list[EnrichedChunk]:
        """
        Enrich document chunks with related facts from knowledge base.

        Args:
            chunks: Document chunks to enrich
            workspace_id: Workspace ID for fact lookup
            org_id: Organization from verified authentication; only its facts
                are read. Without it, OrgScopeRequiredError is raised.

        Returns:
            Enriched chunks with related facts
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized or not self.config.enrich_with_facts:
            # Return unenriched chunks
            return [
                EnrichedChunk(
                    chunk_id=c.get("id", ""),
                    document_id=c.get("document_id", ""),
                    content=c.get("content", ""),
                    sequence=c.get("sequence", 0),
                )
                for c in chunks
            ]

        from aragora.knowledge.embeddings import chunk_namespace

        workspace = workspace_id or self.config.workspace_id
        enriched = []

        for chunk in chunks:
            chunk_content = chunk.get("content", "")
            chunk_id = chunk.get("id", "")
            doc_id = chunk.get("document_id", "")

            # Search for related facts
            try:
                if self._embedding_service is None:
                    raise RuntimeError("Embedding service not initialized")
                related = await self._embedding_service.hybrid_search(
                    query=chunk_content[:500],  # First 500 chars for query
                    workspace_id=chunk_namespace(workspace, org_id, require_org=True),
                    limit=5,
                )

                # Also get facts with matching topics
                from aragora.knowledge.types import FactFilters

                if self._fact_store is None:
                    raise RuntimeError("Fact store not initialized")
                facts = self._fact_store.list_facts(
                    FactFilters(workspace_id=workspace, limit=10, org_id=org_id or None)
                )

                # Filter for relevance (simple keyword matching)
                relevant_facts: list[dict[str, Any]] = []
                chunk_lower = chunk_content.lower()
                for fact in facts:
                    # Check if any topic appears in chunk
                    for topic in fact.topics:
                        if topic.lower() in chunk_lower:
                            relevant_facts.append(
                                {
                                    "id": fact.id,
                                    "statement": fact.statement,
                                    "confidence": fact.confidence,
                                    "topics": fact.topics,
                                }
                            )
                            break

                enriched_chunk = EnrichedChunk(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    content=chunk_content,
                    sequence=chunk.get("sequence", 0),
                    related_facts=relevant_facts,
                    fact_count=len(relevant_facts),
                    relevance_score=(
                        max((r.score for r in related), default=0.0) if related else 0.0
                    ),
                )
                enriched.append(enriched_chunk)

            except (ValueError, RuntimeError, OSError) as e:
                logger.warning("Failed to enrich chunk %s: %s", chunk_id, e)
                enriched.append(
                    EnrichedChunk(
                        chunk_id=chunk_id,
                        document_id=doc_id,
                        content=chunk_content,
                        sequence=chunk.get("sequence", 0),
                    )
                )

        logger.info("Enriched %s chunks with facts", len(enriched))
        return enriched

    async def store_finding_as_fact(
        self,
        finding: AuditFinding,
        session: AuditSession,
    ) -> str | None:
        """
        Store an audit finding as a verified fact.

        Args:
            finding: Audit finding to store
            session: Audit session for context; the fact belongs to its
                ``org_id``. A session without one raises OrgScopeRequiredError.

        Returns:
            Fact ID if stored, None if skipped
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized or not self.config.store_findings_as_facts:
            return None

        # Only store high-confidence findings
        if finding.confidence < self.config.min_finding_confidence:
            return None

        # Skip disputed findings
        if len(finding.disputed_by) > len(finding.confirmed_by):
            return None

        try:
            from aragora.knowledge.types import Fact, ValidationStatus

            # Determine validation status based on confirmation
            if len(finding.confirmed_by) >= 2:
                status = ValidationStatus.BYZANTINE_AGREED
            elif len(finding.confirmed_by) >= 1:
                status = ValidationStatus.MAJORITY_AGREED
            else:
                status = ValidationStatus.UNVERIFIED

            # Create fact from finding
            fact = Fact(
                id=f"audit_fact_{finding.id}",
                statement=f"{finding.title}: {finding.description}",
                confidence=finding.confidence,
                evidence_ids=[finding.id],
                source_documents=[finding.document_id],
                topics=[finding.category, finding.audit_type.value, finding.severity.value],
                workspace_id=self.config.workspace_id,
                validation_status=status,
                created_at=datetime.now(timezone.utc),
            )

            # Store in fact store
            if self._fact_store is None:
                raise RuntimeError("Fact store not initialized")
            self._fact_store.add_fact(
                statement=fact.statement,
                evidence_ids=fact.evidence_ids,
                source_documents=fact.source_documents,
                confidence=fact.confidence,
                workspace_id=fact.workspace_id,
                topics=fact.topics,
                org_id=session.org_id or None,
            )

            logger.debug("Stored finding %s as fact %s", finding.id, fact.id)
            return fact.id

        except (ValueError, RuntimeError, OSError) as e:
            logger.warning("Failed to store finding as fact: %s", e)
            return None

    async def store_session_findings(
        self,
        session: AuditSession,
    ) -> int:
        """
        Store all findings from an audit session as facts.

        Args:
            session: Completed audit session

        Returns:
            Number of findings stored as facts
        """
        stored_count = 0

        for finding in session.findings:
            fact_id = await self.store_finding_as_fact(finding, session)
            if fact_id:
                stored_count += 1

        logger.info("Stored %s/%s findings as facts", stored_count, len(session.findings))
        return stored_count

    async def query_for_cross_references(
        self,
        finding: AuditFinding,
        workspace_id: str | None = None,
        *,
        org_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Query knowledge base for cross-references to a finding.

        Args:
            finding: Finding to cross-reference
            workspace_id: Workspace to search
            org_id: Organization from verified authentication; only its facts
                are read. Without it, OrgScopeRequiredError is raised.

        Returns:
            List of related facts/chunks
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized or not self.config.enable_cross_reference:
            return []

        from aragora.knowledge.embeddings import chunk_namespace

        workspace = workspace_id or self.config.workspace_id
        references: list[dict[str, Any]] = []

        try:
            # Search for similar content
            query = f"{finding.title} {finding.description}"
            if self._embedding_service is None:
                raise RuntimeError("Embedding service not initialized")
            results = await self._embedding_service.hybrid_search(
                query=query,
                workspace_id=chunk_namespace(workspace, org_id, require_org=True),
                limit=5,
            )

            for result in results:
                if result.document_id != finding.document_id:
                    references.append(
                        {
                            "type": "chunk",
                            "document_id": result.document_id,
                            "chunk_id": result.chunk_id,
                            "score": result.score,
                            "preview": result.content[:200] if result.content else None,
                        }
                    )

            # Also search facts
            from aragora.knowledge.types import FactFilters

            if self._fact_store is None:
                raise RuntimeError("Fact store not initialized")
            facts = self._fact_store.query_facts(
                query=finding.title,
                filters=FactFilters(workspace_id=workspace, limit=5, org_id=org_id or None),
            )

            for fact in facts:
                if finding.document_id not in fact.source_documents:
                    references.append(
                        {
                            "type": "fact",
                            "fact_id": fact.id,
                            "statement": fact.statement,
                            "confidence": fact.confidence,
                            "sources": fact.source_documents,
                        }
                    )

        except (ValueError, RuntimeError, OSError) as e:
            logger.warning("Cross-reference query failed: %s", e)

        return references

    async def validate_finding_with_knowledge(
        self,
        finding: AuditFinding,
        workspace_id: str | None = None,
        *,
        org_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Validate a finding against the knowledge base.

        Checks if the finding contradicts or is supported by existing facts.

        Args:
            finding: Finding to validate
            workspace_id: Workspace to search
            org_id: Organization from verified authentication; only its facts
                are read. Without it, OrgScopeRequiredError is raised.

        Returns:
            Validation result with support/contradiction info
        """
        if not self._initialized:
            await self.initialize()

        if not self._initialized:
            return {"validated": False, "reason": "Knowledge base not available"}

        workspace = workspace_id or self.config.workspace_id

        try:
            # Search for related facts
            from aragora.knowledge.types import FactFilters

            if self._fact_store is None:
                raise RuntimeError("Fact store not initialized")
            facts = self._fact_store.query_facts(
                query=f"{finding.title} {finding.description}",
                filters=FactFilters(workspace_id=workspace, limit=10, org_id=org_id or None),
            )

            supporting: list[dict[str, Any]] = []
            contradicting: list[dict[str, Any]] = []

            for fact in facts:
                # Simple heuristic: high confidence facts from different docs might support
                if fact.confidence >= 0.8 and finding.document_id not in fact.source_documents:
                    # Check for keyword overlap
                    finding_words = set(finding.description.lower().split())
                    fact_words = set(fact.statement.lower().split())
                    overlap = len(finding_words & fact_words)

                    if overlap >= 3:
                        supporting.append(
                            {
                                "fact_id": fact.id,
                                "statement": fact.statement,
                                "confidence": fact.confidence,
                            }
                        )

            return {
                "validated": True,
                "supporting_facts": supporting,
                "contradicting_facts": contradicting,
                "support_score": len(supporting) * 0.1,
            }

        except (ValueError, RuntimeError, OSError) as e:
            logger.warning("Knowledge validation failed: %s", e)
            return {"validated": False, "reason": str(e)}


# Global adapter instance
_adapter: AuditKnowledgeAdapter | None = None


def get_audit_knowledge_adapter(
    config: KnowledgeAuditConfig | None = None,
) -> AuditKnowledgeAdapter:
    """Get or create global audit knowledge adapter."""
    global _adapter
    if _adapter is None:
        _adapter = AuditKnowledgeAdapter(config)
    return _adapter


__all__ = [
    "AuditKnowledgeAdapter",
    "KnowledgeAuditConfig",
    "EnrichedChunk",
    "get_audit_knowledge_adapter",
]
