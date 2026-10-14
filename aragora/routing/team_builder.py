"""
Team building utilities for agent selection.

Provides team composition, diversity calculation, and role assignment logic
extracted from AgentSelector for better modularity.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.routing.selection import AgentProfile, TaskRequirements, TeamComposition

logger = logging.getLogger(__name__)

# Phase role configuration: phase -> (agent_role_map, fallback_role)
# agent_role_map: {agent_type: role}
PHASE_ROLES: dict[str, tuple[dict[str, str], str]] = {
    "debate": ({}, "proposer"),  # All agents are proposers
    "design": (
        {
            "gemini": "design_lead",
            "claude": "architecture_critic",
            "codex": "implementation_critic",
            "grok": "devil_advocate",
            "deepseek": "logic_validator",
        },
        "critic",
    ),
    "implement": ({"claude": "implementer"}, "advisor"),
    "verify": (
        {
            "codex": "verification_lead",
            "grok": "quality_auditor",
            "gemini": "design_validator",
            "claude": "implementation_reviewer",
            "deepseek": "formal_verifier",
        },
        "reviewer",
    ),
    "commit": ({}, "reviewer"),
}


class TeamBuilder:
    """
    Builds and composes teams of agents for debate tasks.

    Handles team selection with diversity optimization, role assignment,
    and team composition scoring.
    """

    def __init__(self) -> None:
        """Initialize the team builder."""
        self._selection_history: list[dict] = []

    def select_team(
        self,
        scored_agents: list[tuple[AgentProfile, float]],
        requirements: TaskRequirements,
        score_for_task_fn: Any,
    ) -> TeamComposition:
        """
        Select an optimal team from scored candidates.

        Args:
            scored_agents: List of (agent, score) tuples, sorted by score descending
            requirements: Task requirements
            score_for_task_fn: Function to score an agent for this task

        Returns:
            TeamComposition with selected agents
        """
        # Import here to avoid circular imports
        from aragora.routing.selection import TeamComposition

        if not scored_agents:
            raise ValueError("No available agents to select from")

        # Select team considering diversity
        team = self.select_diverse_team(
            scored_agents,
            requirements.min_agents,
            requirements.max_agents,
            requirements.diversity_preference,
        )

        # Assign roles
        roles = self.assign_roles(team, requirements)

        # Calculate expected quality
        expected_quality = sum(score_for_task_fn(a, requirements) for a in team) / len(team)

        # Calculate cost
        expected_cost = sum(a.cost_factor for a in team)

        # Calculate diversity
        diversity_score = self.calculate_diversity(team)

        # Generate rationale
        rationale = self._generate_rationale(team, requirements, scored_agents)

        # Record selection
        self._selection_history.append(
            {
                "task_id": requirements.task_id,
                "selected": [a.name for a in team],
                "timestamp": datetime.now().isoformat(),
            }
        )

        return TeamComposition(
            team_id=f"team-{requirements.task_id}",
            task_id=requirements.task_id,
            agents=team,
            roles=roles,
            expected_quality=expected_quality,
            expected_cost=expected_cost,
            diversity_score=diversity_score,
            rationale=rationale,
        )

    def select_diverse_team(
        self,
        scored: list[tuple[AgentProfile, float]],
        min_size: int,
        max_size: int,
        diversity_pref: float,
    ) -> list[AgentProfile]:
        """
        Select a diverse team from scored candidates.

        Args:
            scored: List of (agent, score) tuples, sorted by score descending
            min_size: Minimum team size
            max_size: Maximum team size
            diversity_pref: Diversity preference (0=homogeneous, 1=diverse)

        Returns:
            List of selected AgentProfiles
        """
        if len(scored) <= min_size:
            return [a for a, _ in scored]

        team: list[AgentProfile] = []
        remaining = list(scored)

        while len(team) < max_size and remaining:
            if len(team) < min_size or random.random() > diversity_pref:
                # Greedy: pick highest scored
                agent, score = remaining[0]
                team.append(agent)
                remaining = remaining[1:]
            else:
                # Diversity: pick someone different
                team_types = set(a.agent_type for a in team)
                team_traits: set[str] = set()
                for a in team:
                    team_traits.update(a.traits)

                # Find most different agent
                best_diff: AgentProfile | None = None
                best_diff_score: float = -1.0

                for agent, score in remaining:
                    diff_score: float = 0.0
                    if agent.agent_type not in team_types:
                        diff_score += 0.5
                    new_traits = set(agent.traits) - team_traits
                    diff_score += len(new_traits) * 0.1
                    diff_score += score * 0.4  # Still consider quality

                    if diff_score > best_diff_score:
                        best_diff = agent
                        best_diff_score = diff_score

                if best_diff:
                    team.append(best_diff)
                    remaining = [(a, s) for a, s in remaining if a.name != best_diff.name]
                else:
                    break

        return team

    def calculate_diversity(self, team: list[AgentProfile]) -> float:
        """
        Calculate team diversity score.

        Args:
            team: List of agent profiles

        Returns:
            Diversity score between 0 and 1
        """
        if len(team) <= 1:
            return 0.0

        # Type diversity
        types = set(a.agent_type for a in team)
        type_div = len(types) / len(team)

        # Trait diversity
        all_traits: set[str] = set()
        for a in team:
            all_traits.update(a.traits)
        trait_div = len(all_traits) / (len(team) * 3)  # Assume avg 3 traits

        # ELO diversity (mix of skill levels)
        elos = [a.elo_rating for a in team]
        elo_range = max(elos) - min(elos) if len(elos) > 1 else 0
        elo_div = min(elo_range / 500, 1.0)  # Normalize to 500 range

        return type_div * 0.4 + trait_div * 0.3 + elo_div * 0.3

    def assign_roles(
        self,
        team: list[AgentProfile],
        requirements: TaskRequirements,
    ) -> dict[str, str]:
        """
        Assign debate roles to team members.

        Args:
            team: List of agent profiles
            requirements: Task requirements

        Returns:
            Dictionary mapping agent names to roles
        """
        roles: dict[str, str] = {}

        if not team:
            return roles

        # Sort by domain expertise for proposer selection
        by_expertise = sorted(
            team,
            key=lambda a: a.expertise.get(requirements.primary_domain, 0),
            reverse=True,
        )

        # Assign proposer to highest domain expert
        roles[by_expertise[0].name] = "proposer"

        # Assign synthesizer to most balanced agent
        if len(team) > 1:
            remaining = by_expertise[1:]
            balanced = min(
                remaining,
                key=lambda a: abs(a.overall_score - 0.5),
            )
            roles[balanced.name] = "synthesizer"

        # Assign critics to rest
        for agent in team:
            if agent.name not in roles:
                # Try to match critic type to traits
                if "thorough" in agent.traits or "security" in agent.traits:
                    roles[agent.name] = "security_critic"
                elif "pragmatic" in agent.traits or "performance" in agent.traits:
                    roles[agent.name] = "performance_critic"
                else:
                    roles[agent.name] = "critic"

        return roles

    def assign_hybrid_roles(
        self,
        team: list[AgentProfile],
        phase: str,
    ) -> dict[str, str]:
        """
        Assign phase-specific roles for Hybrid Model Architecture.

        Architecture:
        - Gemini: Primary planner/designer (leads Phase 2)
        - Claude: Primary implementer (leads Phase 3)
        - Codex: Primary verifier (leads Phase 4)
        - Grok: Lateral thinker/devil's advocate (critiques all phases)
        - DeepSeek: Rigorous analyst/formal reasoner (validates logic all phases)

        Args:
            team: List of agent profiles
            phase: Current debate phase

        Returns:
            Dictionary mapping agent names to phase-specific roles
        """
        roles: dict[str, str] = {}

        # Get phase configuration or default fallback
        role_map, fallback = PHASE_ROLES.get(phase, ({}, "participant"))

        # Assign roles from the role map
        for agent in team:
            assigned = False
            for agent_type, role in role_map.items():
                if agent_type in agent.name.lower() or agent.agent_type == agent_type:
                    roles[agent.name] = role
                    assigned = True
                    break
            if not assigned:
                roles[agent.name] = fallback

        return roles

    def _generate_rationale(
        self,
        team: list[AgentProfile],
        requirements: TaskRequirements,
        all_scored: list[tuple[AgentProfile, float]],
    ) -> str:
        """Generate human-readable selection rationale."""
        lines = [
            f"Selected {len(team)} agents for task '{requirements.task_id}':",
            f"Primary domain: {requirements.primary_domain}",
            "",
            "Team composition:",
        ]

        for agent in team:
            expertise = agent.expertise.get(requirements.primary_domain, 0)
            domain_elo = agent.domain_ratings.get(requirements.primary_domain, agent.elo_rating)
            lines.append(
                f"- {agent.name} ({agent.agent_type}): "
                f"ELO {agent.elo_rating:.0f}, "
                f"Domain ELO {domain_elo:.0f}, "
                f"Expertise {expertise:.0%}"
            )

        if len(all_scored) > len(team):
            lines.append("")
            lines.append(f"Considered {len(all_scored)} candidates, selected top {len(team)}")

        return "\n".join(lines)

    def record_selection(
        self, task_id: str, selected: list[str], result: str | None = None, confidence: float = 0
    ) -> None:
        """Record a selection to history."""
        entry: dict[str, Any] = {
            "task_id": task_id,
            "selected": selected,
            "timestamp": datetime.now().isoformat(),
        }
        if result:
            entry["result"] = result
            entry["confidence"] = confidence
        self._selection_history.append(entry)

    def get_selection_history(self, limit: int | None = None) -> list[dict]:
        """Retrieve selection history for meta-analysis."""
        history = self._selection_history.copy()
        history.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        if limit:
            history = history[:limit]
        return history


__all__ = [
    "PHASE_ROLES",
    "TeamBuilder",
]
