"""
Nomic Debate Profile: Full-power debate configuration for self-improvement.

Centralizes the configuration for running 8-9 round structured debates with
all 8 frontier model agents, pulling from:
- STRUCTURED_ROUND_PHASES (9 phases, rounds 0-8)
- AgentSettings.default_agents (8 frontier models)
- DebateProtocol (full structured format)

This profile ensures the Nomic loop uses the FULL power of aragora's debate
engine rather than the minimal 2-round/5-agent defaults.

Usage:
    from aragora.nomic.debate_profile import NomicDebateProfile

    profile = NomicDebateProfile()
    debate_config = profile.to_debate_config()
    protocol = profile.to_protocol()
    agent_names = profile.agent_names
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from aragora.protocols.debate import (
    DebateProtocol,
    STRUCTURED_ROUND_PHASES,
    RoundPhase,
)
from aragora.config.settings import AgentSettings, DebateSettings

logger = logging.getLogger(__name__)


def _default_rounds() -> int:
    return DebateSettings().default_rounds


def _default_min_rounds() -> int:
    return max(_default_rounds() - 1, 1)


# The 8 frontier models available in aragora
DEFAULT_NOMIC_AGENTS = AgentSettings().default_agent_list


@dataclass
class NomicDebateProfile:
    """
    Full-power debate configuration for Nomic loop self-improvement debates.

    Defaults to:
    - 9 rounds (+ round 0 context gathering = 9 structured phases)
    - 8 frontier model agents
    - Judge consensus with ELO-ranked selection
    - Full structured round phases (Analyst → Skeptic → Lateral → Devil's
      Advocate → Integrator → Cross-Examination → Synthesizer → Adjudicator)
    - Minimum 7 rounds before early stopping
    """

    # Agent configuration
    agents: list[str] = field(default_factory=lambda: list(DEFAULT_NOMIC_AGENTS))

    # Debate structure
    rounds: int = field(default_factory=_default_rounds)
    use_structured_phases: bool = True
    round_phases: list[RoundPhase] = field(default_factory=lambda: list(STRUCTURED_ROUND_PHASES))

    # Consensus
    consensus_mode: str = "judge"
    judge_selection: str = "elo_ranked"
    consensus_threshold: float = 0.6

    # Role assignments
    proposer_count: int = -1  # All agents propose
    critic_count: int = -1  # All agents critique
    role_rotation: bool = True
    asymmetric_stances: bool = True  # Force perspective diversity

    # Early stopping (set high to ensure thorough debate)
    early_stop_threshold: float = 0.95
    min_rounds_before_early_stop: int = field(default_factory=_default_min_rounds)

    # Agreement intensity (slight disagreement bias improves accuracy)
    agreement_intensity: int = 2

    # Convergence
    convergence_detection: bool = True
    # Force full round execution (disable early stopping/convergence)
    force_full_rounds: bool = False

    @property
    def agent_names(self) -> list[str]:
        """Return the list of agent names for this profile."""
        return list(self.agents)

    @property
    def agent_count(self) -> int:
        """Number of agents in the debate."""
        return len(self.agents)

    @property
    def total_phases(self) -> int:
        """Total number of structured phases (including round 0)."""
        return len(self.round_phases)

    def to_protocol(self) -> DebateProtocol:
        """Convert to a DebateProtocol for use with Arena."""
        consensus_type = cast(
            Literal[
                "majority",
                "unanimous",
                "judge",
                "none",
                "weighted",
                "supermajority",
                "any",
                "byzantine",
            ],
            self.consensus_mode,
        )
        judge_selection_type = cast(
            Literal["random", "voted", "last", "elo_ranked", "calibrated", "crux_aware"],
            self.judge_selection,
        )
        return DebateProtocol(
            rounds=self.rounds,
            use_structured_phases=self.use_structured_phases,
            round_phases=self.round_phases,
            consensus=consensus_type,
            consensus_threshold=self.consensus_threshold,
            judge_selection=judge_selection_type,
            proposer_count=self.proposer_count,
            critic_count=self.critic_count,
            asymmetric_stances=self.asymmetric_stances,
            rotate_stances=self.role_rotation,
            early_stopping=False if self.force_full_rounds else True,
            early_stop_threshold=self.early_stop_threshold,
            min_rounds_before_early_stop=(
                self.rounds if self.force_full_rounds else self.min_rounds_before_early_stop
            ),
            agreement_intensity=self.agreement_intensity,
            convergence_detection=False if self.force_full_rounds else self.convergence_detection,
        )

    def to_debate_config(self) -> Any:
        """Convert to DebateConfig for nomic loop phases."""
        from aragora.nomic.phases.debate import DebateConfig

        return DebateConfig(
            rounds=self.rounds,
            consensus_mode=self.consensus_mode,
            judge_selection=self.judge_selection,
            proposer_count=self.proposer_count,
            role_rotation=self.role_rotation,
            asymmetric_stances=self.asymmetric_stances,
            agreement_intensity=self.agreement_intensity,
            early_stopping=False if self.force_full_rounds else True,
            early_stop_threshold=self.early_stop_threshold,
            min_rounds_before_early_stop=(
                self.rounds if self.force_full_rounds else self.min_rounds_before_early_stop
            ),
            convergence_detection=False if self.force_full_rounds else self.convergence_detection,
        )

    @classmethod
    def minimal(cls) -> NomicDebateProfile:
        """Create a minimal profile for testing (3 rounds, 3 agents)."""
        return cls(
            agents=["anthropic-api", "openai-api", "deepseek"],
            rounds=3,
            min_rounds_before_early_stop=2,
            asymmetric_stances=False,
        )

    @classmethod
    def from_env(cls) -> NomicDebateProfile:
        """Create profile from environment variables."""
        import os

        agents_str = os.environ.get("NOMIC_AGENTS", "")
        agents = (
            [a.strip() for a in agents_str.split(",") if a.strip()]
            if agents_str
            else list(DEFAULT_NOMIC_AGENTS)
        )

        rounds = int(os.environ.get("NOMIC_DEBATE_ROUNDS", str(_default_rounds())))
        agreement = int(os.environ.get("NOMIC_AGREEMENT_INTENSITY", "2"))
        force_full_rounds = (
            os.environ.get("NOMIC_FORCE_FULL_ROUNDS", "0") == "1"
            or os.environ.get("NOMIC_DISABLE_EARLY_STOP", "0") == "1"
        )

        return cls(
            agents=agents,
            rounds=rounds,
            agreement_intensity=agreement,
            force_full_rounds=force_full_rounds,
        )
