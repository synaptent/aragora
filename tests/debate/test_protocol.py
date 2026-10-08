"""
Tests for the DebateProtocol module.

Tests cover:
- DebateProtocol dataclass defaults
- RoundPhase configuration
- user_vote_multiplier function
- Preset protocols (ARAGORA_AI_PROTOCOL, ARAGORA_AI_LIGHT_PROTOCOL)
- get_round_phase method
"""

from __future__ import annotations

import importlib
import sys

import pytest

from aragora.config import DEFAULT_ROUNDS
from aragora.protocols.debate import (
    ARAGORA_AI_LIGHT_PROTOCOL,
    ARAGORA_AI_PROTOCOL,
    STRUCTURED_LIGHT_ROUND_PHASES,
    STRUCTURED_ROUND_PHASES,
    DebateProtocol,
    RoundPhase,
    user_vote_multiplier,
)


def test_legacy_debate_protocol_path_warns_and_preserves_identity():
    """The old domain path remains a warning compatibility shim."""
    sys.modules.pop("aragora.debate.protocol", None)
    with pytest.warns(DeprecationWarning, match=r"aragora\.debate\.protocol"):
        legacy = importlib.import_module("aragora.debate.protocol")

    assert legacy.DebateProtocol is DebateProtocol


class TestRoundPhase:
    """Tests for RoundPhase dataclass."""

    def test_round_phase_creation(self):
        """RoundPhase can be created with all fields."""
        phase = RoundPhase(
            number=1,
            name="Test Phase",
            description="A test phase",
            focus="Testing",
            cognitive_mode="Analyst",
        )

        assert phase.number == 1
        assert phase.name == "Test Phase"
        assert phase.description == "A test phase"
        assert phase.focus == "Testing"
        assert phase.cognitive_mode == "Analyst"

    def test_structured_phases_count(self):
        """STRUCTURED_ROUND_PHASES has correct count."""
        assert len(STRUCTURED_ROUND_PHASES) == 9  # 0-8

    def test_structured_phases_numbers(self):
        """STRUCTURED_ROUND_PHASES has correct numbering."""
        for i, phase in enumerate(STRUCTURED_ROUND_PHASES):
            assert phase.number == i

    def test_structured_phases_context_gathering(self):
        """Round 0 is Context Gathering."""
        assert STRUCTURED_ROUND_PHASES[0].name == "Context Gathering"
        assert STRUCTURED_ROUND_PHASES[0].cognitive_mode == "Researcher"

    def test_structured_phases_adjudication(self):
        """Round 8 is Final Adjudication."""
        assert STRUCTURED_ROUND_PHASES[8].name == "Final Adjudication"
        assert STRUCTURED_ROUND_PHASES[8].cognitive_mode == "Adjudicator"

    def test_light_phases_count(self):
        """STRUCTURED_LIGHT_ROUND_PHASES has correct count."""
        assert len(STRUCTURED_LIGHT_ROUND_PHASES) == 4


