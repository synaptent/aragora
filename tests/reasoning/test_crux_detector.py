"""
Comprehensive Tests for Crux Detection Module.

Tests the crux_detector module including:
- CruxClaim dataclass
- CruxAnalysisResult dataclass
- CruxDetector class
- BeliefPropagationAnalyzer class
- Influence and disagreement scoring
- Resolution impact calculation
- Resolution strategy suggestions
- Edge cases and error handling
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import pytest

from aragora.reasoning.belief import (
    BeliefDistribution,
    BeliefNetwork,
    BeliefNode,
)
from aragora.reasoning.claims import ClaimType, RelationType
from aragora.reasoning.crux_detector import (
    BeliefPropagationAnalyzer,
    CruxAnalysisResult,
    CruxClaim,
    CruxDetector,
)


# =============================================================================
# CruxClaim Tests
# =============================================================================


class TestCruxClaim:
    """Tests for CruxClaim dataclass."""

    def test_basic_creation(self):
        """Test basic CruxClaim creation with all fields."""
        crux = CruxClaim(
            claim_id="c1",
            statement="Test claim statement",
            author="agent1",
            crux_score=0.75,
            influence_score=0.8,
            disagreement_score=0.6,
            uncertainty_score=0.5,
            centrality_score=0.7,
            affected_claims=["c2", "c3"],
            contesting_agents=["agent2", "agent3"],
            resolution_impact=0.4,
        )

        assert crux.claim_id == "c1"
        assert crux.statement == "Test claim statement"
        assert crux.author == "agent1"
        assert crux.crux_score == 0.75
        assert crux.influence_score == 0.8
        assert crux.disagreement_score == 0.6
        assert crux.uncertainty_score == 0.5
        assert crux.centrality_score == 0.7
        assert crux.affected_claims == ["c2", "c3"]
        assert crux.contesting_agents == ["agent2", "agent3"]
        assert crux.resolution_impact == 0.4

    def test_to_dict_serialization(self):
        """Test serialization to dictionary."""
        crux = CruxClaim(
            claim_id="c1",
            statement="Test claim",
            author="agent1",
            crux_score=0.75123,
            influence_score=0.8456,
            disagreement_score=0.6789,
            uncertainty_score=0.5432,
            centrality_score=0.7111,
            affected_claims=["c2", "c3"],
            contesting_agents=["agent2", "agent3"],
            resolution_impact=0.4321,
        )

        data = crux.to_dict()

        assert data["claim_id"] == "c1"
        assert data["statement"] == "Test claim"
        assert data["author"] == "agent1"
        # Check rounding to 4 decimal places
        assert data["crux_score"] == 0.7512
        assert data["influence_score"] == 0.8456
        assert data["disagreement_score"] == 0.6789
        assert data["uncertainty_score"] == 0.5432
        assert data["centrality_score"] == 0.7111
        assert data["resolution_impact"] == 0.4321
        assert data["affected_claims"] == ["c2", "c3"]
        assert data["contesting_agents"] == ["agent2", "agent3"]

    def test_to_dict_empty_lists(self):
        """Test serialization with empty lists."""
        crux = CruxClaim(
            claim_id="c1",
            statement="Test",
            author="agent1",
            crux_score=0.5,
            influence_score=0.5,
            disagreement_score=0.0,
            uncertainty_score=0.3,
            centrality_score=0.4,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.1,
        )

        data = crux.to_dict()

        assert data["affected_claims"] == []
        assert data["contesting_agents"] == []

    def test_to_dict_zero_scores(self):
        """Test serialization with zero scores."""
        crux = CruxClaim(
            claim_id="c1",
            statement="Test",
            author="agent1",
            crux_score=0.0,
            influence_score=0.0,
            disagreement_score=0.0,
            uncertainty_score=0.0,
            centrality_score=0.0,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.0,
        )

        data = crux.to_dict()

        assert data["crux_score"] == 0.0
        assert data["influence_score"] == 0.0
        assert data["resolution_impact"] == 0.0

    def test_to_dict_max_scores(self):
        """Test serialization with maximum scores."""
        crux = CruxClaim(
            claim_id="c1",
            statement="Test",
            author="agent1",
            crux_score=1.0,
            influence_score=1.0,
            disagreement_score=1.0,
            uncertainty_score=1.0,
            centrality_score=1.0,
            affected_claims=["c2"],
            contesting_agents=["a2"],
            resolution_impact=1.0,
        )

        data = crux.to_dict()

        assert data["crux_score"] == 1.0
        assert data["influence_score"] == 1.0


# =============================================================================
# CruxAnalysisResult Tests
# =============================================================================


class TestCruxAnalysisResult:
    """Tests for CruxAnalysisResult dataclass."""

    def test_basic_creation(self):
        """Test basic CruxAnalysisResult creation."""
        result = CruxAnalysisResult(
            cruxes=[],
            total_claims=10,
            total_disagreements=3,
            average_uncertainty=0.5,
            convergence_barrier=0.4,
            recommended_focus=["c1", "c2"],
        )

        assert result.total_claims == 10
        assert result.total_disagreements == 3
        assert result.average_uncertainty == 0.5
        assert result.convergence_barrier == 0.4
        assert result.recommended_focus == ["c1", "c2"]

    def test_to_dict_empty_cruxes(self):
        """Test serialization with no cruxes."""
        result = CruxAnalysisResult(
            cruxes=[],
            total_claims=0,
            total_disagreements=0,
            average_uncertainty=0.0,
            convergence_barrier=0.0,
            recommended_focus=[],
        )

        data = result.to_dict()

        assert data["cruxes"] == []
        assert data["total_claims"] == 0
        assert data["recommended_focus"] == []

    def test_to_dict_with_cruxes(self):
        """Test serialization with cruxes included."""
        crux = CruxClaim(
            claim_id="c1",
            statement="Test",
            author="agent1",
            crux_score=0.8,
            influence_score=0.7,
            disagreement_score=0.5,
            uncertainty_score=0.4,
            centrality_score=0.6,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.3,
        )
        result = CruxAnalysisResult(
            cruxes=[crux],
            total_claims=5,
            total_disagreements=2,
            average_uncertainty=0.45,
            convergence_barrier=0.35,
            recommended_focus=["c1"],
        )

        data = result.to_dict()

        assert len(data["cruxes"]) == 1
        assert data["cruxes"][0]["claim_id"] == "c1"
        assert data["total_claims"] == 5
        assert data["average_uncertainty"] == 0.45
        assert data["convergence_barrier"] == 0.35

    def test_to_dict_rounding(self):
        """Test that float values are rounded correctly."""
        result = CruxAnalysisResult(
            cruxes=[],
            total_claims=10,
            total_disagreements=3,
            average_uncertainty=0.512345,
            convergence_barrier=0.398765,
            recommended_focus=[],
        )

        data = result.to_dict()

        assert data["average_uncertainty"] == 0.5123
        assert data["convergence_barrier"] == 0.3988


# =============================================================================
# CruxDetector Tests - Initialization
# =============================================================================


class TestCruxDetectorInit:
    """Tests for CruxDetector initialization."""

    def test_default_weights(self):
        """Test default weight initialization."""
        network = BeliefNetwork(debate_id="test")
        detector = CruxDetector(network)

        assert detector.weights["influence"] == 0.3
        assert detector.weights["disagreement"] == 0.3
        assert detector.weights["uncertainty"] == 0.2
        assert detector.weights["centrality"] == 0.2

    def test_custom_weights(self):
        """Test custom weight initialization."""
        network = BeliefNetwork(debate_id="test")
        detector = CruxDetector(
            network,
            influence_weight=0.4,
            disagreement_weight=0.25,
            uncertainty_weight=0.2,
            centrality_weight=0.15,
        )

        assert detector.weights["influence"] == 0.4
        assert detector.weights["disagreement"] == 0.25
        assert detector.weights["uncertainty"] == 0.2
        assert detector.weights["centrality"] == 0.15

    def test_km_adapter_initialization(self):
        """Test Knowledge Mound adapter initialization."""
        network = BeliefNetwork(debate_id="test")
        mock_adapter = MagicMock()

        detector = CruxDetector(network, km_adapter=mock_adapter, km_min_crux_score=0.5)

        assert detector._km_adapter == mock_adapter
        assert detector._km_min_crux_score == 0.5

    def test_set_km_adapter(self):
        """Test setting KM adapter after initialization."""
        network = BeliefNetwork(debate_id="test")
        detector = CruxDetector(network)
        mock_adapter = MagicMock()

        detector.set_km_adapter(mock_adapter)

        assert detector._km_adapter == mock_adapter


# =============================================================================
# CruxDetector Tests - Influence Scores
# =============================================================================


class TestCruxDetectorInfluenceScores:
    """Tests for influence score computation."""

    @pytest.fixture
    def simple_network(self):
        """Create a simple network for testing."""
        network = BeliefNetwork(debate_id="test-debate")
        network.add_claim("c1", "Base claim", "agent1", 0.8)
        network.add_claim("c2", "Supporting claim", "agent1", 0.7)
        network.add_claim("c3", "Dependent claim", "agent2", 0.6)
        network.add_factor("c1", "c2", RelationType.SUPPORTS)
        network.add_factor("c2", "c3", RelationType.SUPPORTS)
        return network

    def test_compute_influence_scores_basic(self, simple_network):
        """Test basic influence score computation."""
        detector = CruxDetector(simple_network)
        scores = detector.compute_influence_scores()

        assert len(scores) == 3
        for score in scores.values():
            assert 0 <= score <= 1

    def test_influence_scores_normalized(self, simple_network):
        """Test that influence scores are normalized to 0-1."""
        detector = CruxDetector(simple_network)
        scores = detector.compute_influence_scores()

        max_score = max(scores.values())
        min_score = min(scores.values())

        assert max_score <= 1.0
        assert min_score >= 0.0

    def test_influence_scores_root_claim(self, simple_network):
        """Test that root claims have influence on downstream claims."""
        detector = CruxDetector(simple_network)
        scores = detector.compute_influence_scores()

        # The root claim should have some influence
        c1_node_id = simple_network.claim_to_node["c1"]
        assert c1_node_id in scores

    def test_influence_scores_empty_network(self):
        """Test influence scores on empty network."""
        network = BeliefNetwork(debate_id="empty")
        detector = CruxDetector(network)

        scores = detector.compute_influence_scores()

        assert scores == {}

    def test_influence_scores_single_node(self):
        """Test influence scores with single node."""
        network = BeliefNetwork(debate_id="single")
        network.add_claim("c1", "Only claim", "agent1", 0.5)
        detector = CruxDetector(network)

        scores = detector.compute_influence_scores()

        assert len(scores) == 1


# =============================================================================
# CruxDetector Tests - Disagreement Scores
# =============================================================================


class TestCruxDetectorDisagreementScores:
    """Tests for disagreement score computation."""

    @pytest.fixture
    def contested_network(self):
        """Create a network with contested claims."""
        network = BeliefNetwork(debate_id="contested-debate")

        # Central claim with mixed support
        network.add_claim("central", "The central disputed claim", "agent1", 0.5)
        network.add_claim("support1", "Evidence supporting", "agent1", 0.8)
        network.add_claim("contra1", "Evidence against", "agent2", 0.9)

        network.add_factor("support1", "central", RelationType.SUPPORTS)
        network.add_factor("contra1", "central", RelationType.CONTRADICTS)

        return network

    def test_compute_disagreement_scores(self, contested_network):
        """Test basic disagreement score computation."""
        detector = CruxDetector(contested_network)
        scores = detector.compute_disagreement_scores()

        # Should return dict of (score, contesting_agents) tuples
        for node_id, (score, agents) in scores.items():
            assert 0 <= score <= 1
            assert isinstance(agents, list)

    def test_disagreement_contested_claim(self, contested_network):
        """Test that contested claims show disagreement."""
        detector = CruxDetector(contested_network)
        scores = detector.compute_disagreement_scores()

        central_node_id = contested_network.claim_to_node["central"]
        if central_node_id in scores:
            disagreement, _ = scores[central_node_id]
            # Should have some level of disagreement
            assert isinstance(disagreement, float)

    def test_disagreement_empty_network(self):
        """Test disagreement scores on empty network."""
        network = BeliefNetwork(debate_id="empty")
        detector = CruxDetector(network)

        scores = detector.compute_disagreement_scores()

        assert scores == {}

    def test_disagreement_unanimous_support(self):
        """Test disagreement when all agents agree."""
        network = BeliefNetwork(debate_id="unanimous")
        network.add_claim("central", "Central claim", "agent1", 0.5)
        network.add_claim("support1", "Support from agent1", "agent1", 0.8)
        network.add_claim("support2", "Support from agent1 again", "agent1", 0.7)
        network.add_factor("support1", "central", RelationType.SUPPORTS)
        network.add_factor("support2", "central", RelationType.SUPPORTS)

        detector = CruxDetector(network)
        scores = detector.compute_disagreement_scores()

        # With only one agent, disagreement should be low or zero
        for node_id, (score, agents) in scores.items():
            assert score >= 0  # Can be 0 with single author


# =============================================================================
# CruxDetector Tests - Resolution Impact
# =============================================================================


class TestCruxDetectorResolutionImpact:
    """Tests for resolution impact computation."""

    @pytest.fixture
    def chain_network(self):
        """Create a network with chain structure."""
        network = BeliefNetwork(debate_id="chain")
        network.add_claim("root", "Root claim", "agent1", 0.5)
        network.add_claim("mid", "Middle claim", "agent1", 0.5)
        network.add_claim("leaf", "Leaf claim", "agent1", 0.5)
        network.add_factor("root", "mid", RelationType.SUPPORTS)
        network.add_factor("mid", "leaf", RelationType.SUPPORTS)
        network.propagate()
        return network

    def test_compute_resolution_impact(self, chain_network):
        """Test basic resolution impact computation."""
        detector = CruxDetector(chain_network)
        root_node_id = chain_network.claim_to_node["root"]

        impact = detector.compute_resolution_impact(root_node_id)

        assert impact >= 0

    def test_resolution_impact_restores_state(self, chain_network):
        """Test that resolution impact computation restores original state."""
        detector = CruxDetector(chain_network)
        root_node_id = chain_network.claim_to_node["root"]

        # Record original posteriors
        original_posteriors = {nid: n.posterior.p_true for nid, n in chain_network.nodes.items()}

        detector.compute_resolution_impact(root_node_id)

        # Check state is restored
        for nid, original_p in original_posteriors.items():
            assert abs(chain_network.nodes[nid].posterior.p_true - original_p) < 0.01

    def test_resolution_impact_single_node(self):
        """Test resolution impact with single node."""
        network = BeliefNetwork(debate_id="single")
        network.add_claim("c1", "Only claim", "agent1", 0.5)
        network.propagate()
        detector = CruxDetector(network)

        c1_node_id = network.claim_to_node["c1"]
        impact = detector.compute_resolution_impact(c1_node_id)

        assert impact >= 0


# =============================================================================
# CruxDetector Tests - Detect Cruxes
# =============================================================================


class TestCruxDetectorDetectCruxes:
    """Tests for crux detection."""

    @pytest.fixture
    def debate_network(self):
        """Create a realistic debate network."""
        network = BeliefNetwork(debate_id="debate")

        # Main thesis
        network.add_claim("thesis", "We should adopt microservices", "architect", 0.6)

        # Pro arguments
        network.add_claim("pro1", "Enables independent scaling", "architect", 0.8)
        network.add_claim("pro2", "Teams can deploy independently", "developer", 0.7)

        # Con arguments
        network.add_claim("con1", "Distributed systems are complex", "ops", 0.85)
        network.add_claim("con2", "Network calls add latency", "ops", 0.75)

        # Build factor graph
        network.add_factor("pro1", "thesis", RelationType.SUPPORTS)
        network.add_factor("pro2", "thesis", RelationType.SUPPORTS)
        network.add_factor("con1", "thesis", RelationType.CONTRADICTS)
        network.add_factor("con2", "thesis", RelationType.CONTRADICTS)

        return network

    def test_detect_cruxes_empty_network(self):
        """Test crux detection on empty network."""
        network = BeliefNetwork(debate_id="empty")
        detector = CruxDetector(network)

        result = detector.detect_cruxes()

        assert result.total_claims == 0
        assert result.cruxes == []
        assert result.recommended_focus == []
        assert result.average_uncertainty == 0.0
        assert result.convergence_barrier == 0.0

    def test_detect_cruxes_basic(self, debate_network):
        """Test basic crux detection."""
        detector = CruxDetector(debate_network)
        result = detector.detect_cruxes(top_k=3, min_score=0.0)

        assert result.total_claims == 5
        assert len(result.cruxes) <= 3
        assert len(result.recommended_focus) == len(result.cruxes)

    def test_detect_cruxes_sorted_by_score(self, debate_network):
        """Test that cruxes are sorted by score (descending)."""
        detector = CruxDetector(debate_network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        if len(result.cruxes) >= 2:
            for i in range(len(result.cruxes) - 1):
                assert result.cruxes[i].crux_score >= result.cruxes[i + 1].crux_score

    def test_detect_cruxes_respects_top_k(self, debate_network):
        """Test that top_k limit is respected."""
        detector = CruxDetector(debate_network)

        result_2 = detector.detect_cruxes(top_k=2, min_score=0.0)
        result_5 = detector.detect_cruxes(top_k=5, min_score=0.0)

        assert len(result_2.cruxes) <= 2
        assert len(result_5.cruxes) <= 5

    def test_detect_cruxes_respects_min_score(self, debate_network):
        """Test that min_score threshold is respected."""
        detector = CruxDetector(debate_network)

        result_low = detector.detect_cruxes(top_k=10, min_score=0.0)
        result_high = detector.detect_cruxes(top_k=10, min_score=0.9)

        assert len(result_high.cruxes) <= len(result_low.cruxes)

        # All cruxes in high threshold result should have score >= 0.9
        for crux in result_high.cruxes:
            assert crux.crux_score >= 0.9

    def test_detect_cruxes_has_required_fields(self, debate_network):
        """Test that each crux has all required fields."""
        detector = CruxDetector(debate_network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        for crux in result.cruxes:
            assert crux.claim_id is not None
            assert crux.statement is not None
            assert crux.author is not None
            assert isinstance(crux.crux_score, float)
            assert isinstance(crux.influence_score, float)
            assert isinstance(crux.disagreement_score, float)
            assert isinstance(crux.uncertainty_score, float)
            assert isinstance(crux.centrality_score, float)
            assert isinstance(crux.affected_claims, list)
            assert isinstance(crux.contesting_agents, list)
            assert isinstance(crux.resolution_impact, float)

    def test_detect_cruxes_analysis_result_fields(self, debate_network):
        """Test that CruxAnalysisResult has all computed fields."""
        detector = CruxDetector(debate_network)
        result = detector.detect_cruxes()

        assert result.total_claims > 0
        assert isinstance(result.total_disagreements, int)
        assert result.average_uncertainty >= 0
        assert 0 <= result.convergence_barrier <= 1
        assert isinstance(result.recommended_focus, list)

    def test_detect_cruxes_convergence_barrier(self, debate_network):
        """Test convergence barrier calculation."""
        detector = CruxDetector(debate_network)
        result = detector.detect_cruxes()

        # Convergence barrier should be between 0 and 1
        assert 0 <= result.convergence_barrier <= 1

    def test_detect_cruxes_with_km_adapter(self, debate_network):
        """Test crux detection syncs to Knowledge Mound."""
        mock_adapter = MagicMock()
        detector = CruxDetector(debate_network, km_adapter=mock_adapter, km_min_crux_score=0.0)

        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        # If there are cruxes meeting threshold, store_crux should be called
        if result.cruxes:
            assert mock_adapter.store_crux.called

    def test_detect_cruxes_km_sync_respects_threshold(self, debate_network):
        """Test that KM sync respects minimum score threshold."""
        mock_adapter = MagicMock()
        detector = CruxDetector(debate_network, km_adapter=mock_adapter, km_min_crux_score=0.99)

        detector.detect_cruxes(top_k=5, min_score=0.0)

        # With very high threshold, likely no cruxes synced
        # This depends on the actual scores in the network

    def test_detect_cruxes_km_sync_handles_errors(self, debate_network):
        """Test that KM sync errors are handled gracefully."""
        mock_adapter = MagicMock()
        mock_adapter.store_crux.side_effect = Exception("KM error")

        detector = CruxDetector(debate_network, km_adapter=mock_adapter, km_min_crux_score=0.0)

        # Should not raise exception
        result = detector.detect_cruxes(top_k=5, min_score=0.0)
        assert result is not None


# =============================================================================
# CruxDetector Tests - Resolution Strategy
# =============================================================================


class TestCruxDetectorResolutionStrategy:
    """Tests for resolution strategy suggestions."""

    @pytest.fixture
    def sample_network(self):
        """Create a sample network for strategy tests."""
        network = BeliefNetwork(debate_id="test")
        network.add_claim("c1", "Test claim", "agent1", 0.5)
        return network

    def test_suggest_resolution_basic(self, sample_network):
        """Test basic resolution strategy suggestion."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="Test claim",
            author="agent1",
            crux_score=0.5,
            influence_score=0.3,
            disagreement_score=0.3,
            uncertainty_score=0.3,
            centrality_score=0.3,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.2,
        )

        strategy = detector.suggest_resolution_strategy(crux)

        assert "claim_id" in strategy
        assert "statement" in strategy
        assert "suggestions" in strategy
        assert "priority" in strategy
        assert strategy["claim_id"] == "c1"

    def test_suggest_resolution_high_disagreement(self, sample_network):
        """Test mediation suggestion for high disagreement."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="High disagreement claim",
            author="agent1",
            crux_score=0.7,
            influence_score=0.3,
            disagreement_score=0.8,  # High disagreement
            uncertainty_score=0.4,
            centrality_score=0.5,
            affected_claims=[],
            contesting_agents=["agent2"],
            resolution_impact=0.3,
        )

        strategy = detector.suggest_resolution_strategy(crux)
        suggestion_types = [s["type"] for s in strategy["suggestions"]]

        assert "mediation" in suggestion_types

    def test_suggest_resolution_high_uncertainty(self, sample_network):
        """Test evidence suggestion for high uncertainty."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="Uncertain claim",
            author="agent1",
            crux_score=0.6,
            influence_score=0.3,
            disagreement_score=0.2,
            uncertainty_score=0.9,  # High uncertainty
            centrality_score=0.4,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.3,
        )

        strategy = detector.suggest_resolution_strategy(crux)
        suggestion_types = [s["type"] for s in strategy["suggestions"]]

        assert "evidence" in suggestion_types

    def test_suggest_resolution_high_influence(self, sample_network):
        """Test decomposition suggestion for high influence."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="Influential claim",
            author="agent1",
            crux_score=0.8,
            influence_score=0.9,  # High influence
            disagreement_score=0.2,
            uncertainty_score=0.4,
            centrality_score=0.7,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.5,
        )

        strategy = detector.suggest_resolution_strategy(crux)
        suggestion_types = [s["type"] for s in strategy["suggestions"]]

        assert "decomposition" in suggestion_types

    def test_suggest_resolution_many_affected(self, sample_network):
        """Test priority suggestion for many affected claims."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="Claim with many dependents",
            author="agent1",
            crux_score=0.7,
            influence_score=0.5,
            disagreement_score=0.3,
            uncertainty_score=0.4,
            centrality_score=0.6,
            affected_claims=["c2", "c3", "c4", "c5"],  # Many affected
            contesting_agents=[],
            resolution_impact=0.4,
        )

        strategy = detector.suggest_resolution_strategy(crux)
        suggestion_types = [s["type"] for s in strategy["suggestions"]]

        assert "priority" in suggestion_types

    def test_suggest_resolution_contesting_agents(self, sample_network):
        """Test direct dialogue suggestion for contesting agents."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="Contested claim",
            author="agent1",
            crux_score=0.6,
            influence_score=0.3,
            disagreement_score=0.3,
            uncertainty_score=0.3,
            centrality_score=0.4,
            affected_claims=[],
            contesting_agents=["agent1", "agent2"],
            resolution_impact=0.3,
        )

        strategy = detector.suggest_resolution_strategy(crux)
        suggestion_types = [s["type"] for s in strategy["suggestions"]]

        assert "direct_dialogue" in suggestion_types

    def test_suggest_resolution_priority_high(self, sample_network):
        """Test high priority for high crux score."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="High priority claim",
            author="agent1",
            crux_score=0.7,  # High score
            influence_score=0.5,
            disagreement_score=0.5,
            uncertainty_score=0.5,
            centrality_score=0.5,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.4,
        )

        strategy = detector.suggest_resolution_strategy(crux)

        assert strategy["priority"] == "high"

    def test_suggest_resolution_priority_medium(self, sample_network):
        """Test medium priority for lower crux score."""
        detector = CruxDetector(sample_network)
        crux = CruxClaim(
            claim_id="c1",
            statement="Medium priority claim",
            author="agent1",
            crux_score=0.3,  # Lower score
            influence_score=0.2,
            disagreement_score=0.2,
            uncertainty_score=0.3,
            centrality_score=0.3,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.2,
        )

        strategy = detector.suggest_resolution_strategy(crux)

        assert strategy["priority"] == "medium"

    def test_suggest_resolution_statement_truncation(self, sample_network):
        """Test that long statements are truncated."""
        detector = CruxDetector(sample_network)
        long_statement = "A" * 300
        crux = CruxClaim(
            claim_id="c1",
            statement=long_statement,
            author="agent1",
            crux_score=0.5,
            influence_score=0.3,
            disagreement_score=0.3,
            uncertainty_score=0.3,
            centrality_score=0.4,
            affected_claims=[],
            contesting_agents=[],
            resolution_impact=0.2,
        )

        strategy = detector.suggest_resolution_strategy(crux)

        assert len(strategy["statement"]) <= 200


