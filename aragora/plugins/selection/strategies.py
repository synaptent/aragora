"""
Built-in Selection Strategies - Default implementations of selection plugins.

These strategies implement the protocols defined in protocols.py and
represent the default behavior of the selection system.

Custom plugins can extend or replace these strategies.
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from aragora.plugins.selection.protocols import (
    RoleAssignerProtocol,
    ScorerProtocol,
    SelectionContext,
    TeamSelectorProtocol,
)

if TYPE_CHECKING:
    from aragora.routing.selection import AgentProfile, TaskRequirements

logger = logging.getLogger(__name__)


class ELOWeightedScorer(ScorerProtocol):
    """
    Default scorer using ELO + domain expertise + calibration.

    Score composition:
    - 30% ELO rating (normalized)
    - 30% Domain expertise
    - 20% Domain-specific ELO
    - 10% Secondary domain coverage
    - 10% Trait matching

    Adjustments applied:
    - Probe reliability (penalizes vulnerable agents)
    - Calibration quality (penalizes overconfident agents)
    - Performance history (penalizes unreliable agents)
    """

    @property
    def name(self) -> str:
        return "elo-weighted"

    @property
    def description(self) -> str:
        return "ELO + domain expertise + calibration weighted scoring"

    def score_agent(
        self,
        agent: AgentProfile,
        requirements: TaskRequirements,
        context: SelectionContext,
    ) -> float:
        """Score an agent for a specific task."""
        score = 0.0

        # Base ELO contribution (30%)
        elo_score = (agent.elo_rating - 1000) / 1000
        score += elo_score * 0.3

        # Get dynamic expertise from PersonaManager if available
        expertise = agent.expertise.copy()
        traits = list(agent.traits) if agent.traits else []

        if context.persona_manager:
            try:
                persona = context.persona_manager.get_persona(agent.name)
                if persona:
                    for domain, exp_score in persona.expertise.items():
                        expertise[domain] = exp_score
                    for trait in persona.traits:
                        if trait not in traits:
                            traits.append(trait)
            except (AttributeError, KeyError, ValueError, LookupError) as e:
                logger.debug("Failed to get persona for %s: %s", agent.name, e)

        # Domain expertise (30%)
        primary_exp = expertise.get(requirements.primary_domain, 0.5)
        score += primary_exp * 0.3

        # Domain-specific ELO (20%)
        domain_elo = agent.domain_ratings.get(requirements.primary_domain, 1500)
        score += (domain_elo - 1000) / 1000 * 0.2

        # Secondary domains (10%)
        if requirements.secondary_domains:
            secondary_score = sum(
                expertise.get(d, 0.3) for d in requirements.secondary_domains
            ) / len(requirements.secondary_domains)
            score += secondary_score * 0.1

        # Trait matching (10%)
        if requirements.required_traits:
            matching_traits = sum(1 for t in requirements.required_traits if t in traits)
            score += matching_traits / len(requirements.required_traits) * 0.1

        # Adjust for quality priority
        if requirements.quality_priority > 0.5:
            score = score * 0.7 + agent.success_rate * 0.3
        else:
            speed_score = 1 - min(agent.latency_ms, 5000) / 5000
            cost_score = 1 - min(agent.cost_factor, 3) / 3
            score = score * 0.6 + speed_score * 0.2 + cost_score * 0.2

        # Apply reliability adjustments
        score = self._apply_probe_adjustment(agent, score, context)
        score = self._apply_calibration_adjustment(agent, score, context)
        score = self._apply_performance_adjustment(agent, score, context)

        return max(0.0, min(1.0, score))

    def _apply_probe_adjustment(
        self,
        agent: AgentProfile,
        score: float,
        context: SelectionContext,
    ) -> float:
        """Adjust score based on probe reliability."""
        probe_score = agent.probe_score
        has_critical = agent.has_critical_probes

        if context.probe_filter:
            try:
                probe_profile = context.probe_filter.get_agent_profile(agent.name)
                if probe_profile.total_probes > 0:
                    probe_score = probe_profile.probe_score
                    has_critical = probe_profile.has_critical_issues()
            except (AttributeError, KeyError, ValueError, LookupError) as e:
                logger.debug("Probe filter lookup failed for %s: %s", agent.name, type(e).__name__)

        adjustment = 0.5 + (probe_score * 0.5)
        if has_critical:
            adjustment *= 0.8

        return score * adjustment

    def _apply_calibration_adjustment(
        self,
        agent: AgentProfile,
        score: float,
        context: SelectionContext,
    ) -> float:
        """Adjust score based on calibration quality."""
        calibration_score = agent.calibration_score
        is_overconfident = agent.is_overconfident

        if context.calibration_tracker:
            try:
                summary = context.calibration_tracker.get_calibration_summary(agent.name)
                if summary.total_predictions >= 5:
                    calibration_score = max(0.0, 1.0 - summary.ece)
                    is_overconfident = summary.is_overconfident
            except (AttributeError, KeyError, ValueError, LookupError) as e:
                logger.debug("Calibration lookup failed for %s: %s", agent.name, type(e).__name__)

        adjustment = 0.7 + (calibration_score * 0.3)
        if is_overconfident:
            adjustment *= 0.9

        return score * adjustment

    def _apply_performance_adjustment(
        self,
        agent: AgentProfile,
        score: float,
        context: SelectionContext,
    ) -> float:
        """Adjust score based on performance history."""
        if not context.performance_insights:
            return score

        agent_stats = context.performance_insights.get("agent_stats", {}).get(agent.name, {})
        if not agent_stats:
            return score

        adjustment = 1.0

        success_rate = agent_stats.get("success_rate", 100)
        if success_rate < 70:
            adjustment *= 0.8
        elif success_rate < 85:
            adjustment *= 0.9

        timeout_rate = agent_stats.get("timeout_rate", 0)
        if timeout_rate > 20:
            adjustment *= 0.7
        elif timeout_rate > 10:
            adjustment *= 0.85

        failure_rate = agent_stats.get("failure_rate", 0)
        if failure_rate > 30:
            adjustment *= 0.75

        return score * adjustment


class DiverseTeamSelector(TeamSelectorProtocol):
    """
    Default team selector balancing quality with diversity.

    Selection strategy:
    - Greedily select highest-scored agents up to min_agents
    - For additional agents, balance quality with diversity:
      - Different agent types preferred
      - New traits preferred
      - Still considers underlying score
    """

    @property
    def name(self) -> str:
        return "diverse"

    @property
    def description(self) -> str:
        return "Diversity-aware team selection balancing quality and variety"

    def select_team(
        self,
        scored_agents: list[tuple[AgentProfile, float]],
        requirements: TaskRequirements,
        context: SelectionContext,
    ) -> list[AgentProfile]:
        """Select a diverse team from scored candidates."""
        if len(scored_agents) <= requirements.min_agents:
            return [a for a, _ in scored_agents]

        team: list[AgentProfile] = []
        remaining = list(scored_agents)
        diversity_pref = requirements.diversity_preference

        while len(team) < requirements.max_agents and remaining:
            if len(team) < requirements.min_agents or random.random() > diversity_pref:
                # Greedy: pick highest scored
                agent, _ = remaining[0]
                team.append(agent)
                remaining = remaining[1:]
            else:
                # Diversity: pick someone different
                team_types = set(a.agent_type for a in team)
                team_traits: set[str] = set()
                for a in team:
                    team_traits.update(a.traits)

                best_diff: AgentProfile | None = None
                best_diff_score: float = -1.0

                for agent, score in remaining:
                    diff_score: float = 0.0
                    if agent.agent_type not in team_types:
                        diff_score += 0.5
                    new_traits = set(agent.traits) - team_traits
                    diff_score += len(new_traits) * 0.1
                    diff_score += score * 0.4

                    if diff_score > best_diff_score:
                        best_diff = agent
                        best_diff_score = diff_score

                if best_diff:
                    team.append(best_diff)
                    remaining = [(a, s) for a, s in remaining if a.name != best_diff.name]
                else:
                    break

        return team


class DomainBasedRoleAssigner(RoleAssignerProtocol):
    """
    Default role assigner using domain expertise.

    Assignment strategy:
    - Proposer: Highest domain expertise
    - Synthesizer: Most balanced overall score
    - Critics: Matched by traits (security, performance, etc.)
    - Phase-specific roles for hybrid model

    Phase roles (for hybrid architecture):
    - debate: All proposers
    - design: Gemini leads, others critique
    - implement: Claude leads, others advise
    - verify: Codex leads, others review
    """

    # Phase role configuration
    PHASE_ROLES: dict[str, tuple[dict[str, str], str]] = {
        "debate": ({}, "proposer"),
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

    @property
    def name(self) -> str:
        return "domain-based"

    @property
    def description(self) -> str:
        return "Domain expertise-based role assignment with phase awareness"

    def assign_roles(
        self,
        team: list[AgentProfile],
        requirements: TaskRequirements,
        context: SelectionContext,
        phase: str | None = None,
    ) -> dict[str, str]:
        """Assign roles to team members."""
        if phase:
            return self._assign_phase_roles(team, phase)
        return self._assign_debate_roles(team, requirements)

    def _assign_debate_roles(
        self,
        team: list[AgentProfile],
        requirements: TaskRequirements,
    ) -> dict[str, str]:
        """Assign standard debate roles."""
        roles: dict[str, str] = {}

        if not team:
            return roles

        by_expertise = sorted(
            team,
            key=lambda a: a.expertise.get(requirements.primary_domain, 0),
            reverse=True,
        )

        roles[by_expertise[0].name] = "proposer"

        if len(team) > 1:
            remaining = by_expertise[1:]
            balanced = min(
                remaining,
                key=lambda a: abs(a.overall_score - 0.5),
            )
            roles[balanced.name] = "synthesizer"

        for agent in team:
            if agent.name not in roles:
                if "thorough" in agent.traits or "security" in agent.traits:
                    roles[agent.name] = "security_critic"
                elif "pragmatic" in agent.traits or "performance" in agent.traits:
                    roles[agent.name] = "performance_critic"
                else:
                    roles[agent.name] = "critic"

        return roles

    def _assign_phase_roles(
        self,
        team: list[AgentProfile],
        phase: str,
    ) -> dict[str, str]:
        """Assign phase-specific roles for hybrid model."""
        roles: dict[str, str] = {}
        role_map, fallback = self.PHASE_ROLES.get(phase, ({}, "participant"))

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


class GreedyTeamSelector(TeamSelectorProtocol):
    """
    Simple greedy team selector - picks highest-scored agents.

    Useful as a baseline or for speed-critical scenarios.
    """

    @property
    def name(self) -> str:
        return "greedy"

    @property
    def description(self) -> str:
        return "Simple greedy selection of highest-scored agents"

    def select_team(
        self,
        scored_agents: list[tuple[AgentProfile, float]],
        requirements: TaskRequirements,
        context: SelectionContext,
    ) -> list[AgentProfile]:
        """Select top N agents by score."""
        count = min(requirements.max_agents, len(scored_agents))
        return [a for a, _ in scored_agents[:count]]


class RandomTeamSelector(TeamSelectorProtocol):
    """
    Random team selector - for exploration and testing.

    Useful for A/B testing selection strategies.
    """

    @property
    def name(self) -> str:
        return "random"

    @property
    def description(self) -> str:
        return "Random agent selection for exploration"

    def select_team(
        self,
        scored_agents: list[tuple[AgentProfile, float]],
        requirements: TaskRequirements,
        context: SelectionContext,
    ) -> list[AgentProfile]:
        """Randomly select agents (weighted by score)."""
        agents = [a for a, _ in scored_agents]
        scores = [s for _, s in scored_agents]

        # Weighted random selection
        count = min(requirements.max_agents, len(agents))
        if count >= len(agents):
            return agents

        # Normalize scores to probabilities
        total = sum(scores) or 1.0
        probs = [s / total for s in scores]

        selected: list[AgentProfile] = []
        available = list(zip(agents, probs))

        for _ in range(count):
            if not available:
                break
            roll = random.random()
            cumulative = 0.0
            for i, (agent, prob) in enumerate(available):
                cumulative += prob
                if roll <= cumulative:
                    selected.append(agent)
                    available.pop(i)
                    # Renormalize remaining probabilities
                    remaining_total = sum(p for _, p in available) or 1.0
                    available = [(a, p / remaining_total) for a, p in available]
                    break

        return selected


class AHMADRoleAssigner(RoleAssignerProtocol):
    """
    Adaptive role assigner using A-HMAD dynamic specialization.

    Uses AHMADRoleSpecializer to select roles based on topic/domain and
    agent performance history, with domain-based fallback for phases.
    """

    def __init__(self) -> None:
        self._fallback = DomainBasedRoleAssigner()
        try:
            from aragora.debate.role_specializer import AHMADRoleSpecializer

            self._specializer = AHMADRoleSpecializer()
        except (
            ImportError,
            RuntimeError,
            AttributeError,
        ) as exc:  # pragma: no cover - defensive fallback
            logger.debug("AHMAD role specializer unavailable: %s", exc)
            self._specializer = None

    @property
    def name(self) -> str:
        return "ahmad"

    @property
    def description(self) -> str:
        return "Adaptive role specialization using A-HMAD"

    def assign_roles(
        self,
        team: list[AgentProfile],
        requirements: TaskRequirements,
        context: SelectionContext,
        phase: str | None = None,
    ) -> dict[str, str]:
        if not team:
            return {}

        if phase:
            return self._fallback.assign_roles(team, requirements, context, phase=phase)

        if not self._specializer:
            return self._fallback.assign_roles(team, requirements, context)

        roles = self._specializer.analyze_topic(
            topic=requirements.description or "",
            domain=requirements.primary_domain,
        )

        available_agents = [agent.name for agent in team]
        elo_scores = {agent.name: agent.elo_rating for agent in team}
        calibration_scores = {agent.name: agent.brier_score for agent in team}
        domain_scores = {agent.name: agent.expertise for agent in team}

        composition = self._specializer.assign_roles(
            roles=roles,
            available_agents=available_agents,
            elo_scores=elo_scores,
            calibration_scores=calibration_scores,
            domain_scores=domain_scores,
        )

        role_map = {assign.agent_id: assign.role.value for assign in composition.assignments}

        for agent in team:
            if agent.name not in role_map:
                role_map[agent.name] = "generalist"

        return role_map


class SimpleRoleAssigner(RoleAssignerProtocol):
    """
    Simple role assigner - assigns generic roles.

    Useful as a baseline or when role differentiation isn't needed.
    """

    @property
    def name(self) -> str:
        return "simple"

    @property
    def description(self) -> str:
        return "Simple role assignment with first=proposer, last=synthesizer"

    def assign_roles(
        self,
        team: list[AgentProfile],
        requirements: TaskRequirements,
        context: SelectionContext,
        phase: str | None = None,
    ) -> dict[str, str]:
        """Assign simple positional roles."""
        roles: dict[str, str] = {}

        if not team:
            return roles

        roles[team[0].name] = "proposer"

        if len(team) > 1:
            roles[team[-1].name] = "synthesizer"

        for agent in team[1:-1] if len(team) > 2 else []:
            roles[agent.name] = "critic"

        return roles