class TestDebateProtocolDefaults:
    """Tests for DebateProtocol default values."""

    def test_default_topology(self):
        """Default topology is all-to-all."""
        protocol = DebateProtocol()
        assert protocol.topology == "all-to-all"

    def test_default_rounds(self):
        """Default rounds uses global settings."""
        protocol = DebateProtocol()
        assert protocol.rounds == DEFAULT_ROUNDS

    def test_default_consensus(self):
        """Default consensus is judge."""
        protocol = DebateProtocol()
        assert protocol.consensus == "judge"

    def test_default_use_structured_phases(self):
        """Default uses structured phases."""
        protocol = DebateProtocol()
        assert protocol.use_structured_phases is True

    def test_default_early_stopping(self):
        """Default has early stopping enabled."""
        protocol = DebateProtocol()
        assert protocol.early_stopping is True
        assert protocol.early_stop_threshold == 0.85

    def test_default_convergence_detection(self):
        """Default has convergence detection enabled."""
        protocol = DebateProtocol()
        assert protocol.convergence_detection is True
        assert protocol.convergence_threshold == 0.85

    def test_default_vote_grouping(self):
        """Default has vote grouping enabled."""
        protocol = DebateProtocol()
        assert protocol.vote_grouping is True

    def test_default_role_rotation(self):
        """Default has role rotation enabled."""
        protocol = DebateProtocol()
        assert protocol.role_rotation is True

    def test_default_role_matching(self):
        """Default has role matching enabled."""
        protocol = DebateProtocol()
        assert protocol.role_matching is True

    def test_default_calibration(self):
        """Default has calibration enabled."""
        protocol = DebateProtocol()
        assert protocol.enable_calibration is True

    def test_default_trickster(self):
        """Default has trickster enabled."""
        protocol = DebateProtocol()
        assert protocol.enable_trickster is True

    def test_default_breakpoints(self):
        """Default has breakpoints enabled."""
        protocol = DebateProtocol()
        assert protocol.enable_breakpoints is True

    def test_default_skip_empty_sidecars_disabled(self):
        """Default keeps optional sidecars enabled."""
        protocol = DebateProtocol()
        assert protocol.skip_empty_sidecars is False

    def test_skip_empty_sidecars_can_be_enabled(self):
        """Protocol accepts the sidecar skip flag."""
        protocol = DebateProtocol(skip_empty_sidecars=True)
        assert protocol.skip_empty_sidecars is True


class TestDebateProtocolConsensusTypes:
    """Tests for consensus type configurations."""

    def test_majority_consensus(self):
        """Majority consensus type works."""
        protocol = DebateProtocol(consensus="majority", consensus_threshold=0.6)
        assert protocol.consensus == "majority"
        assert protocol.consensus_threshold == 0.6

    def test_unanimous_consensus(self):
        """Unanimous consensus type works."""
        protocol = DebateProtocol(consensus="unanimous")
        assert protocol.consensus == "unanimous"

    def test_judge_consensus(self):
        """Judge consensus type works."""
        protocol = DebateProtocol(consensus="judge")
        assert protocol.consensus == "judge"

    def test_weighted_consensus(self):
        """Weighted consensus type works."""
        protocol = DebateProtocol(consensus="weighted")
        assert protocol.consensus == "weighted"

    def test_byzantine_consensus(self):
        """Byzantine consensus type works."""
        protocol = DebateProtocol(consensus="byzantine")
        assert protocol.consensus == "byzantine"


class TestDebateProtocolTopologies:
    """Tests for topology configurations."""

    def test_all_to_all_topology(self):
        """All-to-all topology works."""
        protocol = DebateProtocol(topology="all-to-all")
        assert protocol.topology == "all-to-all"

    def test_sparse_topology(self):
        """Sparse topology works with sparsity."""
        protocol = DebateProtocol(topology="sparse", topology_sparsity=0.3)
        assert protocol.topology == "sparse"
        assert protocol.topology_sparsity == 0.3

    def test_ring_topology(self):
        """Ring topology works."""
        protocol = DebateProtocol(topology="ring")
        assert protocol.topology == "ring"

    def test_star_topology(self):
        """Star topology works with hub agent."""
        protocol = DebateProtocol(topology="star", topology_hub_agent="claude")
        assert protocol.topology == "star"
        assert protocol.topology_hub_agent == "claude"


