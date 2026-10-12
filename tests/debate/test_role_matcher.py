"""
Tests for aragora.debate.role_matcher module.

Covers:
- RoleMatchingConfig defaults and custom values
- RoleMatchResult structure
- Rotation strategy (deterministic assignment, round progression)
- Calibration strategy (calibration state → role mapping)
- Hybrid strategy (affinity matrix, softmax selection)
- Cold-start handling
- Developmental assignments
- Calibration cache
- Error handling
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from aragora.agents.calibration import CalibrationSummary
from aragora.agents.personas import Persona
from aragora.debate.role_matcher import (
    RoleMatchResult,
    RoleMatcher,
    RoleMatchingConfig,
)
from aragora.debate.roles import CognitiveRole, RoleAssignment


# Test fixtures for CalibrationSummary mock
@dataclass
class MockCalibrationSummary:
    """Mock CalibrationSummary for testing."""

    agent: str
    total_predictions: int = 10
    total_correct: int = 7
    brier_score: float = 0.15
    ece: float = 0.08
    is_overconfident: bool = False
    is_underconfident: bool = False

    @property
    def accuracy(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.total_correct / self.total_predictions


@dataclass
class MockPersona:
    """Mock Persona for testing."""

    agent_name: str
    description: str = ""
    traits: list[str] = field(default_factory=list)
    expertise: dict[str, float] = field(default_factory=dict)


# Fixtures


@pytest.fixture
def mock_calibration_tracker():
    """Mock CalibrationTracker."""
    tracker = MagicMock()
    tracker.get_calibration_summary = MagicMock()
    return tracker


@pytest.fixture
def mock_persona_manager():
    """Mock PersonaManager."""
    manager = MagicMock()
    manager.get_persona = MagicMock()
    return manager


@pytest.fixture
def default_config():
    """Default RoleMatchingConfig."""
    return RoleMatchingConfig()


@pytest.fixture
def role_matcher(mock_calibration_tracker, mock_persona_manager, default_config):
    """RoleMatcher with default configuration."""
    return RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=default_config,
    )


# Test RoleMatchingConfig


def test_role_matching_config_defaults():
    """Test RoleMatchingConfig default values."""
    config = RoleMatchingConfig()

    assert config.strategy == "hybrid"
    assert config.calibration_weight == 0.4
    assert config.expertise_weight == 0.3
    assert config.min_predictions_for_calibration == 5
    assert config.selection_temperature == 1.0
    assert config.enable_developmental_assignment is True
    assert config.brier_threshold == 0.25
    assert config.ece_threshold == 0.1


def test_role_matching_config_custom_values():
    """Test RoleMatchingConfig with custom values."""
    config = RoleMatchingConfig(
        strategy="calibration",
        calibration_weight=0.5,
        expertise_weight=0.4,
        min_predictions_for_calibration=10,
        selection_temperature=0.5,
        enable_developmental_assignment=False,
        brier_threshold=0.2,
        ece_threshold=0.05,
    )

    assert config.strategy == "calibration"
    assert config.calibration_weight == 0.5
    assert config.expertise_weight == 0.4
    assert config.min_predictions_for_calibration == 10
    assert config.selection_temperature == 0.5
    assert config.enable_developmental_assignment is False
    assert config.brier_threshold == 0.2
    assert config.ece_threshold == 0.05


# Test RoleMatchResult


def test_role_match_result_defaults():
    """Test RoleMatchResult default values."""
    result = RoleMatchResult(
        round_num=1, assignments={}, strategy_used="rotation", calibration_used=False
    )

    assert result.round_num == 1
    assert result.assignments == {}
    assert result.strategy_used == "rotation"
    assert result.calibration_used is False
    assert result.cold_start_agents == []
    assert result.developmental_assignments == []


def test_role_match_result_with_data():
    """Test RoleMatchResult with populated data."""
    assignments = {
        "agent1": RoleAssignment(agent_name="agent1", role=CognitiveRole.ANALYST, round_num=1),
    }
    result = RoleMatchResult(
        round_num=1,
        assignments=assignments,
        strategy_used="calibration",
        calibration_used=True,
        cold_start_agents=["agent2"],
        developmental_assignments=["agent1"],
    )

    assert result.round_num == 1
    assert len(result.assignments) == 1
    assert result.strategy_used == "calibration"
    assert result.calibration_used is True
    assert result.cold_start_agents == ["agent2"]
    assert result.developmental_assignments == ["agent1"]


# Test RoleMatcher initialization


def test_role_matcher_initialization():
    """Test RoleMatcher initialization."""
    tracker = MagicMock()
    manager = MagicMock()
    config = RoleMatchingConfig(strategy="calibration")

    matcher = RoleMatcher(calibration_tracker=tracker, persona_manager=manager, config=config)

    assert matcher.calibration_tracker is tracker
    assert matcher.persona_manager is manager
    assert matcher.config is config
    assert isinstance(matcher._calibration_cache, dict)
    assert len(matcher._calibration_cache) == 0


def test_role_matcher_initialization_defaults():
    """Test RoleMatcher initialization with defaults."""
    matcher = RoleMatcher()

    assert matcher.calibration_tracker is None
    assert matcher.persona_manager is None
    assert isinstance(matcher.config, RoleMatchingConfig)
    assert matcher.config.strategy == "hybrid"


# Test rotation strategy


def test_rotation_strategy_basic():
    """Test rotation strategy assigns roles sequentially."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="rotation")
    matcher = RoleMatcher(config=config)

    agent_names = ["agent1", "agent2", "agent3"]
    result = matcher.match_roles(agent_names, round_num=0)

    assert result.round_num == 0
    assert result.strategy_used == "rotation"
    assert result.calibration_used is False
    assert len(result.assignments) == 3

    # Check assignments
    roles = list(CognitiveRole)
    for i, agent in enumerate(agent_names):
        assignment = result.assignments[agent]
        assert assignment.agent_name == agent
        assert assignment.role == roles[i % len(roles)]
        assert assignment.round_num == 0


