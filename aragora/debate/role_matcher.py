"""
Dynamic Role Matching Based on Agent Calibration.

Assigns cognitive roles to agents based on their calibration scores and expertise,
rather than using simple sequential rotation. This helps agents develop in areas
where they need improvement while leveraging their strengths.

Role-Calibration Mapping:
- Well-calibrated (low Brier, low ECE) → SKEPTIC, QUALITY_CHALLENGER
- Overconfident → DEVIL_ADVOCATE (developmental assignment)
- Underconfident → ADVOCATE (developmental assignment)
- High domain expertise → ANALYST
- High accuracy → SYNTHESIZER

Strategies:
- "calibration": Pure calibration-based matching
- "hybrid": Blend calibration + expertise + randomness
- "rotation": Fall back to simple rotation (default behavior)
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from typing import Literal

from aragora.agents.calibration import CalibrationSummary, CalibrationTracker
from aragora.agents.personas import Persona, PersonaManager
from aragora.debate.roles import ROLE_PROMPTS, CognitiveRole, RoleAssignment

logger = logging.getLogger(__name__)


@dataclass
class RoleMatchingConfig:
    """Configuration for role matching behavior."""

    strategy: Literal["calibration", "hybrid", "rotation"] = "hybrid"
    """Strategy for role assignment."""

    calibration_weight: float = 0.4
    """Weight for calibration scores in hybrid strategy."""

    expertise_weight: float = 0.3
    """Weight for expertise scores in hybrid strategy."""

    min_predictions_for_calibration: int = 5
    """Minimum predictions before using calibration data (cold-start threshold)."""

    selection_temperature: float = 1.0
    """Temperature for softmax selection (higher = more random)."""

    enable_developmental_assignment: bool = True
    """Assign roles that help agents improve weaknesses."""

    brier_threshold: float = 0.25
    """Brier score threshold for 'well-calibrated' status."""

    ece_threshold: float = 0.1
    """ECE threshold for 'well-calibrated' status."""


@dataclass
class RoleMatchResult:
    """Result of role matching for a single round."""

    round_num: int
    assignments: dict[str, RoleAssignment]
    strategy_used: str
    calibration_used: bool
    cold_start_agents: list[str] = field(default_factory=list)
    developmental_assignments: list[str] = field(default_factory=list)


class RoleMatcher:
    """
    Matches agents to cognitive roles based on calibration and expertise.

    Usage:
        matcher = RoleMatcher(
            calibration_tracker=tracker,
            persona_manager=manager,
            config=RoleMatchingConfig(),
        )

        # Get role assignments for a round
        result = matcher.match_roles(
            agent_names=["claude", "gpt", "gemini"],
            round_num=1,
            debate_domain="security",
        )

        # Apply assignments
        for agent_name, assignment in result.assignments.items():
            agent.set_cognitive_role(assignment)
    """

    def __init__(
        self,
        calibration_tracker: CalibrationTracker | None = None,
        persona_manager: PersonaManager | None = None,
        config: RoleMatchingConfig | None = None,
    ):
        """
        Initialize role matcher.

        Args:
            calibration_tracker: For accessing calibration scores
            persona_manager: For accessing expertise data
            config: Role matching configuration
        """
        self.calibration_tracker = calibration_tracker
        self.persona_manager = persona_manager
        self.config = config or RoleMatchingConfig()

        # Cache calibration summaries per agent
        self._calibration_cache: dict[str, CalibrationSummary] = {}

        logger.info(
            "RoleMatcher initialized: strategy=%s, developmental=%s",
            self.config.strategy,
            self.config.enable_developmental_assignment,
        )

    def match_roles(
        self,
        agent_names: list[str],
        round_num: int,
        debate_domain: str | None = None,
    ) -> RoleMatchResult:
        """
        Match agents to cognitive roles for a round.

        Args:
            agent_names: List of participating agent names
            round_num: Current round number (for rotation fallback)
            debate_domain: Optional domain for expertise matching

        Returns:
            RoleMatchResult with assignments for each agent
        """
        if self.config.strategy == "rotation":
            return self._rotation_strategy(agent_names, round_num)

        # Get calibration and expertise data
        calibrations = self._get_calibrations(agent_names)
        personas = self._get_personas(agent_names)

        # Identify cold-start agents
        cold_start = [
            name
            for name in agent_names
            if (cal := calibrations.get(name)) is None
            or cal.total_predictions < self.config.min_predictions_for_calibration
        ]

        if self.config.strategy == "calibration":
            return self._calibration_strategy(agent_names, round_num, calibrations, cold_start)
        else:  # hybrid
            return self._hybrid_strategy(
                agent_names, round_num, calibrations, personas, debate_domain, cold_start
            )

    def _rotation_strategy(
        self,
        agent_names: list[str],
        round_num: int,
    ) -> RoleMatchResult:
        """Simple sequential rotation of roles."""
        roles = list(CognitiveRole)
        assignments: dict[str, RoleAssignment] = {}

        for i, agent in enumerate(agent_names):
            role_idx = (i + round_num) % len(roles)
            role = roles[role_idx]
            assignments[agent] = RoleAssignment(
                agent_name=agent,
                role=role,
                round_num=round_num,
                role_prompt=ROLE_PROMPTS.get(role, ""),
            )

        return RoleMatchResult(
            round_num=round_num,
            assignments=assignments,
            strategy_used="rotation",
            calibration_used=False,
        )

    def _calibration_strategy(
        self,
        agent_names: list[str],
        round_num: int,
        calibrations: dict[str, CalibrationSummary | None],
        cold_start: list[str],
    ) -> RoleMatchResult:
        """Assign roles purely based on calibration."""
        assignments: dict[str, RoleAssignment] = {}
        developmental: list[str] = []
        used_roles: set[CognitiveRole] = set()

        for agent in agent_names:
            cal = calibrations.get(agent)

            if agent in cold_start or cal is None:
                # Random assignment for cold-start agents
                available = [r for r in CognitiveRole if r not in used_roles]
                if not available:
                    available = list(CognitiveRole)
                role = random.choice(available)  # non-security role assignment
            else:
                role = self._select_role_by_calibration(cal, used_roles)
                if self.config.enable_developmental_assignment:
                    if cal.is_overconfident or cal.is_underconfident:
                        developmental.append(agent)

            used_roles.add(role)
            assignments[agent] = RoleAssignment(
                agent_name=agent,
                role=role,
                round_num=round_num,
                role_prompt=ROLE_PROMPTS.get(role, ""),
            )

        return RoleMatchResult(
            round_num=round_num,
            assignments=assignments,
            strategy_used="calibration",
            calibration_used=True,
            cold_start_agents=cold_start,
            developmental_assignments=developmental,
        )

    def _hybrid_strategy(
        self,
        agent_names: list[str],
        round_num: int,
        calibrations: dict[str, CalibrationSummary | None],
        personas: dict[str, Persona | None],
        debate_domain: str | None,
        cold_start: list[str],
    ) -> RoleMatchResult:
        """Hybrid strategy blending calibration, expertise, and randomness."""
        assignments: dict[str, RoleAssignment] = {}
        developmental: list[str] = []
        used_roles: set[CognitiveRole] = set()

        # Compute affinity scores for each agent-role pair
        affinity_matrix = self._compute_affinity_matrix(
            agent_names, calibrations, personas, debate_domain
        )

        # Greedy assignment with temperature-based selection
        for agent in agent_names:
            if agent in cold_start:
                # Random for cold-start
                available = [r for r in CognitiveRole if r not in used_roles]
                if not available:
                    available = list(CognitiveRole)
                role = random.choice(available)  # non-security role assignment
            else:
                role = self._softmax_select_role(
                    affinity_matrix.get(agent, {}),
                    used_roles,
                    self.config.selection_temperature,
                )

                cal = calibrations.get(agent)
                if cal and self.config.enable_developmental_assignment:
                    if cal.is_overconfident or cal.is_underconfident:
                        developmental.append(agent)

            used_roles.add(role)
            assignments[agent] = RoleAssignment(
                agent_name=agent,
                role=role,
                round_num=round_num,
                role_prompt=ROLE_PROMPTS.get(role, ""),
            )

        return RoleMatchResult(
            round_num=round_num,
            assignments=assignments,
            strategy_used="hybrid",
            calibration_used=True,
            cold_start_agents=cold_start,
            developmental_assignments=developmental,
        )

    def _select_role_by_calibration(
        self,
        cal: CalibrationSummary,
        used_roles: set[CognitiveRole],
    ) -> CognitiveRole:
        """Select a role based on calibration metrics."""
        is_well_calibrated = (
            cal.brier_score < self.config.brier_threshold and cal.ece < self.config.ece_threshold
        )

        # Priority order based on calibration status
        if is_well_calibrated:
            # Well-calibrated agents make good skeptics and quality challengers
            preferred = [CognitiveRole.SKEPTIC, CognitiveRole.QUALITY_CHALLENGER]
        elif cal.is_overconfident and self.config.enable_developmental_assignment:
            # Overconfident agents should practice devil's advocate
            preferred = [CognitiveRole.DEVIL_ADVOCATE, CognitiveRole.SKEPTIC]
        elif cal.is_underconfident and self.config.enable_developmental_assignment:
            # Underconfident agents should practice advocacy
            preferred = [CognitiveRole.ADVOCATE, CognitiveRole.ANALYST]
        elif cal.accuracy > 0.7:
            # High accuracy agents make good synthesizers
            preferred = [CognitiveRole.SYNTHESIZER, CognitiveRole.ANALYST]
        else:
            # Default order
            preferred = [CognitiveRole.ANALYST, CognitiveRole.LATERAL_THINKER]

        # Find first available preferred role
        for role in preferred:
            if role not in used_roles:
                return role

        # Fallback to any available role
        available = [r for r in CognitiveRole if r not in used_roles]
        if available:
            return random.choice(available)  # non-security role assignment

        # All roles used, just pick one
        return random.choice(list(CognitiveRole))  # non-security role assignment

    def _compute_affinity_matrix(
        self,
        agent_names: list[str],
        calibrations: dict[str, CalibrationSummary | None],
        personas: dict[str, Persona | None],
        debate_domain: str | None,
    ) -> dict[str, dict[CognitiveRole, float]]:
        """Compute affinity scores for each agent-role pair."""
        matrix: dict[str, dict[CognitiveRole, float]] = {}

        for agent in agent_names:
            cal = calibrations.get(agent)
            persona = personas.get(agent)
            affinities: dict[CognitiveRole, float] = {}

            for role in CognitiveRole:
                score = 0.5  # Base score

                # Calibration contribution
                if cal and cal.total_predictions >= self.config.min_predictions_for_calibration:
                    cal_score = self._calibration_affinity(cal, role)
                    score += self.config.calibration_weight * cal_score

                # Expertise contribution
                if persona and debate_domain and persona.expertise:
                    exp_score = self._expertise_affinity(persona, debate_domain, role)
                    score += self.config.expertise_weight * exp_score

                # Trait contribution (from persona)
                if persona and persona.traits:
                    trait_score = self._trait_affinity(persona.traits, role)
                    score += 0.2 * trait_score  # Fixed weight for traits

                affinities[role] = max(0.0, min(1.0, score))

            matrix[agent] = affinities

        return matrix

    def _calibration_affinity(
        self,
        cal: CalibrationSummary,
        role: CognitiveRole,
    ) -> float:
        """Compute affinity between calibration state and role."""
        is_well_calibrated = (
            cal.brier_score < self.config.brier_threshold and cal.ece < self.config.ece_threshold
        )

        # Role-specific affinities
        if role == CognitiveRole.SKEPTIC:
            return 0.8 if is_well_calibrated else 0.3
        elif role == CognitiveRole.QUALITY_CHALLENGER:
            return 0.9 if is_well_calibrated else 0.2
        elif role == CognitiveRole.DEVIL_ADVOCATE:
            return 0.8 if cal.is_overconfident else 0.3
        elif role == CognitiveRole.ADVOCATE:
            return 0.8 if cal.is_underconfident else 0.3
        elif role == CognitiveRole.SYNTHESIZER:
            return 0.7 if cal.accuracy > 0.7 else 0.4
        elif role == CognitiveRole.ANALYST:
            return 0.6 if cal.accuracy > 0.5 else 0.4
        else:  # LATERAL_THINKER
            return 0.5  # Neutral

    def _expertise_affinity(
        self,
        persona: Persona,
        domain: str,
        role: CognitiveRole,
    ) -> float:
        """Compute affinity between expertise and role."""
        domain_score = persona.expertise.get(domain, 0.0)

        # High expertise → analyst/synthesizer
        if role in (CognitiveRole.ANALYST, CognitiveRole.SYNTHESIZER):
            return domain_score * 0.8
        # Low expertise → lateral thinker (fresh perspectives)
        elif role == CognitiveRole.LATERAL_THINKER:
            return (1.0 - domain_score) * 0.6
        else:
            return 0.5  # Neutral

    def _trait_affinity(
        self,
        traits: list[str],
        role: CognitiveRole,
    ) -> float:
        """Compute affinity between personality traits and role."""
        trait_role_map = {
            CognitiveRole.ANALYST: ["thorough", "pragmatic"],
            CognitiveRole.SKEPTIC: ["contrarian", "direct"],
            CognitiveRole.LATERAL_THINKER: ["innovative", "contrarian"],
            CognitiveRole.SYNTHESIZER: ["collaborative", "diplomatic"],
            CognitiveRole.ADVOCATE: ["diplomatic", "thorough"],
            CognitiveRole.DEVIL_ADVOCATE: ["contrarian", "direct"],
            CognitiveRole.QUALITY_CHALLENGER: ["thorough", "direct"],
        }

        matching = trait_role_map.get(role, [])
        overlap = len(set(traits) & set(matching))
        return min(1.0, overlap * 0.4)

    def _softmax_select_role(
        self,
        affinities: dict[CognitiveRole, float],
        used_roles: set[CognitiveRole],
        temperature: float,
    ) -> CognitiveRole:
        """Select role using softmax with temperature."""
        import math

        available = {r: s for r, s in affinities.items() if r not in used_roles}
        if not available:
            available = affinities  # All used, ignore constraint

        if temperature <= 0 or not available:
            return (
                max(available, key=lambda k: available[k]) if available else CognitiveRole.ANALYST
            )

        # Softmax selection
        max_score = max(available.values())
        exp_scores = {r: math.exp((s - max_score) / temperature) for r, s in available.items()}
        total = sum(exp_scores.values())

        if total == 0:
            return random.choice(list(available.keys()))  # non-security role assignment

        probs = {r: s / total for r, s in exp_scores.items()}

        # Sample
        rand = random.random()  # non-security role assignment
        cumulative = 0.0
        for role, prob in probs.items():
            cumulative += prob
            if rand <= cumulative:
                return role

        return list(probs.keys())[-1]

    def _get_calibrations(
        self,
        agent_names: list[str],
    ) -> dict[str, CalibrationSummary | None]:
        """Get calibration summaries for agents."""
        if not self.calibration_tracker:
            return {}

        result: dict[str, CalibrationSummary | None] = {}
        for agent in agent_names:
            if agent in self._calibration_cache:
                result[agent] = self._calibration_cache[agent]
            else:
                try:
                    summary = self.calibration_tracker.get_calibration_summary(agent)
                    self._calibration_cache[agent] = summary
                    result[agent] = summary
                except (
                    RuntimeError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    KeyError,
                    OSError,
                ) as e:
                    logger.debug("Failed to get calibration for %s: %s", agent, e)
                    result[agent] = None

        return result

    def _get_personas(
        self,
        agent_names: list[str],
    ) -> dict[str, Persona | None]:
        """Get personas for agents."""
        if not self.persona_manager:
            return {}

        result = {}
        for agent in agent_names:
            try:
                result[agent] = self.persona_manager.get_persona(agent)
            except (RuntimeError, ValueError, TypeError, AttributeError, KeyError) as e:
                logger.debug("Failed to get persona for %s: %s", agent, e)
                result[agent] = None

        return result

    def clear_cache(self) -> None:
        """Clear calibration cache (call when calibration data updates)."""
        self._calibration_cache.clear()


__all__ = [
    "RoleMatchingConfig",
    "RoleMatchResult",
    "RoleMatcher",
]
