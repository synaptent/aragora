"""Knowledge Mound type definitions and data classes.

Extracted from mound_core.py to reduce file size.
Contains core dataclasses for KnowledgeNode, ProvenanceChain, relationships, etc.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.knowledge.types import Fact

from aragora.knowledge.types import ValidationStatus
from aragora.memory.tier_manager import MemoryTier


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


# Metadata key of the organization stamp the knowledge pipeline writes.
ORG_STAMP_KEY = "org_id"


def content_dedup_hash(content: str, metadata: dict[str, Any] | None = None) -> str:
    """SHA-256 hex digest that content-hash deduplication compares.

    Workspaces are shared across organizations, so content stamped with an
    organization hashes together with that stamp: identical text from two
    organizations stays two items, each keeping its own stamp. Unstamped
    content hashes exactly as before.
    """
    org_id = metadata.get(ORG_STAMP_KEY) if isinstance(metadata, dict) else None
    keyed = f"{org_id}\x00{content}" if org_id else content
    return hashlib.sha256(keyed.encode()).hexdigest()


# Type alias for node types
NodeType = Literal[
    "fact",
    "claim",
    "memory",
    "evidence",
    "consensus",
    "entity",
    "idea_concept",
    "idea_observation",
    "idea_question",
    "idea_hypothesis",
    "idea_insight",
    "idea_evidence",
    "idea_assumption",
    "idea_constraint",
    "idea_cluster",
    "goal_goal",
    "goal_principle",
    "goal_strategy",
    "goal_milestone",
    "goal_metric",
    "goal_risk",
]

# Type alias for relationship types
RelationshipType = Literal[
    "supports",
    "contradicts",
    "derived_from",
    "related_to",
    "supersedes",
    "inspires",
    "refines",
    "challenges",
    "exemplifies",
]


class ProvenanceType(Enum):
    """Source types for knowledge provenance."""

    DOCUMENT = "document"  # Extracted from document
    DEBATE = "debate"  # Result of multi-agent debate
    USER = "user"  # User-provided knowledge
    AGENT = "agent"  # Agent-generated inference
    INFERENCE = "inference"  # Derived from other knowledge
    MIGRATION = "migration"  # Migrated from legacy system


@dataclass
class ProvenanceChain:
    """
    Tracks the origin and transformations of knowledge.

    Provides full traceability for audit and compliance, recording
    where knowledge came from and how it has been modified.
    """

    source_type: ProvenanceType
    source_id: str  # ID of the source (document, debate, user, etc.)
    agent_id: str | None = None
    debate_id: str | None = None
    document_id: str | None = None
    user_id: str | None = None
    transformations: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def add_transformation(
        self,
        transform_type: str,
        agent_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Record a transformation to this knowledge."""
        self.transformations.append(
            {
                "type": transform_type,
                "agent_id": agent_id,
                "details": details or {},
                "timestamp": datetime.now().isoformat(),
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_type": self.source_type.value,
            "source_id": self.source_id,
            "agent_id": self.agent_id,
            "debate_id": self.debate_id,
            "document_id": self.document_id,
            "user_id": self.user_id,
            "transformations": self.transformations,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProvenanceChain:
        """Create from dictionary."""
        return cls(
            source_type=ProvenanceType(data["source_type"]),
            source_id=data["source_id"],
            agent_id=data.get("agent_id"),
            debate_id=data.get("debate_id"),
            document_id=data.get("document_id"),
            user_id=data.get("user_id"),
            transformations=data.get("transformations", []),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("created_at"), str)
                else datetime.now()
            ),
        )