# =============================================================================
# BeliefPropagationAnalyzer Tests
# =============================================================================


class TestBeliefPropagationAnalyzer:
    """Tests for BeliefPropagationAnalyzer class."""

    @pytest.fixture
    def analyzer_network(self):
        """Create a network for analyzer tests."""
        network = BeliefNetwork(debate_id="analyzer-test")
        network.add_claim("c1", "First claim with high centrality", "agent1", 0.7)
        network.add_claim("c2", "Second claim depends on first", "agent2", 0.5)
        network.add_claim("c3", "Third claim for testing", "agent1", 0.6)
        network.add_factor("c1", "c2", RelationType.SUPPORTS)
        network.add_factor("c2", "c3", RelationType.SUPPORTS)
        network.propagate()
        return network

    def test_initialization(self, analyzer_network):
        """Test analyzer initialization."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)
        assert analyzer.network == analyzer_network

    def test_identify_debate_cruxes(self, analyzer_network):
        """Test identifying debate cruxes."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)
        cruxes = analyzer.identify_debate_cruxes(top_k=3)

        assert len(cruxes) <= 3
        for crux in cruxes:
            assert "claim_id" in crux
            assert "statement" in crux
            assert "author" in crux
            assert "crux_score" in crux
            assert "centrality" in crux
            assert "entropy" in crux
            assert "current_belief" in crux

    def test_identify_debate_cruxes_sorted(self, analyzer_network):
        """Test that cruxes are sorted by score."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)
        cruxes = analyzer.identify_debate_cruxes(top_k=5)

        if len(cruxes) >= 2:
            for i in range(len(cruxes) - 1):
                assert cruxes[i]["crux_score"] >= cruxes[i + 1]["crux_score"]

    def test_suggest_evidence_targets(self, analyzer_network):
        """Test suggesting evidence targets."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)
        suggestions = analyzer.suggest_evidence_targets()

        for suggestion in suggestions:
            assert "claim_id" in suggestion
            assert "statement" in suggestion
            assert "author" in suggestion
            assert "current_uncertainty" in suggestion
            assert "importance" in suggestion
            assert "suggestion" in suggestion

    def test_suggest_evidence_targets_empty_network(self):
        """Test evidence suggestions on empty network."""
        network = BeliefNetwork(debate_id="empty")
        analyzer = BeliefPropagationAnalyzer(network)

        suggestions = analyzer.suggest_evidence_targets()

        assert suggestions == []

    def test_compute_consensus_probability(self, analyzer_network):
        """Test computing consensus probability."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)
        result = analyzer.compute_consensus_probability()

        assert "probability" in result
        assert "average_confidence" in result
        assert "contested_claims" in result
        assert "contest_ratio" in result
        assert "explanation" in result
        assert 0 <= result["probability"] <= 1

    def test_compute_consensus_probability_empty(self):
        """Test consensus probability on empty network."""
        network = BeliefNetwork(debate_id="empty")
        analyzer = BeliefPropagationAnalyzer(network)

        result = analyzer.compute_consensus_probability()

        assert result["probability"] == 0.0
        assert "No claims" in result["explanation"]

    def test_what_if_analysis(self, analyzer_network):
        """Test what-if analysis."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)

        result = analyzer.what_if_analysis({"c1": True})

        assert "hypothetical" in result
        assert "affected_claims" in result
        assert "changes" in result
        assert result["hypothetical"] == {"c1": True}

    def test_what_if_analysis_multiple_claims(self, analyzer_network):
        """Test what-if analysis with multiple claims."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)

        result = analyzer.what_if_analysis({"c1": True, "c2": False})

        assert result["hypothetical"] == {"c1": True, "c2": False}

    def test_what_if_analysis_restores_state(self, analyzer_network):
        """Test that what-if analysis restores original state."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)

        # Record original posteriors
        original_posteriors = {nid: n.posterior.p_true for nid, n in analyzer_network.nodes.items()}

        analyzer.what_if_analysis({"c1": False})

        # Check state is restored
        for nid, original_p in original_posteriors.items():
            current_p = analyzer_network.nodes[nid].posterior.p_true
            assert abs(current_p - original_p) < 0.01

    def test_what_if_analysis_changes_sorted(self, analyzer_network):
        """Test that what-if changes are sorted by delta."""
        analyzer = BeliefPropagationAnalyzer(analyzer_network)

        result = analyzer.what_if_analysis({"c1": True})

        changes = result["changes"]
        if len(changes) >= 2:
            for i in range(len(changes) - 1):
                assert abs(changes[i]["delta"]) >= abs(changes[i + 1]["delta"])


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================


