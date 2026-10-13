"""
Agent selection for automated debate team composition.

This module provides intelligent agent selection using:
- QuestionClassifier for matching question types to personas
- AgentSelector for team composition with ELO and diversity optimization

Every stage only returns agents that the debate controller's credential
preflight accepts, and skips agent types that need no credential at all.
"""

import logging
import uuid
from typing import TYPE_CHECKING, Optional

from aragora.agents.credential_validator import (
    AGENT_CREDENTIAL_MAP,
    filter_available_agents,
    get_credential_status,
)
from aragora.agents.spec import AgentSpec
from aragora.config import ALLOWED_AGENT_TYPES
from aragora.server.initialization import (
    ROUTING_AVAILABLE,
    AgentProfile,
    AgentSelector,
    TaskRequirements,
)

if TYPE_CHECKING:
    from aragora.agents.personas import PersonaManager
    from aragora.ranking.elo import EloSystem

logger = logging.getLogger(__name__)

# Fallback with explicit roles for productive debate
# (proposer + critic ensures constructive disagreement)
_FALLBACK_TEAM = "gemini|||proposer,anthropic-api|||critic"
_MIN_TEAM_SIZE = 2
# Same rotation the question classifier uses when it builds its agent string.
_ROLE_ROTATION = ("proposer", "critic", "synthesizer", "judge")


class NoEligibleAgentTeamError(ValueError):
    """No selection stage produced enough agents with configured credentials."""

    def __init__(self, missing: dict[str, list[str]], eligible: list[str]) -> None:
        self.missing = missing
        self.eligible = eligible
        missing_text = (
            "; ".join(
                f"{provider} ({', '.join(env_vars)})" for provider, env_vars in missing.items()
            )
            or "none"
        )
        super().__init__(
            "Automatic agent selection found no team of at least "
            f"{_MIN_TEAM_SIZE} agents with configured credentials. "
            f"Missing credentials: {missing_text}. "
            f"Eligible agents: {', '.join(eligible) or 'none'}. "
            "Configure the missing API keys or choose agents explicitly."
        )


def _credentialed(specs: list[AgentSpec], missing: dict[str, list[str]]) -> list[AgentSpec]:
    """Return the specs preflight accepts on the strength of a configured credential.

    Agent types without any credential requirement (demo, local, CLI wrappers,
    unregistered types) pass preflight but say nothing about whether the agent
    can actually run, so automatic selection never picks them.
    """
    available, filtered = filter_available_agents(specs, log_filtered=False, min_agents=0)
    for provider, _reason in filtered:
        missing.setdefault(provider, get_credential_status(provider).missing_vars)
    return [spec for spec in available if AGENT_CREDENTIAL_MAP.get(spec.provider)]


def _classifier_team(
    question: str, missing: dict[str, list[str]], eligible: set[str]
) -> str | None:
    try:
        from aragora.server.question_classifier import classify_and_assign_agents_sync

        agent_string, classification = classify_and_assign_agents_sync(question)

        if not (
            classification.recommended_personas and len(classification.recommended_personas) >= 2
        ):
            logger.info(
                "[auto_select] Classifier returned insufficient personas for '%s', falling back to AgentSelector",
                classification.category,
            )
            return None

        specs = AgentSpec.coerce_list(agent_string, warn=False)
        team = _credentialed(specs, missing)
        eligible.update(spec.provider for spec in team)
        if len(team) < _MIN_TEAM_SIZE:
            logger.info(
                "[auto_select] Classifier team for '%s' has %d agent(s) with credentials, "
                "falling back to AgentSelector",
                classification.category,
                len(team),
            )
            return None

        logger.info(
            f"[auto_select] Classified as '{classification.category}' "
            f"(confidence={classification.confidence:.2f}), "
            f"personas={classification.recommended_personas}"
        )
        if len(team) == len(specs):
            return agent_string
        # Dropping agents can remove the proposer; re-rotate so the team keeps one.
        team = [
            spec.with_role(_ROLE_ROTATION[i % len(_ROLE_ROTATION)]) for i, spec in enumerate(team)
        ]
        return ",".join(spec.to_string() for spec in team)
    except (ValueError, TypeError, KeyError, RuntimeError) as e:
        logger.warning("[auto_select] Question classification failed: %s, using AgentSelector", e)
        return None


