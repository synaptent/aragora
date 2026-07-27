"""
Tournament system for structured agent competitions.

Inspired by ChatArena's competitive environments, this module provides:
- Round-robin and bracket tournaments
- Multi-task competitions
- Aggregate scoring and rankings
- Tournament history and statistics
"""

import asyncio
import itertools
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)
from aragora.core import Agent, DebateResult, Environment
from aragora.ranking.elo import EloSystem
from aragora.tournaments.database import TournamentDatabase


class TournamentFormat(Enum):
    """Tournament format types."""

    ROUND_ROBIN = "round_robin"  # Everyone plays everyone
    SINGLE_ELIMINATION = "single_elimination"  # Bracket style
    SWISS = "swiss"  # Swiss-system pairing
    FREE_FOR_ALL = "free_for_all"  # All agents in every debate


@dataclass
class TournamentTask:
    """A task for tournament debates."""

    task_id: str
    description: str
    domain: str  # e.g., "security", "architecture"
    difficulty: float = 0.5  # 0-1
    time_limit: int = 300  # seconds


@dataclass
class TournamentMatch:
    """A single match in the tournament."""

    match_id: str
    round_num: int
    participants: list[str]
    task: TournamentTask
    result: DebateResult | None = None
    scores: dict[str, float] = field(default_factory=dict)
    winner: str | None = None
    started_at: str | None = None
    completed_at: str | None = None

    @property
    def is_complete(self) -> bool:
        return self.result is not None


@dataclass
class TournamentStanding:
    """An agent's standing in the tournament."""

    agent_name: str
    wins: int = 0
    losses: int = 0
    draws: int = 0
    points: float = 0.0
    total_score: float = 0.0
    matches_played: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.matches_played if self.matches_played > 0 else 0.0


@dataclass
class TournamentResult:
    """Final result of a tournament."""

    tournament_id: str
    name: str
    format: TournamentFormat
    standings: list[TournamentStanding]
    matches: list[TournamentMatch]
    champion: str
    total_rounds: int
    started_at: str
    completed_at: str


