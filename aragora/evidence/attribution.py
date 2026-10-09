"""
Source Attribution Chain - Reputation scoring and cross-debate tracking.

Extends the provenance system with:
- Source reputation tracking based on verification history
- Cross-debate attribution chains
- Reputation scoring algorithms (decay, weighted, confidence-based)
- Attribution verification with reputation updates

Works alongside aragora/reasoning/provenance.py which provides:
- ProvenanceChain for individual debate provenance
- CitationGraph for citation dependencies
- MerkleTree for batch verification
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class VerificationOutcome(str, Enum):
    """Outcome of evidence verification."""

    VERIFIED = "verified"  # Evidence confirmed accurate
    PARTIALLY_VERIFIED = "partial"  # Some claims verified, some not
    UNVERIFIED = "unverified"  # Could not verify (neutral)
    CONTESTED = "contested"  # Disputed by other evidence
    REFUTED = "refuted"  # Evidence shown to be incorrect


class ReputationTier(str, Enum):
    """Source reputation tiers."""

    AUTHORITATIVE = "authoritative"  # >= 0.85
    RELIABLE = "reliable"  # >= 0.70
    STANDARD = "standard"  # >= 0.50
    UNCERTAIN = "uncertain"  # >= 0.30
    UNRELIABLE = "unreliable"  # < 0.30

    @classmethod
    def from_score(cls, score: float) -> ReputationTier:
        """Classify score into reputation tier."""
        if score >= 0.85:
            return cls.AUTHORITATIVE
        elif score >= 0.70:
            return cls.RELIABLE
        elif score >= 0.50:
            return cls.STANDARD
        elif score >= 0.30:
            return cls.UNCERTAIN
        else:
            return cls.UNRELIABLE


@dataclass
class VerificationRecord:
    """Record of a single verification event."""

    record_id: str
    source_id: str
    debate_id: str
    outcome: VerificationOutcome
    confidence: float = 1.0  # Confidence in this verification
    timestamp: datetime = field(default_factory=datetime.now)
    verifier_type: str = "system"  # system, agent, user
    verifier_id: str | None = None
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "record_id": self.record_id,
            "source_id": self.source_id,
            "debate_id": self.debate_id,
            "outcome": self.outcome.value,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
            "verifier_type": self.verifier_type,
            "verifier_id": self.verifier_id,
            "notes": self.notes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VerificationRecord:
        """Deserialize from dictionary."""
        return cls(
            record_id=data["record_id"],
            source_id=data["source_id"],
            debate_id=data["debate_id"],
            outcome=VerificationOutcome(data["outcome"]),
            confidence=data.get("confidence", 1.0),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            verifier_type=data.get("verifier_type", "system"),
            verifier_id=data.get("verifier_id"),
            notes=data.get("notes", ""),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SourceReputation:
    """Reputation profile for an evidence source."""

    source_id: str
    source_type: str  # "agent", "api", "web", "academic", etc.

    # Core metrics
    reputation_score: float = 0.5  # 0-1 overall reputation
    verification_count: int = 0
    verified_count: int = 0
    refuted_count: int = 0
    contested_count: int = 0

    # Time-weighted metrics
    recent_score: float = 0.5  # Score based on recent verifications
    trend: float = 0.0  # -1 to 1, negative = declining

    # Timestamps
    first_seen: datetime = field(default_factory=datetime.now)
    last_updated: datetime = field(default_factory=datetime.now)
    debate_count: int = 0  # Number of debates this source appeared in

    # History tracking
    score_history: list[tuple[datetime, float]] = field(default_factory=list)

    # Additional metadata (e.g., tracking debates)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tier(self) -> ReputationTier:
        """Get reputation tier."""
        return ReputationTier.from_score(self.reputation_score)

    @property
    def verification_rate(self) -> float:
        """Fraction of verifications that confirmed the source."""
        if self.verification_count == 0:
            return 0.5  # Neutral for new sources
        return self.verified_count / self.verification_count

    @property
    def refutation_rate(self) -> float:
        """Fraction of verifications that refuted the source."""
        if self.verification_count == 0:
            return 0.0
        return self.refuted_count / self.verification_count

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        # Convert debates set to list for JSON serialization
        metadata_for_json = dict(self.metadata)
        if "debates" in metadata_for_json:
            metadata_for_json["debates"] = list(metadata_for_json["debates"])

        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "reputation_score": self.reputation_score,
            "recent_score": self.recent_score,
            "tier": self.tier.value,
            "trend": self.trend,
            "verification_count": self.verification_count,
            "verified_count": self.verified_count,
            "refuted_count": self.refuted_count,
            "contested_count": self.contested_count,
            "verification_rate": self.verification_rate,
            "refutation_rate": self.refutation_rate,
            "first_seen": self.first_seen.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "debate_count": self.debate_count,
            "score_history": [(ts.isoformat(), score) for ts, score in self.score_history[-10:]],
            "metadata": metadata_for_json,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceReputation:
        """Deserialize from dictionary."""
        # Convert debates list back to set
        metadata = data.get("metadata", {})
        if "debates" in metadata:
            metadata["debates"] = set(metadata["debates"])

        rep = cls(
            source_id=data["source_id"],
            source_type=data["source_type"],
            reputation_score=data.get("reputation_score", 0.5),
            recent_score=data.get("recent_score", 0.5),
            trend=data.get("trend", 0.0),
            verification_count=data.get("verification_count", 0),
            verified_count=data.get("verified_count", 0),
            refuted_count=data.get("refuted_count", 0),
            contested_count=data.get("contested_count", 0),
            first_seen=datetime.fromisoformat(data["first_seen"]),
            last_updated=datetime.fromisoformat(data["last_updated"]),
            debate_count=data.get("debate_count", 0),
            metadata=metadata,
        )
        # Restore score history
        if "score_history" in data:
            rep.score_history = [
                (datetime.fromisoformat(ts), score) for ts, score in data["score_history"]
            ]
        return rep


class ReputationScorer:
    """Algorithms for computing source reputation scores."""

    # Outcome weights for reputation impact
    OUTCOME_WEIGHTS = {
        VerificationOutcome.VERIFIED: 0.15,  # Positive impact
        VerificationOutcome.PARTIALLY_VERIFIED: 0.05,
        VerificationOutcome.UNVERIFIED: 0.0,  # Neutral
        VerificationOutcome.CONTESTED: -0.05,
        VerificationOutcome.REFUTED: -0.20,  # Negative impact
    }

    # Time decay parameters
    DECAY_HALF_LIFE_DAYS = 30  # Half-life for time decay
    RECENT_WINDOW_DAYS = 7  # Window for "recent" calculations

    def __init__(
        self,
        decay_half_life: float = 30.0,
        recent_window: float = 7.0,
        min_verifications_for_trend: int = 3,
    ):
        """Initialize scorer.

        Args:
            decay_half_life: Days for time decay half-life
            recent_window: Days for recent score window
            min_verifications_for_trend: Minimum verifications before computing trend
        """
        self.decay_half_life = decay_half_life
        self.recent_window = recent_window
        self.min_verifications_for_trend = min_verifications_for_trend

    def compute_score(
        self,
        verifications: list[VerificationRecord],
        current_score: float = 0.5,
    ) -> tuple[float, float, float]:
        """Compute reputation score from verification history.

        Returns:
            Tuple of (overall_score, recent_score, trend)
        """
        if not verifications:
            return current_score, current_score, 0.0

        now = datetime.now()

        # Time-weighted score
        total_weight = 0.0
        weighted_impact = 0.0
        recent_impacts = []

        for v in verifications:
            # Time decay factor
            age_days = (now - v.timestamp).total_seconds() / 86400
            decay = 2 ** (-age_days / self.decay_half_life)

            # Weight by confidence and decay
            weight = v.confidence * decay
            total_weight += weight

            # Impact from outcome
            impact = self.OUTCOME_WEIGHTS.get(v.outcome, 0.0)
            weighted_impact += impact * weight

            # Track recent verifications
            if age_days <= self.recent_window:
                recent_impacts.append((v.confidence, impact))

        # Overall score: start from base and adjust
        if total_weight > 0:
            adjustment = weighted_impact / total_weight
            overall_score = max(0.0, min(1.0, current_score + adjustment))
        else:
            overall_score = current_score

        # Recent score
        if recent_impacts:
            recent_total = sum(c for c, _ in recent_impacts)
            if recent_total > 0:
                recent_adjustment = sum(c * i for c, i in recent_impacts) / recent_total
                recent_score = max(0.0, min(1.0, 0.5 + recent_adjustment))
            else:
                recent_score = overall_score
        else:
            recent_score = overall_score

        # Trend: compare recent to overall
        trend = 0.0
        if len(verifications) >= self.min_verifications_for_trend:
            trend = recent_score - overall_score
            # Clamp to [-1, 1]
            trend = max(-1.0, min(1.0, trend * 2))

        return overall_score, recent_score, trend

    def compute_incremental_update(
        self,
        reputation: SourceReputation,
        verification: VerificationRecord,
    ) -> SourceReputation:
        """Update reputation incrementally with a new verification.

        More efficient than recomputing from full history.
        """
        # Update counters
        reputation.verification_count += 1

        if verification.outcome == VerificationOutcome.VERIFIED:
            reputation.verified_count += 1
        elif verification.outcome == VerificationOutcome.REFUTED:
            reputation.refuted_count += 1
        elif verification.outcome == VerificationOutcome.CONTESTED:
            reputation.contested_count += 1

        # Incremental score update
        impact = self.OUTCOME_WEIGHTS.get(verification.outcome, 0.0)
        impact *= verification.confidence

        # Exponential moving average for smooth updates
        alpha = 0.1  # Smoothing factor
        new_score = reputation.reputation_score + alpha * impact
        reputation.reputation_score = max(0.0, min(1.0, new_score))

        # Update recent score (simple moving average)
        reputation.recent_score = reputation.recent_score * 0.9 + new_score * 0.1
        reputation.recent_score = max(0.0, min(1.0, reputation.recent_score))

        # Update trend
        reputation.trend = (reputation.recent_score - reputation.reputation_score) * 2
        reputation.trend = max(-1.0, min(1.0, reputation.trend))

        # Track history
        reputation.score_history.append((datetime.now(), reputation.reputation_score))

        # Keep history bounded
        if len(reputation.score_history) > 100:
            reputation.score_history = reputation.score_history[-100:]

        reputation.last_updated = datetime.now()

        return reputation


class SourceReputationManager:
    """Manages source reputations across debates."""

    def __init__(self, scorer: ReputationScorer | None = None):
        """Initialize manager.

        Args:
            scorer: ReputationScorer instance for computing scores
        """
        self.scorer = scorer or ReputationScorer()
        self.reputations: dict[str, SourceReputation] = {}
        self.verifications: dict[str, list[VerificationRecord]] = defaultdict(list)
        self.debate_sources: dict[str, set] = defaultdict(set)  # debate_id -> source_ids

    def get_reputation(self, source_id: str) -> SourceReputation | None:
        """Get reputation for a source."""
        return self.reputations.get(source_id)

    def get_or_create_reputation(
        self,
        source_id: str,
        source_type: str = "unknown",
    ) -> SourceReputation:
        """Get or create reputation for a source."""
        if source_id not in self.reputations:
            self.reputations[source_id] = SourceReputation(
                source_id=source_id,
                source_type=source_type,
            )
        return self.reputations[source_id]

    def record_verification(
        self,
        record_id: str,
        source_id: str,
        debate_id: str,
        outcome: VerificationOutcome,
        confidence: float = 1.0,
        verifier_type: str = "system",
        verifier_id: str | None = None,
        notes: str = "",
        source_type: str = "unknown",
    ) -> VerificationRecord:
        """Record a verification and update reputation.

        Args:
            record_id: ID of the provenance record being verified
            source_id: Source identifier
            debate_id: ID of the debate
            outcome: Verification outcome
            confidence: Confidence in this verification
            verifier_type: Type of verifier
            verifier_id: ID of the verifier
            notes: Additional notes
            source_type: Type of source for new sources

        Returns:
            The verification record
        """
        verification = VerificationRecord(
            record_id=record_id,
            source_id=source_id,
            debate_id=debate_id,
            outcome=outcome,
            confidence=confidence,
            verifier_type=verifier_type,
            verifier_id=verifier_id,
            notes=notes,
        )

        # Store verification
        self.verifications[source_id].append(verification)

        # Track debate participation
        self.debate_sources[debate_id].add(source_id)

        # Update reputation
        reputation = self.get_or_create_reputation(source_id, source_type)

        # Check if this is a new debate for this source
        debates_set = reputation.metadata.get("debates")
        if debates_set is None:
            debates_set = set()
            reputation.metadata["debates"] = debates_set

        if debate_id not in debates_set:
            reputation.debate_count += 1
            debates_set.add(debate_id)

        # Incremental update
        self.scorer.compute_incremental_update(reputation, verification)

        logger.debug(
            "Recorded %s verification for source %s, new score: %.3f",
            outcome.value,
            source_id,
            reputation.reputation_score,
        )

        return verification

    def recompute_reputation(self, source_id: str) -> SourceReputation | None:
        """Recompute reputation from full history."""
        if source_id not in self.verifications:
            return None

        reputation = self.get_or_create_reputation(source_id)
        verifications = self.verifications[source_id]

        # Recompute counters
        reputation.verification_count = len(verifications)
        reputation.verified_count = sum(
            1 for v in verifications if v.outcome == VerificationOutcome.VERIFIED
        )
        reputation.refuted_count = sum(
            1 for v in verifications if v.outcome == VerificationOutcome.REFUTED
        )
        reputation.contested_count = sum(
            1 for v in verifications if v.outcome == VerificationOutcome.CONTESTED
        )

        # Recompute scores
        overall, recent, trend = self.scorer.compute_score(
            verifications,
            current_score=0.5,  # Reset to neutral base
        )

        reputation.reputation_score = overall
        reputation.recent_score = recent
        reputation.trend = trend
        reputation.last_updated = datetime.now()

        return reputation

    def get_source_history(
        self,
        source_id: str,
        limit: int = 50,
    ) -> list[VerificationRecord]:
        """Get verification history for a source."""
        history = self.verifications.get(source_id, [])
        return sorted(history, key=lambda v: v.timestamp, reverse=True)[:limit]

    def get_debate_sources(self, debate_id: str) -> list[SourceReputation]:
        """Get reputations for all sources in a debate."""
        source_ids = self.debate_sources.get(debate_id, set())
        return [self.reputations[sid] for sid in source_ids if sid in self.reputations]

    def get_top_sources(
        self,
        source_type: str | None = None,
        min_verifications: int = 1,
        limit: int = 10,
    ) -> list[SourceReputation]:
        """Get top-rated sources.

        Args:
            source_type: Filter by source type
            min_verifications: Minimum verification count
            limit: Maximum results

        Returns:
            List of SourceReputation sorted by score
        """
        filtered = [
            rep
            for rep in self.reputations.values()
            if rep.verification_count >= min_verifications
            and (source_type is None or rep.source_type == source_type)
        ]

        return sorted(filtered, key=lambda r: r.reputation_score, reverse=True)[:limit]

    def get_unreliable_sources(
        self,
        threshold: float = 0.3,
        min_verifications: int = 3,
    ) -> list[SourceReputation]:
        """Get sources below reliability threshold."""
        return [
            rep
            for rep in self.reputations.values()
            if rep.reputation_score < threshold and rep.verification_count >= min_verifications
        ]

    def export_state(self) -> dict[str, Any]:
        """Export manager state for persistence."""
        return {
            "reputations": {sid: rep.to_dict() for sid, rep in self.reputations.items()},
            "verifications": {
                sid: [v.to_dict() for v in vlist] for sid, vlist in self.verifications.items()
            },
            "debate_sources": {did: list(sources) for did, sources in self.debate_sources.items()},
            "exported_at": datetime.now().isoformat(),
        }

    def import_state(self, data: dict[str, Any]) -> None:
        """Import manager state from persistence."""
        # Import reputations
        for sid, rep_data in data.get("reputations", {}).items():
            self.reputations[sid] = SourceReputation.from_dict(rep_data)

        # Import verifications
        for sid, vlist in data.get("verifications", {}).items():
            self.verifications[sid] = [VerificationRecord.from_dict(v) for v in vlist]

        # Import debate sources
        for did, sources in data.get("debate_sources", {}).items():
            self.debate_sources[did] = set(sources)

        logger.info(
            "Imported %s reputations, %s verifications",
            len(self.reputations),
            sum(len(v) for v in self.verifications.values()),
        )


@dataclass
class AttributionChainEntry:
    """Entry in the cross-debate attribution chain."""

    evidence_id: str
    source_id: str
    debate_id: str
    content_hash: str
    reputation_at_use: float  # Source reputation when this evidence was used
    timestamp: datetime = field(default_factory=datetime.now)
    verification_outcome: VerificationOutcome | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "debate_id": self.debate_id,
            "content_hash": self.content_hash,
            "reputation_at_use": self.reputation_at_use,
            "timestamp": self.timestamp.isoformat(),
            "verification_outcome": (
                self.verification_outcome.value if self.verification_outcome else None
            ),
            "metadata": self.metadata,
        }


class AttributionChain:
    """Cross-debate attribution chain for evidence tracking."""

    def __init__(self, reputation_manager: SourceReputationManager | None = None):
        """Initialize attribution chain.

        Args:
            reputation_manager: SourceReputationManager for reputation lookups
        """
        self.reputation_manager = reputation_manager or SourceReputationManager()
        self.entries: list[AttributionChainEntry] = []
        self.by_evidence: dict[str, list[AttributionChainEntry]] = defaultdict(list)
        self.by_source: dict[str, list[AttributionChainEntry]] = defaultdict(list)
        self.by_debate: dict[str, list[AttributionChainEntry]] = defaultdict(list)

    def add_entry(
        self,
        evidence_id: str,
        source_id: str,
        debate_id: str,
        content: str,
        source_type: str = "unknown",
        metadata: dict[str, Any] | None = None,
    ) -> AttributionChainEntry:
        """Add evidence to the attribution chain.

        Args:
            evidence_id: Unique evidence identifier
            source_id: Source identifier
            debate_id: Debate where this evidence is used
            content: Evidence content (for hashing)
            source_type: Type of source
            metadata: Additional metadata

        Returns:
            The created entry
        """
        # Get current reputation
        reputation = self.reputation_manager.get_or_create_reputation(source_id, source_type)

        # Compute content hash
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        entry = AttributionChainEntry(
            evidence_id=evidence_id,
            source_id=source_id,
            debate_id=debate_id,
            content_hash=content_hash,
            reputation_at_use=reputation.reputation_score,
            metadata=metadata or {},
        )

        self.entries.append(entry)
        self.by_evidence[evidence_id].append(entry)
        self.by_source[source_id].append(entry)
        self.by_debate[debate_id].append(entry)

        return entry

    def record_verification(
        self,
        evidence_id: str,
        outcome: VerificationOutcome,
        confidence: float = 1.0,
        verifier_type: str = "system",
        verifier_id: str | None = None,
    ) -> VerificationRecord | None:
        """Record verification outcome for evidence in the chain.

        Updates both the chain entry and the source reputation.
        """
        entries = self.by_evidence.get(evidence_id, [])
        if not entries:
            logger.warning("No attribution entries found for evidence %s", evidence_id)
            return None

        # Use most recent entry
        entry = entries[-1]
        entry.verification_outcome = outcome

        # Record in reputation manager
        return self.reputation_manager.record_verification(
            record_id=evidence_id,
            source_id=entry.source_id,
            debate_id=entry.debate_id,
            outcome=outcome,
            confidence=confidence,
            verifier_type=verifier_type,
            verifier_id=verifier_id,
        )

    def get_evidence_chain(self, evidence_id: str) -> list[AttributionChainEntry]:
        """Get full chain for an evidence item across debates."""
        return sorted(self.by_evidence.get(evidence_id, []), key=lambda e: e.timestamp)

    def get_source_chain(self, source_id: str) -> list[AttributionChainEntry]:
        """Get all evidence from a source across debates."""
        return sorted(self.by_source.get(source_id, []), key=lambda e: e.timestamp)

    def get_debate_attributions(self, debate_id: str) -> list[AttributionChainEntry]:
        """Get all attributions for a debate."""
        return self.by_debate.get(debate_id, [])

    def compute_debate_reliability(self, debate_id: str) -> dict[str, Any]:
        """Compute overall reliability metrics for a debate.

        Returns metrics based on source reputations of evidence used.
        """
        entries = self.by_debate.get(debate_id, [])
        if not entries:
            return {
                "debate_id": debate_id,
                "evidence_count": 0,
                "avg_reputation": 0.5,
                "min_reputation": 0.5,
                "verified_count": 0,
                "reliability_score": 0.5,
            }

        reputations = [e.reputation_at_use for e in entries]
        verified = sum(1 for e in entries if e.verification_outcome == VerificationOutcome.VERIFIED)

        avg_rep = sum(reputations) / len(reputations)
        min_rep = min(reputations)

        # Reliability score: weighted average considering verification
        verification_rate = verified / len(entries) if entries else 0
        reliability = (avg_rep * 0.6) + (verification_rate * 0.4)

        return {
            "debate_id": debate_id,
            "evidence_count": len(entries),
            "avg_reputation": avg_rep,
            "min_reputation": min_rep,
            "verified_count": verified,
            "reliability_score": reliability,
        }

    def find_reused_evidence(
        self,
        min_uses: int = 2,
    ) -> dict[str, list[AttributionChainEntry]]:
        """Find evidence that has been reused across debates."""
        return {
            eid: entries for eid, entries in self.by_evidence.items() if len(entries) >= min_uses
        }

    def export_chain(self) -> dict[str, Any]:
        """Export chain state for persistence."""
        return {
            "entries": [e.to_dict() for e in self.entries],
            "reputation_state": self.reputation_manager.export_state(),
            "exported_at": datetime.now().isoformat(),
        }


__all__ = [
    "VerificationOutcome",
    "ReputationTier",
    "VerificationRecord",
    "SourceReputation",
    "ReputationScorer",
    "SourceReputationManager",
    "AttributionChainEntry",
    "AttributionChain",
]
