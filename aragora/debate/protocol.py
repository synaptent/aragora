"""Minimal debate protocol types for the standalone debate wedge."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

DEFAULT_ROUNDS = 3
DEFAULT_AGENT_TIMEOUT_SECONDS = 30
DEFAULT_DEBATE_TIMEOUT_SECONDS = 300
DEFAULT_MAX_CONCURRENT_CRITIQUES = 4
DEFAULT_MAX_CONCURRENT_REVISIONS = 4

__all__ = [
    "ARAGORA_AI_LIGHT_PROTOCOL",
    "ARAGORA_AI_PROTOCOL",
    "CircuitBreaker",
    "DebateProtocol",
    "RoundPhase",
    "STRUCTURED_LIGHT_ROUND_PHASES",
    "STRUCTURED_ROUND_PHASES",
    "resolve_default_protocol",
    "user_vote_multiplier",
]


@dataclass(slots=True)
class CircuitBreaker:
    """Small compatibility stub for the standalone debate path."""

    failure_threshold: int = 5
    recovery_timeout_seconds: int = 60


@dataclass(slots=True)
class RoundPhase:
    """Configuration for one debate round."""

    number: int
    name: str
    description: str
    focus: str
    cognitive_mode: str


STRUCTURED_ROUND_PHASES: list[RoundPhase] = [
    RoundPhase(
        1, "Initial Analysis", "Establish first-pass positions", "core facts", "analyst"
    ),
    RoundPhase(
        2, "Critique", "Challenge and refine positions", "counterarguments", "skeptic"
    ),
    RoundPhase(
        3, "Synthesis", "Converge on the best answer", "final answer", "synthesizer"
    ),
]

STRUCTURED_LIGHT_ROUND_PHASES: list[RoundPhase] = [
    RoundPhase(
        1, "Quick Analysis", "Fast first-pass position", "core facts", "analyst"
    ),
]


@dataclass(slots=True)
class DebateProtocol:
    """Standalone debate configuration used by the minimal ``Arena`` implementation."""

    topology: Literal["all-to-all", "ring", "star"] = "all-to-all"
    rounds: int = DEFAULT_ROUNDS
    consensus: Literal["majority", "unanimous", "judge", "none"] = "majority"
    consensus_threshold: float = 0.5
    allow_abstain: bool = True
    require_reasoning: bool = True
    proposer_count: int = -1
    critic_count: int = -1
    critique_required: bool = False
    use_structured_phases: bool = False
    round_phases: list[RoundPhase] | None = None
    early_stopping: bool = False
    early_stop_threshold: float = 1.0
    min_rounds_before_early_stop: int = 1
    timeout_seconds: int = int(
        os.environ.get("ARAGORA_DEBATE_TIMEOUT", DEFAULT_DEBATE_TIMEOUT_SECONDS)
    )
    round_timeout_seconds: int = int(
        os.environ.get("ARAGORA_AGENT_TIMEOUT", DEFAULT_AGENT_TIMEOUT_SECONDS)
    )
    max_parallel_critiques: int = DEFAULT_MAX_CONCURRENT_CRITIQUES
    max_parallel_revisions: int = DEFAULT_MAX_CONCURRENT_REVISIONS
    user_vote_weight: float = 0.5
    user_vote_intensity_scale: int = 10
    user_vote_intensity_neutral: int = 5
    user_vote_intensity_min_multiplier: float = 0.5
    user_vote_intensity_max_multiplier: float = 2.0
    circuit_breaker: CircuitBreaker | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_round_phase(self, round_number: int) -> RoundPhase | None:
        phases = self.round_phases or STRUCTURED_ROUND_PHASES
        if not self.use_structured_phases:
            return None
        if 0 <= round_number < len(phases):
            return phases[round_number]
        return None


ARAGORA_AI_PROTOCOL = DebateProtocol(
    rounds=3,
    consensus="majority",
    critique_required=False,
    use_structured_phases=True,
    round_phases=STRUCTURED_ROUND_PHASES,
)

ARAGORA_AI_LIGHT_PROTOCOL = DebateProtocol(
    rounds=1,
    consensus="majority",
    critique_required=False,
    use_structured_phases=True,
    round_phases=STRUCTURED_LIGHT_ROUND_PHASES,
)


def resolve_default_protocol(protocol: DebateProtocol | None = None) -> DebateProtocol:
    return protocol or DebateProtocol()


def user_vote_multiplier(intensity: int, protocol: DebateProtocol) -> float:
    intensity = max(1, min(protocol.user_vote_intensity_scale, intensity))
    neutral = protocol.user_vote_intensity_neutral
    scale = protocol.user_vote_intensity_scale
    if intensity == neutral:
        return 1.0
    if intensity < neutral:
        ratio = (intensity - 1) / (neutral - 1) if neutral > 1 else 0
        return (
            protocol.user_vote_intensity_min_multiplier
            + (1.0 - protocol.user_vote_intensity_min_multiplier) * ratio
        )
    ratio = (intensity - neutral) / (scale - neutral) if scale > neutral else 0
    return 1.0 + (protocol.user_vote_intensity_max_multiplier - 1.0) * ratio
