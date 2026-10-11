"""
Consensus Memory - Persistent storage and retrieval of debate outcomes.

Stores historical debate results including:
- Consensus decisions and confidence levels
- Dissenting views and minority positions
- Topic/domain clustering for similarity search
- Decision evolution over time

Enables:
- Learning from past debates on similar topics
- Retrieving relevant dissenting views
- Tracking how consensus evolves
- Avoiding repeated debates on settled topics
"""

import hashlib
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.consensus_adapter import ConsensusAdapter

from aragora.config import DB_TIMEOUT_SECONDS
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.storage.base_store import SQLiteStore
from aragora.utils.cache import TTLCache, invalidate_cache
from aragora.utils.json_helpers import safe_json_loads

# Cache for KM similarity queries (5 min TTL, 1000 entries)
_km_consensus_cache: TTLCache[list] = TTLCache(maxsize=1000, ttl_seconds=300)

logger = logging.getLogger(__name__)

# LRU cache for consensus queries (5 min TTL, 2000 entries max)
# Using Any type to avoid forward reference issues with ConsensusRecord
_consensus_cache: TTLCache[Any] = TTLCache(maxsize=2000, ttl_seconds=300)
_dissents_cache: TTLCache[list] = TTLCache(maxsize=2000, ttl_seconds=300)

# Schema version for ConsensusMemory migrations
# v1: Initial schema (consensus + dissent tables)
# v2: Added verified_proofs table for formal verification results
CONSENSUS_SCHEMA_VERSION = 2


class ConsensusStrength(Enum):
    """Strength of consensus reached."""

    UNANIMOUS = "unanimous"  # All agents agreed
    STRONG = "strong"  # >80% agreement
    MODERATE = "moderate"  # 60-80% agreement
    WEAK = "weak"  # 50-60% agreement
    SPLIT = "split"  # No majority
    CONTESTED = "contested"  # Active disagreement


class DissentType(Enum):
    """Type of dissenting view."""

    MINOR_QUIBBLE = "minor_quibble"  # Small disagreement
    ALTERNATIVE_APPROACH = "alternative_approach"  # Different method, same goal
    FUNDAMENTAL_DISAGREEMENT = "fundamental_disagreement"  # Core disagreement
    EDGE_CASE_CONCERN = "edge_case_concern"  # Specific scenario concern
    RISK_WARNING = "risk_warning"  # Caution about approach
    ABSTENTION = "abstention"  # Agent declined to agree