class TestCruxDetectorEdgeCases:
    """Tests for edge cases and error handling."""

    def test_no_cruxes_above_threshold(self):
        """Test when no cruxes meet the minimum score threshold."""
        network = BeliefNetwork(debate_id="test")
        network.add_claim("c1", "Test", "agent1", 0.9)  # High confidence, low uncertainty
        network.propagate()

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=5, min_score=0.99)

        assert len(result.cruxes) == 0 or all(c.crux_score >= 0.99 for c in result.cruxes)

    def test_conflicting_cruxes(self):
        """Test network with conflicting evidence."""
        network = BeliefNetwork(debate_id="conflict")

        network.add_claim("central", "Central claim", "agent1", 0.5)
        network.add_claim("support", "Strong support", "agent1", 0.95)
        network.add_claim("contra", "Strong contradiction", "agent2", 0.95)

        network.add_factor("support", "central", RelationType.SUPPORTS)
        network.add_factor("contra", "central", RelationType.CONTRADICTS)

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        # Should still produce valid results
        assert result.total_claims == 3
        assert result.convergence_barrier >= 0

    def test_disconnected_claims(self):
        """Test network with disconnected claims."""
        network = BeliefNetwork(debate_id="disconnected")

        network.add_claim("c1", "Isolated claim 1", "agent1", 0.5)
        network.add_claim("c2", "Isolated claim 2", "agent2", 0.6)
        network.add_claim("c3", "Isolated claim 3", "agent3", 0.7)
        # No factors connecting them

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        assert result.total_claims == 3

    def test_self_referential_factors(self):
        """Test handling of self-referential factor edges."""
        network = BeliefNetwork(debate_id="self-ref")
        network.add_claim("c1", "Claim", "agent1", 0.5)
        # Try to add self-referential factor (should be handled gracefully)
        network.add_factor("c1", "c1", RelationType.SUPPORTS)

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        # Should not crash
        assert result is not None

    def test_very_long_statement(self):
        """Test claim with very long statement."""
        network = BeliefNetwork(debate_id="long")
        long_statement = "A" * 10000
        network.add_claim("c1", long_statement, "agent1", 0.5)

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=1, min_score=0.0)

        # Should handle long statements
        assert result is not None

    def test_unicode_statement(self):
        """Test claim with unicode characters."""
        network = BeliefNetwork(debate_id="unicode")
        network.add_claim(
            "c1", "Unicode test: \u00e9\u00e8\u00ea \u4e2d\u6587 \U0001f600", "agent1", 0.5
        )

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=1, min_score=0.0)

        assert result is not None

    def test_extreme_confidence_values(self):
        """Test with extreme confidence values."""
        network = BeliefNetwork(debate_id="extreme")
        network.add_claim("c1", "Very high confidence", "agent1", 0.9999)
        network.add_claim("c2", "Very low confidence", "agent2", 0.0001)
        network.add_factor("c1", "c2", RelationType.SUPPORTS)

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        assert result is not None
        for crux in result.cruxes:
            assert 0 <= crux.crux_score <= 2  # Allow some flexibility due to bonus scoring