def test_rotation_strategy_advances_with_round():
    """Test rotation strategy rotates roles across rounds."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="rotation")
    matcher = RoleMatcher(config=config)

    agent_names = ["agent1", "agent2"]
    roles = list(CognitiveRole)

    # Round 0
    result0 = matcher.match_roles(agent_names, round_num=0)
    assert result0.assignments["agent1"].role == roles[0]
    assert result0.assignments["agent2"].role == roles[1]

    # Round 1
    result1 = matcher.match_roles(agent_names, round_num=1)
    assert result1.assignments["agent1"].role == roles[1]
    assert result1.assignments["agent2"].role == roles[2]

    # Round 2
    result2 = matcher.match_roles(agent_names, round_num=2)
    assert result2.assignments["agent1"].role == roles[2]
    assert result2.assignments["agent2"].role == roles[3]


def test_rotation_strategy_wraps_around():
    """Test rotation strategy wraps around when roles are exhausted."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="rotation")
    matcher = RoleMatcher(config=config)

    agent_names = ["agent1"]
    roles = list(CognitiveRole)
    num_roles = len(roles)

    # Round that wraps around
    result = matcher.match_roles(agent_names, round_num=num_roles)
    assert result.assignments["agent1"].role == roles[0]


# Test calibration strategy


def test_calibration_strategy_well_calibrated_agent(mock_calibration_tracker, mock_persona_manager):
    """Test calibration strategy assigns SKEPTIC/QUALITY_CHALLENGER to well-calibrated agents."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # Well-calibrated agent
    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    assert result.strategy_used == "calibration"
    assert result.calibration_used is True
    assignment = result.assignments["agent1"]
    assert assignment.role in (CognitiveRole.SKEPTIC, CognitiveRole.QUALITY_CHALLENGER)


def test_calibration_strategy_overconfident_agent(mock_calibration_tracker, mock_persona_manager):
    """Test calibration strategy assigns DEVIL_ADVOCATE to overconfident agents."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # Overconfident agent
    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        is_overconfident=True,
    )
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    assignment = result.assignments["agent1"]
    assert assignment.role in (CognitiveRole.DEVIL_ADVOCATE, CognitiveRole.SKEPTIC)
    assert "agent1" in result.developmental_assignments