@dataclass
class KnowledgeNode:
    """
    A node in the knowledge mound (fact, claim, memory, evidence, consensus).

    Central data structure unifying the various memory systems. Each node
    can have relationships with other nodes, forming a knowledge graph.
    """

    id: str = ""
    node_type: NodeType = "fact"
    content: str = ""
    confidence: float = 0.5
    provenance: ProvenanceChain | None = None
    tier: MemoryTier = MemoryTier.SLOW
    workspace_id: str = ""

    # Surprise-based learning (from ContinuumMemory)
    surprise_score: float = 0.0
    update_count: int = 1
    consolidation_score: float = 0.0

    # Validation (from FactStore)
    validation_status: ValidationStatus = ValidationStatus.UNVERIFIED
    consensus_proof_id: str | None = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # Additional metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    topics: list[str] = field(default_factory=list)
    embedding: list[float] | None = None

    # Graph relationships (stored separately, referenced here for convenience)
    supports: list[str] = field(default_factory=list)  # Node IDs this supports
    contradicts: list[str] = field(default_factory=list)  # Node IDs this contradicts
    derived_from: list[str] = field(default_factory=list)  # Source node IDs

    def __post_init__(self) -> None:
        """Generate ID if not provided."""
        if not self.id:
            self.id = f"kn_{uuid.uuid4().hex[:16]}"

    @property
    def content_hash(self) -> str:
        """Hash of content (and organization stamp) for deduplication."""
        return content_dedup_hash(self.content, self.metadata)[:32]

    @property
    def is_verified(self) -> bool:
        """Check if node has been verified."""
        return self.validation_status in (
            ValidationStatus.MAJORITY_AGREED,
            ValidationStatus.BYZANTINE_AGREED,
            ValidationStatus.FORMALLY_PROVEN,
        )

    @property
    def stability_score(self) -> float:
        """Inverse of surprise - how predictable this pattern is."""
        return 1.0 - self.surprise_score

    def should_promote(self) -> bool:
        """Check if this node should be promoted to a faster tier."""
        if self.tier == MemoryTier.FAST:
            return False
        # High surprise score indicates this knowledge is actively relevant
        return self.surprise_score > 0.7 and self.update_count > 5

    def should_demote(self) -> bool:
        """Check if this node should be demoted to a slower tier."""
        if self.tier == MemoryTier.GLACIAL:
            return False
        # Low surprise + high consolidation = stable knowledge
        return self.stability_score > 0.8 and self.consolidation_score > 0.5

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "node_type": self.node_type,
            "content": self.content,
            "confidence": self.confidence,
            "provenance": self.provenance.to_dict() if self.provenance else None,
            "tier": self.tier.value,
            "workspace_id": self.workspace_id,
            "surprise_score": self.surprise_score,
            "update_count": self.update_count,
            "consolidation_score": self.consolidation_score,
            "validation_status": self.validation_status.value,
            "consensus_proof_id": self.consensus_proof_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "topics": self.topics,
            "supports": self.supports,
            "contradicts": self.contradicts,
            "derived_from": self.derived_from,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeNode:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            node_type=data.get("node_type", "fact"),
            content=data["content"],
            confidence=data.get("confidence", 0.5),
            provenance=(
                ProvenanceChain.from_dict(data["provenance"]) if data.get("provenance") else None
            ),
            tier=MemoryTier(data.get("tier", "slow")),
            workspace_id=data.get("workspace_id", ""),
            surprise_score=data.get("surprise_score", 0.0),
            update_count=data.get("update_count", 1),
            consolidation_score=data.get("consolidation_score", 0.0),
            validation_status=ValidationStatus(data.get("validation_status", "unverified")),
            consensus_proof_id=data.get("consensus_proof_id"),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("created_at"), str)
                else datetime.now()
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"])
                if isinstance(data.get("updated_at"), str)
                else datetime.now()
            ),
            metadata=data.get("metadata", {}),
            topics=data.get("topics", []),
            supports=data.get("supports", []),
            contradicts=data.get("contradicts", []),
            derived_from=data.get("derived_from", []),
        )

    @classmethod
    def from_fact(cls, fact: Fact, workspace_id: str = "") -> KnowledgeNode:
        """Create KnowledgeNode from existing Fact."""
        return cls(
            id=f"kn_{fact.id}",
            node_type="fact",
            content=fact.statement,
            confidence=fact.confidence,
            provenance=ProvenanceChain(
                source_type=ProvenanceType.DOCUMENT,
                source_id=fact.source_documents[0] if fact.source_documents else "",
                document_id=fact.source_documents[0] if fact.source_documents else None,
            ),
            workspace_id=workspace_id or fact.workspace_id,
            validation_status=fact.validation_status,
            consensus_proof_id=fact.consensus_proof_id,
            created_at=fact.created_at,
            updated_at=fact.updated_at,
            metadata=fact.metadata,
            topics=fact.topics,
        )


@dataclass
class KnowledgeRelationship:
    """
    A relationship between two knowledge nodes.

    Enables graph traversal and knowledge inference.
    """

    id: str = ""
    from_node_id: str = ""
    to_node_id: str = ""
    relationship_type: RelationshipType = "related_to"
    strength: float = 1.0
    created_by: str = ""  # Agent or user who established relation
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self) -> None:
        """Generate ID if not provided."""
        if not self.id:
            self.id = f"kr_{uuid.uuid4().hex[:16]}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "from_node_id": self.from_node_id,
            "to_node_id": self.to_node_id,
            "relationship_type": self.relationship_type,
            "strength": self.strength,
            "created_by": self.created_by,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeRelationship:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            from_node_id=data["from_node_id"],
            to_node_id=data["to_node_id"],
            relationship_type=data.get("relationship_type", "related_to"),
            strength=data.get("strength", 1.0),
            created_by=data.get("created_by", ""),
            metadata=data.get("metadata", {}),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if isinstance(data.get("created_at"), str)
                else datetime.now()
            ),
        )


@dataclass
class KnowledgeQueryResult:
    """Result of querying the knowledge mound."""

    nodes: list[KnowledgeNode]
    total_count: int
    query: str
    processing_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "NodeType",
    "RelationshipType",
    "ProvenanceType",
    "ProvenanceChain",
    "KnowledgeNode",
    "KnowledgeRelationship",
    "KnowledgeQueryResult",
    "_to_iso_string",
    "_to_enum_value",
]