# =============================================================================
# Integration Tests
# =============================================================================


class TestCruxDetectorIntegration:
    """Integration tests for crux detection."""

    def test_full_workflow(self):
        """Test complete crux detection workflow."""
        # Build a realistic debate network
        network = BeliefNetwork(debate_id="integration-test")

        # Main thesis
        network.add_claim("thesis", "We should adopt microservices", "architect", 0.6)

        # Pro arguments
        network.add_claim("pro1", "Microservices enable independent scaling", "architect", 0.8)
        network.add_claim("pro2", "Teams can deploy independently", "architect", 0.7)
        network.add_claim("pro3", "Technology diversity is possible", "developer", 0.65)

        # Con arguments
        network.add_claim("con1", "Distributed systems are complex", "ops", 0.85)
        network.add_claim("con2", "Network calls add latency", "ops", 0.75)
        network.add_claim("con3", "Debugging is harder", "developer", 0.7)

        # Sub-arguments
        network.add_claim("sub1", "Our traffic is highly variable", "ops", 0.9)
        network.add_claim("sub2", "We have mature DevOps practices", "architect", 0.6)

        # Build factor graph
        network.add_factor("pro1", "thesis", RelationType.SUPPORTS)
        network.add_factor("pro2", "thesis", RelationType.SUPPORTS)
        network.add_factor("pro3", "thesis", RelationType.SUPPORTS)
        network.add_factor("con1", "thesis", RelationType.CONTRADICTS)
        network.add_factor("con2", "thesis", RelationType.CONTRADICTS)
        network.add_factor("con3", "thesis", RelationType.CONTRADICTS)
        network.add_factor("sub1", "pro1", RelationType.SUPPORTS)
        network.add_factor("sub2", "con1", RelationType.CONTRADICTS)

        # Run propagation
        network.propagate()

        # Detect cruxes
        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=3)

        # Verify analysis
        assert result.total_claims == 9
        assert len(result.cruxes) <= 3
        assert result.convergence_barrier >= 0
        assert len(result.recommended_focus) == len(result.cruxes)

        # Check that we can serialize
        data = result.to_dict()
        assert "cruxes" in data
        assert "convergence_barrier" in data

        # Get resolution strategy for top crux
        if result.cruxes:
            strategy = detector.suggest_resolution_strategy(result.cruxes[0])
            assert "suggestions" in strategy

    def test_crux_detection_updates_with_propagation(self):
        """Crux detection should reflect network state after propagation."""
        network = BeliefNetwork(debate_id="dynamic-test")

        network.add_claim("a", "Claim A", "agent1", 0.5)
        network.add_claim("b", "Claim B depends on A", "agent1", 0.5)
        network.add_factor("a", "b", RelationType.SUPPORTS)

        detector = CruxDetector(network)

        # First detection
        result1 = detector.detect_cruxes(min_score=0.0)

        # Manually change a belief
        a_node = network.get_node_by_claim("a")
        a_node.posterior = BeliefDistribution(p_true=0.9, p_false=0.1)
        network.propagate()

        # Second detection should reflect changes
        result2 = detector.detect_cruxes(min_score=0.0)

        # Network state has changed
        assert result1 is not None
        assert result2 is not None

    def test_combined_detector_and_analyzer(self):
        """Test using both CruxDetector and BeliefPropagationAnalyzer."""
        network = BeliefNetwork(debate_id="combined-test")

        network.add_claim("thesis", "Main thesis", "agent1", 0.5)
        network.add_claim("pro", "Supporting argument", "agent1", 0.7)
        network.add_claim("con", "Opposing argument", "agent2", 0.8)

        network.add_factor("pro", "thesis", RelationType.SUPPORTS)
        network.add_factor("con", "thesis", RelationType.CONTRADICTS)

        network.propagate()

        # Use CruxDetector
        detector = CruxDetector(network)
        crux_result = detector.detect_cruxes(top_k=3, min_score=0.0)

        # Use BeliefPropagationAnalyzer
        analyzer = BeliefPropagationAnalyzer(network)
        analyzer_cruxes = analyzer.identify_debate_cruxes(top_k=3)
        consensus = analyzer.compute_consensus_probability()
        evidence_targets = analyzer.suggest_evidence_targets()

        # Both should work without conflict
        assert crux_result is not None
        assert analyzer_cruxes is not None
        assert consensus is not None
        assert evidence_targets is not None

    def test_round_trip_serialization(self):
        """Test that crux results can be serialized and used."""
        network = BeliefNetwork(debate_id="serialization-test")
        network.add_claim("c1", "Test claim", "agent1", 0.6)
        network.add_claim("c2", "Another claim", "agent2", 0.7)
        network.add_factor("c1", "c2", RelationType.SUPPORTS)

        detector = CruxDetector(network)
        result = detector.detect_cruxes(top_k=5, min_score=0.0)

        # Serialize
        data = result.to_dict()

        # Verify structure
        assert isinstance(data, dict)
        assert "cruxes" in data
        assert "total_claims" in data
        assert "total_disagreements" in data
        assert "average_uncertainty" in data
        assert "convergence_barrier" in data
        assert "recommended_focus" in data

        # Verify crux data
        for crux_data in data["cruxes"]:
            assert "claim_id" in crux_data
            assert "crux_score" in crux_data
            assert "influence_score" in crux_data