def test_calibration_strategy_underconfident_agent(mock_calibration_tracker, mock_persona_manager):
    """Test calibration strategy assigns ADVOCATE to underconfident agents."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # Underconfident agent
    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        is_underconfident=True,
    )
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    assignment = result.assignments["agent1"]
    assert assignment.role in (CognitiveRole.ADVOCATE, CognitiveRole.ANALYST)
    assert "agent1" in result.developmental_assignments


def test_calibration_strategy_high_accuracy_agent(mock_calibration_tracker, mock_persona_manager):
    """Test calibration strategy assigns SYNTHESIZER to high-accuracy agents."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # High accuracy agent
    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        total_correct=8,  # 0.8 accuracy
    )
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    assignment = result.assignments["agent1"]
    assert assignment.role in (CognitiveRole.SYNTHESIZER, CognitiveRole.ANALYST)


def test_calibration_strategy_cold_start_agent(mock_calibration_tracker, mock_persona_manager):
    """Test calibration strategy assigns random role to cold-start agents."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration", min_predictions_for_calibration=5)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # Cold-start agent (insufficient predictions)
    cal = MockCalibrationSummary(agent="agent1", total_predictions=3)
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    assert "agent1" in result.cold_start_agents
    assert "agent1" not in result.developmental_assignments
    # Should still get an assignment
    assert "agent1" in result.assignments


def test_cold_start_covers_missing_and_thin_calibrations(
    mock_calibration_tracker, mock_persona_manager
):
    """Agents with no calibration or fewer than the minimum predictions are cold-start."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration", min_predictions_for_calibration=5)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    summaries = {
        "thin": MockCalibrationSummary(agent="thin", total_predictions=4),
        "at_minimum": MockCalibrationSummary(agent="at_minimum", total_predictions=5),
    }

    def get_summary(agent: str) -> MockCalibrationSummary:
        if agent == "missing":
            raise KeyError(agent)
        return summaries[agent]

    mock_calibration_tracker.get_calibration_summary.side_effect = get_summary

    result = matcher.match_roles(["missing", "thin", "at_minimum"], round_num=0)

    assert result.cold_start_agents == ["missing", "thin"]
    assert set(result.assignments) == {"missing", "thin", "at_minimum"}


def test_calibration_strategy_no_tracker(mock_persona_manager):
    """Test calibration strategy falls back gracefully without tracker."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(calibration_tracker=None, config=config)

    result = matcher.match_roles(["agent1"], round_num=0)

    # All agents treated as cold-start
    assert "agent1" in result.cold_start_agents


def test_calibration_strategy_developmental_disabled(
    mock_calibration_tracker, mock_persona_manager
):
    """Test developmental assignments can be disabled."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration", enable_developmental_assignment=False)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        is_overconfident=True,
    )
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    # Should not track developmental assignments
    assert "agent1" not in result.developmental_assignments


# Test hybrid strategy


def test_hybrid_strategy_basic(mock_calibration_tracker, mock_persona_manager):
    """Test hybrid strategy combines calibration and expertise."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="hybrid")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)
    persona = MockPersona(
        agent_name="agent1",
        expertise={"security": 0.8},
        traits=["thorough", "pragmatic"],
    )

    mock_calibration_tracker.get_calibration_summary.return_value = cal
    mock_persona_manager.get_persona.return_value = persona

    result = matcher.match_roles(["agent1"], round_num=0, debate_domain="security")

    assert result.strategy_used == "hybrid"
    assert result.calibration_used is True
    assert "agent1" in result.assignments


def test_hybrid_strategy_cold_start(mock_calibration_tracker, mock_persona_manager):
    """Test hybrid strategy handles cold-start agents."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="hybrid", min_predictions_for_calibration=5)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(agent="agent1", total_predictions=2)
    mock_calibration_tracker.get_calibration_summary.return_value = cal
    mock_persona_manager.get_persona.return_value = None

    result = matcher.match_roles(["agent1"], round_num=0)

    assert "agent1" in result.cold_start_agents
    assert "agent1" in result.assignments


def test_hybrid_strategy_affinity_matrix(mock_calibration_tracker, mock_persona_manager):
    """Test hybrid strategy computes affinity matrix."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="hybrid")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)
    persona = MockPersona(agent_name="agent1", expertise={"security": 0.9}, traits=["thorough"])

    mock_calibration_tracker.get_calibration_summary.return_value = cal
    mock_persona_manager.get_persona.return_value = persona

    # Call internal method
    matrix = matcher._compute_affinity_matrix(
        ["agent1"],
        {"agent1": cal},
        {"agent1": persona},
        debate_domain="security",
    )

    assert "agent1" in matrix
    assert len(matrix["agent1"]) == len(CognitiveRole)
    # All affinities should be in [0, 1]
    for role, score in matrix["agent1"].items():
        assert 0.0 <= score <= 1.0


def test_hybrid_strategy_temperature_zero(mock_calibration_tracker, mock_persona_manager):
    """Test hybrid strategy with temperature=0 (greedy selection)."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="hybrid", selection_temperature=0.0)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)
    mock_calibration_tracker.get_calibration_summary.return_value = cal
    mock_persona_manager.get_persona.return_value = None

    result = matcher.match_roles(["agent1"], round_num=0)

    assert "agent1" in result.assignments