class TestDebateProtocolGetRoundPhase:
    """Tests for get_round_phase method."""

    def test_get_phase_returns_phase(self):
        """get_round_phase returns phase for valid round."""
        protocol = DebateProtocol()

        phase = protocol.get_round_phase(0)

        assert phase is not None
        assert phase.name == "Context Gathering"

    def test_get_phase_returns_none_without_structured(self):
        """get_round_phase returns None when structured phases disabled."""
        protocol = DebateProtocol(use_structured_phases=False)

        phase = protocol.get_round_phase(0)

        assert phase is None

    def test_get_phase_out_of_range(self):
        """get_round_phase returns None for out-of-range round."""
        protocol = DebateProtocol()

        phase = protocol.get_round_phase(100)

        assert phase is None

    def test_get_phase_negative(self):
        """get_round_phase returns None for negative round."""
        protocol = DebateProtocol()

        phase = protocol.get_round_phase(-1)

        assert phase is None

    def test_get_phase_uses_custom_phases(self):
        """get_round_phase uses custom phases when provided."""
        custom_phases = [RoundPhase(0, "Custom", "Custom phase", "Custom focus", "Custom mode")]
        protocol = DebateProtocol(round_phases=custom_phases)

        phase = protocol.get_round_phase(0)

        assert phase.name == "Custom"


class TestUserVoteMultiplier:
    """Tests for user_vote_multiplier function."""

    def test_neutral_intensity_returns_one(self):
        """Neutral intensity returns multiplier of 1.0."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(5, protocol)

        assert multiplier == 1.0

    def test_max_intensity_returns_max_multiplier(self):
        """Max intensity returns max multiplier."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(10, protocol)

        assert multiplier == protocol.user_vote_intensity_max_multiplier

    def test_min_intensity_returns_min_multiplier(self):
        """Min intensity returns min multiplier."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(1, protocol)

        assert multiplier == protocol.user_vote_intensity_min_multiplier

    def test_below_neutral_interpolates(self):
        """Below neutral interpolates between min and 1.0."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(3, protocol)

        assert protocol.user_vote_intensity_min_multiplier < multiplier < 1.0

    def test_above_neutral_interpolates(self):
        """Above neutral interpolates between 1.0 and max."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(7, protocol)

        assert 1.0 < multiplier < protocol.user_vote_intensity_max_multiplier

    def test_clamps_below_range(self):
        """Intensity below 1 is clamped."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(0, protocol)

        assert multiplier == protocol.user_vote_intensity_min_multiplier

    def test_clamps_above_range(self):
        """Intensity above max is clamped."""
        protocol = DebateProtocol()

        multiplier = user_vote_multiplier(15, protocol)

        assert multiplier == protocol.user_vote_intensity_max_multiplier

    def test_custom_multiplier_range(self):
        """Custom min/max multipliers work."""
        protocol = DebateProtocol(
            user_vote_intensity_min_multiplier=0.2,
            user_vote_intensity_max_multiplier=3.0,
        )

        min_mult = user_vote_multiplier(1, protocol)
        max_mult = user_vote_multiplier(10, protocol)

        assert min_mult == 0.2
        assert max_mult == 3.0


class TestAragoraAIProtocol:
    """Tests for ARAGORA_AI_PROTOCOL preset."""

    def test_rounds_count(self):
        """ARAGORA_AI_PROTOCOL uses global default rounds."""
        assert ARAGORA_AI_PROTOCOL.rounds == DEFAULT_ROUNDS

    def test_uses_structured_phases(self):
        """ARAGORA_AI_PROTOCOL uses structured phases."""
        assert ARAGORA_AI_PROTOCOL.use_structured_phases is True

    def test_judge_consensus(self):
        """ARAGORA_AI_PROTOCOL uses judge consensus."""
        assert ARAGORA_AI_PROTOCOL.consensus == "judge"

    def test_all_to_all_topology(self):
        """ARAGORA_AI_PROTOCOL uses all-to-all topology."""
        assert ARAGORA_AI_PROTOCOL.topology == "all-to-all"

    def test_high_early_stop_threshold(self):
        """ARAGORA_AI_PROTOCOL has high early stop threshold."""
        assert ARAGORA_AI_PROTOCOL.early_stop_threshold == 0.95

    def test_trickster_enabled(self):
        """ARAGORA_AI_PROTOCOL has trickster enabled."""
        assert ARAGORA_AI_PROTOCOL.enable_trickster is True

    def test_calibration_enabled(self):
        """ARAGORA_AI_PROTOCOL has calibration enabled."""
        assert ARAGORA_AI_PROTOCOL.enable_calibration is True

    def test_research_enabled(self):
        """ARAGORA_AI_PROTOCOL has research enabled."""
        assert ARAGORA_AI_PROTOCOL.enable_research is True

    def test_breakpoints_enabled(self):
        """ARAGORA_AI_PROTOCOL has breakpoints enabled."""
        assert ARAGORA_AI_PROTOCOL.enable_breakpoints is True

    def test_timeout_30_minutes(self):
        """ARAGORA_AI_PROTOCOL has 30 minute timeout."""
        assert ARAGORA_AI_PROTOCOL.timeout_seconds == 1800


