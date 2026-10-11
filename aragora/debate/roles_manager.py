"""
Roles Manager for debate agent configuration.

Handles role assignment, stance assignment, and agreement intensity
for agents participating in debates. Extracted from orchestrator.py.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from aragora.agents.calibration import CalibrationTracker
    from aragora.agents.personas import PersonaManager
    from aragora.core import Agent
    from aragora.core_types import AgentStance
    from aragora.debate.prompt_builder import PromptBuilder
    from aragora.protocols.debate import DebateProtocol
    from aragora.debate.role_matcher import RoleMatcher
    from aragora.debate.roles import (
        RoleAssignment,
        RoleRotator,
    )

logger = logging.getLogger(__name__)


class RolesManager:
    """
    Manages agent roles, stances, and agreement intensity.

    Extracted from Arena to separate role management concerns from
    debate orchestration.

    Usage:
        manager = RolesManager(agents, protocol, prompt_builder)
        manager.assign_initial_roles()
        manager.assign_stances(round_num=0)
        manager.apply_agreement_intensity()
    """

    def __init__(
        self,
        agents: list[Agent],
        protocol: DebateProtocol,
        prompt_builder: PromptBuilder | None = None,
        calibration_tracker: CalibrationTracker | None = None,
        persona_manager: PersonaManager | None = None,
    ):
        """
        Initialize roles manager.

        Args:
            agents: List of agents to manage
            protocol: Debate protocol with role configuration
            prompt_builder: Optional prompt builder for stance guidance
            calibration_tracker: Optional calibration tracker for role matching
            persona_manager: Optional persona manager for role matching
        """
        self.agents = agents
        self.protocol = protocol
        self.prompt_builder = prompt_builder
        self.calibration_tracker = calibration_tracker
        self.persona_manager = persona_manager

        # Cognitive role rotation (Heavy3-inspired)
        self.role_rotator: RoleRotator | None = None
        self.role_matcher: RoleMatcher | None = None
        self.current_role_assignments: dict[str, RoleAssignment] = {}

        self._init_role_systems()

    def _init_role_systems(self) -> None:
        """Initialize role rotation or matching systems based on protocol."""
        from aragora.debate.role_matcher import RoleMatcher, RoleMatchingConfig
        from aragora.debate.roles import RoleRotationConfig, RoleRotator

        # Role matching takes priority over simple rotation
        if self.protocol.role_matching:
            config = self.protocol.role_matching_config or RoleMatchingConfig()
            self.role_matcher = RoleMatcher(
                calibration_tracker=self.calibration_tracker,
                persona_manager=self.persona_manager,
                config=config,
            )
            logger.info("role_matcher_enabled strategy=%s", config.strategy)
        elif self.protocol.role_rotation:
            rotation_config = self.protocol.role_rotation_config or RoleRotationConfig()
            self.role_rotator = RoleRotator(rotation_config)

    def assign_initial_roles(self) -> None:
        """Assign initial roles to agents based on protocol with safety bounds."""
        # If agents already have roles, respect them.
        # Use getattr to guard against mock pollution that can strip Agent.__init__
        # attributes when tests run in randomized order.
        if all(getattr(a, "role", None) for a in self.agents):
            return

        n_agents = len(self.agents)

        # Safety: Ensure at least 1 critic and 1 synthesizer when we have 3+ agents
        # This prevents all-proposer scenarios that break debate dynamics
        max_proposers = max(1, n_agents - 2) if n_agents >= 3 else 1
        proposers_needed = min(self.protocol.proposer_count, max_proposers)

        for i, agent in enumerate(self.agents):
            if i < proposers_needed:
                agent.role = "proposer"
            elif i == n_agents - 1:
                agent.role = "synthesizer"
            else:
                agent.role = "critic"

        # Log role assignment for debugging
        roles = {a.name: a.role for a in self.agents}
        logger.debug("Role assignment: %s", roles)

    def assign_stances(self, round_num: int = 0) -> None:
        """Assign debate stances to agents for asymmetric debate.

        Stances: "affirmative" (defend), "negative" (challenge), "neutral" (evaluate)
        If rotate_stances is True, stances rotate each round.
        """
        if not self.protocol.asymmetric_stances:
            return

        stances = ["affirmative", "negative", "neutral"]

        for i, agent in enumerate(self.agents):
            # Rotate stance based on round number if enabled
            if self.protocol.rotate_stances:
                stance_idx = (i + round_num) % len(stances)
            else:
                stance_idx = i % len(stances)

            agent.stance = cast("AgentStance", stances[stance_idx])

    def apply_agreement_intensity(self) -> None:
        """Apply agreement intensity guidance to all agents' system prompts.

        This modifies each agent's system_prompt to include guidance on how
        much to agree vs disagree with other agents, based on the protocol's
        agreement_intensity setting.
        """
        guidance = self._get_agreement_intensity_guidance()

        for agent in self.agents:
            if agent.system_prompt:
                agent.system_prompt = f"{agent.system_prompt}\n\n{guidance}"
            else:
                agent.system_prompt = guidance

    def _get_agreement_intensity_guidance(self) -> str:
        """Generate prompt guidance based on agreement intensity setting.

        Agreement intensity (0-10) affects how agents approach disagreements:
        - Low (0-3): Adversarial - strongly challenge others' positions
        - Medium (4-6): Balanced - judge arguments on merit
        - High (7-10): Collaborative - seek common ground and synthesis
        """
        intensity = getattr(self.protocol, "agreement_intensity", None)

        if intensity is None:
            return ""  # No agreement intensity guidance when not set

        if intensity <= 3:
            return """DEBATE MODE: ADVERSARIAL