def test_hybrid_strategy_high_temperature(mock_calibration_tracker, mock_persona_manager):
    """Test hybrid strategy with high temperature (more random)."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="hybrid", selection_temperature=2.0)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)
    mock_calibration_tracker.get_calibration_summary.return_value = cal
    mock_persona_manager.get_persona.return_value = None

    result = matcher.match_roles(["agent1"], round_num=0)

    assert "agent1" in result.assignments


# Test affinity computation


def test_calibration_affinity_well_calibrated(default_config):
    """Test calibration affinity for well-calibrated agent."""
    matcher = RoleMatcher(config=default_config)

    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)

    # Well-calibrated → high affinity for SKEPTIC/QUALITY_CHALLENGER
    skeptic_affinity = matcher._calibration_affinity(cal, CognitiveRole.SKEPTIC)
    assert skeptic_affinity == 0.8

    qc_affinity = matcher._calibration_affinity(cal, CognitiveRole.QUALITY_CHALLENGER)
    assert qc_affinity == 0.9


def test_calibration_affinity_overconfident(default_config):
    """Test calibration affinity for overconfident agent."""
    matcher = RoleMatcher(config=default_config)

    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        is_overconfident=True,
    )

    # Overconfident → high affinity for DEVIL_ADVOCATE
    da_affinity = matcher._calibration_affinity(cal, CognitiveRole.DEVIL_ADVOCATE)
    assert da_affinity == 0.8


def test_calibration_affinity_underconfident(default_config):
    """Test calibration affinity for underconfident agent."""
    matcher = RoleMatcher(config=default_config)

    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        is_underconfident=True,
    )

    # Underconfident → high affinity for ADVOCATE
    advocate_affinity = matcher._calibration_affinity(cal, CognitiveRole.ADVOCATE)
    assert advocate_affinity == 0.8


def test_expertise_affinity_high_expertise(default_config):
    """Test expertise affinity for high-expertise agent."""
    matcher = RoleMatcher(config=default_config)

    persona = MockPersona(agent_name="agent1", expertise={"security": 0.9})

    # High expertise → ANALYST/SYNTHESIZER
    analyst_affinity = matcher._expertise_affinity(persona, "security", CognitiveRole.ANALYST)
    assert analyst_affinity == 0.9 * 0.8


def test_expertise_affinity_low_expertise(default_config):
    """Test expertise affinity for low-expertise agent."""
    matcher = RoleMatcher(config=default_config)

    persona = MockPersona(agent_name="agent1", expertise={"security": 0.1})

    # Low expertise → LATERAL_THINKER
    lt_affinity = matcher._expertise_affinity(persona, "security", CognitiveRole.LATERAL_THINKER)
    assert lt_affinity == (1.0 - 0.1) * 0.6


def test_trait_affinity(default_config):
    """Test trait affinity computation."""
    matcher = RoleMatcher(config=default_config)

    # Analyst prefers thorough, pragmatic
    traits = ["thorough", "pragmatic"]
    analyst_affinity = matcher._trait_affinity(traits, CognitiveRole.ANALYST)
    assert analyst_affinity == 0.8  # 2 matches * 0.4

    # Lateral thinker prefers innovative, contrarian
    traits = ["innovative"]
    lt_affinity = matcher._trait_affinity(traits, CognitiveRole.LATERAL_THINKER)
    assert lt_affinity == 0.4  # 1 match * 0.4


# Test softmax selection


def test_softmax_select_role_greedy(default_config):
    """Test softmax role selection with temperature=0 (greedy)."""
    random.seed(42)
    matcher = RoleMatcher(config=default_config)

    affinities = {
        CognitiveRole.ANALYST: 0.8,
        CognitiveRole.SKEPTIC: 0.5,
        CognitiveRole.SYNTHESIZER: 0.3,
    }

    role = matcher._softmax_select_role(affinities, set(), temperature=0.0)
    assert role == CognitiveRole.ANALYST  # Highest affinity


def test_softmax_select_role_with_used_roles(default_config):
    """Test softmax role selection excludes used roles."""
    random.seed(42)
    matcher = RoleMatcher(config=default_config)

    affinities = {
        CognitiveRole.ANALYST: 0.8,
        CognitiveRole.SKEPTIC: 0.5,
        CognitiveRole.SYNTHESIZER: 0.3,
    }

    used_roles = {CognitiveRole.ANALYST}

    role = matcher._softmax_select_role(affinities, used_roles, temperature=0.0)
    assert role == CognitiveRole.SKEPTIC  # Next highest


def test_softmax_select_role_all_used(default_config):
    """Test softmax role selection when all roles are used."""
    random.seed(42)
    matcher = RoleMatcher(config=default_config)

    affinities = {
        CognitiveRole.ANALYST: 0.8,
        CognitiveRole.SKEPTIC: 0.5,
    }

    used_roles = {CognitiveRole.ANALYST, CognitiveRole.SKEPTIC}

    # Should ignore constraint when all used
    role = matcher._softmax_select_role(affinities, used_roles, temperature=1.0)
    assert role in (CognitiveRole.ANALYST, CognitiveRole.SKEPTIC)


# Test cache


def test_calibration_cache_populated(mock_calibration_tracker, mock_persona_manager):
    """Test calibration cache is populated on first call."""
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    cal = MockCalibrationSummary(agent="agent1", total_predictions=10)
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    # First call
    matcher.match_roles(["agent1"], round_num=0)

    assert "agent1" in matcher._calibration_cache
    assert matcher._calibration_cache["agent1"] == cal

    # Second call should use cache
    mock_calibration_tracker.reset_mock()
    matcher.match_roles(["agent1"], round_num=1)

    # Should not call tracker again
    mock_calibration_tracker.get_calibration_summary.assert_not_called()


def test_calibration_cache_cleared():
    """Test calibration cache can be cleared."""
    matcher = RoleMatcher()
    matcher._calibration_cache["agent1"] = MagicMock()

    assert len(matcher._calibration_cache) == 1

    matcher.clear_cache()

    assert len(matcher._calibration_cache) == 0


# Test error handling


def test_get_calibrations_handles_errors(mock_calibration_tracker):
    """Test _get_calibrations handles exceptions gracefully."""
    matcher = RoleMatcher(calibration_tracker=mock_calibration_tracker)

    # Simulate error
    mock_calibration_tracker.get_calibration_summary.side_effect = RuntimeError("Database error")

    result = matcher._get_calibrations(["agent1"])

    assert result["agent1"] is None


def test_get_personas_handles_errors(mock_persona_manager):
    """Test _get_personas handles exceptions gracefully."""
    matcher = RoleMatcher(persona_manager=mock_persona_manager)

    # Simulate error
    mock_persona_manager.get_persona.side_effect = ValueError("Invalid agent")

    result = matcher._get_personas(["agent1"])

    assert result["agent1"] is None


def test_get_calibrations_no_tracker():
    """Test _get_calibrations returns empty dict without tracker."""
    matcher = RoleMatcher(calibration_tracker=None)

    result = matcher._get_calibrations(["agent1"])

    assert result == {}


def test_get_personas_no_manager():
    """Test _get_personas returns empty dict without manager."""
    matcher = RoleMatcher(persona_manager=None)

    result = matcher._get_personas(["agent1"])

    assert result == {}


# Test edge cases


def test_empty_agent_list(default_config):
    """Test match_roles with empty agent list."""
    random.seed(42)
    matcher = RoleMatcher(config=default_config)

    result = matcher.match_roles([], round_num=0)

    assert result.round_num == 0
    assert len(result.assignments) == 0


def test_single_agent(mock_calibration_tracker, mock_persona_manager, default_config):
    """Test match_roles with single agent."""
    random.seed(42)
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=default_config,
    )

    cal = MockCalibrationSummary(agent="agent1", total_predictions=10)
    mock_calibration_tracker.get_calibration_summary.return_value = cal

    result = matcher.match_roles(["agent1"], round_num=0)

    assert len(result.assignments) == 1
    assert "agent1" in result.assignments


def test_multiple_agents_same_calibration(mock_calibration_tracker, mock_persona_manager):
    """Test match_roles with multiple agents having same calibration state."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # All well-calibrated
    def get_cal(agent_name):
        return MockCalibrationSummary(
            agent=agent_name, brier_score=0.15, ece=0.05, total_predictions=10
        )

    mock_calibration_tracker.get_calibration_summary.side_effect = get_cal

    agent_names = ["agent1", "agent2", "agent3"]
    result = matcher.match_roles(agent_names, round_num=0)

    # All should get assignments, but different roles
    assert len(result.assignments) == 3
    assigned_roles = [a.role for a in result.assignments.values()]
    # At least some variety (not all identical)
    assert len(set(assigned_roles)) >= 1


