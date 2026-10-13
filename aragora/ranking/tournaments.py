"""
Tournament Management System.

Provides tournament bracket generation, match tracking, and standings
calculation for agent competitions.

Hardening features:
- Input validation for participants and bracket types
- Connection pooling with context managers
- Tournament history/event logging
- Double elimination support
- Concurrent access protection
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from collections.abc import Generator

logger = logging.getLogger(__name__)

# =============================================================================
# Validation Constants
# =============================================================================

# Allowed bracket types
VALID_BRACKET_TYPES = {"round_robin", "single_elimination", "double_elimination"}

# Participant name validation
PARTICIPANT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_PARTICIPANTS = 128
MIN_PARTICIPANTS = 2

# Tournament name validation
MAX_TOURNAMENT_NAME_LENGTH = 256


class TournamentStatus(str, Enum):
    """Tournament status enumeration."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TournamentEvent(str, Enum):
    """Types of tournament events for history tracking."""

    CREATED = "created"
    STARTED = "started"
    MATCH_COMPLETED = "match_completed"
    ROUND_ADVANCED = "round_advanced"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class TournamentError(Exception):
    """Base exception for tournament errors."""

    pass


class ValidationError(TournamentError):
    """Invalid input data."""

    pass


class TournamentNotFoundError(TournamentError):
    """Tournament does not exist."""

    pass


class MatchNotFoundError(TournamentError):
    """Match does not exist."""

    pass


class InvalidStateError(TournamentError):
    """Operation not allowed in current state."""

    pass


@dataclass
class TournamentStanding:
    """An agent's standing in a tournament."""

    agent: str
    wins: int = 0
    losses: int = 0
    draws: int = 0
    points: float = 0.0
    total_score: float = 0.0

    @property
    def win_rate(self) -> float:
        """Calculate win rate."""
        total = self.wins + self.losses + self.draws
        if total == 0:
            return 0.0
        return self.wins / total


@dataclass
class TournamentMatch:
    """A match in a tournament."""

    match_id: str
    tournament_id: str
    round_num: int
    agent1: str
    agent2: str
    winner: str | None = None
    score1: float = 0.0
    score2: float = 0.0
    debate_id: str | None = None
    bracket_position: int = 0  # Position in bracket (for elimination)
    is_losers_bracket: bool = False  # For double elimination
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: str | None = None