class TestAragoraAILightProtocol:
    """Tests for ARAGORA_AI_LIGHT_PROTOCOL preset."""

    def test_rounds_count(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has 4 rounds."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.rounds == 4

    def test_uses_structured_phases(self):
        """ARAGORA_AI_LIGHT_PROTOCOL uses structured phases."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.use_structured_phases is True

    def test_uses_light_phases(self):
        """ARAGORA_AI_LIGHT_PROTOCOL uses light round phases."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.round_phases == STRUCTURED_LIGHT_ROUND_PHASES

    def test_aggressive_early_stop(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has lower early stop threshold."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.early_stop_threshold == 0.7

    def test_trickster_disabled(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has trickster disabled."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.enable_trickster is False

    def test_calibration_disabled(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has calibration disabled."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.enable_calibration is False

    def test_research_disabled(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has research disabled."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.enable_research is False

    def test_breakpoints_disabled(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has breakpoints disabled."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.enable_breakpoints is False

    def test_timeout_5_minutes(self):
        """ARAGORA_AI_LIGHT_PROTOCOL has 5 minute timeout."""
        assert ARAGORA_AI_LIGHT_PROTOCOL.timeout_seconds == 300


class TestDebateProtocolByzantine:
    """Tests for Byzantine consensus configuration."""

    def test_default_fault_tolerance(self):
        """Default Byzantine fault tolerance is 33%."""
        protocol = DebateProtocol()
        assert protocol.byzantine_fault_tolerance == 0.33

    def test_default_phase_timeout(self):
        """Default Byzantine phase timeout is 30 seconds."""
        protocol = DebateProtocol()
        assert protocol.byzantine_phase_timeout == 30.0

    def test_default_max_view_changes(self):
        """Default max view changes is 3."""
        protocol = DebateProtocol()
        assert protocol.byzantine_max_view_changes == 3


class TestDebateProtocolFormalVerification:
    """Tests for formal verification configuration."""

    def test_formal_verification_disabled_by_default(self):
        """Formal verification is disabled by default."""
        protocol = DebateProtocol()
        assert protocol.formal_verification_enabled is False

    def test_default_verification_languages(self):
        """Default verification languages include z3_smt."""
        protocol = DebateProtocol()
        assert "z3_smt" in protocol.formal_verification_languages

    def test_default_verification_timeout(self):
        """Default verification timeout is 30 seconds."""
        protocol = DebateProtocol()
        assert protocol.formal_verification_timeout == 30.0


class TestDebateProtocolJudgeSelection:
    """Tests for judge selection configuration."""

    def test_default_judge_selection(self):
        """Default judge selection is random."""
        protocol = DebateProtocol()
        assert protocol.judge_selection == "random"

    def test_elo_ranked_selection(self):
        """ELO ranked judge selection works."""
        protocol = DebateProtocol(judge_selection="elo_ranked")
        assert protocol.judge_selection == "elo_ranked"

    def test_calibrated_selection(self):
        """Calibrated judge selection works."""
        protocol = DebateProtocol(judge_selection="calibrated")
        assert protocol.judge_selection == "calibrated"

    def test_crux_aware_selection(self):
        """Crux aware judge selection works."""
        protocol = DebateProtocol(judge_selection="crux_aware")
        assert protocol.judge_selection == "crux_aware"