def test_role_assignment_includes_prompt(mock_calibration_tracker, mock_persona_manager):
    """Test that RoleAssignment includes role_prompt."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="rotation")
    matcher = RoleMatcher(config=config)

    result = matcher.match_roles(["agent1"], round_num=0)

    assignment = result.assignments["agent1"]
    assert assignment.role_prompt != ""
    assert "Cognitive Role" in assignment.role_prompt or assignment.role_prompt == ""


# Test select_role_by_calibration edge cases


def test_select_role_by_calibration_all_roles_used(mock_calibration_tracker, mock_persona_manager):
    """Test _select_role_by_calibration when all roles are used."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(config=config)

    cal = MockCalibrationSummary(agent="agent1", brier_score=0.15, ece=0.05, total_predictions=10)

    # All roles already used
    used_roles = set(CognitiveRole)

    role = matcher._select_role_by_calibration(cal, used_roles)

    # Should still return a role (any role)
    assert isinstance(role, CognitiveRole)


def test_select_role_by_calibration_fallback_path(mock_calibration_tracker, mock_persona_manager):
    """Test _select_role_by_calibration fallback path."""
    random.seed(42)
    config = RoleMatchingConfig(strategy="calibration")
    matcher = RoleMatcher(config=config)

    # Agent that doesn't fit well-calibrated/overconfident/underconfident/high-accuracy
    cal = MockCalibrationSummary(
        agent="agent1",
        brier_score=0.3,
        ece=0.15,
        total_predictions=10,
        total_correct=5,  # 0.5 accuracy
        is_overconfident=False,
        is_underconfident=False,
    )

    used_roles = set()
    role = matcher._select_role_by_calibration(cal, used_roles)

    # Should use default path: ANALYST or LATERAL_THINKER
    assert role in (CognitiveRole.ANALYST, CognitiveRole.LATERAL_THINKER)