@dataclass
class TournamentHistoryEntry:
    """An event in tournament history for audit/replay."""

    entry_id: str
    tournament_id: str
    event_type: TournamentEvent
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "entry_id": self.entry_id,
            "tournament_id": self.tournament_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class Tournament:
    """A tournament configuration."""

    tournament_id: str
    name: str
    participants: list[str]
    bracket_type: str = "round_robin"  # round_robin, single_elimination, double_elimination
    rounds_completed: int = 0
    total_rounds: int = 0
    status: str = "pending"  # pending, in_progress, completed
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TournamentManager:
    """
    Manages tournaments, brackets, and standings.

    Features:
    - Thread-safe connection management via SQLiteStore
    - Input validation for participants and tournament names
    - Tournament history/event logging
    - Support for round-robin, single elimination, and double elimination
    - Proper state transition management

    Example:
        manager = TournamentManager(db_path="tournaments/contest.db")
        tournament = manager.create_tournament(
            name="Weekly Championship",
            participants=["claude", "gpt4", "gemini"],
            bracket_type="round_robin"
        )
        standings = manager.get_current_standings()
    """

    SCHEMA_NAME = "ranking_tournaments"
    SCHEMA_VERSION = 1

    INITIAL_SCHEMA = """
        CREATE TABLE IF NOT EXISTS tournaments (
            tournament_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            bracket_type TEXT DEFAULT 'round_robin',
            participants TEXT NOT NULL,
            rounds_completed INTEGER DEFAULT 0,
            total_rounds INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            tournament_id TEXT NOT NULL,
            round_num INTEGER NOT NULL,
            agent1 TEXT NOT NULL,
            agent2 TEXT NOT NULL,
            winner TEXT,
            score1 REAL DEFAULT 0.0,
            score2 REAL DEFAULT 0.0,
            debate_id TEXT,
            bracket_position INTEGER DEFAULT 0,
            is_losers_bracket INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id)
        );

        CREATE TABLE IF NOT EXISTS tournament_history (
            entry_id TEXT PRIMARY KEY,
            tournament_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            details TEXT DEFAULT '{}',
            FOREIGN KEY (tournament_id) REFERENCES tournaments(tournament_id)
        );

        CREATE INDEX IF NOT EXISTS idx_matches_tournament
        ON matches(tournament_id);

        CREATE INDEX IF NOT EXISTS idx_matches_agents
        ON matches(agent1, agent2);

        CREATE INDEX IF NOT EXISTS idx_history_tournament
        ON tournament_history(tournament_id);
    """

    def __init__(
        self,
        db_path: str | None = None,
        nomic_dir: Path | None = None,
        elo_system: Any | None = None,
    ):
        """
        Initialize TournamentManager.

        Args:
            db_path: Path to tournament SQLite database
            nomic_dir: Base directory for tournament storage
            elo_system: Optional EloSystem instance for rating updates
        """
        from aragora.storage.base_store import SQLiteStore

        if db_path:
            self.db_path = Path(db_path)
        elif nomic_dir:
            self.db_path = Path(nomic_dir) / "tournaments" / "default.db"
        else:
            from aragora.persistence.db_config import get_nomic_dir

            self.db_path = get_nomic_dir() / "tournaments" / "default.db"

        # Create SQLiteStore-based database wrapper
        class _TournamentDB(SQLiteStore):
            SCHEMA_NAME = TournamentManager.SCHEMA_NAME
            SCHEMA_VERSION = TournamentManager.SCHEMA_VERSION
            INITIAL_SCHEMA = TournamentManager.INITIAL_SCHEMA

        self._db = _TournamentDB(str(self.db_path), timeout=30.0)
        self._lock = threading.RLock()
        self._elo_system = elo_system

    def set_elo_system(self, elo_system: Any) -> None:
        """Set or update the ELO system for rating integration.

        Args:
            elo_system: EloSystem instance for rating updates
        """
        self._elo_system = elo_system

    def get_elo_system(self) -> Any | None:
        """Get the current ELO system if configured."""
        return self._elo_system

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Thread-safe connection context manager."""
        with self._db.connection() as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    # =========================================================================
    # Validation Methods
    # =========================================================================

    def _validate_tournament_name(self, name: str) -> None:
        """Validate tournament name."""
        if not name or not name.strip():
            raise ValidationError("Tournament name cannot be empty")
        if len(name) > MAX_TOURNAMENT_NAME_LENGTH:
            raise ValidationError(
                f"Tournament name exceeds {MAX_TOURNAMENT_NAME_LENGTH} characters"
            )

    def _validate_participants(self, participants: list[str]) -> None:
        """Validate participant list."""
        if not participants:
            raise ValidationError("Participants list cannot be empty")
        if len(participants) < MIN_PARTICIPANTS:
            raise ValidationError(f"Need at least {MIN_PARTICIPANTS} participants")
        if len(participants) > MAX_PARTICIPANTS:
            raise ValidationError(f"Cannot exceed {MAX_PARTICIPANTS} participants")

        seen = set()
        for p in participants:
            if not p or not p.strip():
                raise ValidationError("Participant name cannot be empty")
            if not PARTICIPANT_NAME_PATTERN.match(p):
                raise ValidationError(
                    f"Invalid participant name '{p}'. "
                    "Must be 1-64 alphanumeric characters, underscores, or hyphens."
                )
            if p in seen:
                raise ValidationError(f"Duplicate participant: {p}")
            seen.add(p)

    def _validate_bracket_type(self, bracket_type: str) -> None:
        """Validate bracket type."""
        if bracket_type not in VALID_BRACKET_TYPES:
            raise ValidationError(
                f"Invalid bracket type '{bracket_type}'. "
                f"Must be one of: {', '.join(VALID_BRACKET_TYPES)}"
            )

    def _validate_score(self, score: float) -> float:
        """Validate and normalize score."""
        if not isinstance(score, (int, float)):
            raise ValidationError(f"Score must be a number, got {type(score)}")
        if score < 0:
            raise ValidationError("Score cannot be negative")
        return float(score)

    # =========================================================================
    # History Management
    # =========================================================================

    def _log_event(
        self,
        conn: sqlite3.Connection,
        tournament_id: str,
        event_type: TournamentEvent,
        details: dict | None = None,
    ) -> None:
        """Log a tournament event to history."""
        entry_id = f"evt_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO tournament_history (entry_id, tournament_id, event_type, details)
            VALUES (?, ?, ?, ?)
            """,
            (entry_id, tournament_id, event_type.value, json.dumps(details or {})),
        )

    def get_tournament_history(
        self,
        tournament_id: str,
        limit: int = 100,
    ) -> list[TournamentHistoryEntry]:
        """Get tournament event history.

        Args:
            tournament_id: Tournament identifier
            limit: Maximum entries to return

        Returns:
            List of TournamentHistoryEntry, most recent first
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT entry_id, tournament_id, event_type, timestamp, details
                FROM tournament_history
                WHERE tournament_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (tournament_id, limit),
            )

            history = []
            for row in cursor:
                history.append(
                    TournamentHistoryEntry(
                        entry_id=row["entry_id"],
                        tournament_id=row["tournament_id"],
                        event_type=TournamentEvent(row["event_type"]),
                        timestamp=row["timestamp"],
                        details=json.loads(row["details"]),
                    )
                )

            return history

    def create_tournament(
        self,
        name: str,
        participants: list[str],
        bracket_type: str = "round_robin",
    ) -> Tournament:
        """
        Create a new tournament.

        Args:
            name: Tournament name
            participants: List of agent names
            bracket_type: Type of bracket (round_robin, single_elimination, double_elimination)

        Returns:
            Created Tournament object

        Raises:
            ValidationError: If inputs are invalid
        """
        # Validate inputs
        self._validate_tournament_name(name)
        self._validate_participants(participants)
        self._validate_bracket_type(bracket_type)

        tournament_id = f"tournament_{uuid.uuid4().hex[:8]}"

        # Calculate total rounds based on bracket type
        n = len(participants)
        if bracket_type == "round_robin":
            total_rounds = n - 1 if n > 1 else 0
        elif bracket_type == "single_elimination":
            total_rounds = math.ceil(math.log2(n)) if n > 1 else 0
        elif bracket_type == "double_elimination":
            # Double elimination: winners bracket + losers bracket
            total_rounds = math.ceil(math.log2(n)) * 2 if n > 1 else 0
        else:
            total_rounds = n - 1

        tournament = Tournament(
            tournament_id=tournament_id,
            name=name.strip(),
            participants=participants,
            bracket_type=bracket_type,
            total_rounds=total_rounds,
            status=TournamentStatus.PENDING.value,
        )

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO tournaments
                    (tournament_id, name, bracket_type, participants, total_rounds, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tournament.tournament_id,
                        tournament.name,
                        tournament.bracket_type,
                        json.dumps(tournament.participants),
                        tournament.total_rounds,
                        tournament.status,
                        tournament.created_at,
                    ),
                )

                # Log creation event
                self._log_event(
                    conn,
                    tournament_id,
                    TournamentEvent.CREATED,
                    {"name": name, "participants": participants, "bracket_type": bracket_type},
                )

                conn.commit()
                logger.info("Created tournament: %s", tournament_id)

        # Generate initial bracket/matches
        self._generate_matches(tournament)

        return tournament

    def _generate_matches(self, tournament: Tournament) -> None:
        """Generate matches for a tournament based on bracket type."""
        if tournament.bracket_type == "round_robin":
            self._generate_round_robin_matches(tournament)
        elif tournament.bracket_type == "single_elimination":
            self._generate_single_elimination_matches(tournament)
        elif tournament.bracket_type == "double_elimination":
            self._generate_double_elimination_matches(tournament)

    def _generate_round_robin_matches(self, tournament: Tournament) -> None:
        """Generate all matches for round-robin tournament."""
        participants = tournament.participants
        matches = []

        # Round-robin: every participant plays every other participant once
        position = 0
        for i, agent1 in enumerate(participants):
            for agent2 in participants[i + 1 :]:
                match = TournamentMatch(
                    match_id=f"match_{uuid.uuid4().hex[:8]}",
                    tournament_id=tournament.tournament_id,
                    round_num=1,  # All in round 1 for round-robin
                    agent1=agent1,
                    agent2=agent2,
                    bracket_position=position,
                )
                matches.append(match)
                position += 1

        self._insert_matches(matches, tournament.tournament_id)

    def _insert_matches(self, matches: list[TournamentMatch], tournament_id: str) -> None:
        """Insert matches into database."""
        with self._get_connection() as conn:
            for match in matches:
                conn.execute(
                    """
                    INSERT INTO matches
                    (match_id, tournament_id, round_num, agent1, agent2,
                     bracket_position, is_losers_bracket, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match.match_id,
                        match.tournament_id,
                        match.round_num,
                        match.agent1,
                        match.agent2,
                        match.bracket_position,
                        1 if match.is_losers_bracket else 0,
                        match.created_at,
                    ),
                )
            conn.commit()
            logger.info("Generated %s matches for tournament %s", len(matches), tournament_id)

    def _generate_single_elimination_matches(self, tournament: Tournament) -> None:
        """Generate first round matches for single elimination."""
        participants = tournament.participants
        matches = []

        # Pad to power of 2 for balanced bracket
        n = len(participants)
        next_power = 1
        while next_power < n:
            next_power *= 2

        # First round: pair up participants with BYEs for padding
        padded = participants + ["BYE"] * (next_power - n)
        for position, i in enumerate(range(0, len(padded), 2)):
            match = TournamentMatch(
                match_id=f"match_{uuid.uuid4().hex[:8]}",
                tournament_id=tournament.tournament_id,
                round_num=1,
                agent1=padded[i],
                agent2=padded[i + 1],
                bracket_position=position,
                is_losers_bracket=False,
            )
            matches.append(match)

        self._insert_matches(matches, tournament.tournament_id)

    def _generate_double_elimination_matches(self, tournament: Tournament) -> None:
        """Generate first round matches for double elimination.

        In double elimination:
        - Winners bracket: participants compete; losers drop to losers bracket
        - Losers bracket: eliminated participants compete for second chance
        - Final: winners bracket champion vs losers bracket champion
        """
        participants = tournament.participants
        matches = []

        # Pad to power of 2
        n = len(participants)
        next_power = 1
        while next_power < n:
            next_power *= 2

        # Winners bracket first round
        padded = participants + ["BYE"] * (next_power - n)
        for position, i in enumerate(range(0, len(padded), 2)):
            match = TournamentMatch(
                match_id=f"match_{uuid.uuid4().hex[:8]}",
                tournament_id=tournament.tournament_id,
                round_num=1,
                agent1=padded[i],
                agent2=padded[i + 1],
                bracket_position=position,
                is_losers_bracket=False,
            )
            matches.append(match)

        # Losers bracket matches are generated dynamically as participants lose
        # Only create the winners bracket initially

        self._insert_matches(matches, tournament.tournament_id)
        logger.info(
            "Generated double elimination bracket with %s winners bracket matches", len(matches)
        )

    def record_match_result(
        self,
        match_id: str,
        winner: str | None,
        score1: float = 0.0,
        score2: float = 0.0,
        debate_id: str | None = None,
        update_elo: bool = True,
        elo_k_multiplier: float = 1.5,
    ) -> dict[str, float]:
        """
        Record the result of a match and optionally update ELO ratings.

        Args:
            match_id: Match identifier
            winner: Winner agent name (None for draw)
            score1: Score for agent1
            score2: Score for agent2
            debate_id: Optional associated debate ID
            update_elo: Whether to update ELO ratings (default True)
            elo_k_multiplier: K-factor multiplier for tournament matches (default 1.5)

        Returns:
            Dict of agent -> ELO change (empty if ELO not configured)

        Raises:
            ValidationError: If scores are invalid
            MatchNotFoundError: If match doesn't exist
        """
        # Validate scores
        score1 = self._validate_score(score1)
        score2 = self._validate_score(score2)

        completed_at = datetime.now(timezone.utc).isoformat()
        elo_changes: dict[str, float] = {}
        agent1 = ""
        agent2 = ""

        with self._lock:
            with self._get_connection() as conn:
                # Verify match exists
                cursor = conn.execute(
                    "SELECT tournament_id, agent1, agent2 FROM matches WHERE match_id = ?",
                    (match_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise MatchNotFoundError(f"Match {match_id} not found")

                tournament_id = row["tournament_id"]
                agent1, agent2 = row["agent1"], row["agent2"]

                # Validate winner
                if winner is not None and winner not in (agent1, agent2):
                    raise ValidationError(f"Winner must be one of {agent1} or {agent2}")

                conn.execute(
                    """
                    UPDATE matches
                    SET winner = ?, score1 = ?, score2 = ?, debate_id = ?, completed_at = ?
                    WHERE match_id = ?
                    """,
                    (winner, score1, score2, debate_id, completed_at, match_id),
                )

                # Log event
                self._log_event(
                    conn,
                    tournament_id,
                    TournamentEvent.MATCH_COMPLETED,
                    {
                        "match_id": match_id,
                        "winner": winner,
                        "score1": score1,
                        "score2": score2,
                        "debate_id": debate_id,
                    },
                )

                conn.commit()
                logger.info("Recorded result for match %s: winner=%s", match_id, winner)

        # Update ELO ratings if configured and requested
        if update_elo and self._elo_system and agent1 and agent2:
            try:
                # Tournament matches get higher K-factor for more impactful rating changes
                elo_changes = self._elo_system.record_match(
                    debate_id=debate_id or f"tournament_{match_id}",
                    participants=[agent1, agent2],
                    scores={agent1: score1, agent2: score2},
                    confidence_weight=elo_k_multiplier,
                )
                logger.info(
                    "Updated ELO for tournament match %s: %s=%+.1f, %s=%+.1f",
                    match_id,
                    agent1,
                    elo_changes.get(agent1, 0),
                    agent2,
                    elo_changes.get(agent2, 0),
                )
            except (ValueError, TypeError, KeyError, RuntimeError, OSError) as e:
                logger.warning("Failed to update ELO for match %s: %s", match_id, e)

        return elo_changes

    def record_match_result_with_elo(
        self,
        match_id: str,
        winner: str | None,
        score1: float = 0.0,
        score2: float = 0.0,
        debate_id: str | None = None,
        elo_system: Any | None = None,
    ) -> dict[str, float]:
        """
        Record match result and update ELO ratings with a specific ELO system.

        Convenience method for one-off ELO updates when no persistent ELO system
        is configured on the tournament manager.

        Args:
            match_id: Match identifier
            winner: Winner agent name
            score1: Score for agent1
            score2: Score for agent2
            debate_id: Optional associated debate ID
            elo_system: EloSystem instance to use for this match

        Returns:
            Dict of agent -> ELO change
        """
        # Temporarily set ELO system for this call
        original_elo = self._elo_system
        self._elo_system = elo_system
        try:
            return self.record_match_result(
                match_id=match_id,
                winner=winner,
                score1=score1,
                score2=score2,
                debate_id=debate_id,
                update_elo=True,
            )
        finally:
            self._elo_system = original_elo

    def get_current_standings(self, tournament_id: str | None = None) -> list[TournamentStanding]:
        """
        Get current tournament standings.

        Args:
            tournament_id: Optional tournament ID to filter by

        Returns:
            List of TournamentStanding sorted by points (descending)
        """
        with self._get_connection() as conn:
            # Get all participants from tournaments
            if tournament_id:
                cursor = conn.execute(
                    "SELECT participants FROM tournaments WHERE tournament_id = ?",
                    (tournament_id,),
                )
            else:
                cursor = conn.execute("SELECT participants FROM tournaments LIMIT 1")

            row = cursor.fetchone()
            if not row:
                return []

            participants = json.loads(row["participants"])
            standings_dict = {p: TournamentStanding(agent=p) for p in participants}

            # Calculate standings from completed matches
            if tournament_id:
                cursor = conn.execute(
                    """
                    SELECT agent1, agent2, winner, score1, score2
                    FROM matches
                    WHERE completed_at IS NOT NULL AND tournament_id = ?
                    """,
                    (tournament_id,),
                )
            else:
                cursor = conn.execute("""
                    SELECT agent1, agent2, winner, score1, score2
                    FROM matches
                    WHERE completed_at IS NOT NULL
                    """)

            for row in cursor:
                agent1 = row["agent1"]
                agent2 = row["agent2"]
                winner = row["winner"]
                score1 = row["score1"] or 0.0
                score2 = row["score2"] or 0.0

                if agent1 in standings_dict:
                    standings_dict[agent1].total_score += score1

                if agent2 in standings_dict:
                    standings_dict[agent2].total_score += score2

                if winner is None:
                    # Draw
                    if agent1 in standings_dict:
                        standings_dict[agent1].draws += 1
                        standings_dict[agent1].points += 0.5
                    if agent2 in standings_dict:
                        standings_dict[agent2].draws += 1
                        standings_dict[agent2].points += 0.5
                elif winner == agent1:
                    if agent1 in standings_dict:
                        standings_dict[agent1].wins += 1
                        standings_dict[agent1].points += 1.0
                    if agent2 in standings_dict:
                        standings_dict[agent2].losses += 1
                elif winner == agent2:
                    if agent2 in standings_dict:
                        standings_dict[agent2].wins += 1
                        standings_dict[agent2].points += 1.0
                    if agent1 in standings_dict:
                        standings_dict[agent1].losses += 1

            # Sort by points (descending), then win rate
            standings = list(standings_dict.values())
            standings.sort(key=lambda s: (s.points, s.win_rate), reverse=True)

            return standings

    def get_matches(
        self,
        tournament_id: str | None = None,
        round_num: int | None = None,
        completed_only: bool = False,
        losers_bracket: bool | None = None,
    ) -> list[TournamentMatch]:
        """
        Get matches with optional filtering.

        Args:
            tournament_id: Filter by tournament
            round_num: Filter by round number
            completed_only: Only return completed matches
            losers_bracket: Filter by bracket type (True=losers, False=winners, None=all)

        Returns:
            List of TournamentMatch objects
        """
        with self._get_connection() as conn:
            query = "SELECT * FROM matches WHERE 1=1"
            params: list[Any] = []

            if tournament_id:
                query += " AND tournament_id = ?"
                params.append(tournament_id)

            if round_num is not None:
                query += " AND round_num = ?"
                params.append(round_num)

            if completed_only:
                query += " AND completed_at IS NOT NULL"

            if losers_bracket is not None:
                query += " AND is_losers_bracket = ?"
                params.append(1 if losers_bracket else 0)

            query += " ORDER BY round_num, bracket_position"

            cursor = conn.execute(query, params)
            matches = []

            for row in cursor:
                matches.append(
                    TournamentMatch(
                        match_id=row["match_id"],
                        tournament_id=row["tournament_id"],
                        round_num=row["round_num"],
                        agent1=row["agent1"],
                        agent2=row["agent2"],
                        winner=row["winner"],
                        score1=row["score1"] or 0.0,
                        score2=row["score2"] or 0.0,
                        debate_id=row["debate_id"],
                        bracket_position=row["bracket_position"] or 0,
                        is_losers_bracket=bool(row["is_losers_bracket"]),
                        created_at=row["created_at"],
                        completed_at=row["completed_at"],
                    )
                )

            return matches

    def get_tournament(self, tournament_id: str) -> Tournament | None:
        """Get tournament by ID.

        Args:
            tournament_id: Tournament identifier

        Returns:
            Tournament object or None if not found
        """
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM tournaments WHERE tournament_id = ?",
                (tournament_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None

            return Tournament(
                tournament_id=row["tournament_id"],
                name=row["name"],
                bracket_type=row["bracket_type"],
                participants=json.loads(row["participants"]),
                rounds_completed=row["rounds_completed"],
                total_rounds=row["total_rounds"],
                status=row["status"],
                created_at=row["created_at"],
            )

    def list_tournaments(self, limit: int = 50, status: str | None = None) -> list[Tournament]:
        """List all tournaments.

        Args:
            limit: Maximum tournaments to return
            status: Optional status filter (pending, in_progress, completed, cancelled)

        Returns:
            List of Tournament objects, newest first
        """
        with self._get_connection() as conn:
            if status:
                cursor = conn.execute(
                    "SELECT * FROM tournaments WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM tournaments ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )

            tournaments = []
            for row in cursor:
                tournaments.append(
                    Tournament(
                        tournament_id=row["tournament_id"],
                        name=row["name"],
                        bracket_type=row["bracket_type"],
                        participants=json.loads(row["participants"]),
                        rounds_completed=row["rounds_completed"],
                        total_rounds=row["total_rounds"],
                        status=row["status"],
                        created_at=row["created_at"],
                    )
                )

            return tournaments

    def advance_round(self, tournament_id: str) -> bool:
        """
        Advance tournament to next round (for elimination brackets).

        Args:
            tournament_id: Tournament identifier

        Returns:
            True if advanced, False if tournament is complete or cannot advance

        Raises:
            TournamentNotFoundError: If tournament doesn't exist
            InvalidStateError: If current round is not complete
        """
        tournament = self.get_tournament(tournament_id)
        if not tournament:
            raise TournamentNotFoundError(f"Tournament {tournament_id} not found")

        if tournament.bracket_type == "round_robin":
            # Round-robin completes when all matches are done
            matches = self.get_matches(tournament_id=tournament_id)
            completed = all(m.completed_at for m in matches)
            if completed and tournament.status != TournamentStatus.COMPLETED.value:
                with self._lock:
                    with self._get_connection() as conn:
                        conn.execute(
                            "UPDATE tournaments SET status = ? WHERE tournament_id = ?",
                            (TournamentStatus.COMPLETED.value, tournament_id),
                        )
                        self._log_event(conn, tournament_id, TournamentEvent.COMPLETED)
                        conn.commit()
            return False

        if tournament.bracket_type not in ("single_elimination", "double_elimination"):
            return False

        # Check if all matches in current round are complete
        matches = self.get_matches(tournament_id=tournament_id, losers_bracket=False)
        current_round = tournament.rounds_completed + 1
        current_round_matches = [m for m in matches if m.round_num == current_round]

        if not current_round_matches:
            return False

        if not all(m.completed_at for m in current_round_matches):
            raise InvalidStateError(f"Round {current_round} not complete")

        # Get winners for next round
        winners = [m.winner for m in current_round_matches if m.winner and m.winner != "BYE"]

        with self._lock:
            with self._get_connection() as conn:
                if len(winners) <= 1:
                    # Tournament complete
                    conn.execute(
                        "UPDATE tournaments SET status = ?, rounds_completed = ? WHERE tournament_id = ?",
                        (TournamentStatus.COMPLETED.value, current_round, tournament_id),
                    )
                    self._log_event(
                        conn,
                        tournament_id,
                        TournamentEvent.COMPLETED,
                        {"final_winner": winners[0] if winners else None},
                    )
                    conn.commit()
                    logger.info("Tournament %s completed", tournament_id)
                    return False

                # Generate next round matches
                next_round = current_round + 1
                new_matches = []

                for position, i in enumerate(range(0, len(winners), 2)):
                    agent2 = winners[i + 1] if i + 1 < len(winners) else "BYE"
                    match = TournamentMatch(
                        match_id=f"match_{uuid.uuid4().hex[:8]}",
                        tournament_id=tournament_id,
                        round_num=next_round,
                        agent1=winners[i],
                        agent2=agent2,
                        bracket_position=position,
                        is_losers_bracket=False,
                    )
                    new_matches.append(match)

                # Insert matches using helper
                for match in new_matches:
                    conn.execute(
                        """
                        INSERT INTO matches
                        (match_id, tournament_id, round_num, agent1, agent2,
                         bracket_position, is_losers_bracket, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            match.match_id,
                            match.tournament_id,
                            match.round_num,
                            match.agent1,
                            match.agent2,
                            match.bracket_position,
                            0,
                            match.created_at,
                        ),
                    )

                conn.execute(
                    "UPDATE tournaments SET rounds_completed = ?, status = ? WHERE tournament_id = ?",
                    (current_round, TournamentStatus.IN_PROGRESS.value, tournament_id),
                )

                self._log_event(
                    conn,
                    tournament_id,
                    TournamentEvent.ROUND_ADVANCED,
                    {
                        "from_round": current_round,
                        "to_round": next_round,
                        "matches_created": len(new_matches),
                    },
                )

                conn.commit()
                logger.info("Advanced tournament %s to round %s", tournament_id, next_round)

        return True

    def cancel_tournament(self, tournament_id: str) -> bool:
        """Cancel a tournament.

        Args:
            tournament_id: Tournament identifier

        Returns:
            True if cancelled, False if already completed/cancelled

        Raises:
            TournamentNotFoundError: If tournament doesn't exist
        """
        tournament = self.get_tournament(tournament_id)
        if not tournament:
            raise TournamentNotFoundError(f"Tournament {tournament_id} not found")

        if tournament.status in (
            TournamentStatus.COMPLETED.value,
            TournamentStatus.CANCELLED.value,
        ):
            return False

        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE tournaments SET status = ? WHERE tournament_id = ?",
                    (TournamentStatus.CANCELLED.value, tournament_id),
                )
                self._log_event(conn, tournament_id, TournamentEvent.CANCELLED)
                conn.commit()
                logger.info("Cancelled tournament %s", tournament_id)

        return True
