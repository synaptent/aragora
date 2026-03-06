"""
ELO/Reputation System for agent skill tracking.

Inspired by ChatArena's competitive environments, this module provides:
- ELO ratings for agents
- Domain-specific skill ratings
- Match history and statistics
- Leaderboards

Performance: Uses LRU caching for frequently accessed data like leaderboards.
Cache is automatically invalidated when ratings are updated.

EloSystem is a facade that delegates to focused modules:
- elo_core.py: Pure ELO calculation functions
- elo_matchmaking.py: Match recording orchestration
- elo_leaderboard.py: Snapshot-based leaderboard access
- elo_calibration.py: Calibration leaderboard queries
- elo_domain.py: Knowledge Mound integration
- elo_analysis.py: Learning efficiency and voting accuracy
- leaderboard_engine.py: Core leaderboard queries
- calibration_engine.py: Calibration recording and scoring
- match_recorder.py: Match persistence helpers
- relationships.py: Agent relationship tracking
- redteam.py: Red team integration
- verification.py: Formal verification ELO adjustments
- snapshot.py: JSON snapshot I/O
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.type_protocols import EventEmitterProtocol
    from aragora.knowledge.mound.adapters.performance_adapter import EloAdapter

from aragora.config import (
    CACHE_TTL_CALIBRATION_LB,
    CACHE_TTL_LB_STATS,
    CACHE_TTL_LEADERBOARD,
    CACHE_TTL_RECENT_MATCHES,
    ELO_CALIBRATION_MIN_COUNT,
    ELO_INITIAL_RATING,
    ELO_K_FACTOR,
    resolve_db_path,
)
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.ranking.calibration_engine import CalibrationEngine, DomainCalibrationEngine
from aragora.ranking.database import EloDatabase
from aragora.ranking.elo_analysis import (
    apply_learning_bonus as _apply_learning_bonus,
    compute_consistency_score as _compute_consistency_score_fn,
    compute_elo_gain_rate as _compute_elo_gain_rate_fn,
    categorize_learning as _categorize_learning_fn,
    get_learning_efficiency as _get_learning_efficiency,
    get_learning_efficiency_batch as _get_learning_efficiency_batch,
    get_voting_accuracy as _get_voting_accuracy,
    get_voting_accuracy_batch as _get_voting_accuracy_batch,
    update_voting_accuracy as _update_voting_accuracy,
)
from aragora.ranking.elo_calibration import (
    get_agent_calibration_history as _get_agent_calibration_history,
    get_calibration_leaderboard as _get_calibration_leaderboard,
)
from aragora.ranking.elo_core import (
    apply_elo_changes,
    calculate_new_elo,
    calculate_pairwise_elo_changes,
    expected_score,
)
from aragora.ranking.elo_domain import KMAdapterMixin
from aragora.ranking.elo_leaderboard import (
    get_cached_recent_matches as _get_cached_recent_matches,
    get_snapshot_leaderboard as _get_snapshot_leaderboard,
)
from aragora.ranking.elo_matchmaking import record_match as _record_match
from aragora.ranking.leaderboard_engine import LeaderboardEngine
from aragora.ranking.match_recorder import (
    build_match_scores,
    compute_calibration_k_multipliers,
    generate_match_id,
    normalize_match_params,
    save_match,
)
from aragora.ranking.redteam import RedTeamIntegrator, RedTeamResult, VulnerabilitySummary
from aragora.ranking.relationships import (
    RelationshipMetrics,
    RelationshipStats,
    RelationshipTracker,
)
from aragora.ranking.snapshot import write_snapshot
from aragora.ranking.verification import (
    calculate_verification_elo_change,
    calculate_verification_impact,
    update_rating_from_verification,
)
from aragora.utils.cache import TTLCache
from aragora.utils.json_helpers import safe_json_loads

# Re-export for backwards compatibility (moved to sql_helpers)
from aragora.utils.sql_helpers import _escape_like_pattern

logger = logging.getLogger(__name__)

# Re-export for backwards compatibility
__all__ = [
    "EloSystem",
    "AgentRating",
    "MatchResult",
    "RelationshipTracker",
    "RelationshipStats",
    "RelationshipMetrics",
    "RedTeamIntegrator",
    "RedTeamResult",
    "VulnerabilitySummary",
    "_escape_like_pattern",
    "get_elo_store",
]

# Singleton EloSystem instance
_elo_store: EloSystem | None = None


def get_elo_store() -> EloSystem:
    """Get the global EloSystem singleton instance.

    Returns a singleton EloSystem instance, creating it if necessary.
    Uses the default database path from configuration.

    Returns:
        EloSystem: The global ELO store instance
    """
    global _elo_store
    if _elo_store is None:
        _elo_store = EloSystem()
    return _elo_store


# Use centralized config values (can be overridden via environment variables)
DEFAULT_ELO = ELO_INITIAL_RATING
K_FACTOR = ELO_K_FACTOR
CALIBRATION_MIN_COUNT = ELO_CALIBRATION_MIN_COUNT

# Maximum agent name length (matches SAFE_AGENT_PATTERN in validation/entities.py)
MAX_AGENT_NAME_LENGTH = 32


def _validate_agent_name(agent_name: str) -> None:
    """Validate agent name length to prevent performance issues.

    Args:
        agent_name: Agent name to validate

    Raises:
        ValueError: If agent name exceeds MAX_AGENT_NAME_LENGTH
    """
    if len(agent_name) > MAX_AGENT_NAME_LENGTH:
        raise ValueError(
            f"Agent name exceeds {MAX_AGENT_NAME_LENGTH} characters: {len(agent_name)}"
        )


@dataclass
class AgentRating:
    """An agent's rating and statistics."""

    agent_name: str
    elo: float = DEFAULT_ELO
    domain_elos: dict[str, float] = field(default_factory=dict)
    wins: int = 0
    losses: int = 0
    draws: int = 0
    debates_count: int = 0
    critiques_accepted: int = 0
    critiques_total: int = 0
    # Calibration scoring fields
    calibration_correct: int = 0
    calibration_total: int = 0
    calibration_brier_sum: float = 0.0
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        total = self.wins + self.losses + self.draws
        return self.wins / total if total > 0 else 0.0

    @property
    def critique_acceptance_rate(self) -> float:
        """Calculate critique acceptance rate."""
        return self.critiques_accepted / self.critiques_total if self.critiques_total > 0 else 0.0

    @property
    def games_played(self) -> int:
        """Total games played."""
        return self.wins + self.losses + self.draws

    @property
    def calibration_accuracy(self) -> float:
        """Fraction of correct winner predictions."""
        if self.calibration_total == 0:
            return 0.0
        return self.calibration_correct / self.calibration_total

    @property
    def calibration_brier_score(self) -> float:
        """Average Brier score (lower is better, 0 = perfect)."""
        if self.calibration_total == 0:
            return 1.0
        return self.calibration_brier_sum / self.calibration_total

    @property
    def calibration_score(self) -> float:
        """
        Combined calibration score (higher is better).

        Uses (1 - Brier) weighted by confidence from sample size.
        Requires minimum predictions for meaningful score.
        """
        if self.calibration_total < CALIBRATION_MIN_COUNT:
            return 0.0
        # Confidence scales from 0.5 at min_count to 1.0 at 50+ predictions
        confidence = min(1.0, 0.5 + 0.5 * (self.calibration_total - CALIBRATION_MIN_COUNT) / 40)
        return (1 - self.calibration_brier_score) * confidence

    @property
    def elo_rating(self) -> float:
        """ELO rating (alias for elo)."""
        return self.elo

    @property
    def total_debates(self) -> int:
        """Total debates (alias for debates_count)."""
        return self.debates_count