def _selector_team(
    question: str,
    config: dict,
    elo_system: Optional["EloSystem"],
    persona_manager: Optional["PersonaManager"],
    eligible: set[str],
) -> str | None:
    try:
        # Build task requirements from question and config
        # ROUTING_AVAILABLE check guarantees these are not None
        if TaskRequirements is None:
            raise TypeError("TaskRequirements not available - routing module not loaded")
        if AgentSelector is None:
            raise TypeError("AgentSelector not available - routing module not loaded")
        if AgentProfile is None:
            raise TypeError("AgentProfile not available - routing module not loaded")

        requirements = TaskRequirements(
            task_id=f"debate-{uuid.uuid4().hex[:8]}",
            description=question[:500],  # Truncate for safety
            primary_domain=config.get("primary_domain", "general"),
            secondary_domains=config.get("secondary_domains", []),
            required_traits=config.get("required_traits", []),
            min_agents=min(max(config.get("min_agents", 2), 2), 5),
            max_agents=min(max(config.get("max_agents", 4), 2), 8),
            quality_priority=min(max(config.get("quality_priority", 0.7), 0), 1),
            diversity_preference=min(max(config.get("diversity_preference", 0.5), 0), 1),
        )

        # Create selector with ELO system and persona manager
        selector = AgentSelector(
            elo_system=elo_system,
            persona_manager=persona_manager,
        )

        pool = _credentialed([AgentSpec(provider=t) for t in ALLOWED_AGENT_TYPES], {})
        eligible.update(spec.provider for spec in pool)
        for spec in pool:
            selector.register_agent(
                AgentProfile(
                    name=spec.provider,
                    agent_type=spec.provider,
                )
            )

        # Select optimal team
        team = selector.select_team(requirements)
        if len(team.agents) < requirements.min_agents:
            logger.info(
                "[auto_select] AgentSelector found %d agent(s) with credentials (need %d), "
                "using fallback",
                len(team.agents),
                requirements.min_agents,
            )
            return None

        # Build agent string with roles using pipe format: provider||persona|role
        # Empty model and persona fields, role at the end
        agent_specs = []
        for agent in team.agents:
            role = team.roles.get(agent.name, "proposer")
            # Use pipe format: provider|||role (empty model and persona)
            agent_specs.append(f"{agent.agent_type}|||{role}")

        logger.info(
            "[auto_select] Selected team: %s (rationale: %s)", agent_specs, team.rationale[:100]
        )
        return ",".join(agent_specs)

    except (TypeError, ValueError, AttributeError, KeyError, RuntimeError) as e:
        logger.warning("[auto_select] Failed: %s, using fallback", e)
        return None


def _fallback_team(missing: dict[str, list[str]], eligible: set[str]) -> str:
    specs = AgentSpec.coerce_list(_FALLBACK_TEAM, warn=False)
    team = _credentialed(specs, missing)
    eligible.update(spec.provider for spec in team)
    if len(team) < _MIN_TEAM_SIZE:
        raise NoEligibleAgentTeamError(missing, sorted(eligible))
    if len(team) == len(specs):
        return _FALLBACK_TEAM
    return ",".join(spec.to_string() for spec in team)


def auto_select_agents(
    question: str,
    config: dict,
    elo_system: Optional["EloSystem"] = None,
    persona_manager: Optional["PersonaManager"] = None,
) -> str:
    """Select optimal agents using question classification and AgentSelector.

    First tries the QuestionClassifier to match question type to appropriate
    personas (e.g., ethical/theological -> philosopher, humanist).
    Falls back to AgentSelector if classifier returns no recommendations,
    then to a fixed proposer/critic pair. Each stage keeps only agents with
    configured credentials.

    Args:
        question: The debate question/topic
        config: Optional configuration with:
            - primary_domain: Main domain (default: 'general')
            - secondary_domains: Additional domains
            - min_agents: Minimum team size (default: 2)
            - max_agents: Maximum team size (default: 4)
            - quality_priority: 0-1 scale (default: 0.7)
            - diversity_preference: 0-1 scale (default: 0.5)
        elo_system: Optional EloSystem for agent ratings
        persona_manager: Optional PersonaManager for agent specialization

    Returns:
        Comma-separated string of agent types with optional roles

    Raises:
        NoEligibleAgentTeamError: No stage produced a team whose agents all
            have configured credentials.
    """
    missing: dict[str, list[str]] = {}
    eligible: set[str] = set()

    team = _classifier_team(question, missing, eligible)
    if team is None and ROUTING_AVAILABLE:
        team = _selector_team(question, config, elo_system, persona_manager, eligible)
    if team is None:
        team = _fallback_team(missing, eligible)
    return team


__all__ = ["NoEligibleAgentTeamError", "auto_select_agents"]
