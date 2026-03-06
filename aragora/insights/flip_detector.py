"""
Flip Detector - Semantic position reversal detection.

Detects when agents reverse their positions on claims, tracks flip patterns,
and provides data for UI visualization.

Key components:
- FlipEvent: A detected position reversal
- AgentConsistencyScore: Per-agent consistency metrics
- FlipDetector: Main detection logic with semantic comparison
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

from aragora.insights.database import InsightsDatabase
from aragora.persistence.db_config import DatabaseType, get_db_path

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.insights_adapter import InsightsAdapter

logger = logging.getLogger(__name__)


@dataclass
class FlipEvent:
    """A detected position reversal."""

    id: str
    agent_name: str
    original_claim: str
    new_claim: str
    original_confidence: float
    new_confidence: float
    original_debate_id: str
    new_debate_id: str
    original_position_id: str
    new_position_id: str
    similarity_score: float  # How similar the claims are (high = contradiction likely)
    flip_type: str  # "contradiction", "refinement", "retraction", "qualification"
    domain: str | None = None
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "original_claim": self.original_claim,
            "new_claim": self.new_claim,
            "original_confidence": self.original_confidence,
            "new_confidence": self.new_confidence,
            "original_debate_id": self.original_debate_id,
            "new_debate_id": self.new_debate_id,
            "similarity_score": self.similarity_score,
            "flip_type": self.flip_type,
            "domain": self.domain,
            "detected_at": self.detected_at,
        }


@dataclass
class AgentConsistencyScore:
    """Per-agent consistency metrics."""

    agent_name: str
    total_positions: int = 0
    total_flips: int = 0
    contradictions: int = 0
    refinements: int = 0
    retractions: int = 0
    qualifications: int = 0
    avg_confidence_on_flip: float = 0.0
    domains_with_flips: list[str] = field(default_factory=list)

    @property
    def consistency_score(self) -> float:
        """1.0 = perfectly consistent, 0.0 = always flipping."""
        if self.total_positions == 0:
            return 1.0
        # Weight contradictions more heavily than other flip types
        weighted_flips = (
            self.contradictions * 1.0
            + self.retractions * 0.7
            + self.qualifications * 0.3
            + self.refinements * 0.1
        )
        return max(0.0, 1.0 - (weighted_flips / self.total_positions))

    @property
    def flip_rate(self) -> float:
        """Percentage of positions that were flipped."""
        if self.total_positions == 0:
            return 0.0
        return self.total_flips / self.total_positions

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "agent_name": self.agent_name,
            "total_positions": self.total_positions,
            "total_flips": self.total_flips,
            "contradictions": self.contradictions,
            "refinements": self.refinements,
            "retractions": self.retractions,
            "qualifications": self.qualifications,
            "consistency_score": self.consistency_score,
            "flip_rate": self.flip_rate,
            "avg_confidence_on_flip": self.avg_confidence_on_flip,
            "domains_with_flips": self.domains_with_flips,
        }


class FlipDetector:
    """
    Detects position reversals using semantic similarity.

    Uses the PositionLedger's reversal data and enhances it with
    semantic analysis to classify flip types.
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        similarity_threshold: float = 0.6,
        km_adapter: Optional["InsightsAdapter"] = None,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.PERSONAS)
        self.db_path = Path(db_path)
        self.db = InsightsDatabase(str(db_path))
        self.similarity_threshold = similarity_threshold
        self._km_adapter = km_adapter
        self._similarity_backend = None
        self._init_tables()

    def set_km_adapter(self, adapter: "InsightsAdapter") -> None:
        """Set the Knowledge Mound adapter for bidirectional sync.

        Args:
            adapter: InsightsAdapter instance for KM integration
        """
        self._km_adapter = adapter

    def _init_tables(self) -> None:
        """Create flips and positions tables if not exist."""
        with self.db.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS detected_flips (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    original_claim TEXT NOT NULL,
                    new_claim TEXT NOT NULL,
                    original_confidence REAL,
                    new_confidence REAL,
                    original_debate_id TEXT,
                    new_debate_id TEXT,
                    original_position_id TEXT,
                    new_position_id TEXT,
                    similarity_score REAL,
                    flip_type TEXT,
                    domain TEXT,
                    detected_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flips_agent ON detected_flips(agent_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flips_type ON detected_flips(flip_type)")
            # Also create positions table (shared with PositionLedger)
            # This ensures get_agent_consistency() works even without PositionLedger
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    claim TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    debate_id TEXT NOT NULL,
                    round_num INTEGER NOT NULL,
                    outcome TEXT DEFAULT 'pending',
                    reversed INTEGER DEFAULT 0,
                    reversal_debate_id TEXT,
                    domain TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_agent ON positions(agent_name)")
            conn.commit()

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """Compute semantic similarity between two texts using embedding-based backend."""
        if self._similarity_backend is None:
            from aragora.debate.similarity.factory import get_backend

            self._similarity_backend = get_backend(preferred="auto")
        text1_lower = text1.lower().strip()
        text2_lower = text2.lower().strip()
        return self._similarity_backend.compute_similarity(text1_lower, text2_lower)

    def _classify_flip_type(
        self,
        original_claim: str,
        new_claim: str,
        original_confidence: float,
        new_confidence: float,
    ) -> str:
        """
        Classify the type of position flip.

        Types:
        - contradiction: Direct opposite (e.g., "X is good" -> "X is bad")
        - retraction: Complete withdrawal (e.g., "X is true" -> "I was wrong about X")
        - qualification: Adding nuance (e.g., "X is true" -> "X is sometimes true")
        - refinement: Minor adjustment (e.g., "X is true" -> "X is mostly true")
        """
        orig_lower = original_claim.lower()
        new_lower = new_claim.lower()

        # Check for contradiction signals
        contradiction_signals = [
            ("not ", " not "),
            ("isn't", "is"),
            ("shouldn't", "should"),
            ("bad", "good"),
            ("wrong", "right"),
            ("false", "true"),
            ("disagree", "agree"),
            ("oppose", "support"),
        ]

        for sig1, sig2 in contradiction_signals:
            if (sig1 in orig_lower and sig2 in new_lower) or (
                sig2 in orig_lower and sig1 in new_lower
            ):
                return "contradiction"

        # Check for retraction signals
        retraction_signals = ["was wrong", "reconsider", "take back", "withdraw", "retract"]
        if any(sig in new_lower for sig in retraction_signals):
            return "retraction"

        # Check for qualification signals
        qualification_signals = [
            "sometimes",
            "partially",
            "in some cases",
            "under certain",
            "with caveats",
        ]
        if any(sig in new_lower for sig in qualification_signals):
            return "qualification"

        # Default to refinement for high similarity, contradiction for low
        similarity = self._compute_similarity(original_claim, new_claim)
        if similarity > 0.7:
            return "refinement"
        elif similarity < 0.3:
            return "contradiction"
        else:
            return "qualification"

    def detect_flips_for_agent(
        self,
        agent_name: str,
        lookback_positions: int = 50,
    ) -> list[FlipEvent]:
        """
        Detect position flips for an agent.

        Scans positions marked as reversed in the position ledger
        and classifies them.
        """
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row

            # Get positions marked as reversed
            cursor = conn.execute(
                """
                SELECT p1.*, p2.claim as new_claim, p2.confidence as new_confidence,
                       p2.debate_id as new_debate_id, p2.id as new_position_id
                FROM positions p1
                LEFT JOIN positions p2 ON p1.reversal_debate_id = p2.debate_id
                    AND p1.agent_name = p2.agent_name
                WHERE p1.agent_name = ? AND p1.reversed = 1
                ORDER BY p1.created_at DESC
                LIMIT ?
                """,
                (agent_name, lookback_positions),
            )
            rows = cursor.fetchall()

        flips = []
        for row in rows:
            if not row["new_claim"]:
                continue

            similarity = self._compute_similarity(row["claim"], row["new_claim"])
            flip_type = self._classify_flip_type(
                row["claim"],
                row["new_claim"],
                row["confidence"],
                row["new_confidence"] or 0.5,
            )

            flip = FlipEvent(
                id=f"flip-{row['id']}",
                agent_name=agent_name,
                original_claim=row["claim"],
                new_claim=row["new_claim"],
                original_confidence=row["confidence"],
                new_confidence=row["new_confidence"] or 0.5,
                original_debate_id=row["debate_id"],
                new_debate_id=row["new_debate_id"] or row["reversal_debate_id"],
                original_position_id=row["id"],
                new_position_id=row["new_position_id"] or "",
                similarity_score=similarity,
                flip_type=flip_type,
                domain=row["domain"],
            )
            flips.append(flip)

        # Batch store all detected flips in a single transaction
        if flips:
            self._store_flips_batch(flips)

        return flips

    def _store_flip(self, flip: FlipEvent) -> None:
        """Store a detected flip in the database."""
        self._store_flips_batch([flip])

    def _store_flips_batch(self, flips: list[FlipEvent]) -> None:
        """Store multiple detected flips in a single transaction.

        This is more efficient than calling _store_flip() in a loop,
        as it uses a single connection and executemany() for batch inserts.
        """
        if not flips:
            return

        with self.db.connection() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO detected_flips
                (id, agent_name, original_claim, new_claim, original_confidence,
                 new_confidence, original_debate_id, new_debate_id,
                 original_position_id, new_position_id, similarity_score,
                 flip_type, domain, detected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        flip.id,
                        flip.agent_name,
                        flip.original_claim,
                        flip.new_claim,
                        flip.original_confidence,
                        flip.new_confidence,
                        flip.original_debate_id,
                        flip.new_debate_id,
                        flip.original_position_id,
                        flip.new_position_id,
                        flip.similarity_score,
                        flip.flip_type,
                        flip.domain,
                        flip.detected_at,
                    )
                    for flip in flips
                ],
            )
            conn.commit()

        # Sync flips to Knowledge Mound (flips are always stored for meta-learning)
        if self._km_adapter:
            for flip in flips:
                try:
                    self._km_adapter.store_flip(flip)
                    logger.debug("Flip synced to Knowledge Mound: %s", flip.id)
                except (OSError, ValueError, RuntimeError, TypeError) as e:
                    logger.warning("Failed to sync flip to KM: %s", e)

    def get_agent_consistency(self, agent_name: str) -> AgentConsistencyScore:
        """Get consistency score and metrics for an agent."""
        with self.db.connection() as conn:
            # Count total positions
            cursor = conn.execute(
                "SELECT COUNT(*) FROM positions WHERE agent_name = ?", (agent_name,)
            )
            row = cursor.fetchone()
            total_positions = row[0] if row else 0

            # Count flips by type
            cursor = conn.execute(
                """
                SELECT flip_type, COUNT(*), AVG(original_confidence)
                FROM detected_flips
                WHERE agent_name = ?
                GROUP BY flip_type
                """,
                (agent_name,),
            )
            flip_counts = {}
            avg_conf = 0.0
            total_flips = 0
            for row in cursor.fetchall():
                flip_counts[row[0]] = row[1]
                total_flips += row[1]
                avg_conf += row[2] * row[1] if row[2] else 0

            if total_flips > 0:
                avg_conf /= total_flips

            # Get domains with flips
            cursor = conn.execute(
                """
                SELECT DISTINCT domain FROM detected_flips
                WHERE agent_name = ? AND domain IS NOT NULL
                """,
                (agent_name,),
            )
            domains = [row[0] for row in cursor.fetchall()]

        return AgentConsistencyScore(
            agent_name=agent_name,
            total_positions=total_positions,
            total_flips=total_flips,
            contradictions=flip_counts.get("contradiction", 0),
            refinements=flip_counts.get("refinement", 0),
            retractions=flip_counts.get("retraction", 0),
            qualifications=flip_counts.get("qualification", 0),
            avg_confidence_on_flip=avg_conf,
            domains_with_flips=domains,
        )

    def get_agents_consistency_batch(
        self, agent_names: list[str]
    ) -> dict[str, AgentConsistencyScore]:
        """Get consistency scores for multiple agents in batch (avoids N+1 queries).

        Args:
            agent_names: List of agent names to fetch

        Returns:
            Dict mapping agent names to their consistency scores
        """
        if not agent_names:
            return {}

        # Create placeholders for SQL IN clause
        placeholders = ",".join("?" * len(agent_names))

        with self.db.connection() as conn:
            # Batch query 1: Count positions per agent
            cursor = conn.execute(
                f"SELECT agent_name, COUNT(*) FROM positions WHERE agent_name IN ({placeholders}) GROUP BY agent_name",  # noqa: S608 -- parameterized query
                agent_names,
            )
            positions_map: dict[str, int] = {row[0]: row[1] for row in cursor.fetchall()}

            # Batch query 2: Get flip stats per agent
            cursor = conn.execute(
                f"""
                SELECT agent_name, flip_type, COUNT(*), AVG(original_confidence)
                FROM detected_flips
                WHERE agent_name IN ({placeholders})
                GROUP BY agent_name, flip_type
                """,  # noqa: S608 -- parameterized query
                agent_names,
            )
            flip_stats: dict[str, dict[str, Any]] = {}
            for row in cursor.fetchall():
                agent, flip_type, count, avg_conf = row
                if agent not in flip_stats:
                    flip_stats[agent] = {"counts": {}, "total": 0, "weighted_conf": 0.0}
                flip_stats[agent]["counts"][flip_type] = count
                flip_stats[agent]["total"] += count
                flip_stats[agent]["weighted_conf"] += (avg_conf or 0) * count

            # Batch query 3: Get domains with flips per agent
            cursor = conn.execute(
                f"""
                SELECT agent_name, domain FROM detected_flips
                WHERE agent_name IN ({placeholders}) AND domain IS NOT NULL
                """,  # noqa: S608 -- parameterized query
                agent_names,
            )
            domains_map: dict[str, set[str]] = {}
            for row in cursor.fetchall():
                agent, domain = row
                if agent not in domains_map:
                    domains_map[agent] = set()
                domains_map[agent].add(domain)

        # Build result dict
        result = {}
        for agent in agent_names:
            total_positions = positions_map.get(agent, 0)
            stats = flip_stats.get(agent, {"counts": {}, "total": 0, "weighted_conf": 0.0})
            total_flips = stats["total"]
            avg_conf = stats["weighted_conf"] / total_flips if total_flips > 0 else 0.0

            result[agent] = AgentConsistencyScore(
                agent_name=agent,
                total_positions=total_positions,
                total_flips=total_flips,
                contradictions=stats["counts"].get("contradiction", 0),
                refinements=stats["counts"].get("refinement", 0),
                retractions=stats["counts"].get("retraction", 0),
                qualifications=stats["counts"].get("qualification", 0),
                avg_confidence_on_flip=avg_conf,
                domains_with_flips=list(domains_map.get(agent, [])),
            )

        return result

    def get_recent_flips(self, limit: int = 20) -> list[FlipEvent]:
        """Get recent flips across all agents."""
        with self.db.connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM detected_flips
                ORDER BY detected_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        return [
            FlipEvent(
                id=row["id"],
                agent_name=row["agent_name"],
                original_claim=row["original_claim"],
                new_claim=row["new_claim"],
                original_confidence=row["original_confidence"],
                new_confidence=row["new_confidence"],
                original_debate_id=row["original_debate_id"],
                new_debate_id=row["new_debate_id"],
                original_position_id=row["original_position_id"],
                new_position_id=row["new_position_id"],
                similarity_score=row["similarity_score"],
                flip_type=row["flip_type"],
                domain=row["domain"],
                detected_at=row["detected_at"],
            )
            for row in rows
        ]

    def get_flip_summary(self) -> dict:
        """Get summary of all flips for dashboard display."""
        with self.db.connection() as conn:
            # Total flips
            cursor = conn.execute("SELECT COUNT(*) FROM detected_flips")
            row = cursor.fetchone()
            total_flips = row[0] if row else 0

            # Flips by type
            cursor = conn.execute(
                "SELECT flip_type, COUNT(*) FROM detected_flips GROUP BY flip_type"
            )
            by_type = dict(cursor.fetchall())

            # Flips by agent
            cursor = conn.execute(
                "SELECT agent_name, COUNT(*) FROM detected_flips GROUP BY agent_name ORDER BY COUNT(*) DESC"
            )
            by_agent = dict(cursor.fetchall())

            # Recent 24h flips
            cursor = conn.execute("""
                SELECT COUNT(*) FROM detected_flips
                WHERE detected_at > datetime('now', '-1 day')
                """)
            row = cursor.fetchone()
            recent_24h = row[0] if row else 0

        return {
            "total_flips": total_flips,
            "by_type": by_type,
            "by_agent": by_agent,
            "recent_24h": recent_24h,
        }