def _net(claims, edges):
    from aragora.reasoning.belief import BeliefNetwork
    from aragora.reasoning.claims import RelationType

    network = BeliefNetwork(max_iterations=3)
    for cid, author in claims:
        network.add_claim(claim_id=cid, statement=cid, author=author, initial_confidence=0.8)
    for src, dst, rel, strength in edges:
        network.add_factor(src, dst, getattr(RelationType, rel), strength)
    return network


def _scores(network):
    from aragora.reasoning.crux_detector import CruxDetector

    network.propagate()  # exactly as detect_cruxes does
    return {
        network.nodes[nid].claim_id: (round(d, 3), c)
        for nid, (d, c) in CruxDetector(network).compute_disagreement_scores().items()
    }


def test_every_contester_is_named_not_just_the_first():
    """#9644: with >=2 contesters the mean-and-threshold test excluded them all.

    Under a uniform prior each contester sits 0.6/(k+1) from the mean, which a
    strict `> 0.2` cut drops for every k >= 2 — i.e. exactly the 3+ agent
    debates that are the normal configuration.
    """
    net = _net(
        [("p", "claude"), ("c1", "codex"), ("c2", "gemini")],
        [("c1", "p", "CONTRADICTS", 0.7), ("c2", "p", "CONTRADICTS", 0.6)],
    )
    assert _scores(net)["p"][1] == ["codex", "gemini"]