class Tournament:
    """
    Manages a tournament competition between agents.

    Supports multiple formats and tracks results via ELO system.
    """

    def __init__(
        self,
        name: str,
        agents: list[Agent],
        tasks: list[TournamentTask],
        format: TournamentFormat = TournamentFormat.ROUND_ROBIN,
        elo_system: EloSystem | None = None,
        db_path: str = "aragora_tournaments.db",
    ):
        self.tournament_id = str(uuid.uuid4())[:8]
        self.name = name
        self.agents = {a.name: a for a in agents}
        self.agent_names = [a.name for a in agents]
        self.tasks = tasks
        self.format = format
        self.elo_system = elo_system or EloSystem()
        self.db_path = Path(db_path)
        self.db = TournamentDatabase(db_path)

        self.matches: list[TournamentMatch] = []
        self.standings: dict[str, TournamentStanding] = {
            name: TournamentStanding(agent_name=name) for name in self.agent_names
        }
        self.current_round = 0
        self.started_at: str | None = None
        self.completed_at: str | None = None

    def generate_matches(self) -> list[TournamentMatch]:
        """Generate match schedule based on tournament format."""
        if self.format == TournamentFormat.ROUND_ROBIN:
            return self._generate_round_robin()
        elif self.format == TournamentFormat.FREE_FOR_ALL:
            return self._generate_free_for_all()
        elif self.format == TournamentFormat.SINGLE_ELIMINATION:
            return self._generate_bracket()
        elif self.format == TournamentFormat.SWISS:
            return self._generate_swiss_round()
        else:
            raise ValueError(f"Unknown format: {self.format}")

    def _generate_round_robin(self) -> list[TournamentMatch]:
        """Generate round-robin matches (everyone plays everyone)."""
        matches = []
        pairings = list(itertools.combinations(self.agent_names, 2))

        for round_num, task in enumerate(self.tasks):
            for i, (agent_a, agent_b) in enumerate(pairings):
                match = TournamentMatch(
                    match_id=f"{self.tournament_id}-r{round_num}-m{i}",
                    round_num=round_num,
                    participants=[agent_a, agent_b],
                    task=task,
                )
                matches.append(match)

        return matches

    def _generate_free_for_all(self) -> list[TournamentMatch]:
        """Generate free-for-all matches (all agents compete together)."""
        matches = []

        for round_num, task in enumerate(self.tasks):
            match = TournamentMatch(
                match_id=f"{self.tournament_id}-r{round_num}",
                round_num=round_num,
                participants=self.agent_names.copy(),
                task=task,
            )
            matches.append(match)

        return matches

    def _generate_bracket(self) -> list[TournamentMatch]:
        """Generate single-elimination bracket."""
        matches = []

        # For simplicity, use first task for all matches
        task = (
            self.tasks[0]
            if self.tasks
            else TournamentTask(
                task_id="default",
                description="Default task",
                domain="general",
            )
        )

        # Initial round - pair up agents
        remaining = self.agent_names.copy()
        round_num = 0

        while len(remaining) > 1:
            round_matches: list[TournamentMatch] = []
            next_round: list[str | None] = []

            for i in range(0, len(remaining), 2):
                if i + 1 < len(remaining):
                    match = TournamentMatch(
                        match_id=f"{self.tournament_id}-r{round_num}-m{i // 2}",
                        round_num=round_num,
                        participants=[remaining[i], remaining[i + 1]],
                        task=task,
                    )
                    round_matches.append(match)
                    next_round.append(None)  # Placeholder for winner
                else:
                    # Bye - agent advances automatically
                    next_round.append(remaining[i])

            matches.extend(round_matches)
            remaining = next_round
            round_num += 1

        return matches

    def _generate_swiss_round(self) -> list[TournamentMatch]:
        """Generate Swiss-system pairings based on current standings."""
        matches = []
        if not self.tasks:
            raise ValueError("Cannot generate Swiss round: no tasks configured")
        task = self.tasks[self.current_round % len(self.tasks)]

        # Sort agents by points
        sorted_agents = sorted(
            self.standings.values(),
            key=lambda s: (s.points, s.total_score),
            reverse=True,
        )

        # Pair adjacent agents
        for i in range(0, len(sorted_agents), 2):
            if i + 1 < len(sorted_agents):
                agent_a = sorted_agents[i].agent_name
                agent_b = sorted_agents[i + 1].agent_name

                match = TournamentMatch(
                    match_id=f"{self.tournament_id}-r{self.current_round}-m{i // 2}",
                    round_num=self.current_round,
                    participants=[agent_a, agent_b],
                    task=task,
                )
                matches.append(match)

        return matches

    async def run(
        self,
        run_debate_fn: Callable[[Environment, list[Agent]], Awaitable[DebateResult]],
        parallel: bool = True,
    ) -> TournamentResult:
        """
        Run the full tournament.

        Args:
            run_debate_fn: Function to run a single debate
            parallel: Whether to run matches in parallel

        Returns:
            TournamentResult with final standings
        """
        self.started_at = datetime.now().isoformat()
        self.matches = self.generate_matches()

        if self.format == TournamentFormat.SWISS:
            # Swiss requires round-by-round generation
            await self._run_swiss(run_debate_fn)
        else:
            # Other formats can run all matches
            if parallel:
                await self._run_parallel(run_debate_fn)
            else:
                await self._run_sequential(run_debate_fn)

        self.completed_at = datetime.now().isoformat()

        # Determine champion
        champion = max(
            self.standings.values(),
            key=lambda s: (s.points, s.total_score),
        ).agent_name

        # Save to database (non-blocking)
        await asyncio.to_thread(self._save_tournament, champion)

        return TournamentResult(
            tournament_id=self.tournament_id,
            name=self.name,
            format=self.format,
            standings=sorted(
                self.standings.values(),
                key=lambda s: (s.points, s.total_score),
                reverse=True,
            ),
            matches=self.matches,
            champion=champion,
            total_rounds=self.current_round + 1,
            started_at=self.started_at,
            completed_at=self.completed_at,
        )

    async def _run_match(
        self,
        match: TournamentMatch,
        run_debate_fn: Callable,
    ) -> TournamentMatch:
        """Run a single match."""
        match.started_at = datetime.now().isoformat()

        # Create environment
        env = Environment(
            task=match.task.description,
            max_rounds=5,
        )

        # Get agents
        agents = [self.agents[name] for name in match.participants if name in self.agents]

        # Run debate
        result = await run_debate_fn(env, agents)
        match.result = result

        # Calculate scores
        match.scores = self._calculate_match_scores(result, match.participants)

        # Determine winner
        if match.scores:
            max_score = max(match.scores.values())
            winners = [a for a, s in match.scores.items() if s == max_score]
            match.winner = winners[0] if len(winners) == 1 else None

        match.completed_at = datetime.now().isoformat()

        # Update standings
        self._update_standings(match)

        # Update ELO (non-blocking database operation)
        await asyncio.to_thread(
            self.elo_system.record_match,
            debate_id=match.match_id,
            participants=match.participants,
            scores=match.scores,
            domain=match.task.domain,
        )

        return match

    async def _run_parallel(self, run_debate_fn: Callable):
        """Run all matches in parallel."""
        tasks = [self._run_match(match, run_debate_fn) for match in self.matches]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        # Log any match failures (matches are updated in _run_match)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Tournament match %s failed: %s: %s", i, type(result).__name__, result)

    async def _run_sequential(self, run_debate_fn: Callable):
        """Run matches sequentially."""
        for match in self.matches:
            await self._run_match(match, run_debate_fn)

    async def _run_swiss(self, run_debate_fn: Callable, num_rounds: int = 5):
        """Run Swiss-system tournament with dynamic pairings."""
        for round_num in range(num_rounds):
            self.current_round = round_num
            round_matches = self._generate_swiss_round()
            self.matches.extend(round_matches)

            # Run round matches
            for match in round_matches:
                await self._run_match(match, run_debate_fn)

    def _calculate_match_scores(
        self,
        result: DebateResult,
        participants: list[str],
    ) -> dict[str, float]:
        """Calculate scores for each participant in a match."""
        scores = {name: 0.0 for name in participants}

        if not result:
            return scores

        # Score based on various factors
        for name in participants:
            score = 0.0

            # Contribution to consensus
            if result.consensus_reached:
                score += 0.3

            # Quality of critiques (if this agent gave critiques)
            agent_critiques = [c for c in result.critiques if c.agent == name]
            if agent_critiques:
                # Lower final severity = better (issues were resolved)
                avg_severity = sum(c.severity for c in agent_critiques) / len(agent_critiques)
                score += 0.3 * (1 - avg_severity)

            # Messages contributed
            agent_messages = [m for m in result.messages if m.agent == name]
            if agent_messages:
                score += 0.2 * min(1.0, len(agent_messages) / 5)

            # Confidence boost if consensus reached
            if result.consensus_reached:
                score += 0.2 * result.confidence

            scores[name] = score

        return scores

    def _update_standings(self, match: TournamentMatch):
        """Update standings based on match result."""
        for agent_name in match.participants:
            standing = self.standings[agent_name]
            standing.matches_played += 1
            standing.total_score += match.scores.get(agent_name, 0)

            if match.winner == agent_name:
                standing.wins += 1
                standing.points += 3  # Win = 3 points
            elif match.winner is None:
                standing.draws += 1
                standing.points += 1  # Draw = 1 point
            else:
                standing.losses += 1
                standing.points += 0  # Loss = 0 points

    def _save_tournament(self, champion: str):
        """Save tournament to database."""
        with self.db.connection() as conn:
            cursor = conn.cursor()

            # Save tournament
            cursor.execute(
                """
                INSERT OR REPLACE INTO tournaments
                (tournament_id, name, format, agents, tasks, standings, champion, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.tournament_id,
                    self.name,
                    self.format.value,
                    json.dumps(self.agent_names),
                    json.dumps([{"id": t.task_id, "desc": t.description} for t in self.tasks]),
                    json.dumps(
                        {
                            name: {
                                "wins": s.wins,
                                "losses": s.losses,
                                "draws": s.draws,
                                "points": s.points,
                                "total_score": s.total_score,
                            }
                            for name, s in self.standings.items()
                        }
                    ),
                    champion,
                    self.started_at,
                    self.completed_at,
                ),
            )

            # Save matches
            for match in self.matches:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO tournament_matches
                    (match_id, tournament_id, round_num, participants, task_id, scores, winner, started_at, completed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        match.match_id,
                        self.tournament_id,
                        match.round_num,
                        json.dumps(match.participants),
                        match.task.task_id,
                        json.dumps(match.scores),
                        match.winner,
                        match.started_at,
                        match.completed_at,
                    ),
                )

            conn.commit()

    def get_current_standings(self) -> list[TournamentStanding]:
        """Get current standings sorted by points."""
        return sorted(
            self.standings.values(),
            key=lambda s: (s.points, s.total_score),
            reverse=True,
        )


def create_default_tasks() -> list[TournamentTask]:
    """Create a default set of tournament tasks."""
    return [
        TournamentTask(
            task_id="rate-limiter",
            description="Design a distributed rate limiter that handles 1M requests/sec",
            domain="architecture",
            difficulty=0.7,
        ),
        TournamentTask(
            task_id="auth-system",
            description="Design a secure authentication system with MFA support",
            domain="security",
            difficulty=0.6,
        ),
        TournamentTask(
            task_id="cache-invalidation",
            description="Design a cache invalidation strategy for a social media feed",
            domain="performance",
            difficulty=0.8,
        ),
        TournamentTask(
            task_id="error-handling",
            description="Design a comprehensive error handling strategy for a payment system",
            domain="error_handling",
            difficulty=0.5,
        ),
        TournamentTask(
            task_id="api-versioning",
            description="Design an API versioning strategy for a public REST API",
            domain="api_design",
            difficulty=0.4,
        ),
    ]


class TournamentManager:
    """
    Read-only manager for accessing tournament data from database.

    Used by API handlers to retrieve tournament results and standings.
    """

    def __init__(self, db_path: str):
        """Initialize tournament manager with database path."""
        self.db_path = Path(db_path)
        self.db = TournamentDatabase(db_path)

    def get_tournament(self) -> dict | None:
        """Get the tournament metadata."""
        if not self.db_path.exists():
            return None

        try:
            with self.db.connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT tournament_id, name, format, champion, started_at, completed_at
                    FROM tournaments LIMIT 1
                """)
                row = cursor.fetchone()

                if not row:
                    return None

                return {
                    "tournament_id": row[0],
                    "name": row[1],
                    "format": row[2],
                    "champion": row[3],
                    "started_at": row[4],
                    "completed_at": row[5],
                }
        except (sqlite3.Error, Exception):
            return None

    def get_current_standings(self) -> list[TournamentStanding]:
        """Get current tournament standings sorted by points."""
        if not self.db_path.exists():
            return []

        try:
            with self.db.connection() as conn:
                cursor = conn.cursor()

                cursor.execute("SELECT standings FROM tournaments LIMIT 1")
                row = cursor.fetchone()

                if not row or not row[0]:
                    return []

                standings_json = json.loads(row[0])

                # Convert to list of TournamentStanding objects
                standings = []
                for agent_name, stats in standings_json.items():
                    standing = TournamentStanding(
                        agent_name=agent_name,
                        wins=stats.get("wins", 0),
                        losses=stats.get("losses", 0),
                        draws=stats.get("draws", 0),
                        points=stats.get("points", 0.0),
                        total_score=stats.get("total_score", 0.0),
                        matches_played=stats.get("wins", 0)
                        + stats.get("losses", 0)
                        + stats.get("draws", 0),
                    )
                    standings.append(standing)

                # Sort by points and total_score (descending)
                standings.sort(key=lambda s: (s.points, s.total_score), reverse=True)
                return standings
        except (sqlite3.Error, json.JSONDecodeError, Exception):
            return []

    def get_matches(self, limit: int | None = None) -> list[dict]:
        """Get tournament matches."""
        if not self.db_path.exists():
            return []

        try:
            with self.db.connection() as conn:
                cursor = conn.cursor()

                if limit:
                    cursor.execute(
                        """
                        SELECT match_id, round_num, participants, task_id, scores, winner,
                               started_at, completed_at
                        FROM tournament_matches
                        ORDER BY round_num DESC, match_id DESC
                        LIMIT ?
                    """,
                        (limit,),
                    )
                else:
                    cursor.execute("""
                        SELECT match_id, round_num, participants, task_id, scores, winner,
                               started_at, completed_at
                        FROM tournament_matches
                        ORDER BY round_num DESC, match_id DESC
                    """)

                matches = []
                for row in cursor.fetchall():
                    match_data = {
                        "match_id": row[0],
                        "round_num": row[1],
                        "participants": json.loads(row[2]) if row[2] else [],
                        "task_id": row[3],
                        "scores": json.loads(row[4]) if row[4] else {},
                        "winner": row[5],
                        "started_at": row[6],
                        "completed_at": row[7],
                    }
                    matches.append(match_data)

                return matches
        except (sqlite3.Error, json.JSONDecodeError, Exception):
            return []

    def get_match_summary(self) -> dict:
        """Get summary statistics about tournament matches."""
        if not self.db_path.exists():
            return {"total_matches": 0, "decided_matches": 0, "max_round": 0}

        try:
            with self.db.connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        COUNT(*) as total_matches,
                        SUM(CASE WHEN winner IS NOT NULL THEN 1 ELSE 0 END) as decided_matches,
                        MAX(round_num) as max_round
                    FROM tournament_matches
                """)
                row = cursor.fetchone()

                return {
                    "total_matches": row[0] or 0,
                    "decided_matches": row[1] or 0,
                    "max_round": row[2] or 0,
                }
        except (sqlite3.Error, Exception):
            return {"total_matches": 0, "decided_matches": 0, "max_round": 0}
