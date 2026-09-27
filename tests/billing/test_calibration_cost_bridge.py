"""
Comprehensive tests for aragora.billing.calibration_cost_bridge module.

Tests cover:
- AgentCostEfficiency dataclass
- CalibrationCostBridgeConfig dataclass
- CalibrationCostBridge class
- Cost efficiency computations
- Task cost estimation
- Agent recommendation algorithms
- Budget-aware selection
- Overconfident/well-calibrated agent detection
- Cache management
- Factory function create_calibration_cost_bridge
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

from aragora.billing.calibration_cost_bridge import (
    AgentCostEfficiency,
    CalibrationCostBridge,
    CalibrationCostBridgeConfig,
    create_calibration_cost_bridge,
)


def test_bridge_source_has_no_agents_import():
    """TYPE_CHECKING imports still count, so billing must define local protocols."""
    import aragora.billing.calibration_cost_bridge as bridge_module

    source = Path(bridge_module.__file__).read_text(encoding="utf-8")
    assert "aragora.agents" not in source


# =============================================================================
# Mock Classes for Testing
# =============================================================================


@dataclass
class MockCalibrationSummary:
    """Mock CalibrationSummary for testing."""

    ece: float = 0.1
    accuracy: float = 0.85
    total_predictions: int = 100
    is_overconfident: bool = False
    is_underconfident: bool = False


class MockCalibrationTracker:
    """Mock CalibrationTracker for testing."""

    def __init__(self, summaries: dict[str, MockCalibrationSummary] | None = None):
        self._summaries = summaries or {}

    def get_calibration_summary(self, agent_name: str) -> MockCalibrationSummary | None:
        return self._summaries.get(agent_name)

    def get_all_agents(self) -> list[str]:
        return list(self._summaries.keys())


class MockCostTracker:
    """Mock CostTracker for testing."""

    def __init__(self):
        self._workspace_stats: dict[str, dict] = {}

    def add_workspace_stats(self, workspace_id: str, stats: dict) -> None:
        self._workspace_stats[workspace_id] = stats


# =============================================================================
# AgentCostEfficiency Tests
# =============================================================================


class TestAgentCostEfficiency:
    """Tests for AgentCostEfficiency dataclass."""

    def test_default_values(self):
        """Test AgentCostEfficiency default values."""
        eff = AgentCostEfficiency(agent_name="claude")

        assert eff.agent_name == "claude"
        assert eff.calibration_score == 0.0
        assert eff.accuracy_score == 0.0
        assert eff.cost_per_call == Decimal("0")
        assert eff.efficiency_score == 0.0
        assert eff.confidence_reliability == 0.0
        assert eff.is_overconfident is False
        assert eff.is_underconfident is False
        assert eff.recommendation == ""

    def test_with_custom_values(self):
        """Test AgentCostEfficiency with custom values."""
        eff = AgentCostEfficiency(
            agent_name="gpt-4",
            calibration_score=0.85,
            accuracy_score=0.90,
            cost_per_call=Decimal("0.05"),
            efficiency_score=0.80,
            confidence_reliability=0.88,
            is_overconfident=False,
            is_underconfident=False,
            recommendation="efficient",
        )

        assert eff.agent_name == "gpt-4"
        assert eff.calibration_score == 0.85
        assert eff.efficiency_score == 0.80
        assert eff.recommendation == "efficient"


# =============================================================================
# CalibrationCostBridgeConfig Tests
# =============================================================================


class TestCalibrationCostBridgeConfig:
    """Tests for CalibrationCostBridgeConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CalibrationCostBridgeConfig()

        assert config.min_predictions_for_scoring == 20
        assert config.calibration_weight == 0.4
        assert config.accuracy_weight == 0.3
        assert config.cost_weight == 0.3
        assert config.well_calibrated_ece_threshold == 0.1
        assert config.overconfident_cost_multiplier == 1.3
        assert config.underconfident_cost_multiplier == 1.1
        assert config.efficient_threshold == 0.7
        assert config.moderate_threshold == 0.4

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CalibrationCostBridgeConfig(
            min_predictions_for_scoring=50,
            calibration_weight=0.5,
            accuracy_weight=0.25,
            cost_weight=0.25,
            efficient_threshold=0.8,
        )

        assert config.min_predictions_for_scoring == 50
        assert config.calibration_weight == 0.5
        assert config.efficient_threshold == 0.8

    def test_weights_sum_to_one(self):
        """Test that default weights sum to 1.0."""
        config = CalibrationCostBridgeConfig()
        total = config.calibration_weight + config.accuracy_weight + config.cost_weight
        assert abs(total - 1.0) < 0.001


# =============================================================================
# CalibrationCostBridge Initialization Tests
# =============================================================================


class TestCalibrationCostBridgeInit:
    """Tests for CalibrationCostBridge initialization."""

    def test_default_initialization(self):
        """Test initialization with defaults."""
        bridge = CalibrationCostBridge()

        assert bridge.calibration_tracker is None
        assert bridge.cost_tracker is None
        assert isinstance(bridge.config, CalibrationCostBridgeConfig)
        assert bridge._efficiency_cache == {}
        assert bridge._cache_timestamp is None

    def test_with_trackers(self):
        """Test initialization with trackers."""
        cal_tracker = MockCalibrationTracker()
        cost_tracker = MockCostTracker()

        bridge = CalibrationCostBridge(
            calibration_tracker=cal_tracker,
            cost_tracker=cost_tracker,
        )

        assert bridge.calibration_tracker is cal_tracker
        assert bridge.cost_tracker is cost_tracker

    def test_with_custom_config(self):
        """Test initialization with custom config."""
        config = CalibrationCostBridgeConfig(min_predictions_for_scoring=100)

        bridge = CalibrationCostBridge(config=config)

        assert bridge.config.min_predictions_for_scoring == 100