@dataclass
class DissentRecord:
    """A recorded dissenting view from a debate."""

    id: str
    debate_id: str
    agent_id: str
    dissent_type: DissentType
    content: str
    reasoning: str
    confidence: float = 0.0
    acknowledged: bool = False  # Was this addressed by majority?
    rebuttal: str = ""  # Majority's rebuttal if any
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "debate_id": self.debate_id,
            "agent_id": self.agent_id,
            "dissent_type": self.dissent_type.value,
            "content": self.content,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "acknowledged": self.acknowledged,
            "rebuttal": self.rebuttal,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DissentRecord":
        try:
            dissent_type = DissentType(data.get("dissent_type", "minor_quibble"))
        except (ValueError, KeyError):
            dissent_type = DissentType.MINOR_QUIBBLE

        try:
            timestamp = datetime.fromisoformat(data["timestamp"])
        except (KeyError, ValueError, TypeError):
            timestamp = datetime.now()

        return cls(
            id=data.get("id", ""),
            debate_id=data.get("debate_id", ""),
            agent_id=data.get("agent_id", "unknown"),
            dissent_type=dissent_type,
            content=data.get("content", ""),
            reasoning=data.get("reasoning", ""),
            confidence=data.get("confidence", 0.0),
            acknowledged=data.get("acknowledged", False),
            rebuttal=data.get("rebuttal", ""),
            timestamp=timestamp,
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConsensusRecord:
    """A recorded consensus outcome from a debate."""

    id: str
    topic: str
    topic_hash: str  # For similarity matching
    conclusion: str
    strength: ConsensusStrength
    confidence: float

    # Participants
    participating_agents: list[str] = field(default_factory=list)
    agreeing_agents: list[str] = field(default_factory=list)
    dissenting_agents: list[str] = field(default_factory=list)

    # Details
    key_claims: list[str] = field(default_factory=list)
    supporting_evidence: list[str] = field(default_factory=list)
    dissent_ids: list[str] = field(default_factory=list)

    # Context
    domain: str = "general"
    tags: list[str] = field(default_factory=list)

    # Timing
    timestamp: datetime = field(default_factory=datetime.now)
    debate_duration_seconds: float = 0.0
    rounds: int = 0

    # Evolution
    supersedes: str | None = None  # ID of consensus this replaces
    superseded_by: str | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    def compute_agreement_ratio(self) -> float:
        """Compute the ratio of agreeing to total agents."""
        total = len(self.participating_agents)
        if total == 0:
            return 0.0
        return len(self.agreeing_agents) / total

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "topic_hash": self.topic_hash,
            "conclusion": self.conclusion,
            "strength": self.strength.value,
            "confidence": self.confidence,
            "participating_agents": self.participating_agents,
            "agreeing_agents": self.agreeing_agents,
            "dissenting_agents": self.dissenting_agents,
            "key_claims": self.key_claims,
            "supporting_evidence": self.supporting_evidence,
            "dissent_ids": self.dissent_ids,
            "domain": self.domain,
            "tags": self.tags,
            "timestamp": self.timestamp.isoformat(),
            "debate_duration_seconds": self.debate_duration_seconds,
            "rounds": self.rounds,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConsensusRecord":
        try:
            strength = ConsensusStrength(data.get("strength", "moderate"))
        except (ValueError, KeyError):
            strength = ConsensusStrength.MODERATE

        try:
            timestamp = datetime.fromisoformat(data["timestamp"])
        except (KeyError, ValueError, TypeError):
            timestamp = datetime.now()

        return cls(
            id=data.get("id", ""),
            topic=data.get("topic", ""),
            topic_hash=data.get("topic_hash", ""),
            conclusion=data.get("conclusion", ""),
            strength=strength,
            confidence=data.get("confidence", 0.0),
            participating_agents=data.get("participating_agents", []),
            agreeing_agents=data.get("agreeing_agents", []),
            dissenting_agents=data.get("dissenting_agents", []),
            key_claims=data.get("key_claims", []),
            supporting_evidence=data.get("supporting_evidence", []),
            dissent_ids=data.get("dissent_ids", []),
            domain=data.get("domain", "general"),
            tags=data.get("tags", []),
            timestamp=timestamp,
            debate_duration_seconds=data.get("debate_duration_seconds", 0.0),
            rounds=data.get("rounds", 0),
            supersedes=data.get("supersedes"),
            superseded_by=data.get("superseded_by"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SimilarDebate:
    """A similar past debate found in memory."""

    consensus: ConsensusRecord
    similarity_score: float
    dissents: list[DissentRecord]
    relevance_notes: str = ""

    @property
    def similarity(self) -> float:
        """Alias for similarity_score for backward compatibility."""
        return self.similarity_score


class ConsensusMemory(SQLiteStore):
    """
    Persistent storage for debate consensus and dissent.

    Uses SQLite for storage with optional embedding-based
    similarity search for finding related past debates.
    """

    SCHEMA_NAME = "consensus_memory"
    SCHEMA_VERSION = CONSENSUS_SCHEMA_VERSION

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS consensus (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            topic_hash TEXT NOT NULL,
            conclusion TEXT NOT NULL,
            strength TEXT NOT NULL,
            confidence REAL,
            domain TEXT,
            tags TEXT,
            timestamp TEXT,
            data TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dissent (
            id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            dissent_type TEXT NOT NULL,
            content TEXT NOT NULL,
            confidence REAL,
            timestamp TEXT,
            data TEXT NOT NULL,
            FOREIGN KEY (debate_id) REFERENCES consensus(id)
        );

        CREATE INDEX IF NOT EXISTS idx_consensus_topic_hash
        ON consensus(topic_hash);

        CREATE INDEX IF NOT EXISTS idx_consensus_domain
        ON consensus(domain);

        CREATE INDEX IF NOT EXISTS idx_dissent_debate
        ON dissent(debate_id);

        CREATE INDEX IF NOT EXISTS idx_dissent_type
        ON dissent(dissent_type);

        -- Optimized indices for common query patterns
        CREATE INDEX IF NOT EXISTS idx_consensus_confidence_ts
        ON consensus(confidence DESC, timestamp DESC);

        CREATE INDEX IF NOT EXISTS idx_dissent_timestamp
        ON dissent(timestamp DESC);

        -- Verified proofs table (added in v2)
        CREATE TABLE IF NOT EXISTS verified_proofs (
            id TEXT PRIMARY KEY,
            debate_id TEXT NOT NULL,
            proof_status TEXT NOT NULL,
            language TEXT,
            formal_statement TEXT,
            is_verified INTEGER DEFAULT 0,
            proof_hash TEXT,
            translation_time_ms REAL,
            proof_search_time_ms REAL,
            prover_version TEXT,
            error_message TEXT,
            timestamp TEXT NOT NULL,
            data TEXT NOT NULL,
            FOREIGN KEY (debate_id) REFERENCES consensus(id)
        );

        CREATE INDEX IF NOT EXISTS idx_verified_proofs_debate
        ON verified_proofs(debate_id);

        CREATE INDEX IF NOT EXISTS idx_verified_proofs_status
        ON verified_proofs(proof_status);

        CREATE INDEX IF NOT EXISTS idx_verified_proofs_verified
        ON verified_proofs(is_verified);
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        km_adapter: Optional["ConsensusAdapter"] = None,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.CONSENSUS_MEMORY)
        super().__init__(db_path, timeout=DB_TIMEOUT_SECONDS)

        # Optional Knowledge Mound adapter for bidirectional integration
        self._km_adapter: ConsensusAdapter | None = km_adapter

    def set_km_adapter(self, adapter: "ConsensusAdapter") -> None:
        """Set the Knowledge Mound adapter for bidirectional sync.

        Args:
            adapter: ConsensusAdapter instance for KM integration
        """
        self._km_adapter = adapter

    def query_km_for_similar_consensus(
        self,
        topic: str,
        limit: int = 5,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        """Query Knowledge Mound for similar consensus records (reverse flow).

        Uses TTL caching to avoid redundant queries for same topic.

        Args:
            topic: Topic to find similar consensus for
            limit: Maximum results
            min_confidence: Minimum confidence threshold

        Returns:
            List of similar consensus records from KM
        """
        if not self._km_adapter:
            return []

        # Generate cache key from topic hash + params
        topic_hash = self._hash_topic(topic)
        cache_key = f"{topic_hash}:{limit}:{min_confidence}"

        # Check cache first
        cached = _km_consensus_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            results = self._km_adapter.search_similar(
                topic=topic,
                limit=limit,
                min_confidence=min_confidence,
            )
            # Cache the results
            _km_consensus_cache.set(cache_key, results)
            return results
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.warning("Failed to query KM for similar consensus: %s", e)
            return []

    def _hash_topic(self, topic: str) -> str:
        """Create a hash for topic similarity matching."""
        # Normalize: lowercase, remove punctuation, sort words
        words = sorted(set(topic.lower().split()))
        normalized = " ".join(words)
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def store_consensus(
        self,
        topic: str,
        conclusion: str,
        strength: ConsensusStrength,
        confidence: float,
        participating_agents: list[str],
        agreeing_agents: list[str],
        dissenting_agents: list[str] | None = None,
        key_claims: list[str] | None = None,
        domain: str = "general",
        tags: list[str] | None = None,
        debate_duration: float = 0.0,
        rounds: int = 0,
        metadata: dict | None = None,
    ) -> ConsensusRecord:
        """Store a new consensus record."""

        record = ConsensusRecord(
            id=str(uuid.uuid4()),
            topic=topic,
            topic_hash=self._hash_topic(topic),
            conclusion=conclusion,
            strength=strength,
            confidence=confidence,
            participating_agents=participating_agents,
            agreeing_agents=agreeing_agents,
            dissenting_agents=dissenting_agents or [],
            key_claims=key_claims or [],
            domain=domain,
            tags=tags or [],
            debate_duration_seconds=debate_duration,
            rounds=rounds,
            metadata=metadata or {},
        )

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO consensus (id, topic, topic_hash, conclusion, strength,
                                       confidence, domain, tags, timestamp, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.topic,
                    record.topic_hash,
                    record.conclusion,
                    record.strength.value,
                    record.confidence,
                    record.domain,
                    json.dumps(record.tags),
                    record.timestamp.isoformat(),
                    json.dumps(record.to_dict()),
                ),
            )
            conn.commit()

        # Invalidate related caches so API returns fresh data
        invalidate_cache("consensus")
        _consensus_cache.clear()  # Clear LRU cache on write

        # Sync to Knowledge Mound if adapter is configured and confidence is high
        if self._km_adapter and confidence >= 0.7:
            try:
                self._km_adapter.store_consensus(record)
            except (ConnectionError, TimeoutError, OSError, RuntimeError, ValueError) as e:
                logger.debug("Failed to sync consensus to KM: %s", e)

        return record

    def store_dissent(
        self,
        debate_id: str,
        agent_id: str,
        dissent_type: DissentType,
        content: str,
        reasoning: str,
        confidence: float = 0.0,
        acknowledged: bool = False,
        rebuttal: str = "",
        metadata: dict | None = None,
    ) -> DissentRecord:
        """Store a dissenting view."""

        record = DissentRecord(
            id=str(uuid.uuid4()),
            debate_id=debate_id,
            agent_id=agent_id,
            dissent_type=dissent_type,
            content=content,
            reasoning=reasoning,
            confidence=confidence,
            acknowledged=acknowledged,
            rebuttal=rebuttal,
            metadata=metadata or {},
        )

        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO dissent (id, debate_id, agent_id, dissent_type,
                                    content, confidence, timestamp, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.debate_id,
                    record.agent_id,
                    record.dissent_type.value,
                    record.content,
                    record.confidence,
                    record.timestamp.isoformat(),
                    json.dumps(record.to_dict()),
                ),
            )

            # Update consensus record with dissent ID
            cursor.execute(
                "SELECT data FROM consensus WHERE id = ?",
                (debate_id,),
            )
            row = cursor.fetchone()
            if row:
                consensus_data: dict = safe_json_loads(row[0], {}, context=f"consensus:{debate_id}")
                consensus_data["dissent_ids"] = consensus_data.get("dissent_ids", []) + [record.id]
                cursor.execute(
                    "UPDATE consensus SET data = ? WHERE id = ?",
                    (json.dumps(consensus_data), debate_id),
                )

            conn.commit()

        # Invalidate related caches so API returns fresh data
        invalidate_cache("consensus")
        _consensus_cache.invalidate(f"consensus:{debate_id}")  # Invalidate specific consensus
        _dissents_cache.invalidate(f"dissents:{debate_id}")  # Invalidate dissents for this debate

        return record

    def update_cruxes(
        self,
        consensus_id: str,
        cruxes: list[dict],
    ) -> bool:
        """Attach belief cruxes to an existing consensus record.

        Cruxes are the key points of contention that drove the debate.
        Storing them enables future debates on similar topics to seed
        discussion around known areas of disagreement.

        Args:
            consensus_id: The ID of the consensus record to update
            cruxes: List of crux dicts with keys like 'claim', 'positions', 'resolution'

        Returns:
            True if update succeeded, False if consensus not found
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data FROM consensus WHERE id = ?",
                (consensus_id,),
            )
            row = cursor.fetchone()

            if not row:
                return False

            consensus_data: dict = safe_json_loads(row[0], {}, context=f"consensus:{consensus_id}")
            # Store up to 5 cruxes to avoid bloat
            consensus_data["belief_cruxes"] = cruxes[:5]

            cursor.execute(
                "UPDATE consensus SET data = ? WHERE id = ?",
                (json.dumps(consensus_data), consensus_id),
            )
            conn.commit()

        logger.debug("Updated consensus %s with %s cruxes", consensus_id, len(cruxes[:5]))
        return True

    def store_verified_proof(
        self,
        debate_id: str,
        proof_result: dict,
    ) -> str:
        """Store a formal verification result for a debate.

        Args:
            debate_id: The ID of the consensus/debate this proof relates to
            proof_result: Dict from FormalProofResult.to_dict() containing:
                - status: proof_found, proof_failed, translation_failed, etc.
                - language: z3_smt, lean4, etc.
                - formal_statement: The translated formal statement
                - is_verified: Whether the proof succeeded
                - proof_hash: Hash of the proof for deduplication
                - translation_time_ms, proof_search_time_ms: Timing info
                - prover_version: Version of the prover used
                - error_message: Any error message

        Returns:
            The ID of the stored proof record
        """
        proof_id = str(uuid.uuid4())
        timestamp = datetime.now().isoformat()

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO verified_proofs (
                    id, debate_id, proof_status, language, formal_statement,
                    is_verified, proof_hash, translation_time_ms, proof_search_time_ms,
                    prover_version, error_message, timestamp, data
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proof_id,
                    debate_id,
                    proof_result.get("status", "unknown"),
                    proof_result.get("language"),
                    proof_result.get("formal_statement"),
                    1 if proof_result.get("is_verified", False) else 0,
                    proof_result.get("proof_hash"),
                    proof_result.get("translation_time_ms"),
                    proof_result.get("proof_search_time_ms"),
                    proof_result.get("prover_version"),
                    proof_result.get("error_message"),
                    timestamp,
                    json.dumps(proof_result),
                ),
            )
            conn.commit()

        logger.debug(
            "Stored verified proof %s for debate %s status=%s verified=%s",
            proof_id,
            debate_id,
            proof_result.get("status"),
            proof_result.get("is_verified"),
        )

        # Invalidate related caches
        invalidate_cache("consensus")
        _consensus_cache.invalidate(f"consensus:{debate_id}")  # Invalidate specific consensus

        return proof_id

    def get_verified_proof(self, debate_id: str) -> dict | None:
        """Get the formal verification result for a debate.

        Args:
            debate_id: The debate/consensus ID

        Returns:
            The proof result dict if found, None otherwise
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT data FROM verified_proofs
                WHERE debate_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                (debate_id,),
            )
            row = cursor.fetchone()

        if row:
            return safe_json_loads(row[0], None, context=f"proof:{debate_id}")
        return None

    def list_verified_debates(
        self,
        verified_only: bool = True,
        limit: int = 50,
    ) -> list[dict]:
        """List debates with formal verification attempts.

        Args:
            verified_only: If True, only return successfully verified debates
            limit: Maximum number of results

        Returns:
            List of dicts with debate_id, proof_status, is_verified, timestamp
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            if verified_only:
                cursor.execute(
                    """
                    SELECT debate_id, proof_status, is_verified, language, timestamp
                    FROM verified_proofs
                    WHERE is_verified = 1
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cursor.execute(
                    """
                    SELECT debate_id, proof_status, is_verified, language, timestamp
                    FROM verified_proofs
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (limit,),
                )

            rows = cursor.fetchall()

        return [
            {
                "debate_id": row[0],
                "proof_status": row[1],
                "is_verified": bool(row[2]),
                "language": row[3],
                "timestamp": row[4],
            }
            for row in rows
        ]

    def get_consensus(self, consensus_id: str) -> ConsensusRecord | None:
        """Get a consensus record by ID.

        Uses LRU cache with 5-minute TTL to reduce database queries
        for frequently accessed consensus records.
        """
        # Check cache first
        cache_key = f"consensus:{consensus_id}"
        cached = _consensus_cache.get(cache_key)
        if cached is not None:
            return cached

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data FROM consensus WHERE id = ?", (consensus_id,))
            row = cursor.fetchone()

        if row:
            data: dict = safe_json_loads(row[0], {}, context=f"consensus:{consensus_id}")
            if data:
                record = ConsensusRecord.from_dict(data)
                _consensus_cache.set(cache_key, record)
                return record
        return None

    def get_dissents(self, debate_id: str) -> list[DissentRecord]:
        """Get all dissenting views for a debate.

        Uses LRU cache with 5-minute TTL to reduce database queries
        for frequently accessed dissent records.
        """
        # Check cache first
        cache_key = f"dissents:{debate_id}"
        cached = _dissents_cache.get(cache_key)
        if cached is not None:
            return cached

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data FROM dissent WHERE debate_id = ?",
                (debate_id,),
            )
            rows = cursor.fetchall()

        results: list[DissentRecord] = []
        for row in rows:
            data: dict = safe_json_loads(row[0], {}, context=f"dissent:debate={debate_id}")
            if data:
                results.append(DissentRecord.from_dict(data))

        # Cache the results
        _dissents_cache.set(cache_key, results)
        return results

    def delete_consensus(
        self,
        consensus_id: str,
        cascade_dissents: bool = True,
    ) -> bool:
        """Delete a consensus record and optionally its associated dissents.

        Used for rollback operations when a transaction fails.

        Args:
            consensus_id: ID of the consensus to delete
            cascade_dissents: If True, also delete associated dissent records

        Returns:
            True if the record was deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.cursor()

            # Check if record exists
            cursor.execute("SELECT 1 FROM consensus WHERE id = ?", (consensus_id,))
            if not cursor.fetchone():
                return False

            # Delete associated dissents first if cascading
            if cascade_dissents:
                cursor.execute("DELETE FROM dissent WHERE debate_id = ?", (consensus_id,))
                deleted_dissents = cursor.rowcount
                if deleted_dissents > 0:
                    logger.debug(
                        "[consensus] Deleted %d dissent records for %s",
                        deleted_dissents,
                        consensus_id,
                    )

            # Delete the consensus record
            cursor.execute("DELETE FROM consensus WHERE id = ?", (consensus_id,))
            conn.commit()

            # Invalidate relevant caches (clear all consensus/dissents caches)
            invalidate_cache("consensus")
            _consensus_cache.clear()
            _dissents_cache.clear()

            logger.debug("[consensus] Deleted consensus record: %s", consensus_id)
            return True

    def delete_dissent(self, dissent_id: str) -> bool:
        """Delete a single dissent record.

        Args:
            dissent_id: ID of the dissent to delete

        Returns:
            True if deleted, False if not found
        """
        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM dissent WHERE id = ?", (dissent_id,))
            conn.commit()

            if cursor.rowcount > 0:
                # Invalidate dissent caches
                invalidate_cache("consensus")
                _dissents_cache.clear()
                logger.debug("[consensus] Deleted dissent record: %s", dissent_id)
                return True
            return False

    def find_similar_debates(
        self,
        topic: str,
        domain: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 10,
    ) -> list[SimilarDebate]:
        """Find similar past debates on a topic.

        Optimized to batch-fetch dissents instead of N+1 queries.
        """

        topic_hash = self._hash_topic(topic)
        topic_words = set(topic.lower().split())

        query = """
            SELECT data FROM consensus
            WHERE confidence >= ?
        """
        params: list = [min_confidence]

        if domain:
            query += " AND domain = ?"
            params.append(domain)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit * 3)  # Get more for filtering

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()

        # Score similarity and collect qualifying consensus IDs
        scored_candidates: list[tuple[ConsensusRecord, float]] = []
        for row in rows:
            data: dict = safe_json_loads(
                row[0], {}, context=f"consensus:find_similar:{topic_hash[:8]}"
            )
            if not data:
                continue
            consensus = ConsensusRecord.from_dict(data)

            # Compute similarity (simple word overlap for now)
            consensus_words = set(consensus.topic.lower().split())
            if topic_words and consensus_words:
                intersection = len(topic_words & consensus_words)
                union = len(topic_words | consensus_words)
                similarity = intersection / union if union > 0 else 0.0
            else:
                similarity = 0.0

            # Boost exact hash match
            if consensus.topic_hash == topic_hash:
                similarity = 1.0

            if similarity > 0.1:  # Minimum threshold
                scored_candidates.append((consensus, similarity))

        # Batch-fetch all dissents in a single query (optimization)
        consensus_ids = [c.id for c, _ in scored_candidates]
        dissents_by_consensus = self._get_dissents_batch(consensus_ids)

        # Build final candidates with pre-fetched dissents
        candidates = [
            SimilarDebate(
                consensus=consensus,
                similarity_score=similarity,
                dissents=dissents_by_consensus.get(consensus.id, []),
            )
            for consensus, similarity in scored_candidates
        ]

        # Sort by similarity and limit
        candidates.sort(key=lambda x: -x.similarity_score)
        return candidates[:limit]

    def _get_dissents_batch(self, consensus_ids: list[str]) -> dict[str, list[DissentRecord]]:
        """Batch-fetch dissents for multiple consensus IDs.

        Optimization to avoid N+1 queries in find_similar_debates().

        Args:
            consensus_ids: List of consensus IDs to fetch dissents for

        Returns:
            Dict mapping consensus_id -> list of DissentRecords
        """
        if not consensus_ids:
            return {}

        # Build parameterized IN query
        placeholders = ",".join("?" * len(consensus_ids))
        query = f"""
            SELECT debate_id, data FROM dissent
            WHERE debate_id IN ({placeholders})
            ORDER BY timestamp DESC
        """  # parameterized query

        result: dict[str, list[DissentRecord]] = {cid: [] for cid in consensus_ids}

        try:
            with self.connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, consensus_ids)
                for row in cursor.fetchall():
                    debate_id = row[0]
                    data: dict = safe_json_loads(row[1], {}, context=f"dissent:batch:{debate_id}")
                    if data and debate_id in result:
                        result[debate_id].append(DissentRecord.from_dict(data))
        except sqlite3.Error as e:
            logger.exception("Failed to batch fetch dissents: %s", e)

        return result

    def find_relevant_dissent(
        self,
        topic: str,
        dissent_types: list[DissentType] | None = None,
        min_confidence: float = 0.0,
        limit: int = 10,
    ) -> list[DissentRecord]:
        """Find dissenting views relevant to a topic."""

        # First find similar debates
        similar = self.find_similar_debates(topic, limit=limit * 2)

        dissents = []
        for s in similar:
            for d in s.dissents:
                if d.confidence >= min_confidence:
                    if dissent_types is None or d.dissent_type in dissent_types:
                        dissents.append(d)

        # Sort by confidence
        dissents.sort(key=lambda x: -x.confidence)
        return dissents[:limit]

    def get_domain_consensus_history(
        self,
        domain: str,
        limit: int = 50,
    ) -> list[ConsensusRecord]:
        """Get consensus history for a domain."""

        with self.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT data FROM consensus
                WHERE domain = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (domain, limit),
            )
            rows = cursor.fetchall()

        results = []
        for row in rows:
            data: dict = safe_json_loads(row[0], {}, context=f"consensus:domain={domain}")
            if data:
                results.append(ConsensusRecord.from_dict(data))
        return results

    def supersede_consensus(
        self,
        old_consensus_id: str,
        new_topic: str,
        new_conclusion: str,
        **kwargs,
    ) -> ConsensusRecord:
        """Create a new consensus that supersedes an old one."""

        # Create new consensus
        new_record = self.store_consensus(
            topic=new_topic,
            conclusion=new_conclusion,
            metadata={"supersedes": old_consensus_id},
            **kwargs,
        )

        # Update old record
        with self.connection() as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT data FROM consensus WHERE id = ?",
                (old_consensus_id,),
            )
            row = cursor.fetchone()

            if row:
                old_data: dict = safe_json_loads(
                    row[0], {}, context=f"consensus:supersede:{old_consensus_id}"
                )
                old_data["superseded_by"] = new_record.id
                cursor.execute(
                    "UPDATE consensus SET data = ? WHERE id = ?",
                    (json.dumps(old_data), old_consensus_id),
                )

            conn.commit()

        return new_record

    def cleanup_old_records(
        self,
        max_age_days: int = 90,
        archive: bool = True,
    ) -> dict[str, Any]:
        """
        Clean up old consensus and dissent records.

        Args:
            max_age_days: Records older than this are cleaned up
            archive: If True, archive before deletion (archive table must exist)

        Returns:
            Dict with counts: {"archived": N, "deleted": N}
        """
        result: dict[str, Any] = {"archived": 0, "deleted": 0}
        cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()

        with self.connection() as conn:
            cursor = conn.cursor()

            # Check if archive table exists; create if needed
            # NOTE: Archive table schema matches main table schema (not extended columns)
            if archive:
                # Drop old archive tables if they have wrong schema (migration)
                # Check if consensus_archive has 'timestamp' column
                cursor.execute("PRAGMA table_info(consensus_archive)")
                columns = {row[1] for row in cursor.fetchall()}
                if columns and "timestamp" not in columns:
                    logger.info("Migrating consensus_archive table to new schema")
                    cursor.execute("DROP TABLE IF EXISTS consensus_archive")
                    cursor.execute("DROP TABLE IF EXISTS dissent_archive")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS consensus_archive (
                        id TEXT PRIMARY KEY,
                        topic TEXT NOT NULL,
                        topic_hash TEXT NOT NULL,
                        conclusion TEXT NOT NULL,
                        strength TEXT NOT NULL,
                        confidence REAL,
                        domain TEXT,
                        tags TEXT,
                        timestamp TEXT,
                        data TEXT NOT NULL,
                        archived_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS dissent_archive (
                        id TEXT PRIMARY KEY,
                        debate_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        dissent_type TEXT NOT NULL,
                        content TEXT NOT NULL,
                        confidence REAL,
                        timestamp TEXT,
                        data TEXT NOT NULL,
                        archived_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Archive old consensus records (select columns that exist in main table)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO consensus_archive
                        (id, topic, topic_hash, conclusion, strength, confidence,
                         domain, tags, timestamp, data)
                    SELECT id, topic, topic_hash, conclusion, strength, confidence,
                           domain, tags, timestamp, data
                    FROM consensus
                    WHERE datetime(timestamp) < datetime(?)
                """,
                    (cutoff,),
                )
                archived_consensus = cursor.rowcount

                # Archive old dissent records (select columns that exist in main table)
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO dissent_archive
                        (id, debate_id, agent_id, dissent_type, content, confidence, timestamp, data)
                    SELECT id, debate_id, agent_id, dissent_type, content, confidence, timestamp, data
                    FROM dissent
                    WHERE datetime(timestamp) < datetime(?)
                """,
                    (cutoff,),
                )
                archived_dissent = cursor.rowcount

                result["archived"] = archived_consensus + archived_dissent

            # Delete old records from main tables
            cursor.execute(
                "DELETE FROM consensus WHERE datetime(timestamp) < datetime(?)", (cutoff,)
            )
            deleted_consensus = cursor.rowcount

            cursor.execute("DELETE FROM dissent WHERE datetime(timestamp) < datetime(?)", (cutoff,))
            deleted_dissent = cursor.rowcount

            result["deleted"] = deleted_consensus + deleted_dissent

            conn.commit()

        logger.info(
            "Consensus cleanup: archived=%d, deleted=%d (cutoff=%d days)",
            result["archived"],
            result["deleted"],
            max_age_days,
        )

        return result

    def get_relevant_context(self, task: str) -> str:
        """Return formatted institutional knowledge for a debate topic.

        This method enables ConsensusMemory to be used directly as the
        ``cross_debate_memory`` source in :class:`ContextInitPhase`.  It
        queries past debates for the given *task* and returns a human-readable
        summary of conclusions and dissents that can be injected into a new
        debate's context.

        Args:
            task: The topic / task description for the upcoming debate.

        Returns:
            A formatted string with conclusions from similar past debates,
            or an empty string when nothing relevant is found.
        """
        similar = self.find_similar_debates(topic=task, min_confidence=0.3, limit=5)
        if not similar:
            return ""

        lines: list[str] = []
        for s in similar:
            conclusion_preview = s.consensus.conclusion[:200]
            lines.append(
                f"- [{s.consensus.strength.value}] {s.consensus.topic}: {conclusion_preview}"
            )
            for d in s.dissents[:2]:
                lines.append(f"  * Dissent ({d.dissent_type.value}): {d.content[:120]}")

        return "\n".join(lines)

    def get_statistics(self) -> dict[str, Any]:
        """Get statistics about stored consensus."""

        with self.connection() as conn:
            cursor = conn.cursor()

            stats = {}

            # Total counts
            cursor.execute("SELECT COUNT(*) FROM consensus")
            row = cursor.fetchone()
            stats["total_consensus"] = row[0] if row else 0

            cursor.execute("SELECT COUNT(*) FROM dissent")
            row = cursor.fetchone()
            stats["total_dissents"] = row[0] if row else 0

            # By strength
            cursor.execute("SELECT strength, COUNT(*) FROM consensus GROUP BY strength")
            stats["by_strength"] = dict(cursor.fetchall())

            # By domain
            cursor.execute(
                "SELECT domain, COUNT(*) FROM consensus GROUP BY domain ORDER BY COUNT(*) DESC LIMIT 10"
            )
            stats["by_domain"] = dict(cursor.fetchall())

            # By dissent type
            cursor.execute("SELECT dissent_type, COUNT(*) FROM dissent GROUP BY dissent_type")
            stats["by_dissent_type"] = dict(cursor.fetchall())

            # Average confidence
            cursor.execute("SELECT AVG(confidence) FROM consensus")
            row = cursor.fetchone()
            stats["avg_confidence"] = (row[0] if row else None) or 0.0

        return stats


class DissentRetriever:
    """
    Specialized retriever for finding relevant dissenting views.

    Helps debates benefit from past minority positions that
    may have been overlooked or become more relevant.
    """

    def __init__(self, memory: ConsensusMemory):
        self.memory = memory

    @staticmethod
    def _smart_truncate(text: str, max_chars: int) -> str:
        """Truncate text preserving sentence boundaries when possible."""
        if not text or len(text) <= max_chars:
            return text

        truncated = text[:max_chars]

        # Try to break at sentence boundary
        for i in range(len(truncated) - 1, int(max_chars * 0.5), -1):
            if truncated[i] in ".!?" and (i + 1 >= len(truncated) or truncated[i + 1] in " \n"):
                return text[: i + 1]

        # Break at word boundary
        if " " in truncated:
            last_space = truncated.rfind(" ")
            if last_space > max_chars * 0.7:
                return text[:last_space] + "..."

        return truncated + "..."

    def retrieve_for_new_debate(
        self,
        topic: str,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve relevant historical context for a new debate."""

        # Find similar past debates
        similar = self.memory.find_similar_debates(topic, domain=domain, limit=5)

        # Find relevant dissents
        dissents = self.memory.find_relevant_dissent(topic, limit=10)

        # Categorize dissents by type
        dissent_by_type: dict[str, list] = {}
        for d in dissents:
            dtype = d.dissent_type.value
            if dtype not in dissent_by_type:
                dissent_by_type[dtype] = []
            dissent_by_type[dtype].append(d)

        # Find unacknowledged dissents (potentially important)
        unacknowledged = [d for d in dissents if not d.acknowledged]

        return {
            "similar_debates": [
                {
                    "topic": s.consensus.topic,
                    "conclusion": s.consensus.conclusion,
                    "strength": s.consensus.strength.value,
                    "similarity": s.similarity_score,
                    "dissent_count": len(s.dissents),
                }
                for s in similar
            ],
            "relevant_dissents": [d.to_dict() for d in dissents],
            "dissent_by_type": {k: [d.to_dict() for d in v] for k, v in dissent_by_type.items()},
            "unacknowledged_dissents": [d.to_dict() for d in unacknowledged],
            "total_similar": len(similar),
            "total_dissents": len(dissents),
        }

    def find_contrarian_views(
        self,
        consensus_position: str,
        domain: str | None = None,
        limit: int = 5,
    ) -> list[DissentRecord]:
        """Find historical dissents that contradict a position."""

        # Look for fundamental disagreements
        dissents = self.memory.find_relevant_dissent(
            topic=consensus_position,
            dissent_types=[
                DissentType.FUNDAMENTAL_DISAGREEMENT,
                DissentType.ALTERNATIVE_APPROACH,
            ],
            limit=limit * 2,
        )

        return dissents[:limit]

    def find_risk_warnings(
        self,
        topic: str,
        domain: str | None = None,
        limit: int = 5,
    ) -> list[DissentRecord]:
        """Find historical risk warnings relevant to a topic."""

        return self.memory.find_relevant_dissent(
            topic=topic,
            dissent_types=[DissentType.RISK_WARNING, DissentType.EDGE_CASE_CONCERN],
            limit=limit,
        )

    def get_debate_preparation_context(
        self,
        topic: str,
        domain: str | None = None,
    ) -> str:
        """Generate a context string to inform a new debate."""

        context = self.retrieve_for_new_debate(topic, domain)

        lines = [f"# Historical Context for: {topic}\n"]

        if context["similar_debates"]:
            lines.append("## Similar Past Debates")
            for s in context["similar_debates"][:3]:
                lines.append(f"- **{s['topic']}** ({s['strength']}, {s['similarity']:.0%} similar)")
                # Use smart truncation that preserves sentence boundaries
                conclusion = self._smart_truncate(s["conclusion"], 100)
                lines.append(f"  Conclusion: {conclusion}")
                if s["dissent_count"] > 0:
                    lines.append(f"  ⚠️ {s['dissent_count']} dissenting view(s)")
            lines.append("")

        if context["unacknowledged_dissents"]:
            lines.append("## Unaddressed Historical Concerns")
            for d in context["unacknowledged_dissents"][:3]:
                # Use smart truncation that preserves sentence boundaries
                content = self._smart_truncate(d["content"], 100)
                lines.append(f"- [{d['dissent_type']}] {content}")
            lines.append("")

        if context["relevant_dissents"]:
            lines.append(
                f"## {len(context['relevant_dissents'])} Relevant Historical Dissents Available"
            )

        return "\n".join(lines)


class ConsensusStore(ConsensusMemory):
    """Compatibility wrapper that supports vote recording for bot handlers."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        km_adapter: Optional["ConsensusAdapter"] = None,
    ):
        super().__init__(db_path=db_path, km_adapter=km_adapter)
        self._recorded_votes: list[dict[str, str]] = []

    def record_vote(
        self,
        debate_id: str,
        user_id: str,
        vote: str,
        source: str,
    ) -> None:
        """Record a user vote on a debate outcome."""
        self._recorded_votes.append(
            {
                "debate_id": debate_id,
                "user_id": user_id,
                "vote": vote,
                "source": source,
            }
        )
