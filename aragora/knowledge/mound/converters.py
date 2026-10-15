"""
Knowledge Mound Converters - Type conversion helpers.

These functions convert between internal storage types and the unified
KnowledgeItem/KnowledgeLink types used by the facade API.
"""

from datetime import datetime
from typing import Any

from aragora.knowledge.mound.types import (
    ConfidenceLevel,
    KnowledgeItem,
    KnowledgeLink,
    KnowledgeSource,
    RelationshipType,
)


def node_to_item(node: Any) -> KnowledgeItem:
    """Convert KnowledgeNode to KnowledgeItem."""
    return KnowledgeItem(
        id=node.id,
        content=node.content,
        source=KnowledgeSource.FACT,
        source_id=node.id,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=node.created_at,
        updated_at=node.updated_at,
        metadata=node.metadata,
        importance=node.confidence,
    )


def relationship_to_link(rel: Any) -> KnowledgeLink:
    """Convert KnowledgeRelationship to KnowledgeLink."""
    return KnowledgeLink(
        id=rel.id,
        source_id=rel.from_node_id,
        target_id=rel.to_node_id,
        relationship=RelationshipType(rel.relationship_type),
        confidence=rel.strength,
        created_at=rel.created_at,
        metadata=rel.metadata,
    )


def continuum_to_item(entry: Any) -> KnowledgeItem:
    """Convert ContinuumMemory entry to KnowledgeItem."""
    return KnowledgeItem(
        id=f"cm_{entry.id}",
        content=entry.content,
        source=KnowledgeSource.CONTINUUM,
        source_id=entry.id,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=datetime.fromisoformat(entry.created_at),
        updated_at=datetime.fromisoformat(entry.last_updated),
        metadata={"tier": entry.tier.value},
        importance=entry.importance,
    )


def consensus_to_item(entry: Any) -> KnowledgeItem:
    """Convert ConsensusMemory entry to KnowledgeItem."""
    return KnowledgeItem(
        id=f"cs_{entry.id}",
        content=getattr(entry, "final_claim", None) or entry.topic,
        source=KnowledgeSource.CONSENSUS,
        source_id=entry.id,
        confidence=ConfidenceLevel.HIGH,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        metadata={"debate_id": getattr(entry, "debate_id", None)},
        importance=getattr(entry, "confidence", 0.5),
    )


def fact_to_item(fact: Any) -> KnowledgeItem:
    """Convert Fact to KnowledgeItem."""
    return KnowledgeItem(
        id=f"fc_{fact.id}",
        content=fact.statement,
        source=KnowledgeSource.FACT,
        source_id=fact.id,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=fact.created_at,
        updated_at=fact.updated_at or fact.created_at,
        metadata={"evidence_ids": fact.evidence_ids},
        importance=fact.confidence,
    )


def vector_result_to_item(result: Any) -> KnowledgeItem:
    """Convert vector search result to KnowledgeItem."""
    return KnowledgeItem(
        id=f"vc_{result.id}",
        content=result.content,
        source=KnowledgeSource.VECTOR,
        source_id=result.id,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        metadata=result.metadata or {},
        importance=getattr(result, "score", 0.5),
    )


def evidence_to_item(evidence: Any) -> KnowledgeItem:
    """Convert EvidenceSnippet to KnowledgeItem."""
    return KnowledgeItem(
        id=f"ev_{evidence.id}",
        content=evidence.content,
        source=KnowledgeSource.EVIDENCE,
        source_id=evidence.id,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=getattr(evidence, "created_at", datetime.now()),
        updated_at=getattr(evidence, "updated_at", datetime.now()),
        metadata={
            "source_url": getattr(evidence, "source_url", None),
            "debate_id": getattr(evidence, "debate_id", None),
            "agent_id": getattr(evidence, "agent_id", None),
        },
        importance=getattr(evidence, "quality_score", 0.5),
    )


def critique_to_item(pattern: Any) -> KnowledgeItem:
    """Convert CritiquePattern to KnowledgeItem."""
    content = getattr(pattern, "pattern", "") or getattr(pattern, "content", "")
    return KnowledgeItem(
        id=f"cr_{pattern.id}",
        content=content,
        source=KnowledgeSource.CRITIQUE,
        source_id=pattern.id,
        confidence=ConfidenceLevel.MEDIUM,
        created_at=getattr(pattern, "created_at", datetime.now()),
        updated_at=getattr(pattern, "updated_at", datetime.now()),
        metadata={
            "success_count": getattr(pattern, "success_count", 0),
            "agent_name": getattr(pattern, "agent_name", None),
        },
        importance=getattr(pattern, "success_rate", 0.5),
    )
