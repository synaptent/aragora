"""Evidence collection, verification, and persistence module."""

from aragora.evidence.attribution import (
    AttributionChain,
    AttributionChainEntry,
    ReputationScorer,
    ReputationTier,
    SourceReputation,
    SourceReputationManager,
    VerificationOutcome,
    VerificationRecord,
)
from aragora.evidence.collector import (
    EvidenceCollector,
    EvidencePack,
    EvidenceSnippet,
)
from aragora.evidence.metadata import (
    EnrichedMetadata,
    MetadataEnricher,
    Provenance,
    SourceType,
    enrich_evidence_snippet,
)
from aragora.evidence.quality import (
    QualityContext,
    QualityFilter,
    QualityScorer,
    QualityScores,
    QualityTier,
    score_evidence_snippet,
)
from aragora.evidence.store import (
    EvidenceStore,
    InMemoryEvidenceStore,
)

# Import EvidenceType and Evidence from reasoning where they're defined
from aragora.reasoning.claims import EvidenceType
from aragora.reasoning.source_evidence import Evidence

__all__ = [
    # Collector
    "EvidenceCollector",
    "EvidenceSnippet",
    "EvidencePack",
    # Metadata
    "EnrichedMetadata",
    "MetadataEnricher",
    "Provenance",
    "SourceType",
    "enrich_evidence_snippet",
    # Quality
    "QualityContext",
    "QualityFilter",
    "QualityScorer",
    "QualityScores",
    "QualityTier",
    "score_evidence_snippet",
    # Store
    "EvidenceStore",
    "InMemoryEvidenceStore",
    # Attribution
    "AttributionChain",
    "AttributionChainEntry",
    "ReputationScorer",
    "ReputationTier",
    "SourceReputation",
    "SourceReputationManager",
    "VerificationOutcome",
    "VerificationRecord",
    # External
    "Evidence",
    "EvidenceType",
]