def format_flip_for_ui(flip: FlipEvent) -> dict:
    """Format a flip event for UI display."""
    return {
        "id": flip.id,
        "agent": flip.agent_name,
        "type": flip.flip_type,
        "type_emoji": {
            "contradiction": "🔄",
            "retraction": "↩️",
            "qualification": "📝",
            "refinement": "🔧",
        }.get(flip.flip_type, "❓"),
        "before": {
            "claim": (
                flip.original_claim[:100] + "..."
                if len(flip.original_claim) > 100
                else flip.original_claim
            ),
            "confidence": f"{flip.original_confidence:.0%}",
        },
        "after": {
            "claim": flip.new_claim[:100] + "..." if len(flip.new_claim) > 100 else flip.new_claim,
            "confidence": f"{flip.new_confidence:.0%}",
        },
        "similarity": f"{flip.similarity_score:.0%}",
        "domain": flip.domain,
        "timestamp": flip.detected_at,
    }


def format_consistency_for_ui(score: AgentConsistencyScore) -> dict:
    """Format agent consistency score for UI display."""
    return {
        "agent": score.agent_name,
        "consistency": f"{score.consistency_score:.0%}",
        "consistency_class": (
            "high"
            if score.consistency_score > 0.8
            else "medium"
            if score.consistency_score > 0.5
            else "low"
        ),
        "total_positions": score.total_positions,
        "flip_rate": f"{score.flip_rate:.0%}",
        "breakdown": {
            "contradictions": score.contradictions,
            "retractions": score.retractions,
            "qualifications": score.qualifications,
            "refinements": score.refinements,
        },
        "problem_domains": score.domains_with_flips[:3],
    }
