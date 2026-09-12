"""
ELO Repository for agent ratings and match history.

Provides data access for agent ELO ratings, match results,
and leaderboard queries with caching support.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from aragora.config import (
    DB_TIMEOUT_SECONDS,
    ELO_INITIAL_RATING,
)
from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.utils.cache import TTLCache

from .base import BaseRepository

logger = logging.getLogger(__name__)

DEFAULT_ELO = ELO_INITIAL_RATING


@dataclass
class RatingEntity:
    """
    Agent rating entity.

    Represents an agent's ELO rating and statistics.
    """

    agent_name: str
    elo: float = DEFAULT_ELO
    domain_elos: dict[str, float] = field(default_factory=dict)
    wins: int = 0
    losses: int = 0
    draws: int = 0
    debates_count: int = 0
    critiques_accepted: int = 0
    critiques_total: int = 0
    calibration_correct: int = 0
    calibration_total: int = 0
    calibration_brier_sum: float = 0.0
    updated_at: datetime | None = None

    @property
    def id(self) -> str:
        """Entity ID is the agent name."""
        return self.agent_name

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        total = self.wins + self.losses + self.draws
        return self.wins / total if total > 0 else 0.0

    @property
    def games_played(self) -> int:
        """Total games played."""
        return self.wins + self.losses + self.draws

    @property
    def critique_acceptance_rate(self) -> float:
        """Calculate critique acceptance rate."""
        if self.critiques_total == 0:
            return 0.0
        return self.critiques_accepted / self.critiques_total


@dataclass
class MatchEntity:
    """
    Match result entity.

    Represents a debate match between agents.
    """

    id: int
    debate_id: str
    winner: str | None  # None for draw
    participants: list[str]
    domain: str | None
    scores: dict[str, float]
    elo_changes: dict[str, float] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass
class LeaderboardEntry:
    """Entry in the leaderboard."""

    rank: int
    agent_name: str
    elo: float
    wins: int
    losses: int
    draws: int
    win_rate: float
    games_played: int


class EloRepository(BaseRepository[RatingEntity]):
    """
    Repository for ELO ratings and match history.

    Provides CRUD operations for agent ratings and match results,
    plus leaderboard and statistics queries.

    Usage:
        repo = EloRepository()

        # Get agent rating
        rating = repo.get_rating("gpt-4")

        # Update rating
        repo.save_rating(rating)

        # Get leaderboard
        leaderboard = repo.get_leaderboard(limit=10)

        # Record match
        repo.record_match(match)
    """

    # Cache for leaderboard (shared across instances)
    _leaderboard_cache: TTLCache = TTLCache(maxsize=50, ttl_seconds=300)
    _rating_cache: TTLCache = TTLCache(maxsize=200, ttl_seconds=120)

    def __init__(
        self,
        db_path: str | Path | None = None,
        timeout: float = DB_TIMEOUT_SECONDS,
    ) -> None:
        """
        Initialize the ELO repository.

        Args:
            db_path: Path to the SQLite database file. Defaults to get_db_path(DatabaseType.ELO).
            timeout: Connection timeout in seconds.
        """
        if db_path is None:
            db_path = get_db_path(DatabaseType.ELO)
        super().__init__(db_path, timeout)

    @property
    def _table_name(self) -> str:
        return "ratings"

    @property
    def _entity_name(self) -> str:
        return "Rating"

    def _ensure_schema(self) -> None:
        """Create database schema if needed."""
        with self._connection() as conn:
            # Ratings table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ratings (
                    agent_name TEXT PRIMARY KEY,
                    elo REAL DEFAULT 1500,
                    domain_elos TEXT,
                    wins INTEGER DEFAULT 0,
                    losses INTEGER DEFAULT 0,
                    draws INTEGER DEFAULT 0,
                    debates_count INTEGER DEFAULT 0,
                    critiques_accepted INTEGER DEFAULT 0,
                    critiques_total INTEGER DEFAULT 0,
                    calibration_correct INTEGER DEFAULT 0,
                    calibration_total INTEGER DEFAULT 0,
                    calibration_brier_sum REAL DEFAULT 0.0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Matches table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS matches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    debate_id TEXT UNIQUE,
                    winner TEXT,
                    participants TEXT,
                    domain TEXT,
                    scores TEXT,
                    elo_changes TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # ELO history table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS elo_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    elo REAL NOT NULL,
                    debate_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_winner ON matches(winner)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_created ON matches(created_at)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_elo_history_agent ON elo_history(agent_name)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ratings_elo ON ratings(elo DESC)")

            conn.commit()

    def _to_entity(self, row: Any) -> RatingEntity:
        """Convert database row to RatingEntity."""
        updated_at = row["updated_at"]
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except (ValueError, TypeError):
                updated_at = None

        domain_elos = {}
        if row["domain_elos"]:
            try:
                domain_elos = json.loads(row["domain_elos"])
            except (json.JSONDecodeError, TypeError):
                domain_elos = {}

        return RatingEntity(
            agent_name=row["agent_name"],
            elo=row["elo"] or DEFAULT_ELO,
            domain_elos=domain_elos,
            wins=row["wins"] or 0,
            losses=row["losses"] or 0,
            draws=row["draws"] or 0,
            debates_count=row["debates_count"] or 0,
            critiques_accepted=row["critiques_accepted"] or 0,
            critiques_total=row["critiques_total"] or 0,
            calibration_correct=row["calibration_correct"] or 0,
            calibration_total=row["calibration_total"] or 0,
            calibration_brier_sum=row["calibration_brier_sum"] or 0.0,
            updated_at=updated_at,
        )

    def _from_entity(self, entity: RatingEntity) -> dict[str, Any]:
        """Convert RatingEntity to database columns."""
        return {
            "agent_name": entity.agent_name,
            "elo": entity.elo,
            "domain_elos": json.dumps(entity.domain_elos),
            "wins": entity.wins,
            "losses": entity.losses,
            "draws": entity.draws,
            "debates_count": entity.debates_count,
            "critiques_accepted": entity.critiques_accepted,
            "critiques_total": entity.critiques_total,
            "calibration_correct": entity.calibration_correct,
            "calibration_total": entity.calibration_total,
            "calibration_brier_sum": entity.calibration_brier_sum,
            "updated_at": (
                entity.updated_at.isoformat() if entity.updated_at else datetime.now().isoformat()
            ),
        }

    def get(self, entity_id: str) -> RatingEntity | None:
        """
        Get rating by agent name (overrides base to use agent_name).

        Args:
            entity_id: Agent name.

        Returns:
            RatingEntity or None.
        """
        row = self._fetch_one(
            "SELECT * FROM ratings WHERE agent_name = ?",
            (entity_id,),
        )
        return self._to_entity(row) if row else None

    def get_rating(self, agent_name: str, use_cache: bool = True) -> RatingEntity:
        """
        Get or create rating for an agent.

        Args:
            agent_name: Name of the agent.
            use_cache: Whether to use cached value.

        Returns:
            RatingEntity (creates new one if not found).
        """
        cache_key = f"rating:{agent_name}"

        if use_cache:
            cached = self._rating_cache.get(cache_key)
            if cached is not None:
                return cached

        entity = self.get(agent_name)
        if entity is None:
            entity = RatingEntity(agent_name=agent_name)

        if use_cache:
            self._rating_cache.set(cache_key, entity)

        return entity

    def save(self, entity: RatingEntity) -> str:
        """
        Save a rating entity.

        Args:
            entity: RatingEntity to save.

        Returns:
            Agent name.
        """
        data = self._from_entity(entity)

        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO ratings (
                    agent_name, elo, domain_elos, wins, losses, draws,
                    debates_count, critiques_accepted, critiques_total,
                    calibration_correct, calibration_total, calibration_brier_sum,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    data["agent_name"],
                    data["elo"],
                    data["domain_elos"],
                    data["wins"],
                    data["losses"],
                    data["draws"],
                    data["debates_count"],
                    data["critiques_accepted"],
                    data["critiques_total"],
                    data["calibration_correct"],
                    data["calibration_total"],
                    data["calibration_brier_sum"],
                    data["updated_at"],
                ),
            )

        # Invalidate caches
        self._rating_cache.invalidate(f"rating:{entity.agent_name}")
        self._leaderboard_cache.clear()

        return entity.agent_name

    def save_rating(self, entity: RatingEntity) -> str:
        """Alias for save() for clarity."""
        return self.save(entity)

    def get_leaderboard(
        self,
        limit: int = 20,
        offset: int = 0,
        min_games: int = 0,
        use_cache: bool = True,
    ) -> list[LeaderboardEntry]:
        """
        Get the ELO leaderboard.

        Args:
            limit: Maximum entries to return.
            offset: Pagination offset.
            min_games: Minimum games played to be included.
            use_cache: Whether to use cached results.

        Returns:
            List of LeaderboardEntry objects.
        """
        cache_key = f"leaderboard:{limit}:{offset}:{min_games}"

        if use_cache:
            cached = self._leaderboard_cache.get(cache_key)
            if cached is not None:
                return cached

        rows = self._fetch_all(
            """
            SELECT agent_name, elo, wins, losses, draws
            FROM ratings
            WHERE (wins + losses + draws) >= ?
            ORDER BY elo DESC
            LIMIT ? OFFSET ?
            """,
            (min_games, limit, offset),
        )

        entries = []
        for i, row in enumerate(rows):
            games = row["wins"] + row["losses"] + row["draws"]
            entries.append(
                LeaderboardEntry(
                    rank=offset + i + 1,
                    agent_name=row["agent_name"],
                    elo=row["elo"],
                    wins=row["wins"],
                    losses=row["losses"],
                    draws=row["draws"],
                    win_rate=row["wins"] / games if games > 0 else 0.0,
                    games_played=games,
                )
            )

        if use_cache:
            self._leaderboard_cache.set(cache_key, entries)

        return entries

    def get_top_agents(self, n: int = 10) -> list[tuple[str, float]]:
        """
        Get top N agents by ELO.

        Args:
            n: Number of top agents.

        Returns:
            List of (agent_name, elo) tuples.
        """
        rows = self._fetch_all(
            "SELECT agent_name, elo FROM ratings ORDER BY elo DESC LIMIT ?",
            (n,),
        )
        return [(row["agent_name"], row["elo"]) for row in rows]

    # ===== Match Operations =====

    def _match_to_dict(self, row: Any) -> MatchEntity:
        """Convert match row to MatchEntity."""
        created_at = row["created_at"]
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except (ValueError, TypeError):
                created_at = None

        participants = []
        if row["participants"]:
            try:
                participants = json.loads(row["participants"])
            except (json.JSONDecodeError, TypeError):
                participants = []

        scores = {}
        if row["scores"]:
            try:
                scores = json.loads(row["scores"])
            except (json.JSONDecodeError, TypeError):
                scores = {}

        elo_changes = {}
        if row["elo_changes"]:
            try:
                elo_changes = json.loads(row["elo_changes"])
            except (json.JSONDecodeError, TypeError):
                elo_changes = {}

        return MatchEntity(
            id=row["id"],
            debate_id=row["debate_id"],
            winner=row["winner"],
            participants=participants,
            domain=row["domain"],
            scores=scores,
            elo_changes=elo_changes,
            created_at=created_at,
        )

    def record_match(
        self,
        debate_id: str,
        winner: str | None,
        participants: list[str],
        scores: dict[str, float],
        elo_changes: dict[str, float],
        domain: str | None = None,
    ) -> int:
        """
        Record a match result.

        Args:
            debate_id: Unique debate identifier.
            winner: Winning agent name or None for draw.
            participants: List of participating agent names.
            scores: Agent scores {agent_name: score}.
            elo_changes: ELO changes {agent_name: delta}.
            domain: Optional domain/topic.

        Returns:
            Match ID.
        """
        with self._transaction() as conn:
            cursor = conn.execute(
                """
                INSERT INTO matches (
                    debate_id, winner, participants, domain, scores, elo_changes
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    debate_id,
                    winner,
                    json.dumps(participants),
                    domain,
                    json.dumps(scores),
                    json.dumps(elo_changes),
                ),
            )

            # Record ELO history for each participant
            for agent, change in elo_changes.items():
                rating = self.get_rating(agent, use_cache=False)
                new_elo = rating.elo + change
                conn.execute(
                    """
                    INSERT INTO elo_history (agent_name, elo, debate_id)
                    VALUES (?, ?, ?)
                    """,
                    (agent, new_elo, debate_id),
                )

            match_id = cursor.lastrowid
            if match_id is None:
                raise RuntimeError("SQLite did not return an ID for the recorded match")
            return match_id

    def get_match(self, debate_id: str) -> MatchEntity | None:
        """
        Get a match by debate ID.

        Args:
            debate_id: Debate identifier.

        Returns:
            MatchEntity or None.
        """
        row = self._fetch_one(
            "SELECT * FROM matches WHERE debate_id = ?",
            (debate_id,),
        )
        return self._match_to_dict(row) if row else None

    def get_recent_matches(
        self,
        limit: int = 20,
        offset: int = 0,
        agent_name: str | None = None,
    ) -> list[MatchEntity]:
        """
        Get recent matches, optionally filtered by agent.

        Args:
            limit: Maximum matches to return.
            offset: Pagination offset.
            agent_name: Optional filter by participating agent.

        Returns:
            List of MatchEntity objects.
        """
        if agent_name:
            # Filter by agent participation
            rows = self._fetch_all(
                """
                SELECT * FROM matches
                WHERE participants LIKE ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (f'%"{agent_name}"%', limit, offset),
            )
        else:
            rows = self._fetch_all(
                """
                SELECT * FROM matches
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )

        return [self._match_to_dict(row) for row in rows]

    def get_head_to_head(self, agent_a: str, agent_b: str) -> dict[str, Any]:
        """
        Get head-to-head statistics between two agents.

        Args:
            agent_a: First agent name.
            agent_b: Second agent name.

        Returns:
            Dict with wins_a, wins_b, draws, total_matches.
        """
        rows = self._fetch_all(
            """
            SELECT winner FROM matches
            WHERE participants LIKE ? AND participants LIKE ?
            """,
            (f'%"{agent_a}"%', f'%"{agent_b}"%'),
        )

        wins_a = 0
        wins_b = 0
        draws = 0

        for row in rows:
            if row["winner"] == agent_a:
                wins_a += 1
            elif row["winner"] == agent_b:
                wins_b += 1
            else:
                draws += 1

        return {
            "agent_a": agent_a,
            "agent_b": agent_b,
            "wins_a": wins_a,
            "wins_b": wins_b,
            "draws": draws,
            "total_matches": wins_a + wins_b + draws,
        }

    def get_elo_history(
        self,
        agent_name: str,
        limit: int = 50,
    ) -> list[tuple[float, str, str | None]]:
        """
        Get ELO history for an agent.

        Args:
            agent_name: Agent name.
            limit: Maximum history entries.

        Returns:
            List of (elo, timestamp, debate_id) tuples.
        """
        rows = self._fetch_all(
            """
            SELECT elo, created_at, debate_id
            FROM elo_history
            WHERE agent_name = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (agent_name, limit),
        )

        return [(row["elo"], row["created_at"], row["debate_id"]) for row in rows]

    def get_agent_stats(self, agent_name: str) -> dict[str, Any]:
        """
        Get comprehensive statistics for an agent.

        Args:
            agent_name: Agent name.

        Returns:
            Dict with rating, match history, and statistics.
        """
        rating = self.get_rating(agent_name)
        recent_matches = self.get_recent_matches(limit=10, agent_name=agent_name)
        elo_history = self.get_elo_history(agent_name, limit=20)

        return {
            "agent_name": agent_name,
            "elo": rating.elo,
            "wins": rating.wins,
            "losses": rating.losses,
            "draws": rating.draws,
            "games_played": rating.games_played,
            "win_rate": rating.win_rate,
            "critique_acceptance_rate": rating.critique_acceptance_rate,
            "recent_matches": [
                {
                    "debate_id": m.debate_id,
                    "winner": m.winner,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in recent_matches
            ],
            "elo_history": [
                {"elo": elo, "timestamp": ts, "debate_id": did} for elo, ts, did in elo_history
            ],
        }

    def clear_caches(self) -> None:
        """Clear all caches (useful for testing)."""
        self._rating_cache.clear()
        self._leaderboard_cache.clear()
