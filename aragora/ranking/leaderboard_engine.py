"""
Leaderboard and Statistics Engine.

Provides read-only analytics operations for the ELO ranking system:
- Leaderboards (global and domain-specific)
- Agent statistics and history
- Head-to-head comparisons
- System-wide statistics

Extracted from EloSystem to separate query/analytics concerns from
rating mutation operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.config import ELO_INITIAL_RATING
from aragora.exceptions import ConfigurationError
from aragora.utils.json_helpers import safe_json_loads

if TYPE_CHECKING:
    from aragora.ranking.database import EloDatabase
    from aragora.ranking.elo import AgentRating
    from aragora.utils.cache import TTLCache

logger = logging.getLogger(__name__)

DEFAULT_ELO = ELO_INITIAL_RATING

# Maximum agent name length for validation
MAX_AGENT_NAME_LENGTH = 32


def _validate_agent_name(agent_name: str) -> None:
    """Validate agent name length."""
    if len(agent_name) > MAX_AGENT_NAME_LENGTH:
        raise ValueError(
            f"Agent name exceeds {MAX_AGENT_NAME_LENGTH} characters: {len(agent_name)}"
        )


# Import from centralized location (defined here for backwards compatibility)
from aragora.utils.sql_helpers import _escape_like_pattern


class LeaderboardEngine:
    """
    Read-only analytics engine for ELO rankings.

    Provides leaderboards, statistics, and history queries with optional
    caching support. All operations are read-only and don't modify ratings.

    Usage:
        engine = LeaderboardEngine(db, leaderboard_cache, stats_cache)
        leaderboard = engine.get_leaderboard(limit=20)
        stats = engine.get_stats()
        history = engine.get_elo_history("claude")
    """

    def __init__(
        self,
        db: EloDatabase,
        leaderboard_cache: TTLCache | None = None,
        stats_cache: TTLCache | None = None,
        rating_cache: TTLCache | None = None,
        rating_factory: Callable[..., Any] | None = None,
    ):
        """
        Initialize the leaderboard engine.

        Args:
            db: EloDatabase instance for queries
            leaderboard_cache: Optional TTLCache for leaderboard results
            stats_cache: Optional TTLCache for statistics
            rating_cache: Optional TTLCache for individual ratings
            rating_factory: Callable to create AgentRating from row data
        """
        self._db = db
        self._leaderboard_cache = leaderboard_cache
        self._stats_cache = stats_cache
        self._rating_cache = rating_cache
        self._rating_factory = rating_factory

    def get_leaderboard(
        self,
        limit: int = 20,
        domain: str | None = None,
    ) -> list[AgentRating]:
        """
        Get top agents by ELO.

        Args:
            limit: Maximum number of agents to return
            domain: Optional domain to sort by domain-specific ELO

        Returns:
            List of AgentRating sorted by ELO (highest first)
        """
        if not self._rating_factory:
            raise ConfigurationError(
                component="LeaderboardEngine",
                reason="rating_factory must be set to create AgentRating objects",
            )

        with self._db.connection() as conn:
            cursor = conn.cursor()

            if domain:
                cursor.execute(
                    """
                    SELECT agent_name, elo, domain_elos, wins, losses, draws,
                           debates_count, critiques_accepted, critiques_total, updated_at
                    FROM ratings
                    ORDER BY COALESCE(json_extract(domain_elos, ?), elo) DESC
                    LIMIT ?
                    """,
                    (f'$."{domain}"', limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT agent_name, elo, domain_elos, wins, losses, draws,
                           debates_count, critiques_accepted, critiques_total, updated_at
                    FROM ratings
                    ORDER BY elo DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            rows = cursor.fetchall()

        return [self._rating_factory(row) for row in rows] if callable(self._rating_factory) else []

    def get_cached_leaderboard(
        self,
        limit: int = 20,
        domain: str | None = None,
    ) -> list[AgentRating]:
        """
        Get leaderboard with caching for better performance.

        Uses TTL cache if available. For real-time data, use get_leaderboard().

        Args:
            limit: Maximum number of agents to return
            domain: Optional domain to sort by

        Returns:
            Cached list of AgentRating sorted by ELO
        """
        if self._leaderboard_cache is None:
            return self.get_leaderboard(limit=limit, domain=domain)

        cache_key = f"leaderboard:{limit}:{domain or 'global'}"
        cached = self._leaderboard_cache.get(cache_key)
        if cached is not None:
            logger.debug("Leaderboard cache hit for %s", cache_key)
            return cached

        result = self.get_leaderboard(limit=limit, domain=domain)
        self._leaderboard_cache.set(cache_key, result)
        logger.debug("Leaderboard cache miss, stored %s", cache_key)
        return result

    def invalidate_leaderboard_cache(self) -> int:
        """Invalidate all cached leaderboard data."""
        count = 0
        if self._stats_cache:
            self._stats_cache.clear()
        if self._leaderboard_cache:
            count = self._leaderboard_cache.clear()
        return count

    def invalidate_rating_cache(self, agent_name: str | None = None) -> int:
        """Invalidate cached ratings."""
        if not self._rating_cache:
            return 0
        if agent_name:
            return 1 if self._rating_cache.invalidate(f"rating:{agent_name}") else 0
        return self._rating_cache.clear()

    def get_top_agents_for_domain(
        self,
        domain: str,
        limit: int = 5,
    ) -> list[AgentRating]:
        """
        Get agents ranked by domain-specific performance.

        Args:
            domain: Domain to rank by (e.g., 'security', 'performance')
            limit: Maximum number of agents to return

        Returns:
            List of AgentRating sorted by domain-specific ELO
        """
        return self.get_cached_leaderboard(limit=limit, domain=domain)

    def get_elo_history(
        self,
        agent_name: str,
        limit: int = 50,
    ) -> list[tuple[str, float]]:
        """
        Get ELO history for an agent.

        Args:
            agent_name: Agent to query
            limit: Maximum history entries to return

        Returns:
            List of (timestamp, elo) tuples
        """
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT created_at, elo FROM elo_history
                WHERE agent_name = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_name, limit),
            )
            rows = cursor.fetchall()
            return [(row[0], row[1]) for row in rows]

    def get_recent_matches(self, limit: int = 10) -> list[dict]:
        """
        Get recent match results with ELO changes.

        Args:
            limit: Maximum matches to return

        Returns:
            List of match dicts with debate_id, winner, participants,
            domain, elo_changes, created_at
        """
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT debate_id, winner, participants, domain, elo_changes, created_at
                FROM matches
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        return [self._match_from_row(row) for row in rows]

    def get_match(self, debate_id: str) -> dict[str, Any] | None:
        """
        Get one match result by its debate ID (unique per match).

        Returns:
            Match dict in the same shape as get_recent_matches entries,
            or None if no match was recorded for the debate.
        """
        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT debate_id, winner, participants, domain, elo_changes, created_at
                FROM matches
                WHERE debate_id = ?
                """,
                (debate_id,),
            )
            row = cursor.fetchone()

        return self._match_from_row(row) if row is not None else None

    @staticmethod
    def _match_from_row(row: Any) -> dict[str, Any]:
        elo_changes: dict[str, Any] = safe_json_loads(row[4], {})
        participants: list[str] = safe_json_loads(row[2], [])
        return {
            "debate_id": row[0],
            "winner": row[1],
            "participants": participants,
            "domain": row[3],
            "elo_changes": elo_changes,
            "created_at": row[5],
        }

    def get_head_to_head(self, agent_a: str, agent_b: str) -> dict:
        """
        Get head-to-head statistics between two agents.

        Args:
            agent_a: First agent name
            agent_b: Second agent name

        Returns:
            Dict with matches, wins for each agent, and draws
        """
        _validate_agent_name(agent_a)
        _validate_agent_name(agent_b)

        with self._db.connection() as conn:
            cursor = conn.cursor()

            escaped_a = _escape_like_pattern(agent_a)
            escaped_b = _escape_like_pattern(agent_b)

            cursor.execute(
                """
                SELECT winner, scores FROM matches
                WHERE participants LIKE ? ESCAPE '\\' AND participants LIKE ? ESCAPE '\\'
                """,
                (f"%{escaped_a}%", f"%{escaped_b}%"),
            )
            rows = cursor.fetchall()

        a_wins = 0
        b_wins = 0
        draws = 0

        for winner, _ in rows:
            if winner == agent_a:
                a_wins += 1
            elif winner == agent_b:
                b_wins += 1
            else:
                draws += 1

        return {
            "matches": len(rows),
            f"{agent_a}_wins": a_wins,
            f"{agent_b}_wins": b_wins,
            "draws": draws,
        }

    def get_stats(self, use_cache: bool = True) -> dict:
        """
        Get overall system statistics.

        Args:
            use_cache: Whether to use cached value (default True)

        Returns:
            Dict with total_agents, avg_elo, max_elo, min_elo, total_matches
        """
        cache_key = "elo_stats"

        if use_cache and self._stats_cache:
            cached = self._stats_cache.get(cache_key)
            if cached is not None:
                return cached

        with self._db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), AVG(elo), MAX(elo), MIN(elo) FROM ratings")
            ratings_row = cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM matches")
            matches_row = cursor.fetchone()

        if ratings_row is None:
            ratings_row = (0, None, None, None)
        if matches_row is None:
            matches_row = (0,)

        result = {
            "total_agents": ratings_row[0] or 0,
            "avg_elo": ratings_row[1] or DEFAULT_ELO,
            "max_elo": ratings_row[2] or DEFAULT_ELO,
            "min_elo": ratings_row[3] or DEFAULT_ELO,
            "total_matches": matches_row[0] or 0,
        }

        if self._stats_cache:
            self._stats_cache.set(cache_key, result)
        return result


__all__ = ["LeaderboardEngine"]