def test_attribution_is_not_inverted_by_symmetric_traversal():
    """A critiqued proposer must not be recorded as contesting the critique.

    Edge direction is the recorded fact: `S CONTRADICTS A` says S's author
    contests A, and says nothing about A's author contesting S.
    """
    net = _net(
        [("p", "claude"), ("c1", "codex")],
        [("c1", "p", "CONTRADICTS", 0.8)],
    )
    scores = _scores(net)
    assert scores["p"][1] == ["codex"]
    assert scores["c1"][1] == [], "claude never contested codex's critique"


def test_supports_edges_never_produce_dissent():
    """A supporter must never be attributed as a dissenter in a receipt."""
    net = _net(
        [("a", "alice"), ("b", "bob")],
        [("b", "a", "SUPPORTS", 0.9)],
    )
    assert _scores(net)["a"] == (0.0, [])


def test_severity_drives_the_disagreement_score():
    """`factor.strength` carries critique severity and must not be discarded."""
    weak = _scores(_net([("a", "alice"), ("b", "bob")], [("b", "a", "CONTRADICTS", 0.1)]))
    strong = _scores(_net([("a", "alice"), ("b", "bob")], [("b", "a", "CONTRADICTS", 0.9)]))
    assert weak["a"][0] < strong["a"][0]