@dataclass
class MatchResult:
    """Result of a debate match between agents."""

    debate_id: str
    winner: str | None  # None for draw
    participants: list[str]
    domain: str | None
    scores: dict[str, float]  # agent -> score
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class EloSystem(KMAdapterMixin):
    """
    ELO-based ranking system for agents.

    Tracks agent skill ratings, match history, and provides leaderboards.
    Uses LRU caching for frequently accessed data.

    This is a facade class that delegates to focused modules for:
    - Match recording (elo_matchmaking)
    - Leaderboard queries (leaderboard_engine, elo_leaderboard)
    - Calibration (calibration_engine, elo_calibration)
    - Analysis (elo_analysis)
    - KM integration (elo_domain)
    - Relationships (relationships)
    - Red team (redteam)
    - Verification (verification)
    """

    # Class-level cache for leaderboard data (shared across instances)
    _leaderboard_cache: TTLCache[list[AgentRating]] = TTLCache(
        maxsize=50, ttl_seconds=CACHE_TTL_LEADERBOARD
    )
    _rating_cache: TTLCache[AgentRating] = TTLCache(
        maxsize=200, ttl_seconds=CACHE_TTL_RECENT_MATCHES
    )
    _stats_cache: TTLCache[dict[str, Any]] = TTLCache(maxsize=10, ttl_seconds=CACHE_TTL_LB_STATS)
    _calibration_cache: TTLCache[list[AgentRating]] = TTLCache(
        maxsize=20, ttl_seconds=CACHE_TTL_CALIBRATION_LB
    )

    def __init__(
        self,
        db_path: str | Path | None = None,
        event_emitter: EventEmitterProtocol | None = None,
        km_adapter: EloAdapter | None = None,
    ):
        if db_path is None:
            db_path = get_db_path(DatabaseType.ELO)
        resolved_path = resolve_db_path(str(db_path))
        self.db_path = Path(resolved_path)
        self._db = EloDatabase(resolved_path)
        self.event_emitter = event_emitter  # For emitting ELO update events
        self._km_adapter = km_adapter  # For Knowledge Mound integration

        # Delegate to extracted modules (lazy initialization)
        self._relationship_tracker: RelationshipTracker | None = None
        self._redteam_integrator: RedTeamIntegrator | None = None

        # Leaderboard engine for read-only analytics
        self._leaderboard_engine = LeaderboardEngine(
            db=self._db,
            leaderboard_cache=self._leaderboard_cache,
            stats_cache=self._stats_cache,
            rating_cache=self._rating_cache,
            rating_factory=self._rating_from_row,
        )

        # Calibration engines for tournament and domain-specific calibration
        self._calibration_engine = CalibrationEngine(db_path=resolved_path, elo_system=self)
        self._domain_calibration_engine = DomainCalibrationEngine(
            db_path=resolved_path, elo_system=self
        )

    # =========================================================================
    # Lazy-initialized sub-components
    # =========================================================================

    @property
    def relationship_tracker(self) -> RelationshipTracker:
        """Get the relationship tracker (lazy initialized)."""
        if self._relationship_tracker is None:
            self._relationship_tracker = RelationshipTracker(self.db_path)
        return self._relationship_tracker

    @property
    def redteam_integrator(self) -> RedTeamIntegrator:
        """Get the red team integrator (lazy initialized)."""
        if self._redteam_integrator is None:
            self._redteam_integrator = RedTeamIntegrator(self)
        return self._redteam_integrator

    # =========================================================================
    # Core CRUD (rating get/save, agent listing)
    # =========================================================================

    def register_agent(self, agent_name: str, model: str | None = None) -> AgentRating:
        """Ensure an agent exists in the ratings table (legacy compatibility)."""
        _validate_agent_name(agent_name)
        return self.get_rating(agent_name, use_cache=False)

    def initialize_agent(self, agent_name: str, model: str | None = None) -> AgentRating:
        """Backward-compatible alias for register_agent."""
        return self.register_agent(agent_name, model=model)

    def get_rating(self, agent_name: str, use_cache: bool = True) -> AgentRating:
        """Get or create rating for an agent."""
        _validate_agent_name(agent_name)
        cache_key = f"rating:{agent_name}"

        if use_cache:
            cached = self._rating_cache.get(cache_key)
            if cached is not None:
                return cached

        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT agent_name, elo, domain_elos, wins, losses, draws,
                       debates_count, critiques_accepted, critiques_total,
                       calibration_correct, calibration_total, calibration_brier_sum,
                       updated_at
                FROM ratings WHERE agent_name = ?
                """,
                (agent_name,),
            )
            row = cursor.fetchone()

        if not row:
            rating = AgentRating(agent_name=agent_name)
        else:
            rating = AgentRating(
                agent_name=row[0],
                elo=row[1],
                domain_elos=safe_json_loads(row[2], {}),
                wins=row[3],
                losses=row[4],
                draws=row[5],
                debates_count=row[6],
                critiques_accepted=row[7],
                critiques_total=row[8],
                calibration_correct=row[9] or 0,
                calibration_total=row[10] or 0,
                calibration_brier_sum=row[11] or 0.0,
                updated_at=row[12],
            )

        self._rating_cache.set(cache_key, rating)
        return rating

    def _rating_from_row(self, row: tuple[Any, ...]) -> AgentRating:
        """Create AgentRating from a database row (leaderboard query format)."""
        return AgentRating(
            agent_name=row[0],
            elo=row[1],
            domain_elos=safe_json_loads(row[2], {}),
            wins=row[3],
            losses=row[4],
            draws=row[5],
            debates_count=row[6],
            critiques_accepted=row[7],
            critiques_total=row[8],
            updated_at=row[9],
        )

    def list_agents(self) -> list[str]:
        """Get list of all known agent names."""
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT agent_name FROM ratings ORDER BY elo DESC")
            return [row[0] for row in cursor.fetchall()]

    def get_all_ratings(self) -> list[AgentRating]:
        """Get all agent ratings in a single query (batch optimization)."""
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT agent_name, elo, domain_elos, wins, losses, draws,
                       debates_count, critiques_accepted, critiques_total,
                       calibration_correct, calibration_total, calibration_brier_sum,
                       updated_at
                FROM ratings
                ORDER BY elo DESC
                """)
            rows = cursor.fetchall()

        return [
            AgentRating(
                agent_name=row[0],
                elo=row[1],
                domain_elos=safe_json_loads(row[2], {}),
                wins=row[3],
                losses=row[4],
                draws=row[5],
                debates_count=row[6],
                critiques_accepted=row[7],
                critiques_total=row[8],
                calibration_correct=row[9] or 0,
                calibration_total=row[10] or 0,
                calibration_brier_sum=row[11] or 0.0,
                updated_at=row[12],
            )
            for row in rows
        ]

    def _save_rating(self, rating: AgentRating) -> None:
        """Save rating to database."""
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ratings (agent_name, elo, domain_elos, wins, losses, draws,
                                    debates_count, critiques_accepted, critiques_total,
                                    calibration_correct, calibration_total, calibration_brier_sum,
                                    updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_name) DO UPDATE SET
                    elo = excluded.elo,
                    domain_elos = excluded.domain_elos,
                    wins = excluded.wins,
                    losses = excluded.losses,
                    draws = excluded.draws,
                    debates_count = excluded.debates_count,
                    critiques_accepted = excluded.critiques_accepted,
                    critiques_total = excluded.critiques_total,
                    calibration_correct = excluded.calibration_correct,
                    calibration_total = excluded.calibration_total,
                    calibration_brier_sum = excluded.calibration_brier_sum,
                    updated_at = excluded.updated_at
                """,
                (
                    rating.agent_name,
                    rating.elo,
                    json.dumps(rating.domain_elos),
                    rating.wins,
                    rating.losses,
                    rating.draws,
                    rating.debates_count,
                    rating.critiques_accepted,
                    rating.critiques_total,
                    rating.calibration_correct,
                    rating.calibration_total,
                    rating.calibration_brier_sum,
                    rating.updated_at,
                ),
            )
            conn.commit()

        # Invalidate caches after write
        self._rating_cache.invalidate(f"rating:{rating.agent_name}")
        self._leaderboard_cache.clear()
        self._stats_cache.clear()
        self._calibration_cache.clear()

    def _save_ratings_batch(self, ratings: list[AgentRating]) -> None:
        """Save multiple ratings in a single transaction."""
        if not ratings:
            return

        with self._db.connection() as conn:
            cursor = conn.cursor()
            for rating in ratings:
                cursor.execute(
                    """
                    INSERT INTO ratings (agent_name, elo, domain_elos, wins, losses, draws,
                                        debates_count, critiques_accepted, critiques_total,
                                        calibration_correct, calibration_total, calibration_brier_sum,
                                        updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_name) DO UPDATE SET
                        elo = excluded.elo,
                        domain_elos = excluded.domain_elos,
                        wins = excluded.wins,
                        losses = excluded.losses,
                        draws = excluded.draws,
                        debates_count = excluded.debates_count,
                        critiques_accepted = excluded.critiques_accepted,
                        critiques_total = excluded.critiques_total,
                        calibration_correct = excluded.calibration_correct,
                        calibration_total = excluded.calibration_total,
                        calibration_brier_sum = excluded.calibration_brier_sum,
                        updated_at = excluded.updated_at
                    """,
                    (
                        rating.agent_name,
                        rating.elo,
                        json.dumps(rating.domain_elos),
                        rating.wins,
                        rating.losses,
                        rating.draws,
                        rating.debates_count,
                        rating.critiques_accepted,
                        rating.critiques_total,
                        rating.calibration_correct,
                        rating.calibration_total,
                        rating.calibration_brier_sum,
                        rating.updated_at,
                    ),
                )
            conn.commit()

        for rating in ratings:
            self._rating_cache.invalidate(f"rating:{rating.agent_name}")
        self._leaderboard_cache.clear()
        self._stats_cache.clear()
        self._calibration_cache.clear()

    def _record_elo_history_batch(self, entries: list[tuple[str, float, str | None]]) -> None:
        """Record multiple ELO history entries in a single transaction."""
        if not entries:
            return
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(
                "INSERT INTO elo_history (agent_name, elo, debate_id) VALUES (?, ?, ?)",
                entries,
            )
            conn.commit()

    def _record_elo_history(
        self, agent_name: str, elo: float, debate_id: str | None = None
    ) -> None:
        """Record ELO at a point in time."""
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO elo_history (agent_name, elo, debate_id) VALUES (?, ?, ?)",
                (agent_name, elo, debate_id),
            )
            conn.commit()

    def get_ratings_batch(self, agent_names: list[str]) -> dict[str, AgentRating]:
        """Get ratings for multiple agents in a single database query."""
        if not agent_names:
            return {}

        results: dict[str, AgentRating] = {}
        uncached = []
        for name in agent_names:
            _validate_agent_name(name)
            cache_key = f"rating:{name}"
            cached = self._rating_cache.get(cache_key)
            if cached is not None:
                results[name] = cached
            else:
                uncached.append(name)

        if not uncached:
            return results

        placeholders = ",".join("?" * len(uncached))
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT agent_name, elo, domain_elos, wins, losses, draws,
                       debates_count, critiques_accepted, critiques_total,
                       calibration_correct, calibration_total, calibration_brier_sum,
                       updated_at
                FROM ratings WHERE agent_name IN ({placeholders})
                """,  # noqa: S608 -- parameterized query
                uncached,
            )
            rows = cursor.fetchall()

        found_names = set()
        for row in rows:
            rating = AgentRating(
                agent_name=row[0],
                elo=row[1],
                domain_elos=safe_json_loads(row[2], {}),
                wins=row[3],
                losses=row[4],
                draws=row[5],
                debates_count=row[6],
                critiques_accepted=row[7],
                critiques_total=row[8],
                calibration_correct=row[9],
                calibration_total=row[10],
                calibration_brier_sum=row[11],
            )
            results[rating.agent_name] = rating
            found_names.add(rating.agent_name)
            self._rating_cache.set(f"rating:{rating.agent_name}", rating)

        for name in uncached:
            if name not in found_names:
                rating = AgentRating(agent_name=name)
                results[name] = rating

        return results

    def record_critique(self, agent_name: str, accepted: bool) -> None:
        """Record a critique and whether it was accepted."""
        rating = self.get_rating(agent_name)
        rating.critiques_total += 1
        if accepted:
            rating.critiques_accepted += 1
        rating.updated_at = datetime.now().isoformat()
        self._save_rating(rating)

    # =========================================================================
    # ELO Calculation Delegates (backward compatibility)
    # =========================================================================

    def _expected_score(self, elo_a: float, elo_b: float) -> float:
        """Calculate expected score for player A against player B."""
        return expected_score(elo_a, elo_b)

    def _calculate_new_elo(
        self, current_elo: float, expected: float, actual: float, k: float = K_FACTOR
    ) -> float:
        """Calculate new ELO rating."""
        return calculate_new_elo(current_elo, expected, actual, k)

    def _calculate_pairwise_elo_changes(
        self,
        participants: list[str],
        scores: dict[str, float],
        ratings: dict[str, AgentRating],
        confidence_weight: float,
        k_multipliers: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Calculate pairwise ELO changes for all participant combinations."""
        k_multipliers = k_multipliers or {}
        return calculate_pairwise_elo_changes(
            participants, scores, ratings, confidence_weight, K_FACTOR, k_multipliers
        )

    def _apply_elo_changes(
        self,
        elo_changes: dict[str, float],
        ratings: dict[str, AgentRating],
        winner: str | None,
        domain: str | None,
        debate_id: str,
    ) -> tuple[list[AgentRating], list[tuple[str, float, str]]]:
        """Apply ELO changes to ratings and prepare for batch save."""
        return apply_elo_changes(elo_changes, ratings, winner, domain, debate_id, DEFAULT_ELO)

    def _compute_calibration_k_multipliers(
        self,
        participants: list[str],
        calibration_tracker: Any | None = None,
    ) -> dict[str, float]:
        """Compute per-agent K-factor multipliers based on calibration quality."""
        return compute_calibration_k_multipliers(participants, calibration_tracker)

    @staticmethod
    def _build_match_scores(winner: str, loser: str, is_draw: bool) -> dict[str, float]:
        """Build score dict for a two-player match."""
        return build_match_scores(winner, loser, is_draw)

    @staticmethod
    def _generate_match_id(
        participants: list[str], task: str | None = None, domain: str | None = None
    ) -> str:
        """Generate a unique match ID."""
        return generate_match_id(participants, task, domain)

    def _normalize_match_params(
        self,
        debate_id: str | None,
        participants: list[str] | str | None,
        scores: dict[str, float] | None,
        winner: str | None,
        loser: str | None,
        draw: bool | None,
        task: str | None,
        domain: str | None,
    ) -> tuple[str, list[str] | None, dict[str, float] | None]:
        """Normalize legacy and modern match signatures."""
        return normalize_match_params(
            debate_id, participants, scores, winner, loser, draw, task, domain
        )

    # =========================================================================
    # Match Recording (delegates to elo_matchmaking)
    # =========================================================================

    def record_match(
        self,
        debate_id: str | None = None,
        participants: list[str] | str | None = None,
        scores: dict[str, float] | None = None,
        domain: str | None = None,
        confidence_weight: float = 1.0,
        calibration_tracker: object | None = None,
        *,
        winner: str | None = None,
        loser: str | None = None,
        draw: bool | None = None,
        task: str | None = None,
    ) -> dict[str, float]:
        """Record a match result and update ELO ratings."""
        return _record_match(
            self,
            debate_id=debate_id,
            participants=participants,
            scores=scores,
            domain=domain,
            confidence_weight=confidence_weight,
            calibration_tracker=calibration_tracker,
            winner=winner,
            loser=loser,
            draw=draw,
            task=task,
        )

    def _save_match(
        self,
        debate_id: str | None,
        winner: str | None,
        participants: list[str],
        domain: str | None,
        scores: dict[str, float] | None,
        elo_changes: dict[str, float],
    ) -> None:
        """Save match to history."""
        save_match(self._db, debate_id, winner, participants, domain, scores, elo_changes)

    def _write_snapshot(self) -> None:
        """Write JSON snapshot for fast reads."""
        snapshot_path = self.db_path.parent / "elo_snapshot.json"
        write_snapshot(snapshot_path, self.get_leaderboard, self.get_recent_matches)

    # =========================================================================
    # Leaderboard Delegates (delegates to LeaderboardEngine + elo_leaderboard)
    # =========================================================================

    def get_leaderboard(self, limit: int = 20, domain: str | None = None) -> list[AgentRating]:
        """Get top agents by ELO."""
        return self._leaderboard_engine.get_leaderboard(limit=limit, domain=domain)

    def get_cached_leaderboard(
        self, limit: int = 20, domain: str | None = None
    ) -> list[AgentRating]:
        """Get leaderboard with caching."""
        return self._leaderboard_engine.get_cached_leaderboard(limit=limit, domain=domain)

    def invalidate_leaderboard_cache(self) -> int:
        """Invalidate all cached leaderboard data."""
        self._calibration_cache.clear()
        return self._leaderboard_engine.invalidate_leaderboard_cache()

    def invalidate_rating_cache(self, agent_name: str | None = None) -> int:
        """Invalidate cached ratings."""
        return self._leaderboard_engine.invalidate_rating_cache(agent_name)

    def get_top_agents_for_domain(self, domain: str, limit: int = 5) -> list[AgentRating]:
        """Get agents ranked by domain-specific performance."""
        return self._leaderboard_engine.get_top_agents_for_domain(domain=domain, limit=limit)

    def get_elo_history(self, agent_name: str, limit: int = 50) -> list[tuple[str, float]]:
        """Get ELO history for an agent."""
        return self._leaderboard_engine.get_elo_history(agent_name, limit)

    def get_recent_matches(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent match results with ELO changes."""
        return self._leaderboard_engine.get_recent_matches(limit)

    def get_head_to_head(self, agent_a: str, agent_b: str) -> dict[str, Any]:
        """Get head-to-head statistics between two agents."""
        return self._leaderboard_engine.get_head_to_head(agent_a, agent_b)

    def get_stats(self, use_cache: bool = True) -> dict[str, Any]:
        """Get overall system statistics."""
        return self._leaderboard_engine.get_stats(use_cache)

    def get_snapshot_leaderboard(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get leaderboard from JSON snapshot file."""
        return _get_snapshot_leaderboard(self.db_path, self.get_leaderboard, limit)

    def get_cached_recent_matches(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent matches from cache if available."""
        return _get_cached_recent_matches(self.db_path, self.get_recent_matches, limit)

    # =========================================================================
    # Calibration Delegates (delegates to CalibrationEngine + elo_calibration)
    # =========================================================================

    def record_winner_prediction(
        self, tournament_id: str, predictor_agent: str, predicted_winner: str, confidence: float
    ) -> None:
        """Record an agent's prediction for a tournament winner."""
        self._calibration_engine.record_winner_prediction(
            tournament_id, predictor_agent, predicted_winner, confidence
        )

    def resolve_tournament_calibration(
        self, tournament_id: str, actual_winner: str
    ) -> dict[str, float]:
        """Resolve tournament and update calibration scores."""
        return self._calibration_engine.resolve_tournament(tournament_id, actual_winner)

    def get_calibration_leaderboard(
        self, limit: int = 20, use_cache: bool = True
    ) -> list[AgentRating]:
        """Get agents ranked by calibration score."""
        return _get_calibration_leaderboard(self._db, self._calibration_cache, limit, use_cache)

    def get_agent_calibration_history(
        self, agent_name: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get recent predictions made by an agent."""
        return _get_agent_calibration_history(self._db, agent_name, limit)

    # =========================================================================
    # Domain Calibration Delegates (delegates to DomainCalibrationEngine)
    # =========================================================================

    def _get_bucket_key(self, confidence: float) -> str:
        """Convert confidence to bucket key."""
        return DomainCalibrationEngine.get_bucket_key(confidence)

    def record_domain_prediction(
        self, agent_name: str, domain: str, confidence: float, correct: bool
    ) -> None:
        """Record a domain-specific prediction."""
        self._domain_calibration_engine.record_prediction(agent_name, domain, confidence, correct)

    def get_domain_calibration(self, agent_name: str, domain: str | None = None) -> dict[str, Any]:
        """Get calibration statistics for an agent."""
        return self._domain_calibration_engine.get_domain_stats(agent_name, domain)

    def get_calibration_by_bucket(
        self, agent_name: str, domain: str | None = None
    ) -> list[dict[str, Any]]:
        """Get calibration broken down by confidence bucket."""
        buckets = self._domain_calibration_engine.get_calibration_curve(agent_name, domain)
        return [
            {
                "bucket_key": b.bucket_key,
                "bucket_start": b.bucket_start,
                "bucket_end": b.bucket_end,
                "predictions": b.predictions,
                "correct": b.correct,
                "accuracy": b.accuracy,
                "expected_accuracy": b.expected_accuracy,
                "brier_score": b.brier_score,
            }
            for b in buckets
        ]

    def get_expected_calibration_error(self, agent_name: str) -> float:
        """Calculate Expected Calibration Error."""
        return self._domain_calibration_engine.get_expected_calibration_error(agent_name)

    def get_best_domains(self, agent_name: str, limit: int = 5) -> list[tuple[str, float]]:
        """Get domains where agent is best calibrated."""
        return self._domain_calibration_engine.get_best_domains(agent_name, limit=limit)

    # =========================================================================
    # Relationship Delegates (delegates to RelationshipTracker)
    # =========================================================================

    def update_relationship(
        self,
        agent_a: str,
        agent_b: str,
        debate_increment: int = 0,
        agreement_increment: int = 0,
        critique_a_to_b: int = 0,
        critique_b_to_a: int = 0,
        critique_accepted_a_to_b: int = 0,
        critique_accepted_b_to_a: int = 0,
        position_change_a_after_b: int = 0,
        position_change_b_after_a: int = 0,
        a_win: int = 0,
        b_win: int = 0,
    ) -> None:
        """Update relationship stats between two agents."""
        self.relationship_tracker.update_relationship(
            agent_a=agent_a,
            agent_b=agent_b,
            debate_increment=debate_increment,
            agreement_increment=agreement_increment,
            critique_a_to_b=critique_a_to_b,
            critique_b_to_a=critique_b_to_a,
            critique_accepted_a_to_b=critique_accepted_a_to_b,
            critique_accepted_b_to_a=critique_accepted_b_to_a,
            position_change_a_after_b=position_change_a_after_b,
            position_change_b_after_a=position_change_b_after_a,
            a_win=a_win,
            b_win=b_win,
        )

    def update_relationships_batch(self, updates: list[dict[str, Any]]) -> None:
        """Batch update multiple agent relationships."""
        self.relationship_tracker.update_batch(updates)

    def get_relationship_raw(self, agent_a: str, agent_b: str) -> dict[str, Any] | None:
        """Get raw relationship data between two agents."""
        stats = self.relationship_tracker.get_raw(agent_a, agent_b)
        if stats is None:
            return None
        return {
            "agent_a": stats.agent_a,
            "agent_b": stats.agent_b,
            "debate_count": stats.debate_count,
            "agreement_count": stats.agreement_count,
            "critique_count_a_to_b": stats.critique_count_a_to_b,
            "critique_count_b_to_a": stats.critique_count_b_to_a,
            "critique_accepted_a_to_b": stats.critique_accepted_a_to_b,
            "critique_accepted_b_to_a": stats.critique_accepted_b_to_a,
            "position_changes_a_after_b": stats.position_changes_a_after_b,
            "position_changes_b_after_a": stats.position_changes_b_after_a,
            "a_wins_over_b": stats.a_wins_over_b,
            "b_wins_over_a": stats.b_wins_over_a,
        }

    def get_all_relationships_for_agent(
        self, agent_name: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get all relationships involving an agent."""
        _validate_agent_name(agent_name)
        stats_list = self.relationship_tracker.get_all_for_agent(agent_name, limit)
        return [
            {
                "agent_a": s.agent_a,
                "agent_b": s.agent_b,
                "debate_count": s.debate_count,
                "agreement_count": s.agreement_count,
                "critique_count_a_to_b": s.critique_count_a_to_b,
                "critique_count_b_to_a": s.critique_count_b_to_a,
                "critique_accepted_a_to_b": s.critique_accepted_a_to_b,
                "critique_accepted_b_to_a": s.critique_accepted_b_to_a,
                "position_changes_a_after_b": s.position_changes_a_after_b,
                "position_changes_b_after_a": s.position_changes_b_after_a,
                "a_wins_over_b": s.a_wins_over_b,
                "b_wins_over_a": s.b_wins_over_a,
            }
            for s in stats_list
        ]

    def compute_relationship_metrics(self, agent_a: str, agent_b: str) -> dict[str, Any]:
        """Compute rivalry and alliance scores between two agents."""
        metrics = self.relationship_tracker.compute_metrics(agent_a, agent_b)
        return {
            "agent_a": metrics.agent_a,
            "agent_b": metrics.agent_b,
            "rivalry_score": metrics.rivalry_score,
            "alliance_score": metrics.alliance_score,
            "relationship": metrics.relationship,
            "debate_count": metrics.debate_count,
            "agreement_rate": metrics.agreement_rate,
            "head_to_head": metrics.head_to_head,
        }

    def _compute_metrics_from_raw(
        self, agent_a: str, agent_b: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        """Compute relationship metrics from raw data (no database call)."""
        stats = RelationshipStats(
            agent_a=raw.get("agent_a", agent_a),
            agent_b=raw.get("agent_b", agent_b),
            debate_count=raw.get("debate_count", 0),
            agreement_count=raw.get("agreement_count", 0),
            critique_count_a_to_b=raw.get("critique_count_a_to_b", 0),
            critique_count_b_to_a=raw.get("critique_count_b_to_a", 0),
            critique_accepted_a_to_b=raw.get("critique_accepted_a_to_b", 0),
            critique_accepted_b_to_a=raw.get("critique_accepted_b_to_a", 0),
            position_changes_a_after_b=raw.get("position_changes_a_after_b", 0),
            position_changes_b_after_a=raw.get("position_changes_b_after_a", 0),
            a_wins_over_b=raw.get("a_wins_over_b", 0),
            b_wins_over_a=raw.get("b_wins_over_a", 0),
        )
        metrics = self.relationship_tracker._compute_metrics_from_stats(agent_a, agent_b, stats)
        return {
            "agent_a": metrics.agent_a,
            "agent_b": metrics.agent_b,
            "rivalry_score": metrics.rivalry_score,
            "alliance_score": metrics.alliance_score,
            "relationship": metrics.relationship,
            "debate_count": metrics.debate_count,
        }

    def get_rivals(self, agent_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get agent's top rivals by rivalry score."""
        _validate_agent_name(agent_name)
        metrics_list = self.relationship_tracker.get_rivals(agent_name, limit)
        return [
            {
                "agent_a": m.agent_a,
                "agent_b": m.agent_b,
                "rivalry_score": m.rivalry_score,
                "alliance_score": m.alliance_score,
                "relationship": m.relationship,
                "debate_count": m.debate_count,
            }
            for m in metrics_list
        ]

    def get_allies(self, agent_name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get agent's top allies by alliance score."""
        _validate_agent_name(agent_name)
        metrics_list = self.relationship_tracker.get_allies(agent_name, limit)
        return [
            {
                "agent_a": m.agent_a,
                "agent_b": m.agent_b,
                "rivalry_score": m.rivalry_score,
                "alliance_score": m.alliance_score,
                "relationship": m.relationship,
                "debate_count": m.debate_count,
            }
            for m in metrics_list
        ]

    # =========================================================================
    # Red Team Delegates (delegates to RedTeamIntegrator)
    # =========================================================================

    def record_redteam_result(
        self,
        agent_name: str,
        robustness_score: float,
        successful_attacks: int,
        total_attacks: int,
        critical_vulnerabilities: int = 0,
        session_id: str | None = None,
    ) -> float:
        """Record red team results and adjust ELO based on vulnerability."""
        return self.redteam_integrator.record_result(
            agent_name=agent_name,
            robustness_score=robustness_score,
            successful_attacks=successful_attacks,
            total_attacks=total_attacks,
            critical_vulnerabilities=critical_vulnerabilities,
            session_id=session_id,
        )

    def get_vulnerability_summary(self, agent_name: str) -> dict[str, Any]:
        """Get summary of agent's red team history."""
        summary = self.redteam_integrator.get_vulnerability_summary(agent_name)
        return {
            "redteam_sessions": summary.redteam_sessions,
            "total_elo_impact": summary.total_elo_impact,
            "last_session": summary.last_session,
        }

    # =========================================================================
    # Verification Delegates (delegates to verification module)
    # =========================================================================

    def update_from_verification(
        self,
        agent_name: str,
        domain: str,
        verified_count: int,
        disproven_count: int = 0,
        k_factor: float = 16.0,
    ) -> float:
        """Adjust ELO based on formal verification results."""
        _validate_agent_name(agent_name)

        if verified_count == 0 and disproven_count == 0:
            return 0.0

        net_change = calculate_verification_elo_change(verified_count, disproven_count, k_factor)
        rating = self.get_rating(agent_name, use_cache=False)
        old_elo = rating.elo

        if net_change != 0.0:
            update_rating_from_verification(rating, domain, net_change, DEFAULT_ELO)
            self._save_rating(rating)

        self._record_elo_history(
            agent_name,
            rating.elo,
            debate_id=f"verification:{domain}:{verified_count}v{disproven_count}d",
        )

        logger.info(
            "verification_elo_update agent=%s domain=%s verified=%d disproven=%d "
            "change=%.1f old_elo=%.1f new_elo=%.1f",
            agent_name,
            domain,
            verified_count,
            disproven_count,
            net_change,
            old_elo,
            rating.elo,
        )
        return net_change

    def get_verification_impact(self, agent_name: str) -> dict[str, Any]:
        """Get summary of verification impact on an agent's ELO."""
        _validate_agent_name(agent_name)
        return calculate_verification_impact(self._db, agent_name)

    # =========================================================================
    # Analysis Delegates (delegates to elo_analysis)
    # =========================================================================

    def update_voting_accuracy(
        self,
        agent_name: str,
        voted_for_consensus: bool,
        domain: str = "general",
        debate_id: str | None = None,
        apply_elo_bonus: bool = True,
        bonus_k_factor: float = 4.0,
    ) -> float:
        """Update an agent's voting accuracy and optionally apply ELO bonus."""
        return _update_voting_accuracy(
            self,
            agent_name,
            voted_for_consensus,
            domain,
            debate_id,
            apply_elo_bonus,
            bonus_k_factor,
        )

    def get_voting_accuracy(self, agent_name: str) -> dict[str, Any]:
        """Get voting accuracy statistics for an agent."""
        return _get_voting_accuracy(self, agent_name)

    def get_voting_accuracy_batch(self, agent_names: list[str]) -> dict[str, dict[str, Any]]:
        """Get voting accuracy statistics for multiple agents in one query."""
        return _get_voting_accuracy_batch(self, agent_names)

    def get_learning_efficiency(
        self, agent_name: str, domain: str | None = None, window_debates: int = 20
    ) -> dict[str, Any]:
        """Compute learning efficiency for an agent based on ELO improvement rate."""
        return _get_learning_efficiency(self, agent_name, domain, window_debates)

    def get_learning_efficiency_batch(
        self, agent_names: list[str], domain: str | None = None, window_debates: int = 20
    ) -> dict[str, dict[str, Any]]:
        """Get learning efficiency for multiple agents with batch optimization."""
        return _get_learning_efficiency_batch(self, agent_names, domain, window_debates)

    def _compute_elo_gain_rate(self, elo_values: list[float]) -> float:
        """Compute average ELO gain per debate from history."""
        return _compute_elo_gain_rate_fn(elo_values)

    def _compute_consistency_score(self, elo_values: list[float]) -> float:
        """Compute consistency of improvement (0-1 scale)."""
        return _compute_consistency_score_fn(elo_values)

    def _categorize_learning(self, gain_rate: float, consistency: float) -> str:
        """Categorize learning efficiency based on metrics."""
        return _categorize_learning_fn(gain_rate, consistency)

    def record_quality_score(
        self,
        agent_name: str,
        debate_id: str,
        score: float,
        dimension_scores: dict[str, float] | None = None,
    ) -> None:
        """Record an LLM judge quality score for an agent's debate contribution.

        Stores the quality assessment in ELO history for tracking quality trends.
        Does not directly modify ELO ratings — quality data is informational.

        Args:
            agent_name: Name of the agent
            debate_id: ID of the debate evaluated
            score: Overall quality score (1-5 scale)
            dimension_scores: Optional per-dimension scores
        """
        _validate_agent_name(agent_name)
        self._record_elo_history(
            agent_name,
            self.get_rating(agent_name).elo,
            debate_id=f"quality:{debate_id}:score={score:.2f}",
        )
        logger.info(
            "quality_score_recorded agent=%s debate=%s score=%.2f",
            agent_name,
            debate_id,
            score,
        )

    def apply_learning_bonus(
        self,
        agent_name: str,
        domain: str = "general",
        debate_id: str | None = None,
        bonus_factor: float = 0.5,
    ) -> float:
        """Apply ELO bonus based on agent's learning efficiency."""
        return _apply_learning_bonus(self, agent_name, domain, debate_id, bonus_factor)