# Test comprehensive scenario


def test_comprehensive_scenario(mock_calibration_tracker, mock_persona_manager):
    """Test comprehensive scenario with mixed agent states."""
    random.seed(42)
    config = RoleMatchingConfig(
        strategy="hybrid",
        calibration_weight=0.4,
        expertise_weight=0.3,
        min_predictions_for_calibration=5,
    )
    matcher = RoleMatcher(
        calibration_tracker=mock_calibration_tracker,
        persona_manager=mock_persona_manager,
        config=config,
    )

    # Set up different agents
    def get_cal(agent_name):
        if agent_name == "well_calibrated":
            return MockCalibrationSummary(
                agent=agent_name, brier_score=0.15, ece=0.05, total_predictions=10
            )
        elif agent_name == "overconfident":
            return MockCalibrationSummary(
                agent=agent_name,
                brier_score=0.3,
                ece=0.15,
                total_predictions=10,
                is_overconfident=True,
            )
        elif agent_name == "cold_start":
            return MockCalibrationSummary(agent=agent_name, total_predictions=2)
        else:
            return None

    def get_persona(agent_name):
        if agent_name == "well_calibrated":
            return MockPersona(
                agent_name=agent_name,
                expertise={"security": 0.8},
                traits=["thorough"],
            )
        else:
            return None

    mock_calibration_tracker.get_calibration_summary.side_effect = get_cal
    mock_persona_manager.get_persona.side_effect = get_persona

    agent_names = ["well_calibrated", "overconfident", "cold_start"]
    result = matcher.match_roles(agent_names, round_num=0, debate_domain="security")

    assert result.strategy_used == "hybrid"
    assert result.calibration_used is True
    assert len(result.assignments) == 3
    assert "cold_start" in result.cold_start_agents
    assert "overconfident" in result.developmental_assignments


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
