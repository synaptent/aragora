"""
Core types for the Knowledge Base module.

Defines the data structures for facts, validation status,
and related concepts used throughout the knowledge system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ValidationStatus(Enum):
    """Validation status of a fact in the knowledge base.

    Facts progress through validation stages as more agents
    verify them and consensus is reached.
    """

    UNVERIFIED = "unverified"  # Initial state, no verification
    CONTESTED = "contested"  # Agents disagree on validity
    MAJORITY_AGREED = "majority_agreed"  # Simple majority consensus
    BYZANTINE_AGREED = "byzantine_agreed"  # Byzantine fault-tolerant consensus
    FORMALLY_PROVEN = "formally_proven"  # Verified via formal methods (Z3/Lean)


class FactRelationType(Enum):
    """Types of relationships between facts."""

    SUPPORTS = "supports"  # Fact A provides evidence for Fact B
    CONTRADICTS = "contradicts"  # Facts are mutually exclusive
    SUPERSEDES = "supersedes"  # Fact A replaces/updates Fact B
    IMPLIES = "implies"  # Fact A logically implies Fact B
    RELATED_TO = "related_to"  # General topical relationship


@dataclass
class Fact:
    """A verified factual claim from the knowledge base.

    Facts are extracted from documents and verified through
    multi-agent debate. They link to evidence and can be
    related to other facts.

    Attributes:
        id: Unique identifier
        statement: The factual claim as natural language
        confidence: Aggregated confidence score (0-1)
        evidence_ids: Links to EvidenceStore entries
        consensus_proof_id: Byzantine verification proof ID if verified
        source_documents: Document IDs this fact was extracted from
        workspace_id: Workspace this fact belongs to
        validation_status: Current verification state
        topics: Extracted topics for categorization
        metadata: Additional structured data
        created_at: When fact was first recorded
        updated_at: When fact was last modified
        superseded_by: ID of fact that supersedes this one
        org_id: Owning organization; None means unassigned (quarantined
            from every org-scoped caller). Deliberately left out of to_dict().
    """

    id: str
    statement: str
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    consensus_proof_id: str | None = None
    source_documents: list[str] = field(default_factory=list)
    workspace_id: str = ""
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    superseded_by: str | None = None
    org_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert fact to dictionary for serialization."""
        return {
            "id": self.id,
            "statement": self.statement,
            "confidence": self.confidence,
            "evidence_ids": self.evidence_ids,
            "consensus_proof_id": self.consensus_proof_id,
            "source_documents": self.source_documents,
            "workspace_id": self.workspace_id,
            "validation_status": self.validation_status.value,
            "topics": self.topics,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "superseded_by": self.superseded_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        """Create fact from dictionary."""
        return cls(
            id=data["id"],
            statement=data["statement"],
            confidence=data.get("confidence", 0.5),
            evidence_ids=data.get("evidence_ids", []),
            consensus_proof_id=data.get("consensus_proof_id"),
            source_documents=data.get("source_documents", []),
            workspace_id=data.get("workspace_id", ""),
            validation_status=ValidationStatus(data.get("validation_status", "unverified")),
            topics=data.get("topics", []),
            metadata=data.get("metadata", {}),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("created_at"), str)
                else data.get("created_at", datetime.now())
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"])
                if isinstance(data.get("updated_at"), str)
                else data.get("updated_at", datetime.now())
            ),
            superseded_by=data.get("superseded_by"),
        )

    @property
    def is_verified(self) -> bool:
        """Check if fact has been verified through any consensus mechanism."""
        return self.validation_status in (
            ValidationStatus.MAJORITY_AGREED,
            ValidationStatus.BYZANTINE_AGREED,
            ValidationStatus.FORMALLY_PROVEN,
        )

    @property
    def is_active(self) -> bool:
        """Check if fact is still active (not superseded)."""
        return self.superseded_by is None


@dataclass
class FactRelation:
    """A relationship between two facts.

    Captures how facts relate to each other, enabling
    knowledge graph construction and contradiction detection.
    """

    id: str
    source_fact_id: str
    target_fact_id: str
    relation_type: FactRelationType
    confidence: float = 0.5
    created_by: str = ""  # Agent or user who established relation
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert relation to dictionary."""
        return {
            "id": self.id,
            "source_fact_id": self.source_fact_id,
            "target_fact_id": self.target_fact_id,
            "relation_type": self.relation_type.value,
            "confidence": self.confidence,
            "created_by": self.created_by,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FactRelation:
        """Create relation from dictionary."""
        return cls(
            id=data["id"],
            source_fact_id=data["source_fact_id"],
            target_fact_id=data["target_fact_id"],
            relation_type=FactRelationType(data["relation_type"]),
            confidence=data.get("confidence", 0.5),
            created_by=data.get("created_by", ""),
            metadata=data.get("metadata", {}),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("created_at"), str)
                else data.get("created_at", datetime.now())
            ),
        )


@dataclass
class FactFilters:
    """Filters for querying facts.

    Used to narrow down fact searches by various criteria.
    """

    workspace_id: str | None = None
    topics: list[str] | None = None
    min_confidence: float = 0.0
    validation_status: ValidationStatus | None = None
    include_superseded: bool = False
    source_documents: list[str] | None = None
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: int = 100
    offset: int = 0
    org_id: str | None = None


@dataclass
class VerificationResult:
    """Result of verifying a fact through multi-agent consensus.

    Captures the outcome of asking multiple agents to verify
    a factual claim.
    """

    fact_id: str
    success: bool
    new_status: ValidationStatus
    confidence: float
    agent_votes: dict[str, bool]  # agent_name -> agreed
    consensus_proof_id: str | None = None
    dissenting_reasons: list[str] = field(default_factory=list)
    verification_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "fact_id": self.fact_id,
            "success": self.success,
            "new_status": self.new_status.value,
            "confidence": self.confidence,
            "agent_votes": self.agent_votes,
            "consensus_proof_id": self.consensus_proof_id,
            "dissenting_reasons": self.dissenting_reasons,
            "verification_time_ms": self.verification_time_ms,
            "metadata": self.metadata,
        }


@dataclass
class QueryResult:
    """Result of a natural language query against the knowledge base.

    Contains the answer, supporting facts, and confidence metrics.
    """

    answer: str
    facts: list[Fact]
    evidence_ids: list[str]
    confidence: float
    query: str
    workspace_id: str
    processing_time_ms: int = 0
    agent_contributions: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "answer": self.answer,
            "facts": [f.to_dict() for f in self.facts],
            "evidence_ids": self.evidence_ids,
            "confidence": self.confidence,
            "query": self.query,
            "workspace_id": self.workspace_id,
            "processing_time_ms": self.processing_time_ms,
            "agent_contributions": self.agent_contributions,
            "metadata": self.metadata,
        }
