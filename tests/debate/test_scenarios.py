"""
Tests for the scenario matrix debates module.

Tests cover:
- ScenarioType and OutcomeCategory enums
- Scenario data class and context application
- ScenarioResult and ScenarioComparison data classes
- MatrixResult data class and methods
- ScenarioMatrix builder and generation methods
- ScenarioComparator analysis
- MatrixDebateRunner execution
- Convenience functions for preset scenarios
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.debate.scenarios import (
    MatrixDebateRunner,
    MatrixResult,
    OutcomeCategory,
    Scenario,
    ScenarioComparator,
    ScenarioComparison,
    ScenarioMatrix,
    ScenarioResult,
    ScenarioType,
    create_risk_scenarios,
    create_scale_scenarios,
    create_time_horizon_scenarios,
)


class TestScenarioType:
    """Tests for ScenarioType enum."""

    @pytest.mark.smoke
    def test_scenario_type_values(self):
        """Test ScenarioType enum values."""
        assert ScenarioType.CONSTRAINT.value == "constraint"
        assert ScenarioType.ASSUMPTION.value == "assumption"
        assert ScenarioType.STAKEHOLDER.value == "stakeholder"
        assert ScenarioType.SCALE.value == "scale"
        assert ScenarioType.RISK_TOLERANCE.value == "risk_tolerance"
        assert ScenarioType.TIME_HORIZON.value == "time_horizon"
        assert ScenarioType.TECHNOLOGY.value == "technology"
        assert ScenarioType.REGULATORY.value == "regulatory"
        assert ScenarioType.CUSTOM.value == "custom"

    def test_scenario_type_from_string(self):
        """Test creating ScenarioType from string."""
        assert ScenarioType("constraint") == ScenarioType.CONSTRAINT
        assert ScenarioType("scale") == ScenarioType.SCALE
        assert ScenarioType("custom") == ScenarioType.CUSTOM


class TestOutcomeCategory:
    """Tests for OutcomeCategory enum."""

    @pytest.mark.smoke
    def test_outcome_category_values(self):
        """Test OutcomeCategory enum values."""
        assert OutcomeCategory.CONSISTENT.value == "consistent"
        assert OutcomeCategory.CONDITIONAL.value == "conditional"
        assert OutcomeCategory.DIVERGENT.value == "divergent"
        assert OutcomeCategory.INCONCLUSIVE.value == "inconclusive"

    def test_outcome_category_from_string(self):
        """Test creating OutcomeCategory from string."""
        assert OutcomeCategory("consistent") == OutcomeCategory.CONSISTENT
        assert OutcomeCategory("divergent") == OutcomeCategory.DIVERGENT


class TestScenario:
    """Tests for Scenario data class."""

    def test_scenario_creation(self):
        """Test creating a Scenario."""
        scenario = Scenario(
            id="scn_001",
            name="Small Scale Deployment",
            scenario_type=ScenarioType.SCALE,
            description="Small-scale deployment for 100 users",
        )

        assert scenario.id == "scn_001"
        assert scenario.name == "Small Scale Deployment"
        assert scenario.scenario_type == ScenarioType.SCALE
        assert scenario.description == "Small-scale deployment for 100 users"
        assert scenario.parameters == {}
        assert scenario.constraints == []
        assert scenario.assumptions == []
        assert scenario.context_additions == ""
        assert scenario.context_replacements == {}
        assert scenario.priority == 1
        assert scenario.is_baseline is False
        assert scenario.tags == []

    def test_scenario_with_parameters(self):
        """Test Scenario with parameters."""
        scenario = Scenario(
            id="scn_002",
            name="Medium Scale",
            scenario_type=ScenarioType.SCALE,
            description="Medium scale deployment",
            parameters={"users": 5000, "data_gb": 100, "servers": 3},
        )

        assert scenario.parameters["users"] == 5000
        assert scenario.parameters["data_gb"] == 100
        assert scenario.parameters["servers"] == 3

    def test_scenario_with_constraints_and_assumptions(self):
        """Test Scenario with constraints and assumptions."""
        scenario = Scenario(
            id="scn_003",
            name="Budget Constrained",
            scenario_type=ScenarioType.CONSTRAINT,
            description="Limited budget scenario",
            constraints=["Budget < $50k", "Single server only"],
            assumptions=["Team has Python expertise", "AWS preferred"],
        )

        assert len(scenario.constraints) == 2
        assert "Budget < $50k" in scenario.constraints
        assert len(scenario.assumptions) == 2
        assert "Team has Python expertise" in scenario.assumptions

    def test_scenario_as_baseline(self):
        """Test Scenario marked as baseline."""
        scenario = Scenario(
            id="baseline",
            name="Baseline Scenario",
            scenario_type=ScenarioType.CUSTOM,
            description="The baseline scenario",
            is_baseline=True,
            priority=10,
        )

        assert scenario.is_baseline is True
        assert scenario.priority == 10

    def test_scenario_with_tags(self):
        """Test Scenario with tags."""
        scenario = Scenario(
            id="scn_004",
            name="Tagged Scenario",
            scenario_type=ScenarioType.CUSTOM,
            description="A scenario with tags",
            tags=["production", "high-priority", "enterprise"],
        )

        assert "production" in scenario.tags
        assert "enterprise" in scenario.tags

    def test_scenario_to_dict(self):
        """Test Scenario serialization to dict."""
        scenario = Scenario(
            id="scn_005",
            name="Serialized Scenario",
            scenario_type=ScenarioType.TECHNOLOGY,
            description="Test serialization",
            parameters={"language": "python"},
            constraints=["Must use REST API"],
            assumptions=["Cloud deployment"],
            context_additions="Additional context here",
            context_replacements={"old_text": "new_text"},
            priority=5,
            is_baseline=True,
            tags=["test"],
        )

        data = scenario.to_dict()

        assert data["id"] == "scn_005"
        assert data["name"] == "Serialized Scenario"
        assert data["scenario_type"] == "technology"
        assert data["description"] == "Test serialization"
        assert data["parameters"]["language"] == "python"
        assert data["constraints"] == ["Must use REST API"]
        assert data["assumptions"] == ["Cloud deployment"]
        assert data["context_additions"] == "Additional context here"
        assert data["context_replacements"] == {"old_text": "new_text"}
        assert data["priority"] == 5
        assert data["is_baseline"] is True
        assert data["tags"] == ["test"]

    def test_scenario_from_dict(self):
        """Test Scenario deserialization from dict."""
        data = {
            "id": "scn_006",
            "name": "Deserialized Scenario",
            "scenario_type": "risk_tolerance",
            "description": "Test deserialization",
            "parameters": {"risk_level": "high"},
            "constraints": ["Fast iteration"],
            "assumptions": ["Experienced team"],
            "context_additions": "Risk context",
            "context_replacements": {"safe": "risky"},
            "priority": 3,
            "is_baseline": False,
            "tags": ["risk"],
        }

        scenario = Scenario.from_dict(data)

        assert scenario.id == "scn_006"
        assert scenario.name == "Deserialized Scenario"
        assert scenario.scenario_type == ScenarioType.RISK_TOLERANCE
        assert scenario.parameters["risk_level"] == "high"
        assert scenario.is_baseline is False

    def test_scenario_from_dict_minimal(self):
        """Test Scenario deserialization with minimal data."""
        data = {
            "id": "scn_007",
            "name": "Minimal Scenario",
            "scenario_type": "custom",
            "description": "Minimal test",
        }

        scenario = Scenario.from_dict(data)

        assert scenario.id == "scn_007"
        assert scenario.parameters == {}
        assert scenario.constraints == []
        assert scenario.assumptions == []
        assert scenario.priority == 1
        assert scenario.is_baseline is False

    def test_scenario_roundtrip_serialization(self):
        """Test that to_dict and from_dict are inverse operations."""
        original = Scenario(
            id="roundtrip",
            name="Roundtrip Test",
            scenario_type=ScenarioType.STAKEHOLDER,
            description="Testing roundtrip",
            parameters={"stakeholder": "customer"},
            constraints=["Must be user-friendly"],
            assumptions=["Non-technical users"],
            priority=7,
            is_baseline=True,
            tags=["ux", "customer"],
        )

        restored = Scenario.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.scenario_type == original.scenario_type
        assert restored.parameters == original.parameters
        assert restored.constraints == original.constraints
        assert restored.assumptions == original.assumptions
        assert restored.priority == original.priority
        assert restored.is_baseline == original.is_baseline
        assert restored.tags == original.tags

    def test_apply_to_context_empty(self):
        """Test applying scenario to empty context."""
        scenario = Scenario(
            id="ctx_001",
            name="Empty Context Test",
            scenario_type=ScenarioType.CUSTOM,
            description="Test with empty context",
        )

        result = scenario.apply_to_context("")
        assert result == ""

    def test_apply_to_context_additions(self):
        """Test applying context additions."""
        scenario = Scenario(
            id="ctx_002",
            name="Addition Test",
            scenario_type=ScenarioType.CUSTOM,
            description="Test additions",
            context_additions="This is additional context.",
        )

        result = scenario.apply_to_context("Base context here.")
        assert "Base context here." in result
        assert "This is additional context." in result

    def test_apply_to_context_replacements(self):
        """Test applying context replacements."""
        scenario = Scenario(
            id="ctx_003",
            name="Replacement Test",
            scenario_type=ScenarioType.CUSTOM,
            description="Test replacements",
            context_replacements={"old_value": "new_value", "foo": "bar"},
        )

        result = scenario.apply_to_context("The old_value should be replaced and foo too.")
        assert "new_value" in result
        assert "bar" in result
        assert "old_value" not in result

    def test_apply_to_context_with_constraints(self):
        """Test applying context with constraints."""
        scenario = Scenario(
            id="ctx_004",
            name="Constraint Test",
            scenario_type=ScenarioType.CONSTRAINT,
            description="Test constraints",
            constraints=["Budget limit: $10k", "Timeline: 2 weeks"],
        )

        result = scenario.apply_to_context("Design a system.")
        assert "Constraints:" in result
        assert "- Budget limit: $10k" in result
        assert "- Timeline: 2 weeks" in result

    def test_apply_to_context_with_assumptions(self):
        """Test applying context with assumptions."""
        scenario = Scenario(
            id="ctx_005",
            name="Assumption Test",
            scenario_type=ScenarioType.ASSUMPTION,
            description="Test assumptions",
            assumptions=["Team knows Python", "Cloud-first approach"],
        )

        result = scenario.apply_to_context("Design a system.")
        assert "Assumptions:" in result
        assert "- Team knows Python" in result
        assert "- Cloud-first approach" in result

    def test_apply_to_context_full(self):
        """Test applying context with all modifications."""
        scenario = Scenario(
            id="ctx_006",
            name="Full Context Test",
            scenario_type=ScenarioType.CUSTOM,
            description="Full test",
            context_additions="Extra info for this scenario.",
            context_replacements={"PLACEHOLDER": "actual_value"},
            constraints=["Must be fast"],
            assumptions=["Users are technical"],
        )

        base = "Base context with PLACEHOLDER."
        result = scenario.apply_to_context(base)

        assert "actual_value" in result
        assert "PLACEHOLDER" not in result
        assert "Extra info for this scenario." in result
        assert "Constraints:" in result
        assert "- Must be fast" in result
        assert "Assumptions:" in result
        assert "- Users are technical" in result


class TestScenarioResult:
    """Tests for ScenarioResult data class."""

    def test_result_creation(self):
        """Test creating ScenarioResult."""
        result = ScenarioResult(
            scenario_id="scn_001",
            scenario_name="Test Scenario",
            conclusion="Use microservices architecture",
            confidence=0.85,
            consensus_reached=True,
        )

        assert result.scenario_id == "scn_001"
        assert result.scenario_name == "Test Scenario"
        assert result.conclusion == "Use microservices architecture"
        assert result.confidence == 0.85
        assert result.consensus_reached is True
        assert result.key_claims == []
        assert result.dissenting_views == []
        assert result.duration_seconds == 0.0
        assert result.rounds == 0
        assert result.metadata == {}

    def test_result_with_claims(self):
        """Test ScenarioResult with claims and dissenting views."""
        result = ScenarioResult(
            scenario_id="scn_002",
            scenario_name="Claims Test",
            conclusion="Go monolith first",
            confidence=0.72,
            consensus_reached=False,
            key_claims=["Simpler deployment", "Easier debugging", "Lower initial cost"],
            dissenting_views=["Will hit scaling issues", "Harder to parallelize development"],
        )

        assert len(result.key_claims) == 3
        assert "Simpler deployment" in result.key_claims
        assert len(result.dissenting_views) == 2

    def test_result_with_metadata(self):
        """Test ScenarioResult with metadata."""
        result = ScenarioResult(
            scenario_id="scn_003",
            scenario_name="Metadata Test",
            conclusion="Test result",
            confidence=0.6,
            consensus_reached=True,
            duration_seconds=45.5,
            rounds=3,
            metadata={"agents": ["claude", "gpt4"], "votes": {"agree": 3, "disagree": 1}},
        )

        assert result.duration_seconds == 45.5
        assert result.rounds == 3
        assert result.metadata["agents"] == ["claude", "gpt4"]

    def test_result_to_dict(self):
        """Test ScenarioResult serialization."""
        result = ScenarioResult(
            scenario_id="scn_004",
            scenario_name="Serialization Test",
            conclusion="Test conclusion",
            confidence=0.9,
            consensus_reached=True,
            key_claims=["Claim 1"],
            dissenting_views=["Dissent 1"],
            duration_seconds=30.0,
            rounds=2,
            metadata={"test": True},
        )

        data = result.to_dict()

        assert data["scenario_id"] == "scn_004"
        assert data["conclusion"] == "Test conclusion"
        assert data["confidence"] == 0.9
        assert data["consensus_reached"] is True
        assert data["key_claims"] == ["Claim 1"]
        assert data["duration_seconds"] == 30.0


class TestScenarioComparison:
    """Tests for ScenarioComparison data class."""

    def test_comparison_creation(self):
        """Test creating ScenarioComparison."""
        comparison = ScenarioComparison(
            scenario_a_id="scn_001",
            scenario_b_id="scn_002",
            conclusions_match=True,
            similarity_score=0.85,
        )

        assert comparison.scenario_a_id == "scn_001"
        assert comparison.scenario_b_id == "scn_002"
        assert comparison.conclusions_match is True
        assert comparison.similarity_score == 0.85
        assert comparison.key_differences == []
        assert comparison.shared_claims == []
        assert comparison.unique_to_a == []
        assert comparison.unique_to_b == []

    def test_comparison_with_differences(self):
        """Test ScenarioComparison with differences."""
        comparison = ScenarioComparison(
            scenario_a_id="scn_001",
            scenario_b_id="scn_002",
            conclusions_match=False,
            similarity_score=0.35,
            key_differences=["Different conclusions reached", "Confidence differs"],
            shared_claims=["Both agree on security"],
            unique_to_a=["Performance priority"],
            unique_to_b=["Cost priority"],
        )

        assert not comparison.conclusions_match
        assert len(comparison.key_differences) == 2
        assert "Both agree on security" in comparison.shared_claims
        assert "Performance priority" in comparison.unique_to_a
        assert "Cost priority" in comparison.unique_to_b


class TestMatrixResult:
    """Tests for MatrixResult data class."""

    def test_matrix_result_creation(self):
        """Test creating MatrixResult."""
        result = MatrixResult(
            matrix_id="matrix_001",
            task="Design a caching system",
            created_at=datetime(2024, 1, 15, 10, 0, 0),
        )

        assert result.matrix_id == "matrix_001"
        assert result.task == "Design a caching system"
        assert result.created_at == datetime(2024, 1, 15, 10, 0, 0)
        assert result.completed_at is None
        assert result.scenarios == []
        assert result.results == []
        assert result.outcome_category == OutcomeCategory.INCONCLUSIVE
        assert result.baseline_scenario_id is None
        assert result.universal_conclusions == []
        assert result.conditional_conclusions == {}
        assert result.summary == ""
        assert result.recommendations == []

    def test_matrix_result_with_scenarios(self):
        """Test MatrixResult with scenarios."""
        scenarios = [
            Scenario("s1", "Small", ScenarioType.SCALE, "Small scale"),
            Scenario("s2", "Large", ScenarioType.SCALE, "Large scale"),
        ]

        result = MatrixResult(
            matrix_id="matrix_002",
            task="Test task",
            created_at=datetime.now(),
            scenarios=scenarios,
        )

        assert len(result.scenarios) == 2
        assert result.scenarios[0].id == "s1"

    def test_matrix_result_get_result(self):
        """Test getting result by scenario ID."""
        results = [
            ScenarioResult("s1", "Small", "Use Redis", 0.9, True),
            ScenarioResult("s2", "Large", "Use Redis Cluster", 0.85, True),
        ]

        matrix = MatrixResult(
            matrix_id="matrix_003",
            task="Caching decision",
            created_at=datetime.now(),
            results=results,
        )

        found = matrix.get_result("s1")
        assert found is not None
        assert found.conclusion == "Use Redis"

        found2 = matrix.get_result("s2")
        assert found2 is not None
        assert found2.conclusion == "Use Redis Cluster"

    def test_matrix_result_get_result_not_found(self):
        """Test getting result for non-existent scenario."""
        matrix = MatrixResult(
            matrix_id="matrix_004",
            task="Test",
            created_at=datetime.now(),
            results=[ScenarioResult("s1", "Test", "Conclusion", 0.5, True)],
        )

        found = matrix.get_result("nonexistent")
        assert found is None

    def test_matrix_result_to_dict(self):
        """Test MatrixResult serialization."""
        created = datetime(2024, 1, 15, 10, 0, 0)
        completed = datetime(2024, 1, 15, 10, 30, 0)

        result = MatrixResult(
            matrix_id="matrix_005",
            task="Serialization test",
            created_at=created,
            completed_at=completed,
            scenarios=[Scenario("s1", "Test", ScenarioType.CUSTOM, "Desc")],
            results=[ScenarioResult("s1", "Test", "Result", 0.8, True)],
            outcome_category=OutcomeCategory.CONSISTENT,
            baseline_scenario_id="s1",
            universal_conclusions=["All agree on X"],
            conditional_conclusions={"scale=small": ["Use simple solution"]},
            summary="Test summary",
            recommendations=["Recommend A"],
        )

        data = result.to_dict()

        assert data["matrix_id"] == "matrix_005"
        assert data["task"] == "Serialization test"
        assert data["created_at"] == "2024-01-15T10:00:00"
        assert data["completed_at"] == "2024-01-15T10:30:00"
        assert len(data["scenarios"]) == 1
        assert len(data["results"]) == 1
        assert data["outcome_category"] == "consistent"
        assert data["baseline_scenario_id"] == "s1"
        assert data["universal_conclusions"] == ["All agree on X"]
        assert data["summary"] == "Test summary"

    def test_matrix_result_to_dict_no_completed_at(self):
        """Test MatrixResult serialization without completed_at."""
        result = MatrixResult(
            matrix_id="matrix_006",
            task="Incomplete test",
            created_at=datetime.now(),
        )

        data = result.to_dict()
        assert data["completed_at"] is None


class TestScenarioMatrix:
    """Tests for ScenarioMatrix class."""

    def test_matrix_creation(self):
        """Test creating ScenarioMatrix."""
        matrix = ScenarioMatrix(name="Test Matrix")

        assert matrix.name == "Test Matrix"
        assert matrix.scenarios == []
        assert matrix.dimensions == {}

    def test_matrix_default_name(self):
        """Test ScenarioMatrix default name."""
        matrix = ScenarioMatrix()
        assert matrix.name == "Scenario Matrix"

    def test_add_scenario(self):
        """Test adding scenarios to matrix."""
        matrix = ScenarioMatrix()

        scenario = Scenario("s1", "Test", ScenarioType.CUSTOM, "Description")
        result = matrix.add_scenario(scenario)

        assert result is matrix  # Returns self for chaining
        assert len(matrix.scenarios) == 1
        assert matrix.scenarios[0].id == "s1"

    def test_add_multiple_scenarios(self):
        """Test adding multiple scenarios with chaining."""
        matrix = ScenarioMatrix()

        matrix.add_scenario(Scenario("s1", "One", ScenarioType.CUSTOM, "First")).add_scenario(
            Scenario("s2", "Two", ScenarioType.CUSTOM, "Second")
        ).add_scenario(Scenario("s3", "Three", ScenarioType.CUSTOM, "Third"))

        assert len(matrix.scenarios) == 3

    def test_add_dimension(self):
        """Test adding dimensions to matrix."""
        matrix = ScenarioMatrix()

        result = matrix.add_dimension("scale", ["small", "medium", "large"])

        assert result is matrix
        assert "scale" in matrix.dimensions
        assert matrix.dimensions["scale"] == ["small", "medium", "large"]

    def test_add_multiple_dimensions(self):
        """Test adding multiple dimensions."""
        matrix = ScenarioMatrix()

        matrix.add_dimension("scale", ["small", "large"]).add_dimension(
            "risk", ["low", "high"]
        ).add_dimension("time", ["short", "long"])

        assert len(matrix.dimensions) == 3

    def test_generate_grid_empty(self):
        """Test grid generation with no dimensions."""
        matrix = ScenarioMatrix()
        result = matrix.generate_grid()

        assert result is matrix
        assert len(matrix.scenarios) == 0

    def test_generate_grid_single_dimension(self):
        """Test grid generation with single dimension."""
        matrix = ScenarioMatrix()
        matrix.add_dimension("scale", ["small", "medium", "large"])
        matrix.generate_grid()

        assert len(matrix.scenarios) == 3

    def test_generate_grid_multiple_dimensions(self):
        """Test grid generation with multiple dimensions (cartesian product)."""
        matrix = ScenarioMatrix()
        matrix.add_dimension("scale", ["small", "large"])  # 2 values
        matrix.add_dimension("risk", ["low", "high"])  # 2 values
        matrix.generate_grid()

        # 2 x 2 = 4 scenarios
        assert len(matrix.scenarios) == 4

        # Check all combinations exist
        params = [s.parameters for s in matrix.scenarios]
        assert {"scale": "small", "risk": "low"} in params
        assert {"scale": "small", "risk": "high"} in params
        assert {"scale": "large", "risk": "low"} in params
        assert {"scale": "large", "risk": "high"} in params

    def test_generate_grid_three_dimensions(self):
        """Test grid generation with three dimensions."""
        matrix = ScenarioMatrix()
        matrix.add_dimension("a", [1, 2])
        matrix.add_dimension("b", ["x", "y"])
        matrix.add_dimension("c", [True, False])
        matrix.generate_grid()

        # 2 x 2 x 2 = 8 scenarios
        assert len(matrix.scenarios) == 8

    def test_generate_grid_with_scenario_type(self):
        """Test grid generation with custom scenario type."""
        matrix = ScenarioMatrix()
        matrix.add_dimension("risk", ["low", "high"])
        matrix.generate_grid(scenario_type=ScenarioType.RISK_TOLERANCE)

        assert all(s.scenario_type == ScenarioType.RISK_TOLERANCE for s in matrix.scenarios)

    def test_generate_grid_name_template(self):
        """Test grid generation with custom name template."""
        matrix = ScenarioMatrix()
        matrix.add_dimension("scale", ["small"])
        matrix.add_dimension("risk", ["low"])
        matrix.generate_grid(name_template="Scale: {scale}, Risk: {risk}")

        assert matrix.scenarios[0].name == "Scale: small, Risk: low"

    def test_generate_sensitivity_baseline(self):
        """Test sensitivity analysis includes baseline."""
        matrix = ScenarioMatrix()
        baseline = {"param_a": 10, "param_b": "default"}
        vary = {"param_a": [5, 15, 20]}

        matrix.generate_sensitivity(baseline, vary)

        # 1 baseline + 3 variations (5, 15, 20 - excluding 10)
        assert len(matrix.scenarios) == 4

        baseline_scenario = next(s for s in matrix.scenarios if s.is_baseline)
        assert baseline_scenario.name == "Baseline"
        assert baseline_scenario.parameters == {"param_a": 10, "param_b": "default"}

    def test_generate_sensitivity_skips_baseline_value(self):
        """Test sensitivity analysis skips baseline value in variations."""
        matrix = ScenarioMatrix()
        baseline = {"param_a": 10}
        vary = {"param_a": [5, 10, 15]}  # 10 is baseline value

        matrix.generate_sensitivity(baseline, vary)

        # 1 baseline + 2 variations (5 and 15, not 10)
        assert len(matrix.scenarios) == 3

    def test_generate_sensitivity_multiple_params(self):
        """Test sensitivity analysis with multiple varying params."""
        matrix = ScenarioMatrix()
        baseline = {"a": 1, "b": 10, "c": 100}
        vary = {"a": [2, 3], "b": [20, 30]}  # 2 variations for a, 2 for b

        matrix.generate_sensitivity(baseline, vary)

        # 1 baseline + 2 for a + 2 for b = 5
        assert len(matrix.scenarios) == 5

    def test_get_scenarios_sorted_by_priority(self):
        """Test scenarios are returned sorted by priority (descending)."""
        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("low", "Low Priority", ScenarioType.CUSTOM, "Low", priority=1))
        matrix.add_scenario(
            Scenario("high", "High Priority", ScenarioType.CUSTOM, "High", priority=10)
        )
        matrix.add_scenario(Scenario("mid", "Mid Priority", ScenarioType.CUSTOM, "Mid", priority=5))

        sorted_scenarios = matrix.get_scenarios()

        assert sorted_scenarios[0].priority == 10
        assert sorted_scenarios[1].priority == 5
        assert sorted_scenarios[2].priority == 1

    def test_from_presets_scale(self):
        """Test creating matrix from 'scale' preset."""
        matrix = ScenarioMatrix.from_presets("scale")

        assert matrix.name == "scale"
        assert len(matrix.scenarios) == 4  # small, medium, large, enterprise

    def test_from_presets_time_horizon(self):
        """Test creating matrix from 'time_horizon' preset."""
        matrix = ScenarioMatrix.from_presets("time_horizon")

        assert len(matrix.scenarios) == 3  # short, medium, long term

    def test_from_presets_risk(self):
        """Test creating matrix from 'risk' preset."""
        matrix = ScenarioMatrix.from_presets("risk")

        assert len(matrix.scenarios) == 3  # conservative, moderate, aggressive

    def test_from_presets_stakeholder(self):
        """Test creating matrix from 'stakeholder' preset."""
        matrix = ScenarioMatrix.from_presets("stakeholder")

        assert len(matrix.scenarios) == 4  # developer, manager, executive, customer

    def test_from_presets_tech_stack(self):
        """Test creating matrix from 'tech_stack' preset."""
        matrix = ScenarioMatrix.from_presets("tech_stack")

        # 4 languages x 3 infra = 12
        assert len(matrix.scenarios) == 12

    def test_from_presets_comprehensive(self):
        """Test creating matrix from 'comprehensive' preset."""
        matrix = ScenarioMatrix.from_presets("comprehensive")

        # 2 scale x 2 risk x 2 time = 8
        assert len(matrix.scenarios) == 8

    def test_from_presets_unknown(self):
        """Test creating matrix from unknown preset returns empty."""
        matrix = ScenarioMatrix.from_presets("unknown_preset")

        assert len(matrix.scenarios) == 0


class TestScenarioComparator:
    """Tests for ScenarioComparator class."""

    def test_comparator_creation(self):
        """Test creating ScenarioComparator."""
        comparator = ScenarioComparator()
        assert comparator is not None

    def test_compare_pair_matching_conclusions(self):
        """Test comparing results with matching conclusions."""
        comparator = ScenarioComparator()

        result_a = ScenarioResult(
            "s1",
            "Scenario A",
            "Use Redis for caching the data",
            0.9,
            True,
            key_claims=["Fast access", "Simple API", "Widely used"],
        )
        result_b = ScenarioResult(
            "s2",
            "Scenario B",
            "Use Redis for caching the data",
            0.85,
            True,
            key_claims=["Fast access", "Simple API", "Good documentation"],
        )

        comparison = comparator.compare_pair(result_a, result_b)

        assert comparison.scenario_a_id == "s1"
        assert comparison.scenario_b_id == "s2"
        assert comparison.conclusions_match is True
        # 2 shared claims out of 4 total unique claims = 0.5
        assert comparison.similarity_score >= 0.5
        assert "Fast access" in comparison.shared_claims
        assert "Simple API" in comparison.shared_claims

    def test_compare_pair_different_conclusions(self):
        """Test comparing results with different conclusions."""
        comparator = ScenarioComparator()

        result_a = ScenarioResult(
            "s1",
            "Scenario A",
            "Use Redis for caching",
            0.9,
            True,
            key_claims=["Memory-based", "Fast"],
        )
        result_b = ScenarioResult(
            "s2",
            "Scenario B",
            "Use PostgreSQL with materialized views",
            0.85,
            True,
            key_claims=["ACID compliant", "Persistent"],
        )

        comparison = comparator.compare_pair(result_a, result_b)

        assert comparison.conclusions_match is False
        assert comparison.similarity_score == 0.0  # No shared claims
        assert "Different conclusions reached" in comparison.key_differences
        assert "Memory-based" in comparison.unique_to_a
        assert "ACID compliant" in comparison.unique_to_b

    def test_compare_pair_confidence_difference(self):
        """Test comparison notes large confidence differences."""
        comparator = ScenarioComparator()

        result_a = ScenarioResult("s1", "A", "Same conclusion here", 0.95, True)
        result_b = ScenarioResult("s2", "B", "Same conclusion here", 0.60, True)

        comparison = comparator.compare_pair(result_a, result_b)

        assert any("Confidence differs" in d for d in comparison.key_differences)

    def test_compare_pair_no_claims(self):
        """Test comparison with no claims."""
        comparator = ScenarioComparator()

        result_a = ScenarioResult("s1", "A", "Same conclusion", 0.8, True, key_claims=[])
        result_b = ScenarioResult("s2", "B", "Same conclusion", 0.8, True, key_claims=[])

        comparison = comparator.compare_pair(result_a, result_b)

        # With matching conclusions and no claims, similarity is 1.0
        assert comparison.conclusions_match is True
        assert comparison.similarity_score == 1.0

    def test_compare_pair_no_claims_different_conclusions(self):
        """Test comparison with no claims and different conclusions."""
        comparator = ScenarioComparator()

        result_a = ScenarioResult("s1", "A", "Totally different", 0.8, True, key_claims=[])
        result_b = ScenarioResult("s2", "B", "Completely unique", 0.8, True, key_claims=[])

        comparison = comparator.compare_pair(result_a, result_b)

        assert comparison.conclusions_match is False
        assert comparison.similarity_score == 0.0

    def test_conclusions_similar_high_overlap(self):
        """Test conclusions similarity with high word overlap."""
        comparator = ScenarioComparator()

        result = comparator._conclusions_similar(
            "Use Redis for caching and session storage", "Use Redis for caching and data storage"
        )

        assert result is True

    def test_conclusions_similar_low_overlap(self):
        """Test conclusions similarity with low word overlap."""
        comparator = ScenarioComparator()

        result = comparator._conclusions_similar(
            "Use Redis for caching", "Deploy PostgreSQL with read replicas"
        )

        assert result is False

    def test_conclusions_similar_empty_strings(self):
        """Test conclusions similarity with empty strings."""
        comparator = ScenarioComparator()

        assert comparator._conclusions_similar("", "") is False
        assert comparator._conclusions_similar("words here", "") is False
        assert comparator._conclusions_similar("", "words here") is False

    def test_analyze_matrix_no_results(self):
        """Test analyzing matrix with no results."""
        comparator = ScenarioComparator()

        matrix_result = MatrixResult(
            matrix_id="test",
            task="Test task",
            created_at=datetime.now(),
        )

        analysis = comparator.analyze_matrix(matrix_result)

        assert analysis["error"] == "No results to analyze"
        assert analysis["outcome_category"] == "inconclusive"
        assert analysis["total_scenarios"] == 0
        assert analysis["universal_conclusions"] == []

    def test_analyze_matrix_consistent_outcomes(self):
        """Test analyzing matrix with consistent outcomes."""
        comparator = ScenarioComparator()

        results = [
            ScenarioResult(
                "s1", "Small", "Use Redis for caching", 0.9, True, key_claims=["Fast", "Simple"]
            ),
            ScenarioResult(
                "s2", "Large", "Use Redis for caching", 0.85, True, key_claims=["Fast", "Simple"]
            ),
        ]

        matrix_result = MatrixResult(
            matrix_id="test",
            task="Caching decision",
            created_at=datetime.now(),
            scenarios=[
                Scenario("s1", "Small", ScenarioType.SCALE, "Small scale"),
                Scenario("s2", "Large", ScenarioType.SCALE, "Large scale"),
            ],
            results=results,
        )

        analysis = comparator.analyze_matrix(matrix_result)

        assert analysis["outcome_category"] == "consistent"
        assert analysis["total_scenarios"] == 2
        assert analysis["avg_similarity"] == 1.0
        assert "Fast" in analysis["universal_conclusions"]
        assert "Simple" in analysis["universal_conclusions"]

    def test_analyze_matrix_divergent_outcomes(self):
        """Test analyzing matrix with divergent outcomes."""
        comparator = ScenarioComparator()

        results = [
            ScenarioResult(
                "s1", "Small", "Use SQLite", 0.9, True, key_claims=["Simple", "Lightweight"]
            ),
            ScenarioResult(
                "s2",
                "Large",
                "Use distributed PostgreSQL cluster",
                0.85,
                True,
                key_claims=["Scalable", "ACID"],
            ),
        ]

        matrix_result = MatrixResult(
            matrix_id="test",
            task="Database decision",
            created_at=datetime.now(),
            scenarios=[
                Scenario("s1", "Small", ScenarioType.SCALE, "Small", parameters={"scale": "small"}),
                Scenario("s2", "Large", ScenarioType.SCALE, "Large", parameters={"scale": "large"}),
            ],
            results=results,
        )

        analysis = comparator.analyze_matrix(matrix_result)

        assert analysis["outcome_category"] == "divergent"
        assert analysis["avg_similarity"] == 0.0
        assert len(analysis["universal_conclusions"]) == 0

    def test_analyze_matrix_conditional_patterns(self):
        """Test that analysis captures conditional patterns."""
        comparator = ScenarioComparator()

        results = [
            ScenarioResult(
                "s1",
                "Small Low Risk",
                "Use simple approach",
                0.9,
                True,
                key_claims=["Simple is better"],
            ),
            ScenarioResult(
                "s2",
                "Large High Risk",
                "Use enterprise approach",
                0.85,
                True,
                key_claims=["Enterprise grade"],
            ),
        ]

        matrix_result = MatrixResult(
            matrix_id="test",
            task="Architecture decision",
            created_at=datetime.now(),
            scenarios=[
                Scenario(
                    "s1",
                    "Small Low Risk",
                    ScenarioType.SCALE,
                    "Small",
                    parameters={"scale": "small", "risk": "low"},
                ),
                Scenario(
                    "s2",
                    "Large High Risk",
                    ScenarioType.SCALE,
                    "Large",
                    parameters={"scale": "large", "risk": "high"},
                ),
            ],
            results=results,
        )

        analysis = comparator.analyze_matrix(matrix_result)

        assert "conditional_patterns" in analysis
        assert "scale=small" in analysis["conditional_patterns"]
        assert "scale=large" in analysis["conditional_patterns"]

    def test_generate_summary(self):
        """Test generating human-readable summary."""
        comparator = ScenarioComparator()

        results = [
            ScenarioResult(
                "s1",
                "Conservative",
                "Use proven technology",
                0.9,
                True,
                key_claims=["Stable", "Tested"],
            ),
            ScenarioResult(
                "s2",
                "Aggressive",
                "Use cutting edge tech",
                0.7,
                False,
                key_claims=["Innovative", "Fast"],
            ),
        ]

        matrix_result = MatrixResult(
            matrix_id="test",
            task="Tech stack decision",
            created_at=datetime.now(),
            scenarios=[
                Scenario(
                    "s1",
                    "Conservative",
                    ScenarioType.RISK_TOLERANCE,
                    "Conservative approach",
                    parameters={"risk": "low"},
                ),
                Scenario(
                    "s2",
                    "Aggressive",
                    ScenarioType.RISK_TOLERANCE,
                    "Aggressive approach",
                    parameters={"risk": "high"},
                ),
            ],
            results=results,
        )

        summary = comparator.generate_summary(matrix_result)

        assert "# Scenario Matrix Analysis" in summary
        assert "Tech stack decision" in summary
        assert "Scenarios Analyzed**: 2" in summary
        assert "Conservative" in summary
        assert "Aggressive" in summary
        assert "Confidence:" in summary


class TestMatrixDebateRunner:
    """Tests for MatrixDebateRunner class."""

    def test_runner_creation(self):
        """Test creating MatrixDebateRunner."""
        mock_func = AsyncMock()
        runner = MatrixDebateRunner(mock_func, max_parallel=5)

        assert runner.debate_func is mock_func
        assert runner.max_parallel == 5
        assert runner.comparator is not None

    def test_runner_default_max_parallel(self):
        """Test default max_parallel value."""
        runner = MatrixDebateRunner(AsyncMock())
        assert runner.max_parallel == 3

    @pytest.mark.asyncio
    async def test_run_matrix_sequential(self):
        """Test running matrix sequentially (max_parallel=1)."""
        mock_result = MagicMock()
        mock_result.final_answer = "Use Redis"
        mock_result.confidence = 0.85
        mock_result.consensus_reached = True
        mock_result.key_claims = ["Fast"]
        mock_result.dissenting_views = []
        mock_result.rounds = 3

        mock_func = AsyncMock(return_value=mock_result)
        runner = MatrixDebateRunner(mock_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "Test 1", ScenarioType.CUSTOM, "First"))
        matrix.add_scenario(Scenario("s2", "Test 2", ScenarioType.CUSTOM, "Second"))

        result = await runner.run_matrix("Test task", matrix)

        assert len(result.results) == 2
        assert mock_func.call_count == 2
        assert result.completed_at is not None
        assert result.matrix_id is not None

    @pytest.mark.asyncio
    async def test_run_matrix_parallel(self):
        """Test running matrix in parallel batches."""
        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.confidence = 0.8
        mock_result.consensus_reached = True
        mock_result.key_claims = []
        mock_result.dissenting_views = []
        mock_result.rounds = 2

        mock_func = AsyncMock(return_value=mock_result)
        runner = MatrixDebateRunner(mock_func, max_parallel=2)

        matrix = ScenarioMatrix()
        for i in range(5):
            matrix.add_scenario(Scenario(f"s{i}", f"Test {i}", ScenarioType.CUSTOM, f"Desc {i}"))

        result = await runner.run_matrix("Parallel test", matrix)

        assert len(result.results) == 5
        assert mock_func.call_count == 5

    @pytest.mark.asyncio
    async def test_run_matrix_with_baseline(self):
        """Test matrix identifies baseline scenario."""
        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.confidence = 0.8
        mock_result.consensus_reached = True
        mock_result.key_claims = []
        mock_result.dissenting_views = []
        mock_result.rounds = 1

        mock_func = AsyncMock(return_value=mock_result)
        runner = MatrixDebateRunner(mock_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "Regular", ScenarioType.CUSTOM, "Regular scenario"))
        matrix.add_scenario(
            Scenario("baseline", "Baseline", ScenarioType.CUSTOM, "Base", is_baseline=True)
        )

        result = await runner.run_matrix("Baseline test", matrix)

        assert result.baseline_scenario_id == "baseline"

    @pytest.mark.asyncio
    async def test_run_matrix_with_callback(self):
        """Test callback is called for each completed scenario."""
        mock_result = MagicMock()
        mock_result.final_answer = "Answer"
        mock_result.confidence = 0.8
        mock_result.consensus_reached = True
        mock_result.key_claims = []
        mock_result.dissenting_views = []
        mock_result.rounds = 1

        mock_func = AsyncMock(return_value=mock_result)
        runner = MatrixDebateRunner(mock_func, max_parallel=1)

        callback_results = []

        def on_complete(result: ScenarioResult):
            callback_results.append(result)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "First", ScenarioType.CUSTOM, "First"))
        matrix.add_scenario(Scenario("s2", "Second", ScenarioType.CUSTOM, "Second"))

        await runner.run_matrix("Callback test", matrix, on_scenario_complete=on_complete)

        assert len(callback_results) == 2

    @pytest.mark.asyncio
    async def test_run_matrix_applies_context(self):
        """Test that scenario context is applied to debates."""
        captured_tasks = []
        captured_contexts = []

        async def capture_func(task, context):
            captured_tasks.append(task)
            captured_contexts.append(context)
            mock_result = MagicMock()
            mock_result.final_answer = "Answer"
            mock_result.confidence = 0.8
            mock_result.consensus_reached = True
            mock_result.key_claims = []
            mock_result.dissenting_views = []
            mock_result.rounds = 1
            return mock_result

        runner = MatrixDebateRunner(capture_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(
            Scenario(
                "s1",
                "Constrained",
                ScenarioType.CONSTRAINT,
                "Limited resources",
                constraints=["Budget: $10k"],
                context_additions="Extra info here",
            )
        )

        await runner.run_matrix("Test task", matrix, base_context="Base context")

        assert len(captured_tasks) == 1
        assert "[Scenario: Constrained]" in captured_tasks[0]
        assert "Limited resources" in captured_tasks[0]
        assert "Constraints:" in captured_contexts[0]
        assert "Budget: $10k" in captured_contexts[0]
        assert "Extra info here" in captured_contexts[0]

    @pytest.mark.asyncio
    async def test_run_scenario_debate_timeout(self):
        """Test handling timeout in scenario debate."""

        async def timeout_func(task, context):
            raise asyncio.TimeoutError("Debate timed out")

        runner = MatrixDebateRunner(timeout_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "Timeout Test", ScenarioType.CUSTOM, "Will timeout"))

        result = await runner.run_matrix("Timeout test", matrix)

        assert len(result.results) == 1
        assert result.results[0].confidence == 0.0
        assert result.results[0].consensus_reached is False
        assert "timed out" in result.results[0].conclusion
        assert result.results[0].metadata.get("error_type") == "timeout"

    @pytest.mark.asyncio
    async def test_run_scenario_debate_cancelled(self):
        """Test handling cancellation in scenario debate."""

        async def cancel_func(task, context):
            raise asyncio.CancelledError()

        runner = MatrixDebateRunner(cancel_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "Cancel Test", ScenarioType.CUSTOM, "Will cancel"))

        result = await runner.run_matrix("Cancel test", matrix)

        assert len(result.results) == 1
        assert result.results[0].consensus_reached is False
        assert result.results[0].metadata.get("error_type") == "timeout"

    @pytest.mark.asyncio
    async def test_run_scenario_debate_value_error(self):
        """Test handling ValueError in scenario debate."""

        async def error_func(task, context):
            raise ValueError("Invalid input")

        runner = MatrixDebateRunner(error_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "Error Test", ScenarioType.CUSTOM, "Will error"))

        result = await runner.run_matrix("Error test", matrix)

        assert len(result.results) == 1
        assert "data error" in result.results[0].conclusion
        assert result.results[0].metadata.get("error_type") == "data"

    @pytest.mark.asyncio
    async def test_run_scenario_debate_unexpected_error(self):
        """Test handling unexpected errors in scenario debate."""

        async def unexpected_error(task, context):
            raise RuntimeError("Unexpected failure")

        runner = MatrixDebateRunner(unexpected_error, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "Unexpected", ScenarioType.CUSTOM, "Unexpected error"))

        result = await runner.run_matrix("Unexpected test", matrix)

        assert len(result.results) == 1
        assert "unexpected error" in result.results[0].conclusion
        assert result.results[0].metadata.get("error_type") == "unexpected"

    @pytest.mark.asyncio
    async def test_run_matrix_parallel_with_exception(self):
        """Test parallel execution handles exceptions gracefully."""
        call_count = 0

        async def mixed_func(task, context):
            nonlocal call_count
            call_count += 1
            if "fail" in context.lower():
                raise RuntimeError("Deliberate failure")
            mock_result = MagicMock()
            mock_result.final_answer = "Success"
            mock_result.confidence = 0.9
            mock_result.consensus_reached = True
            mock_result.key_claims = []
            mock_result.dissenting_views = []
            mock_result.rounds = 1
            return mock_result

        runner = MatrixDebateRunner(mixed_func, max_parallel=3)

        matrix = ScenarioMatrix()
        matrix.add_scenario(
            Scenario(
                "s1", "Good 1", ScenarioType.CUSTOM, "Will succeed", context_additions="success"
            )
        )
        matrix.add_scenario(
            Scenario("s2", "Bad", ScenarioType.CUSTOM, "Will fail", context_additions="fail")
        )
        matrix.add_scenario(
            Scenario(
                "s3", "Good 2", ScenarioType.CUSTOM, "Will succeed", context_additions="success"
            )
        )

        result = await runner.run_matrix("Mixed test", matrix)

        # All scenarios get results - failed ones get error results
        # The _run_scenario_debate method catches exceptions and returns error ScenarioResults
        assert len(result.results) == 3

        # Check successful scenarios
        successful = [r for r in result.results if r.confidence > 0]
        assert len(successful) == 2

        # Check failed scenario has error result
        failed = [r for r in result.results if r.confidence == 0]
        assert len(failed) == 1
        assert "error" in failed[0].conclusion.lower()
        assert failed[0].metadata.get("error_type") == "unexpected"

    @pytest.mark.asyncio
    async def test_run_matrix_updates_analysis(self):
        """Test that matrix result includes analysis."""
        mock_result = MagicMock()
        mock_result.final_answer = "Same answer for all"
        mock_result.confidence = 0.9
        mock_result.consensus_reached = True
        mock_result.key_claims = ["Universal claim"]
        mock_result.dissenting_views = []
        mock_result.rounds = 2

        mock_func = AsyncMock(return_value=mock_result)
        runner = MatrixDebateRunner(mock_func, max_parallel=1)

        matrix = ScenarioMatrix()
        matrix.add_scenario(Scenario("s1", "First", ScenarioType.CUSTOM, "First"))
        matrix.add_scenario(Scenario("s2", "Second", ScenarioType.CUSTOM, "Second"))

        result = await runner.run_matrix("Analysis test", matrix)

        assert result.outcome_category == OutcomeCategory.CONSISTENT
        assert "Universal claim" in result.universal_conclusions
        assert len(result.summary) > 0


class TestConvenienceFunctions:
    """Tests for convenience scenario creation functions."""

    def test_create_scale_scenarios(self):
        """Test creating scale scenarios."""
        scenarios = create_scale_scenarios()

        assert len(scenarios) == 3

        ids = [s.id for s in scenarios]
        assert "small" in ids
        assert "medium" in ids
        assert "large" in ids

        for s in scenarios:
            assert s.scenario_type == ScenarioType.SCALE

        small = next(s for s in scenarios if s.id == "small")
        assert small.parameters["users"] == 100
        assert "Limited budget" in small.constraints

        large = next(s for s in scenarios if s.id == "large")
        assert large.parameters["users"] == 100000
        assert "Enterprise requirements" in large.constraints

    def test_create_risk_scenarios(self):
        """Test creating risk scenarios."""
        scenarios = create_risk_scenarios()

        assert len(scenarios) == 3

        ids = [s.id for s in scenarios]
        assert "conservative" in ids
        assert "moderate" in ids
        assert "aggressive" in ids

        for s in scenarios:
            assert s.scenario_type == ScenarioType.RISK_TOLERANCE

        moderate = next(s for s in scenarios if s.id == "moderate")
        assert moderate.is_baseline is True

        conservative = next(s for s in scenarios if s.id == "conservative")
        assert "Prefer proven solutions" in conservative.assumptions

        aggressive = next(s for s in scenarios if s.id == "aggressive")
        assert "Prioritize innovation" in aggressive.assumptions

    def test_create_time_horizon_scenarios(self):
        """Test creating time horizon scenarios."""
        scenarios = create_time_horizon_scenarios()

        assert len(scenarios) == 3

        ids = [s.id for s in scenarios]
        assert "short_term" in ids
        assert "medium_term" in ids
        assert "long_term" in ids

        for s in scenarios:
            assert s.scenario_type == ScenarioType.TIME_HORIZON

        short = next(s for s in scenarios if s.id == "short_term")
        assert short.parameters["horizon_months"] == 6
        assert "Quick implementation" in short.constraints

        medium = next(s for s in scenarios if s.id == "medium_term")
        assert medium.is_baseline is True
        assert medium.parameters["horizon_months"] == 18

        long_term = next(s for s in scenarios if s.id == "long_term")
        assert long_term.parameters["horizon_months"] == 48
        assert "Allow architectural changes" in long_term.constraints


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_scenario_empty_parameters(self):
        """Test scenario with empty parameters."""
        scenario = Scenario(
            id="empty",
            name="Empty Params",
            scenario_type=ScenarioType.CUSTOM,
            description="Empty parameters",
            parameters={},
        )

        data = scenario.to_dict()
        restored = Scenario.from_dict(data)

        assert restored.parameters == {}

    def test_scenario_apply_context_no_modifications(self):
        """Test applying context with no modifications."""
        scenario = Scenario(
            id="plain",
            name="Plain",
            scenario_type=ScenarioType.CUSTOM,
            description="No mods",
        )

        result = scenario.apply_to_context("Original context")
        assert result == "Original context"

    def test_matrix_result_empty_scenarios(self):
        """Test matrix result with empty scenarios list."""
        result = MatrixResult(
            matrix_id="empty",
            task="Empty test",
            created_at=datetime.now(),
        )

        assert result.get_result("any") is None

    def test_comparator_single_result(self):
        """Test analyzing matrix with single result."""
        comparator = ScenarioComparator()

        matrix_result = MatrixResult(
            matrix_id="single",
            task="Single scenario",
            created_at=datetime.now(),
            results=[
                ScenarioResult("s1", "Only One", "The answer", 0.9, True, key_claims=["Claim"])
            ],
        )

        analysis = comparator.analyze_matrix(matrix_result)

        # With single result, no comparisons but still valid analysis
        assert analysis["total_scenarios"] == 1
        assert analysis["comparisons"] == []
        assert "Claim" in analysis["universal_conclusions"]

    def test_scenario_large_parameters(self):
        """Test scenario with many parameters."""
        params = {f"param_{i}": i * 10 for i in range(100)}

        scenario = Scenario(
            id="large",
            name="Large Params",
            scenario_type=ScenarioType.CUSTOM,
            description="Many parameters",
            parameters=params,
        )

        assert len(scenario.parameters) == 100
        assert scenario.parameters["param_50"] == 500

    def test_matrix_generate_grid_single_value_dimension(self):
        """Test grid generation with single-value dimension."""
        matrix = ScenarioMatrix()
        matrix.add_dimension("only_one", ["value"])
        matrix.generate_grid()

        assert len(matrix.scenarios) == 1
        assert matrix.scenarios[0].parameters["only_one"] == "value"

    def test_scenario_unicode_content(self):
        """Test scenario with unicode content."""
        scenario = Scenario(
            id="unicode",
            name="Unicode Test 日本語",
            scenario_type=ScenarioType.CUSTOM,
            description="Testing unicode: 测试中文 한국어",
            constraints=["Constraint with emoji: ✓"],
            context_additions="Additional context: αβγ",
        )

        data = scenario.to_dict()
        restored = Scenario.from_dict(data)

        assert restored.name == "Unicode Test 日本語"
        assert "测试中文" in restored.description
        assert "✓" in restored.constraints[0]

    @pytest.mark.asyncio
    async def test_runner_empty_matrix(self):
        """Test running with empty matrix falls back to inconclusive analysis."""
        mock_func = AsyncMock()
        runner = MatrixDebateRunner(mock_func, max_parallel=1)

        matrix = ScenarioMatrix()  # Empty matrix

        result = await runner.run_matrix("Empty matrix test", matrix)

        # The debate function should never have been called
        assert mock_func.call_count == 0
        assert result.outcome_category == OutcomeCategory.INCONCLUSIVE
        assert result.results == []
        assert "Scenarios Analyzed**: 0" in result.summary

    def test_scenario_special_characters_in_replacements(self):
        """Test context replacements with special characters."""
        scenario = Scenario(
            id="special",
            name="Special Chars",
            scenario_type=ScenarioType.CUSTOM,
            description="Special characters test",
            context_replacements={
                "{{PLACEHOLDER}}": "actual_value",
                "$VAR": "replaced",
                "regex.*pattern": "literal_text",
            },
        )

        context = "Use {{PLACEHOLDER}} and $VAR with regex.*pattern"
        result = scenario.apply_to_context(context)

        assert "actual_value" in result
        assert "replaced" in result
        assert "literal_text" in result
        assert "{{PLACEHOLDER}}" not in result