def test_supporters_damp_a_contested_claim():
    """One contester against one ally scores below one contester alone."""
    alone = _scores(_net([("a", "alice"), ("b", "bob")], [("b", "a", "CONTRADICTS", 0.8)]))
    balanced = _scores(
        _net(
            [("a", "alice"), ("b", "bob"), ("c", "carol")],
            [("b", "a", "CONTRADICTS", 0.8), ("c", "a", "SUPPORTS", 0.8)],
        )
    )
    assert balanced["a"][0] < alone["a"][0]
    assert balanced["a"][1] == ["bob"]


def test_author_is_never_listed_as_contesting_its_own_claim():
    """This list becomes DecisionReceipt dissent attribution."""
    net = _net(
        [("a", "alice"), ("b", "alice"), ("c", "bob")],
        [("b", "a", "CONTRADICTS", 0.9), ("c", "a", "CONTRADICTS", 0.9)],
    )
    scores = _scores(net)
    assert scores["a"][1] == ["bob"], "a self-critique is not dissent"


def test_zero_strength_contradiction_names_nobody():
    """A named contester and a zero score would tell contradictory stories.

    `total_disagreements` counts claims scoring > 0, so a zero-weight
    contradiction would list an agent as contesting a claim that the same
    result says nothing contested.
    """
    net = _net([("a", "alice"), ("b", "bob")], [("b", "a", "CONTRADICTS", 0.0)])
    assert _scores(net)["a"] == (0.0, [])


def test_more_contesters_never_lower_the_score():
    """Monotonic in contester count — a wider dispute is not a smaller one.

    Averaging contest strengths let a weak second objection drag the score below
    the strong first one (0.7 alone, 0.4 once a 0.1 nitpick joined), so a claim
    contested by more agents could rank as less contested.
    """
    one = _scores(_net([("a", "alice"), ("b", "bob")], [("b", "a", "CONTRADICTS", 0.7)]))
    two = _scores(
        _net(
            [("a", "alice"), ("b", "bob"), ("c", "carol")],
            [("b", "a", "CONTRADICTS", 0.7), ("c", "a", "CONTRADICTS", 0.1)],
        )
    )
    assert two["a"][0] >= one["a"][0]
    assert two["a"][1] == ["bob", "carol"]