You should strongly challenge and question other agents' positions.
Look for weaknesses, contradictions, and unsupported claims.
Push back on assertions that lack evidence.
Your role is to stress-test ideas through rigorous critique."""
        elif intensity >= 7:
            return """DEBATE MODE: COLLABORATIVE
You should seek common ground and synthesize different perspectives.
Build upon others' ideas constructively.
Focus on finding points of agreement while addressing differences.
Your role is to help the group converge on the best solution."""
        else:  # 4-6
            return """DEBATE MODE: BALANCED
Evaluate arguments on their merits objectively.
Acknowledge good points while also noting weaknesses.
Neither automatically agree nor disagree - let evidence guide you.
Your role is to contribute fair and reasoned analysis."""

    def get_stance_guidance(self, agent: Agent) -> str:
        """Generate prompt guidance based on agent's debate stance.

        Args:
            agent: The agent to get stance guidance for

        Returns:
            Stance-specific guidance string
        """
        # Use prompt builder if available
        if self.prompt_builder:
            return self.prompt_builder.get_stance_guidance(agent)

        # Check if asymmetric stances are enabled
        if not getattr(self.protocol, "asymmetric_stances", False):
            return ""

        stance = getattr(agent, "stance", None)
        if not stance:
            return ""

        if stance == "affirmative":
            return """DEBATE STANCE: AFFIRMATIVE
You are assigned to DEFEND and SUPPORT proposals. Your role is to:
- Find strengths and merits in arguments
- Build upon existing ideas
- Advocate for the proposal's value
- Counter criticisms constructively
Even if you personally disagree, argue the affirmative position."""

        elif stance == "negative":
            return """DEBATE STANCE: NEGATIVE
You are assigned to CHALLENGE and CRITIQUE proposals. Your role is to:
- Identify weaknesses and potential problems
- Question assumptions and evidence
- Present counterarguments
- Play devil's advocate
Even if you personally agree, argue the negative position."""

        elif stance == "neutral":
            return """DEBATE STANCE: NEUTRAL