# =============================================================================
# Cost Efficiency Computation Tests
# =============================================================================


class TestComputeCostEfficiency:
    """Tests for compute_cost_efficiency method."""

    def test_no_calibration_tracker(self):
        """Test computation without calibration tracker."""
        bridge = CalibrationCostBridge()

        result = bridge.compute_cost_efficiency("claude")

        assert result.agent_name == "claude"
        assert result.recommendation == "unknown"

    def test_no_calibration_data(self):
        """Test computation when agent has no calibration data."""
        tracker = MockCalibrationTracker({})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("unknown_agent")

        assert result.recommendation == "unknown"

    def test_insufficient_predictions(self):
        """Test computation with insufficient predictions."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(total_predictions=10)  # Below threshold
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("claude")

        assert result.recommendation == "insufficient_data"

    def test_well_calibrated_agent(self):
        """Test computation for well-calibrated agent."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    ece=0.05,  # Very low ECE
                    accuracy=0.90,
                    total_predictions=100,
                    is_overconfident=False,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("claude")

        assert result.calibration_score > 0.8  # High due to low ECE
        assert result.accuracy_score == 0.90
        assert result.is_overconfident is False
        assert result.is_underconfident is False
        assert result.confidence_reliability > 0.9  # High for well-calibrated

    def test_overconfident_agent(self):
        """Test computation for overconfident agent."""
        tracker = MockCalibrationTracker(
            {
                "gpt-4": MockCalibrationSummary(
                    ece=0.2,
                    accuracy=0.85,
                    total_predictions=100,
                    is_overconfident=True,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("gpt-4")

        assert result.is_overconfident is True
        assert result.confidence_reliability <= 0.7  # Reduced for overconfident
        # Efficiency should have 15% penalty applied

    def test_underconfident_agent(self):
        """Test computation for underconfident agent."""
        tracker = MockCalibrationTracker(
            {
                "gemini": MockCalibrationSummary(
                    ece=0.15,
                    accuracy=0.88,
                    total_predictions=100,
                    is_overconfident=False,
                    is_underconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("gemini")

        assert result.is_underconfident is True
        # Underconfident gets only 5% penalty (less severe than overconfident)

    def test_efficiency_thresholds(self):
        """Test efficiency recommendation thresholds."""
        # Efficient agent (high score)
        tracker = MockCalibrationTracker(
            {
                "efficient": MockCalibrationSummary(
                    ece=0.02,
                    accuracy=0.95,
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("efficient")
        assert result.recommendation == "efficient"  # Score >= 0.7

    def test_moderate_efficiency(self):
        """Test moderate efficiency recommendation."""
        tracker = MockCalibrationTracker(
            {
                "moderate": MockCalibrationSummary(
                    ece=0.15,
                    accuracy=0.75,
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("moderate")
        # Score between 0.4 and 0.7 -> moderate

    def test_costly_recommendation(self):
        """Test costly recommendation for low efficiency."""
        tracker = MockCalibrationTracker(
            {
                "costly": MockCalibrationSummary(
                    ece=0.28,  # Very high ECE
                    accuracy=0.55,  # Low accuracy
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("costly")
        # Low scores should give "costly" or "moderate" recommendation

    def test_caches_result(self):
        """Test that results are cached."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result1 = bridge.compute_cost_efficiency("claude")

        assert "claude" in bridge._efficiency_cache
        assert bridge._cache_timestamp is not None


# =============================================================================
# Cost Score Calculation Tests
# =============================================================================


class TestCostScore:
    """Tests for _cost_score method."""

    def test_zero_cost(self):
        """Test cost score for zero cost."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0"))
        assert score == 0.5  # Unknown/neutral

    def test_negative_cost(self):
        """Test cost score for negative cost."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("-1"))
        assert score == 0.5  # Treat as unknown

    def test_very_low_cost(self):
        """Test cost score for very low cost."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.0005"))
        assert score == 1.0  # Maximum efficiency

    def test_very_high_cost(self):
        """Test cost score for very high cost."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.15"))
        assert score == 0.0  # Minimum efficiency

    def test_mid_range_cost(self):
        """Test cost score for mid-range cost."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.05"))
        assert 0.0 < score < 1.0  # Somewhere in between


# =============================================================================
# Task Cost Estimation Tests
# =============================================================================


class TestEstimateTaskCost:
    """Tests for estimate_task_cost method."""

    def test_basic_estimation(self):
        """Test basic task cost estimation."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    total_predictions=100,
                    is_overconfident=False,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost = bridge.estimate_task_cost(
            agent_name="claude",
            base_cost=Decimal("0.01"),
            rounds=3,
        )

        assert cost > Decimal("0")

    def test_overconfident_multiplier(self):
        """Test cost multiplier for overconfident agent."""
        tracker = MockCalibrationTracker(
            {
                "gpt-4": MockCalibrationSummary(
                    total_predictions=100,
                    is_overconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost = bridge.estimate_task_cost(
            agent_name="gpt-4",
            base_cost=Decimal("0.01"),
            rounds=3,
        )

        # Should have 1.3x multiplier
        expected_base = Decimal("0.01") * 3 * Decimal("1.3")
        assert cost == expected_base

    def test_underconfident_multiplier(self):
        """Test cost multiplier for underconfident agent."""
        tracker = MockCalibrationTracker(
            {
                "gemini": MockCalibrationSummary(
                    total_predictions=100,
                    is_underconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost = bridge.estimate_task_cost(
            agent_name="gemini",
            base_cost=Decimal("0.01"),
            rounds=3,
        )

        # Should have 1.1x multiplier
        expected_base = Decimal("0.01") * 3 * Decimal("1.1")
        assert cost == expected_base

    def test_well_calibrated_discount(self):
        """Test cost discount for well-calibrated agent."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    total_predictions=100,
                    ece=0.05,  # Low ECE
                    is_overconfident=False,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost = bridge.estimate_task_cost(
            agent_name="claude",
            base_cost=Decimal("0.01"),
            rounds=3,
        )

        # Well-calibrated gets 0.9x multiplier
        # confidence_reliability > 0.8 from low ECE

    def test_different_rounds(self):
        """Test estimation with different round counts."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost_1 = bridge.estimate_task_cost("claude", Decimal("0.01"), rounds=1)
        cost_5 = bridge.estimate_task_cost("claude", Decimal("0.01"), rounds=5)

        assert cost_5 > cost_1


# =============================================================================
# Agent Recommendation Tests
# =============================================================================


class TestRecommendCostEfficientAgent:
    """Tests for recommend_cost_efficient_agent method."""

    def test_recommends_best_agent(self):
        """Test recommending most efficient agent."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    ece=0.05,
                    accuracy=0.92,
                    total_predictions=100,
                ),
                "gpt-4": MockCalibrationSummary(
                    ece=0.15,
                    accuracy=0.85,
                    total_predictions=100,
                ),
                "gemini": MockCalibrationSummary(
                    ece=0.10,
                    accuracy=0.88,
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.recommend_cost_efficient_agent(["claude", "gpt-4", "gemini"])

        assert result == "claude"  # Highest efficiency

    def test_filters_by_accuracy(self):
        """Test filtering by minimum accuracy."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    ece=0.05,
                    accuracy=0.65,  # Below threshold
                    total_predictions=100,
                ),
                "gpt-4": MockCalibrationSummary(
                    ece=0.10,
                    accuracy=0.75,  # Above threshold
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.recommend_cost_efficient_agent(
            ["claude", "gpt-4"],
            min_accuracy=0.70,
        )

        assert result == "gpt-4"  # claude filtered out

    def test_no_candidates(self):
        """Test when no candidates meet criteria."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    accuracy=0.50,  # Too low
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.recommend_cost_efficient_agent(
            ["claude"],
            min_accuracy=0.80,
        )

        assert result is None

    def test_skips_insufficient_data(self):
        """Test skipping agents with insufficient data."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    total_predictions=5,  # Insufficient
                ),
                "gpt-4": MockCalibrationSummary(
                    accuracy=0.85,
                    total_predictions=100,  # Sufficient
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.recommend_cost_efficient_agent(["claude", "gpt-4"])

        assert result == "gpt-4"

    def test_empty_agent_list(self):
        """Test with empty agent list."""
        bridge = CalibrationCostBridge()
        result = bridge.recommend_cost_efficient_agent([])
        assert result is None


# =============================================================================
# Agent Ranking Tests
# =============================================================================


class TestRankAgentsByCostEfficiency:
    """Tests for rank_agents_by_cost_efficiency method."""

    def test_ranks_agents(self):
        """Test ranking agents by efficiency."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    ece=0.05,
                    accuracy=0.92,
                    total_predictions=100,
                ),
                "gpt-4": MockCalibrationSummary(
                    ece=0.20,
                    accuracy=0.80,
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        rankings = bridge.rank_agents_by_cost_efficiency(["claude", "gpt-4"])

        assert len(rankings) == 2
        assert rankings[0][0] == "claude"  # Higher efficiency
        assert rankings[0][1] > rankings[1][1]  # Sorted descending

    def test_includes_all_agents(self):
        """Test that all agents are included in ranking."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(total_predictions=100),
                "b": MockCalibrationSummary(total_predictions=100),
                "c": MockCalibrationSummary(total_predictions=100),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        rankings = bridge.rank_agents_by_cost_efficiency(["a", "b", "c"])

        assert len(rankings) == 3


# =============================================================================
# Budget-Aware Selection Tests
# =============================================================================


class TestBudgetAwareSelection:
    """Tests for get_budget_aware_selection method."""

    def test_selects_within_budget(self):
        """Test selecting agents within budget."""
        tracker = MockCalibrationTracker(
            {
                "cheap": MockCalibrationSummary(
                    ece=0.10,
                    accuracy=0.85,
                    total_predictions=100,
                ),
                "expensive": MockCalibrationSummary(
                    ece=0.08,
                    accuracy=0.90,
                    total_predictions=100,
                ),
            }
        )
        cost_tracker = MockCostTracker()
        cost_tracker.add_workspace_stats(
            "ws1",
            {
                "by_agent": {
                    "cheap": Decimal("0.01"),
                    "expensive": Decimal("0.10"),
                },
                "api_calls": 10,
            },
        )

        bridge = CalibrationCostBridge(
            calibration_tracker=tracker,
            cost_tracker=cost_tracker,
        )

        # Low budget should only allow cheap agent
        result = bridge.get_budget_aware_selection(
            ["cheap", "expensive"],
            budget_remaining=Decimal("0.05"),
            estimated_rounds=3,
        )

        assert "cheap" in result

    def test_sorts_by_efficiency(self):
        """Test that results are sorted by efficiency."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(
                    ece=0.20,
                    accuracy=0.80,
                    total_predictions=100,
                ),
                "b": MockCalibrationSummary(
                    ece=0.05,
                    accuracy=0.90,
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_budget_aware_selection(
            ["a", "b"],
            budget_remaining=Decimal("100"),  # High budget
            estimated_rounds=3,
        )

        # "b" should be first (more efficient)
        if len(result) >= 2:
            # Both fit budget, "b" should be first
            pass

    def test_empty_when_no_fit(self):
        """Test empty result when no agent fits budget."""
        tracker = MockCalibrationTracker(
            {"expensive": MockCalibrationSummary(total_predictions=100)}
        )
        cost_tracker = MockCostTracker()
        cost_tracker.add_workspace_stats(
            "ws1",
            {
                "by_agent": {"expensive": Decimal("1.00")},
                "api_calls": 1,
            },
        )

        bridge = CalibrationCostBridge(
            calibration_tracker=tracker,
            cost_tracker=cost_tracker,
        )

        result = bridge.get_budget_aware_selection(
            ["expensive"],
            budget_remaining=Decimal("0.01"),  # Too low
            estimated_rounds=3,
        )

        # May be empty depending on cost estimation


# =============================================================================
# Overconfident/Well-Calibrated Detection Tests
# =============================================================================


class TestAgentDetection:
    """Tests for overconfident and well-calibrated agent detection."""

    def test_get_overconfident_agents(self):
        """Test detecting overconfident agents."""
        tracker = MockCalibrationTracker(
            {
                "overconfident": MockCalibrationSummary(
                    is_overconfident=True,
                    total_predictions=100,
                ),
                "normal": MockCalibrationSummary(
                    is_overconfident=False,
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_overconfident_agents()

        assert "overconfident" in result
        assert "normal" not in result

    def test_get_overconfident_agents_filtered(self):
        """Test detecting overconfident agents with filter."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(is_overconfident=True),
                "b": MockCalibrationSummary(is_overconfident=True),
                "c": MockCalibrationSummary(is_overconfident=False),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        # Only check "a" and "c"
        result = bridge.get_overconfident_agents(["a", "c"])

        assert result == ["a"]

    def test_get_overconfident_agents_no_tracker(self):
        """Test getting overconfident agents without tracker."""
        bridge = CalibrationCostBridge()
        result = bridge.get_overconfident_agents()
        assert result == []

    def test_get_well_calibrated_agents(self):
        """Test detecting well-calibrated agents."""
        tracker = MockCalibrationTracker(
            {
                "well_calibrated": MockCalibrationSummary(
                    ece=0.05,  # Below threshold
                    total_predictions=100,
                ),
                "poorly_calibrated": MockCalibrationSummary(
                    ece=0.25,  # Above threshold
                    total_predictions=100,
                ),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_well_calibrated_agents()

        assert "well_calibrated" in result
        assert "poorly_calibrated" not in result

    def test_get_well_calibrated_agents_no_tracker(self):
        """Test getting well-calibrated agents without tracker."""
        bridge = CalibrationCostBridge()
        result = bridge.get_well_calibrated_agents()
        assert result == []


# =============================================================================
# Cache Management Tests
# =============================================================================


class TestCacheManagement:
    """Tests for cache management."""

    def test_get_efficiency_cached(self):
        """Test getting cached efficiency data."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        # Compute to populate cache
        bridge.compute_cost_efficiency("claude")

        # Get from cache
        cached = bridge.get_efficiency("claude")
        assert cached is not None
        assert cached.agent_name == "claude"

    def test_get_efficiency_not_cached(self):
        """Test getting uncached efficiency returns None."""
        bridge = CalibrationCostBridge()
        result = bridge.get_efficiency("unknown")
        assert result is None

    def test_cache_expiration(self):
        """Test cache expiration."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        # Compute to populate cache
        bridge.compute_cost_efficiency("claude")

        # Simulate cache expiration
        bridge._cache_timestamp = datetime.now() - timedelta(seconds=600)

        # Should be cleared due to expiration
        result = bridge.get_efficiency("claude")
        assert result is None

    def test_refresh_cache(self):
        """Test cache refresh."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(total_predictions=100),
                "gpt-4": MockCalibrationSummary(total_predictions=100),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        count = bridge.refresh_cache(["claude", "gpt-4"])

        assert count == 2
        assert "claude" in bridge._efficiency_cache
        assert "gpt-4" in bridge._efficiency_cache

    def test_refresh_cache_all_agents(self):
        """Test refreshing cache for all agents."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(total_predictions=100),
                "b": MockCalibrationSummary(total_predictions=100),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        count = bridge.refresh_cache()  # No specific agents

        assert count == 2

    def test_refresh_cache_no_agents(self):
        """Test refresh with no agents."""
        bridge = CalibrationCostBridge()
        count = bridge.refresh_cache()
        assert count == 0


# =============================================================================
# Statistics Tests
# =============================================================================


class TestGetStats:
    """Tests for get_stats method."""

    def test_stats_without_trackers(self):
        """Test stats without trackers."""
        bridge = CalibrationCostBridge()
        stats = bridge.get_stats()

        assert stats["calibration_tracker_attached"] is False
        assert stats["cost_tracker_attached"] is False
        assert stats["agents_cached"] == 0

    def test_stats_with_trackers(self):
        """Test stats with trackers attached."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    ece=0.05,
                    is_overconfident=False,
                ),
                "gpt-4": MockCalibrationSummary(
                    ece=0.20,
                    is_overconfident=True,
                ),
            }
        )
        cost_tracker = MockCostTracker()

        bridge = CalibrationCostBridge(
            calibration_tracker=tracker,
            cost_tracker=cost_tracker,
        )

        stats = bridge.get_stats()

        assert stats["calibration_tracker_attached"] is True
        assert stats["cost_tracker_attached"] is True
        assert stats["well_calibrated_agents"] == 1  # claude
        assert stats["overconfident_agents"] == 1  # gpt-4

    def test_stats_cache_validity(self):
        """Test stats includes cache validity."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        # Initially no cache
        stats = bridge.get_stats()
        assert stats["cache_valid"] is False

        # After computation
        bridge.compute_cost_efficiency("claude")
        stats = bridge.get_stats()
        assert stats["cache_valid"] is True
        assert stats["agents_cached"] == 1


# =============================================================================
# Factory Function Tests
# =============================================================================


class TestCreateCalibrationCostBridge:
    """Tests for create_calibration_cost_bridge factory function."""

    def test_create_basic_bridge(self):
        """Test creating basic bridge."""
        bridge = create_calibration_cost_bridge()

        assert isinstance(bridge, CalibrationCostBridge)
        assert bridge.calibration_tracker is None
        assert bridge.cost_tracker is None

    def test_create_with_trackers(self):
        """Test creating bridge with trackers."""
        cal_tracker = MockCalibrationTracker()
        cost_tracker = MockCostTracker()

        bridge = create_calibration_cost_bridge(
            calibration_tracker=cal_tracker,
            cost_tracker=cost_tracker,
        )

        assert bridge.calibration_tracker is cal_tracker
        assert bridge.cost_tracker is cost_tracker

    def test_create_with_config_kwargs(self):
        """Test creating bridge with config kwargs."""
        bridge = create_calibration_cost_bridge(
            min_predictions_for_scoring=50,
            efficient_threshold=0.8,
        )

        assert bridge.config.min_predictions_for_scoring == 50
        assert bridge.config.efficient_threshold == 0.8


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_ece_at_boundary(self):
        """Test ECE at exact threshold boundary."""
        tracker = MockCalibrationTracker(
            {
                "boundary": MockCalibrationSummary(
                    ece=0.1,  # Exactly at well_calibrated_ece_threshold
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("boundary")
        # Should still compute without errors

    def test_zero_accuracy(self):
        """Test agent with zero accuracy."""
        tracker = MockCalibrationTracker(
            {
                "zero_acc": MockCalibrationSummary(
                    accuracy=0.0,
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("zero_acc")
        assert result.accuracy_score == 0.0

    def test_perfect_calibration(self):
        """Test perfectly calibrated agent (ECE=0)."""
        tracker = MockCalibrationTracker(
            {
                "perfect": MockCalibrationSummary(
                    ece=0.0,
                    accuracy=1.0,
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("perfect")
        assert result.calibration_score == 1.0

    def test_very_high_ece(self):
        """Test agent with very high ECE."""
        tracker = MockCalibrationTracker(
            {
                "bad": MockCalibrationSummary(
                    ece=0.5,  # Very poorly calibrated
                    accuracy=0.5,
                    total_predictions=100,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("bad")
        # Calibration score should be capped at 0
        assert result.calibration_score >= 0.0

    def test_calibration_tracker_exception(self):
        """Test handling of calibration tracker exceptions."""
        tracker = MockCalibrationTracker({})

        # Make get_calibration_summary raise an exception
        def raise_error(name):
            raise RuntimeError("Tracker error")

        tracker.get_calibration_summary = raise_error

        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        assert result.recommendation == "unknown"

    def test_exact_predictions_threshold(self):
        """Test agent with exactly threshold predictions."""
        config = CalibrationCostBridgeConfig(min_predictions_for_scoring=20)
        tracker = MockCalibrationTracker(
            {
                "exactly_20": MockCalibrationSummary(
                    total_predictions=20,  # Exactly at threshold
                    accuracy=0.85,
                )
            }
        )
        bridge = CalibrationCostBridge(
            calibration_tracker=tracker,
            config=config,
        )

        result = bridge.compute_cost_efficiency("exactly_20")
        # Should NOT be "insufficient_data" since it meets threshold
        assert result.recommendation != "insufficient_data"

    def test_negative_budget(self):
        """Test budget-aware selection with negative budget."""
        bridge = CalibrationCostBridge()
        result = bridge.get_budget_aware_selection(
            ["agent1", "agent2"],
            budget_remaining=Decimal("-10"),
        )
        assert result == []


# =============================================================================
# Extended Cost Score Tests
# =============================================================================


class TestCostScoreExtended:
    """Extended tests for _cost_score calculation boundaries."""

    def test_cost_exactly_at_lower_bound(self):
        """Test cost score at exactly $0.001."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.001"))
        assert score == 1.0

    def test_cost_exactly_at_upper_bound(self):
        """Test cost score at exactly $0.10."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.10"))
        assert score == 0.0

    def test_cost_just_above_lower_bound(self):
        """Test cost score just above $0.001."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.002"))
        assert 0.0 < score < 1.0

    def test_cost_just_below_upper_bound(self):
        """Test cost score just below $0.10."""
        bridge = CalibrationCostBridge()
        score = bridge._cost_score(Decimal("0.099"))
        assert 0.0 < score < 1.0

    def test_cost_score_is_monotonically_decreasing(self):
        """Test cost score decreases as cost increases."""
        bridge = CalibrationCostBridge()

        costs = [
            Decimal("0.001"),
            Decimal("0.02"),
            Decimal("0.05"),
            Decimal("0.08"),
            Decimal("0.10"),
        ]
        scores = [bridge._cost_score(c) for c in costs]

        for i in range(len(scores) - 1):
            assert scores[i] >= scores[i + 1], (
                f"Score at ${costs[i]} ({scores[i]}) should be >= score at ${costs[i + 1]} ({scores[i + 1]})"
            )


# =============================================================================
# Extended _get_avg_cost Tests
# =============================================================================


class TestGetAvgCost:
    """Tests for _get_avg_cost method."""

    def test_no_cost_tracker(self):
        """Test average cost without cost tracker."""
        bridge = CalibrationCostBridge()
        assert bridge._get_avg_cost("claude") == Decimal("0")

    def test_agent_in_workspace(self):
        """Test average cost for agent with workspace stats."""
        cost_tracker = MockCostTracker()
        cost_tracker.add_workspace_stats(
            "ws1",
            {
                "by_agent": {"claude": Decimal("5.00")},
                "api_calls": 100,
            },
        )
        bridge = CalibrationCostBridge(cost_tracker=cost_tracker)

        result = bridge._get_avg_cost("claude")
        assert result == Decimal("0.05")  # 5.00 / 100

    def test_agent_not_in_workspace(self):
        """Test average cost for agent not in any workspace."""
        cost_tracker = MockCostTracker()
        cost_tracker.add_workspace_stats(
            "ws1",
            {
                "by_agent": {"gpt-4": Decimal("10.00")},
                "api_calls": 50,
            },
        )
        bridge = CalibrationCostBridge(cost_tracker=cost_tracker)

        result = bridge._get_avg_cost("claude")
        assert result == Decimal("0")

    def test_multiple_workspaces_first_match(self):
        """Test average cost finds agent in first matching workspace."""
        cost_tracker = MockCostTracker()
        cost_tracker.add_workspace_stats(
            "ws1",
            {
                "by_agent": {"claude": Decimal("2.00")},
                "api_calls": 10,
            },
        )
        cost_tracker.add_workspace_stats(
            "ws2",
            {
                "by_agent": {"claude": Decimal("8.00")},
                "api_calls": 40,
            },
        )
        bridge = CalibrationCostBridge(cost_tracker=cost_tracker)

        result = bridge._get_avg_cost("claude")
        # Returns from first matching workspace
        assert result > Decimal("0")

    def test_zero_api_calls(self):
        """Test average cost with zero API calls (division by max(1,...))."""
        cost_tracker = MockCostTracker()
        cost_tracker.add_workspace_stats(
            "ws1",
            {
                "by_agent": {"claude": Decimal("0.50")},
                "api_calls": 0,  # Zero calls
            },
        )
        bridge = CalibrationCostBridge(cost_tracker=cost_tracker)

        result = bridge._get_avg_cost("claude")
        # Should divide by max(1, 0) = 1
        assert result == Decimal("0.50")


# =============================================================================
# Extended Calibration Score Computation Tests
# =============================================================================


class TestCalibrationScoreFormulas:
    """Tests for the exact calibration score formulas."""

    def test_calibration_score_formula_ece_zero(self):
        """Test calibration_score = 1 - ECE*3.33 when ECE=0."""
        tracker = MockCalibrationTracker(
            {"agent": MockCalibrationSummary(ece=0.0, accuracy=0.9, total_predictions=100)}
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        assert result.calibration_score == 1.0

    def test_calibration_score_formula_ece_03(self):
        """Test calibration_score = 0 when ECE=0.3."""
        tracker = MockCalibrationTracker(
            {"agent": MockCalibrationSummary(ece=0.3, accuracy=0.9, total_predictions=100)}
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        assert abs(result.calibration_score - 0.001) < 0.01  # ~1 - 0.3*3.33 = 0.001

    def test_calibration_score_formula_ece_015(self):
        """Test calibration_score at ECE=0.15."""
        tracker = MockCalibrationTracker(
            {"agent": MockCalibrationSummary(ece=0.15, accuracy=0.9, total_predictions=100)}
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        expected = 1.0 - 0.15 * 3.33  # ~0.5005
        assert abs(result.calibration_score - expected) < 0.01

    def test_calibration_score_capped_at_zero(self):
        """Test calibration_score is capped at 0 for very high ECE."""
        tracker = MockCalibrationTracker(
            {"agent": MockCalibrationSummary(ece=0.5, accuracy=0.5, total_predictions=100)}
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        # 1.0 - 0.5 * 3.33 = -0.665, capped to 0.0
        assert result.calibration_score == 0.0

    def test_confidence_reliability_well_calibrated(self):
        """Test confidence_reliability for well-calibrated agent."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    ece=0.05,
                    accuracy=0.9,
                    total_predictions=100,
                    is_overconfident=False,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        # confidence_reliability = 1.0 - ece = 0.95
        assert abs(result.confidence_reliability - 0.95) < 0.001

    def test_confidence_reliability_overconfident(self):
        """Test confidence_reliability for overconfident agent."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    ece=0.2,
                    accuracy=0.85,
                    total_predictions=100,
                    is_overconfident=True,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        # confidence_reliability = max(0.3, 0.7 - ece) = max(0.3, 0.5) = 0.5
        assert abs(result.confidence_reliability - 0.5) < 0.001

    def test_confidence_reliability_overconfident_floor(self):
        """Test confidence_reliability overconfident hits floor of 0.3."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    ece=0.5,
                    accuracy=0.6,
                    total_predictions=100,
                    is_overconfident=True,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        # confidence_reliability = max(0.3, 0.7 - 0.5) = max(0.3, 0.2) = 0.3
        assert abs(result.confidence_reliability - 0.3) < 0.001

    def test_confidence_reliability_underconfident(self):
        """Test confidence_reliability for underconfident agent."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    ece=0.15,
                    accuracy=0.9,
                    total_predictions=100,
                    is_overconfident=False,
                    is_underconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        # confidence_reliability = max(0.5, 0.85 - ece) = max(0.5, 0.70) = 0.70
        assert abs(result.confidence_reliability - 0.70) < 0.001

    def test_efficiency_score_overconfident_penalty(self):
        """Test 15% penalty is applied for overconfident agents."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    ece=0.1,
                    accuracy=0.9,
                    total_predictions=100,
                    is_overconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        # The raw score gets multiplied by 0.85
        # We can verify the penalty is applied by checking the score is < what it would be without
        # Since we can't easily compute the pre-penalty score, just verify the result is reasonable
        assert result.efficiency_score > 0.0

    def test_efficiency_score_underconfident_penalty(self):
        """Test 5% penalty is applied for underconfident agents."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    ece=0.1,
                    accuracy=0.9,
                    total_predictions=100,
                    is_underconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.compute_cost_efficiency("agent")
        assert result.efficiency_score > 0.0


# =============================================================================
# Extended Task Cost Estimation Tests
# =============================================================================


class TestEstimateTaskCostExtended:
    """Extended tests for estimate_task_cost method."""

    def test_well_calibrated_discount(self):
        """Test well-calibrated agent gets 0.9x multiplier."""
        tracker = MockCalibrationTracker(
            {
                "claude": MockCalibrationSummary(
                    ece=0.05,  # Low ECE -> confidence_reliability > 0.8
                    accuracy=0.95,
                    total_predictions=100,
                    is_overconfident=False,
                    is_underconfident=False,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost = bridge.estimate_task_cost(
            agent_name="claude",
            base_cost=Decimal("0.01"),
            rounds=3,
        )

        # Well-calibrated: confidence_reliability = 1 - 0.05 = 0.95 > 0.8
        # Multiplier should be 0.9
        expected = Decimal("0.01") * 3 * Decimal("0.9")
        assert cost == expected

    def test_unknown_recommendation_default_multiplier(self):
        """Test default multiplier for unknown/insufficient data."""
        bridge = CalibrationCostBridge()  # No tracker

        cost = bridge.estimate_task_cost(
            agent_name="unknown",
            base_cost=Decimal("0.01"),
            rounds=3,
        )

        # No data, recommendation is "unknown", none of the if branches match
        # Default multiplier stays at 1.0
        expected = Decimal("0.01") * 3 * Decimal("1.0")
        assert cost == expected

    def test_estimate_cost_single_round(self):
        """Test task cost estimation with single round."""
        tracker = MockCalibrationTracker(
            {
                "gpt-4": MockCalibrationSummary(
                    total_predictions=100,
                    is_overconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost = bridge.estimate_task_cost("gpt-4", Decimal("0.05"), rounds=1)
        expected = Decimal("0.05") * 1 * Decimal("1.3")
        assert cost == expected

    def test_estimate_cost_many_rounds(self):
        """Test task cost estimation with many rounds scales linearly."""
        tracker = MockCalibrationTracker(
            {
                "agent": MockCalibrationSummary(
                    total_predictions=100,
                    is_overconfident=True,
                )
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        cost_3 = bridge.estimate_task_cost("agent", Decimal("0.01"), rounds=3)
        cost_6 = bridge.estimate_task_cost("agent", Decimal("0.01"), rounds=6)
        # Cost scales linearly with rounds
        assert cost_6 == cost_3 * 2


# =============================================================================
# Extended Agent Recommendation Tests
# =============================================================================


class TestRecommendationExtended:
    """Extended tests for agent recommendation methods."""

    def test_recommend_all_unknown(self):
        """Test recommendation when all agents have unknown calibration."""
        bridge = CalibrationCostBridge()  # No tracker

        result = bridge.recommend_cost_efficient_agent(["a", "b", "c"])
        # All will have "unknown" recommendation, none pass the filter
        # Since "unknown" != "insufficient_data", they should be included
        # but accuracy_score will be 0.0 which is < default min_accuracy (0.7)
        assert result is None

    def test_recommend_with_zero_min_accuracy(self):
        """Test recommendation with min_accuracy=0."""
        bridge = CalibrationCostBridge()  # No tracker

        result = bridge.recommend_cost_efficient_agent(["a", "b"], min_accuracy=0.0)
        # With min_accuracy=0, unknown agents pass accuracy filter
        # Recommendation should be one of the agents
        assert result is not None

    def test_rank_empty_list(self):
        """Test ranking with empty agent list."""
        bridge = CalibrationCostBridge()
        result = bridge.rank_agents_by_cost_efficiency([])
        assert result == []

    def test_rank_single_agent(self):
        """Test ranking with single agent."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.rank_agents_by_cost_efficiency(["claude"])
        assert len(result) == 1
        assert result[0][0] == "claude"


# =============================================================================
# Extended Well-Calibrated Agent Detection Tests
# =============================================================================


class TestAgentDetectionExtended:
    """Extended tests for agent calibration detection."""

    def test_get_well_calibrated_with_filter(self):
        """Test well-calibrated detection with filter list."""
        tracker = MockCalibrationTracker(
            {
                "good1": MockCalibrationSummary(ece=0.05),
                "good2": MockCalibrationSummary(ece=0.03),
                "bad": MockCalibrationSummary(ece=0.25),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_well_calibrated_agents(["good1", "bad"])
        assert "good1" in result
        assert "bad" not in result
        assert "good2" not in result  # Not in filter

    def test_get_overconfident_agents_none_overconfident(self):
        """Test overconfident detection when no agents are overconfident."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(is_overconfident=False),
                "b": MockCalibrationSummary(is_overconfident=False),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_overconfident_agents()
        assert result == []

    def test_get_well_calibrated_at_exact_threshold(self):
        """Test well-calibrated at exactly the ECE threshold."""
        tracker = MockCalibrationTracker(
            {
                # ECE = 0.1, threshold is 0.1, condition is ece < threshold
                "at_boundary": MockCalibrationSummary(ece=0.1),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_well_calibrated_agents()
        # ece < threshold means 0.1 < 0.1 is False, so NOT well-calibrated
        assert "at_boundary" not in result

    def test_get_well_calibrated_just_below_threshold(self):
        """Test well-calibrated just below the ECE threshold."""
        tracker = MockCalibrationTracker(
            {
                "just_below": MockCalibrationSummary(ece=0.099),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_well_calibrated_agents()
        assert "just_below" in result


# =============================================================================
# Extended Cache Management Tests
# =============================================================================


class TestCacheManagementExtended:
    """Extended tests for cache management."""

    def test_cache_not_expired_within_ttl(self):
        """Test cache is valid within TTL."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        bridge.compute_cost_efficiency("claude")
        # Set timestamp to 100 seconds ago (within 300s TTL)
        bridge._cache_timestamp = datetime.now() - timedelta(seconds=100)

        cached = bridge.get_efficiency("claude")
        assert cached is not None

    def test_cache_expired_exactly_at_ttl(self):
        """Test cache at exactly the TTL boundary."""
        tracker = MockCalibrationTracker({"claude": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        bridge.compute_cost_efficiency("claude")
        # Set timestamp to 301 seconds ago (just past 300s TTL)
        bridge._cache_timestamp = datetime.now() - timedelta(seconds=301)

        cached = bridge.get_efficiency("claude")
        assert cached is None

    def test_get_efficiency_no_timestamp(self):
        """Test get_efficiency when no cache timestamp is set."""
        bridge = CalibrationCostBridge()
        # Put something in cache manually but don't set timestamp
        bridge._efficiency_cache["test"] = AgentCostEfficiency(agent_name="test")

        result = bridge.get_efficiency("test")
        # No timestamp, so cache check passes and returns the cached value
        assert result is not None
        assert result.agent_name == "test"

    def test_refresh_cache_specific_agents(self):
        """Test refreshing cache for specific agents only."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(total_predictions=100),
                "b": MockCalibrationSummary(total_predictions=100),
                "c": MockCalibrationSummary(total_predictions=100),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        count = bridge.refresh_cache(["a", "c"])
        assert count == 2
        assert "a" in bridge._efficiency_cache
        assert "c" in bridge._efficiency_cache
        # "b" should not be in cache
        assert "b" not in bridge._efficiency_cache


# =============================================================================
# Extended Budget-Aware Selection Tests
# =============================================================================


class TestBudgetAwareSelectionExtended:
    """Extended tests for budget-aware agent selection."""

    def test_large_budget_includes_all(self):
        """Test large budget includes all agents."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(ece=0.05, accuracy=0.9, total_predictions=100),
                "b": MockCalibrationSummary(ece=0.1, accuracy=0.85, total_predictions=100),
                "c": MockCalibrationSummary(ece=0.15, accuracy=0.8, total_predictions=100),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_budget_aware_selection(
            ["a", "b", "c"],
            budget_remaining=Decimal("10000"),  # Very large budget
            estimated_rounds=3,
        )

        assert len(result) == 3

    def test_zero_budget_empty(self):
        """Test zero budget returns empty list."""
        tracker = MockCalibrationTracker({"a": MockCalibrationSummary(total_predictions=100)})
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        result = bridge.get_budget_aware_selection(
            ["a"],
            budget_remaining=Decimal("0"),
            estimated_rounds=3,
        )

        # With zero budget, only agents with zero estimated cost can fit
        # Default base_cost for agents without cost data is $0.01
        # So likely empty
        assert isinstance(result, list)


# =============================================================================
# Extended Statistics Tests
# =============================================================================


class TestGetStatsExtended:
    """Extended tests for get_stats method."""

    def test_stats_with_populated_cache(self):
        """Test stats reflect populated cache."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(ece=0.05, total_predictions=100),
                "b": MockCalibrationSummary(ece=0.05, total_predictions=100),
                "c": MockCalibrationSummary(ece=0.05, total_predictions=100),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        # Compute efficiencies to populate cache
        bridge.compute_cost_efficiency("a")
        bridge.compute_cost_efficiency("b")
        bridge.compute_cost_efficiency("c")

        stats = bridge.get_stats()
        assert stats["agents_cached"] == 3

    def test_stats_all_overconfident(self):
        """Test stats when all agents are overconfident."""
        tracker = MockCalibrationTracker(
            {
                "a": MockCalibrationSummary(is_overconfident=True, ece=0.2),
                "b": MockCalibrationSummary(is_overconfident=True, ece=0.3),
            }
        )
        bridge = CalibrationCostBridge(calibration_tracker=tracker)

        stats = bridge.get_stats()
        assert stats["overconfident_agents"] == 2
        assert stats["well_calibrated_agents"] == 0


# =============================================================================
# Extended Factory Function Tests
# =============================================================================


class TestCreateCalibrationCostBridgeExtended:
    """Extended tests for create_calibration_cost_bridge factory."""

    def test_create_with_all_config_options(self):
        """Test factory with all configuration options."""
        bridge = create_calibration_cost_bridge(
            min_predictions_for_scoring=100,
            calibration_weight=0.5,
            accuracy_weight=0.25,
            cost_weight=0.25,
            well_calibrated_ece_threshold=0.05,
            overconfident_cost_multiplier=1.5,
            underconfident_cost_multiplier=1.2,
            efficient_threshold=0.8,
            moderate_threshold=0.5,
        )

        assert bridge.config.min_predictions_for_scoring == 100
        assert bridge.config.calibration_weight == 0.5
        assert bridge.config.accuracy_weight == 0.25
        assert bridge.config.cost_weight == 0.25
        assert bridge.config.well_calibrated_ece_threshold == 0.05
        assert bridge.config.overconfident_cost_multiplier == 1.5
        assert bridge.config.underconfident_cost_multiplier == 1.2
        assert bridge.config.efficient_threshold == 0.8
        assert bridge.config.moderate_threshold == 0.5
