"""
Agent relationship tracking for grounded personas.

This module re-exports relationship tracking functionality from the canonical
implementation in aragora.ranking.relationships and provides additional
convenience methods for agent-specific use cases.

For new code, prefer importing directly from aragora.ranking.relationships.
"""

from __future__ import annotations

__all__ = [
    "AgentRelationship",
    "RelationshipTracker",
]

import logging
from datetime import datetime
from pathlib import Path

from aragora.persistence.db_config import DatabaseType, get_db_path
from aragora.ranking.relationships import (
    AgentRelationship,
    RelationshipTracker as BaseRelationshipTracker,
)

logger = logging.getLogger(__name__)


class RelationshipTracker(BaseRelationshipTracker):
    """
    Extended RelationshipTracker with agent-specific convenience methods.

    Inherits all functionality from aragora.ranking.relationships.RelationshipTracker
    and adds:
    - update_from_debate() for bulk updates from debate events
    - get_relationship() returning AgentRelationship with computed properties
    - get_influence_network() for influence analysis
    """

    def __init__(self, elo_db_path: str | Path | None = None):
        """
        Initialize the relationship tracker.

        Args:
            elo_db_path: Path to the ELO database file. Defaults to get_db_path(DatabaseType.ELO).
        """
        if elo_db_path is None:
            elo_db_path = get_db_path(DatabaseType.ELO)
        super().__init__(elo_db_path)
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure relationship tables exist."""
        with self._db.connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_relationships (
                    agent_a TEXT NOT NULL,
                    agent_b TEXT NOT NULL,
                    debate_count INTEGER DEFAULT 0,
                    agreement_count INTEGER DEFAULT 0,
                    critique_count_a_to_b INTEGER DEFAULT 0,
                    critique_count_b_to_a INTEGER DEFAULT 0,
                    critique_accepted_a_to_b INTEGER DEFAULT 0,
                    critique_accepted_b_to_a INTEGER DEFAULT 0,
                    position_changes_a_after_b INTEGER DEFAULT 0,
                    position_changes_b_after_a INTEGER DEFAULT 0,
                    a_wins_over_b INTEGER DEFAULT 0,
                    b_wins_over_a INTEGER DEFAULT 0,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (agent_a, agent_b),
                    CHECK (agent_a < agent_b)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationships_a ON agent_relationships(agent_a)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationships_b ON agent_relationships(agent_b)"
            )
            conn.commit()

    def _canonical_pair(self, agent_a: str, agent_b: str) -> tuple[str, str]:
        """Return agents in canonical order (alphabetical)."""
        if agent_a < agent_b:
            return (agent_a, agent_b)
        return (agent_b, agent_a)

    def update_from_debate(
        self,
        debate_id: str,
        participants: list[str],
        winner: str | None,
        votes: dict[str, str],
        critiques: list[dict],
        position_changes: dict[str, list[str] | None] | None = None,
    ) -> None:
        """
        Update all relationship metrics from a completed debate.

        Args:
            debate_id: Unique identifier for the debate
            participants: List of agent names that participated
            winner: Name of the winning agent (if any)
            votes: Mapping of agent -> vote value
            critiques: List of critique records
            position_changes: Optional mapping of agent -> list of agents that influenced them
        """
        with self._db.connection() as conn:
            # Update relationships for each pair
            for i, agent_a in enumerate(participants):
                for agent_b in participants[i + 1 :]:
                    canonical_a, canonical_b = self._canonical_pair(agent_a, agent_b)
                    is_swapped = canonical_a != agent_a

                    # Get or create relationship
                    cursor = conn.execute(
                        "SELECT * FROM agent_relationships WHERE agent_a = ? AND agent_b = ?",
                        (canonical_a, canonical_b),
                    )
                    row = cursor.fetchone()

                    if row is None:
                        conn.execute(
                            "INSERT INTO agent_relationships (agent_a, agent_b) VALUES (?, ?)",
                            (canonical_a, canonical_b),
                        )

                    # Increment debate count
                    conn.execute(
                        """
                        UPDATE agent_relationships
                        SET debate_count = debate_count + 1, updated_at = ?
                        WHERE agent_a = ? AND agent_b = ?
                        """,
                        (datetime.now().isoformat(), canonical_a, canonical_b),
                    )

                    # Check agreement (same vote)
                    if votes.get(agent_a) == votes.get(agent_b):
                        conn.execute(
                            """
                            UPDATE agent_relationships
                            SET agreement_count = agreement_count + 1
                            WHERE agent_a = ? AND agent_b = ?
                            """,
                            (canonical_a, canonical_b),
                        )

                    # Track winner
                    if winner == agent_a:
                        col = "a_wins_over_b" if not is_swapped else "b_wins_over_a"
                        conn.execute(
                            f"""
                            UPDATE agent_relationships
                            SET {col} = {col} + 1
                            WHERE agent_a = ? AND agent_b = ?
                            """,  # nosec B608 - col is from controlled set  # noqa: S608
                            (canonical_a, canonical_b),
                        )
                    elif winner == agent_b:
                        col = "b_wins_over_a" if not is_swapped else "a_wins_over_b"
                        conn.execute(
                            f"""
                            UPDATE agent_relationships
                            SET {col} = {col} + 1
                            WHERE agent_a = ? AND agent_b = ?
                            """,  # nosec B608 - col is from controlled set  # noqa: S608
                            (canonical_a, canonical_b),
                        )

            # Track critiques
            for critique in critiques:
                critic = critique.get("agent") or critique.get("critic")
                target = critique.get("target") or critique.get("target_agent")
                if not critic or not target or critic == target:
                    continue

                canonical_a, canonical_b = self._canonical_pair(critic, target)
                is_critic_a = canonical_a == critic

                col = "critique_count_a_to_b" if is_critic_a else "critique_count_b_to_a"
                conn.execute(
                    f"""
                    UPDATE agent_relationships
                    SET {col} = {col} + 1
                    WHERE agent_a = ? AND agent_b = ?
                    """,  # nosec B608 - col is from controlled set  # noqa: S608
                    (canonical_a, canonical_b),
                )

            conn.commit()

    def get_relationship(self, agent_a: str, agent_b: str) -> AgentRelationship:
        """
        Get relationship between two agents with computed properties.

        Args:
            agent_a: First agent name
            agent_b: Second agent name

        Returns:
            AgentRelationship with rivalry_score, alliance_score, and influence properties
        """
        stats = self.get_raw(agent_a, agent_b)
        if stats is None:
            canonical_a, canonical_b = self._canonical_pair(agent_a, agent_b)
            return AgentRelationship(agent_a=canonical_a, agent_b=canonical_b)

        return AgentRelationship.from_stats(stats)

    def get_all_relationships(self, agent_name: str) -> list[AgentRelationship]:
        """
        Get all relationships for an agent with computed properties.

        Args:
            agent_name: Agent to get relationships for

        Returns:
            List of AgentRelationship sorted by debate_count descending
        """
        stats_list = self.get_all_for_agent(agent_name)
        return [AgentRelationship.from_stats(s) for s in stats_list]

    def get_influence_network(self, agent_name: str) -> dict[str, list[tuple[str, float]]]:
        """
        Get who this agent influences and who influences them.

        Args:
            agent_name: Agent to analyze

        Returns:
            Dict with 'influences' and 'influenced_by' lists of (agent, score) tuples
        """
        relationships = self.get_all_relationships(agent_name)

        influences = []  # Who this agent influences
        influenced_by = []  # Who influences this agent

        for rel in relationships:
            other = rel.agent_b if rel.agent_a == agent_name else rel.agent_a
            is_a = rel.agent_a == agent_name

            if is_a:
                if rel.influence_a_on_b > 0:
                    influences.append((other, rel.influence_a_on_b))
                if rel.influence_b_on_a > 0:
                    influenced_by.append((other, rel.influence_b_on_a))
            else:
                if rel.influence_b_on_a > 0:
                    influences.append((other, rel.influence_b_on_a))
                if rel.influence_a_on_b > 0:
                    influenced_by.append((other, rel.influence_a_on_b))

        influences.sort(key=lambda x: x[1], reverse=True)
        influenced_by.sort(key=lambda x: x[1], reverse=True)

        return {"influences": influences, "influenced_by": influenced_by}