You are assigned to EVALUATE objectively. Your role is to:
- Weigh both sides fairly
- Identify the strongest arguments from each position
- Note where consensus exists vs disagreement
- Provide balanced analysis
Do not advocate - analyze impartially."""

        return ""

    def rotate_roles_for_round(self, round_num: int) -> None:
        """Rotate cognitive roles for a new debate round.

        Args:
            round_num: Current round number
        """
        if self.role_rotator:
            agent_names = [a.name for a in self.agents]
            total_rounds = self.protocol.rounds
            self.current_role_assignments = self.role_rotator.get_assignments(
                agent_names, round_num, total_rounds
            )
        elif self.role_matcher:
            # Role matcher uses task-based matching, not round rotation
            pass

    def match_roles_for_task(self, task: str, round_num: int = 0) -> dict[str, RoleAssignment]:
        """Match agents to optimal roles for a specific task.

        Args:
            task: The debate task description (used as domain hint)
            round_num: Current round number for rotation fallback

        Returns:
            Dict mapping agent name to role assignment
        """
        if self.role_matcher:
            agent_names = [a.name for a in self.agents]
            result = self.role_matcher.match_roles(agent_names, round_num, debate_domain=task)
            self.current_role_assignments = result.assignments
        return self.current_role_assignments

    def update_role_assignments(self, round_num: int, debate_domain: str | None = None) -> None:
        """Update cognitive role assignments for the current round.

        Uses role matcher if available (calibration-based), otherwise
        falls back to simple role rotation.

        Args:
            round_num: Current round number
            debate_domain: Optional domain hint for role matching
        """
        agent_names = [a.name for a in self.agents]

        # Use role matcher if available (calibration-based)
        if self.role_matcher:
            result = self.role_matcher.match_roles(
                agent_names=agent_names,
                round_num=round_num,
                debate_domain=debate_domain,
            )
            self.current_role_assignments = result.assignments
            logger.debug("Role matcher assigned: %s", list(self.current_role_assignments.keys()))
        # Fall back to simple role rotation
        elif self.role_rotator:
            total_rounds = getattr(self.protocol, "rounds", 3)
            self.current_role_assignments = self.role_rotator.get_assignments(
                agent_names, round_num, total_rounds
            )
            logger.debug("Role rotator assigned: %s", list(self.current_role_assignments.keys()))

    def get_role_context(self, agent: Agent) -> str:
        """Get cognitive role context for an agent in the current round.

        Args:
            agent: The agent to get role context for

        Returns:
            Role context string for prompt injection, or empty string if not available
        """
        if not self.role_rotator or agent.name not in self.current_role_assignments:
            return ""

        assignment = self.current_role_assignments[agent.name]
        return self.role_rotator.format_role_context(assignment)

    # =========================================================================
    # Convenience aliases and summary methods
    # =========================================================================

    def assign_roles(self) -> None:
        """Alias for assign_initial_roles() for API compatibility."""
        self.assign_initial_roles()

    def get_agreement_intensity_guidance(self) -> str:
        """Public wrapper for _get_agreement_intensity_guidance().

        Returns:
            Agreement intensity guidance string
        """
        return self._get_agreement_intensity_guidance()

    def get_role_summary(self) -> dict[str, list[str]]:
        """Get summary of current role assignments.

        Returns:
            Dict mapping role -> list of agent names
        """
        summary: dict[str, list[str]] = {
            "proposer": [],
            "critic": [],
            "synthesizer": [],
        }

        for agent in self.agents:
            role = getattr(agent, "role", "unknown")
            if role in summary:
                summary[role].append(agent.name)
            else:
                summary.setdefault(role, []).append(agent.name)

        return summary

    def get_stance_summary(self) -> dict[str, list[str]]:
        """Get summary of current stance assignments.

        Returns:
            Dict mapping stance -> list of agent names
        """
        summary: dict[str, list[str]] = {
            "affirmative": [],
            "negative": [],
            "neutral": [],
        }

        for agent in self.agents:
            stance = getattr(agent, "stance", None)
            if stance in summary:
                summary[stance].append(agent.name)

        return summary

    def format_role_assignments_for_log(self) -> str:
        """Format current role assignments as a log-friendly string.

        Returns:
            Comma-separated string of agent name: role pairs
        """
        if not self.current_role_assignments:
            return ""
        return ", ".join(
            f"{name}: {assign.role.value}" for name, assign in self.current_role_assignments.items()
        )

    def log_role_assignments(self, round_num: int) -> None:
        """Log current role assignments if any exist.

        Args:
            round_num: Current round number for log context
        """
        if self.current_role_assignments:
            roles_str = self.format_role_assignments_for_log()
            logger.debug("role_assignments round=%s roles=%s", round_num, roles_str)


__all__ = ["RolesManager"]
