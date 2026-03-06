"""
Tests for the FlipDetector module.

Tests flip detection, consistency scoring, and UI formatting.
"""

import tempfile
from pathlib import Path

import pytest

from aragora.insights.flip_detector import (
    FlipEvent,
    AgentConsistencyScore,
    FlipDetector,
    format_flip_for_ui,
    format_consistency_for_ui,
)


# =============================================================================
# FlipEvent Tests
# =============================================================================


class TestFlipEvent:
    """Tests for FlipEvent dataclass."""

    def test_create_flip_event(self):
        """Test creating a FlipEvent with all fields."""
        flip = FlipEvent(
            id="flip-123",
            agent_name="claude",
            original_claim="AI is beneficial",
            new_claim="AI has significant risks",
            original_confidence=0.9,
            new_confidence=0.85,
            original_debate_id="debate-1",
            new_debate_id="debate-2",
            original_position_id="pos-1",
            new_position_id="pos-2",
            similarity_score=0.45,
            flip_type="contradiction",
            domain="technology",
        )

        assert flip.id == "flip-123"
        assert flip.agent_name == "claude"
        assert flip.flip_type == "contradiction"
        assert flip.similarity_score == 0.45
        assert flip.domain == "technology"

    def test_flip_event_to_dict(self):
        """Test FlipEvent serialization."""
        flip = FlipEvent(
            id="flip-456",
            agent_name="gpt",
            original_claim="Claim A",
            new_claim="Claim B",
            original_confidence=0.8,
            new_confidence=0.7,
            original_debate_id="d1",
            new_debate_id="d2",
            original_position_id="p1",
            new_position_id="p2",
            similarity_score=0.6,
            flip_type="refinement",
        )

        data = flip.to_dict()

        assert data["id"] == "flip-456"
        assert data["agent_name"] == "gpt"
        assert data["original_claim"] == "Claim A"
        assert data["new_claim"] == "Claim B"
        assert data["flip_type"] == "refinement"
        assert "detected_at" in data

    def test_flip_event_optional_domain(self):
        """Test FlipEvent with no domain."""
        flip = FlipEvent(
            id="flip-789",
            agent_name="gemini",
            original_claim="X",
            new_claim="Y",
            original_confidence=0.5,
            new_confidence=0.5,
            original_debate_id="d",
            new_debate_id="d2",
            original_position_id="p",
            new_position_id="p2",
            similarity_score=0.3,
            flip_type="contradiction",
        )

        assert flip.domain is None
        assert flip.to_dict()["domain"] is None


# =============================================================================
# AgentConsistencyScore Tests
# =============================================================================


class TestAgentConsistencyScore:
    """Tests for AgentConsistencyScore dataclass."""

    def test_perfect_consistency(self):
        """Test agent with no flips has perfect consistency."""
        score = AgentConsistencyScore(
            agent_name="claude",
            total_positions=100,
            total_flips=0,
            contradictions=0,
            refinements=0,
            retractions=0,
            qualifications=0,
        )

        assert score.consistency_score == 1.0
        assert score.flip_rate == 0.0

    def test_consistency_with_contradictions(self):
        """Test consistency score with contradictions (heavily weighted)."""
        score = AgentConsistencyScore(
            agent_name="agent",
            total_positions=10,
            total_flips=3,
            contradictions=3,
            refinements=0,
            retractions=0,
            qualifications=0,
        )

        # 3 contradictions * 1.0 weight / 10 positions = 0.3
        # consistency = 1.0 - 0.3 = 0.7
        assert score.consistency_score == 0.7
        assert score.flip_rate == 0.3

    def test_consistency_with_refinements(self):
        """Test consistency score with refinements (light weight)."""
        score = AgentConsistencyScore(
            agent_name="agent",
            total_positions=10,
            total_flips=5,
            contradictions=0,
            refinements=5,
            retractions=0,
            qualifications=0,
        )

        # 5 refinements * 0.1 weight / 10 positions = 0.05
        # consistency = 1.0 - 0.05 = 0.95
        assert score.consistency_score == 0.95

    def test_consistency_mixed_flip_types(self):
        """Test consistency with mixed flip types."""
        score = AgentConsistencyScore(
            agent_name="agent",
            total_positions=100,
            total_flips=10,
            contradictions=2,  # 2 * 1.0 = 2.0
            refinements=3,  # 3 * 0.1 = 0.3
            retractions=2,  # 2 * 0.7 = 1.4
            qualifications=3,  # 3 * 0.3 = 0.9
        )

        # weighted_flips = 2.0 + 0.3 + 1.4 + 0.9 = 4.6
        # consistency = 1.0 - (4.6 / 100) = 0.954
        assert abs(score.consistency_score - 0.954) < 0.001

    def test_flip_rate(self):
        """Test flip rate calculation."""
        score = AgentConsistencyScore(
            agent_name="agent",
            total_positions=20,
            total_flips=5,
        )

        assert score.flip_rate == 0.25

    def test_flip_rate_zero_positions(self):
        """Test flip rate with zero positions."""
        score = AgentConsistencyScore(
            agent_name="agent",
            total_positions=0,
            total_flips=0,
        )

        assert score.flip_rate == 0.0
        assert score.consistency_score == 1.0

    def test_to_dict(self):
        """Test serialization of consistency score."""
        score = AgentConsistencyScore(
            agent_name="claude",
            total_positions=50,
            total_flips=5,
            contradictions=2,
            refinements=3,
            avg_confidence_on_flip=0.75,
            domains_with_flips=["tech", "science"],
        )

        data = score.to_dict()

        assert data["agent_name"] == "claude"
        assert data["total_positions"] == 50
        assert data["total_flips"] == 5
        assert "consistency_score" in data
        assert "flip_rate" in data
        assert data["domains_with_flips"] == ["tech", "science"]


# =============================================================================
# FlipDetector Tests
# =============================================================================


class TestFlipDetector:
    """Tests for FlipDetector class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield Path(f.name)

    @pytest.fixture
    def detector(self, temp_db):
        """Create a FlipDetector with temp database."""
        return FlipDetector(db_path=temp_db, similarity_threshold=0.6)

    def test_compute_similarity_identical(self, detector):
        """Test similarity computation for identical texts."""
        similarity = detector._compute_similarity("This is a test", "This is a test")
        assert abs(similarity - 1.0) < 1e-9

    def test_compute_similarity_different(self, detector):
        """Test similarity computation for different texts."""
        similarity = detector._compute_similarity(
            "AI is beneficial for humanity", "Quantum computing is the future"
        )
        assert similarity < 0.5

    def test_compute_similarity_similar(self, detector):
        """Test similarity computation for similar texts."""
        similarity = detector._compute_similarity(
            "AI is beneficial for society", "AI is helpful for society"
        )
        assert similarity > 0.5

    def test_compute_similarity_case_insensitive(self, detector):
        """Test similarity is case insensitive."""
        similarity = detector._compute_similarity("Hello World", "hello world")
        assert abs(similarity - 1.0) < 1e-9

    def test_classify_flip_type_contradiction(self, detector):
        """Test classification of contradiction."""
        flip_type = detector._classify_flip_type(
            "AI is good for humanity",
            "AI is bad for humanity",
            0.9,
            0.9,
        )
        assert flip_type == "contradiction"

    def test_classify_flip_type_retraction(self, detector):
        """Test classification of retraction."""
        flip_type = detector._classify_flip_type(
            "AI will revolutionize healthcare",
            "I was wrong about AI in healthcare",
            0.9,
            0.6,
        )
        assert flip_type == "retraction"

    def test_classify_flip_type_qualification(self, detector):
        """Test classification of qualification."""
        flip_type = detector._classify_flip_type(
            "AI is always beneficial",
            "AI is sometimes beneficial with caveats",
            0.9,
            0.7,
        )
        assert flip_type == "qualification"

    def test_classify_flip_type_refinement(self, detector):
        """Test classification of refinement for similar claims."""
        flip_type = detector._classify_flip_type(
            "AI improves efficiency",
            "AI greatly improves efficiency",
            0.85,
            0.90,
        )
        assert flip_type == "refinement"

    def test_init_creates_tables(self, detector, temp_db):
        """Test that initialization creates required tables."""
        import sqlite3

        with sqlite3.connect(str(temp_db)) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

        assert "detected_flips" in tables
        assert "positions" in tables

    def test_get_agent_consistency_no_data(self, detector):
        """Test getting consistency for agent with no data."""
        score = detector.get_agent_consistency("nonexistent_agent")

        assert score.agent_name == "nonexistent_agent"
        assert score.total_positions == 0
        assert score.total_flips == 0
        assert score.consistency_score == 1.0

    def test_store_and_retrieve_flips(self, detector):
        """Test storing and retrieving flip events."""
        flip = FlipEvent(
            id="test-flip-1",
            agent_name="test_agent",
            original_claim="Original",
            new_claim="New",
            original_confidence=0.8,
            new_confidence=0.7,
            original_debate_id="d1",
            new_debate_id="d2",
            original_position_id="p1",
            new_position_id="p2",
            similarity_score=0.5,
            flip_type="contradiction",
            domain="test_domain",
        )

        detector._store_flip(flip)
        recent = detector.get_recent_flips(limit=10)

        assert len(recent) >= 1
        found = next((f for f in recent if f.id == "test-flip-1"), None)
        assert found is not None
        assert found.agent_name == "test_agent"
        assert found.flip_type == "contradiction"

    def test_store_flips_batch(self, detector):
        """Test batch storing of multiple flips."""
        flips = [
            FlipEvent(
                id=f"batch-flip-{i}",
                agent_name="batch_agent",
                original_claim=f"Claim {i}",
                new_claim=f"New claim {i}",
                original_confidence=0.8,
                new_confidence=0.7,
                original_debate_id="d1",
                new_debate_id="d2",
                original_position_id=f"p{i}",
                new_position_id=f"np{i}",
                similarity_score=0.5,
                flip_type="refinement",
            )
            for i in range(5)
        ]

        detector._store_flips_batch(flips)
        recent = detector.get_recent_flips(limit=20)

        batch_flips = [f for f in recent if f.id.startswith("batch-flip-")]
        assert len(batch_flips) == 5

    def test_get_flip_summary(self, detector):
        """Test getting flip summary statistics."""
        # Store some test flips
        for i, flip_type in enumerate(
            ["contradiction", "contradiction", "refinement", "retraction"]
        ):
            flip = FlipEvent(
                id=f"summary-flip-{i}",
                agent_name=f"agent_{i % 2}",
                original_claim=f"Claim {i}",
                new_claim=f"New claim {i}",
                original_confidence=0.8,
                new_confidence=0.7,
                original_debate_id="d1",
                new_debate_id="d2",
                original_position_id=f"p{i}",
                new_position_id=f"np{i}",
                similarity_score=0.5,
                flip_type=flip_type,
            )
            detector._store_flip(flip)

        summary = detector.get_flip_summary()

        assert summary["total_flips"] >= 4
        assert "by_type" in summary
        assert "by_agent" in summary
        assert "recent_24h" in summary

    def test_get_agents_consistency_batch(self, detector):
        """Test batch consistency score retrieval."""
        agents = ["agent_a", "agent_b", "agent_c"]
        scores = detector.get_agents_consistency_batch(agents)

        assert len(scores) == 3
        for agent in agents:
            assert agent in scores
            assert scores[agent].agent_name == agent

    def test_get_agents_consistency_batch_empty(self, detector):
        """Test batch consistency with empty list."""
        scores = detector.get_agents_consistency_batch([])
        assert scores == {}


# =============================================================================
# UI Formatting Tests
# =============================================================================


class TestUIFormatting:
    """Tests for UI formatting functions."""

    def test_format_flip_for_ui(self):
        """Test formatting flip event for UI display."""
        flip = FlipEvent(
            id="ui-flip-1",
            agent_name="claude",
            original_claim="This is a very long original claim that should be truncated in the UI display to prevent it from taking too much space",
            new_claim="Short new claim",
            original_confidence=0.95,
            new_confidence=0.85,
            original_debate_id="d1",
            new_debate_id="d2",
            original_position_id="p1",
            new_position_id="p2",
            similarity_score=0.65,
            flip_type="contradiction",
            domain="technology",
        )

        formatted = format_flip_for_ui(flip)

        assert formatted["id"] == "ui-flip-1"
        assert formatted["agent"] == "claude"
        assert formatted["type"] == "contradiction"
        assert formatted["type_emoji"] == "\U0001f504"  # Rotating arrows
        assert formatted["similarity"] == "65%"
        assert formatted["before"]["confidence"] == "95%"
        assert formatted["after"]["confidence"] == "85%"
        assert formatted["domain"] == "technology"
        # Check truncation
        assert len(formatted["before"]["claim"]) <= 103

    def test_format_flip_emoji_mapping(self):
        """Test emoji mapping for different flip types."""
        types_and_emojis = [
            ("contradiction", "\U0001f504"),
            ("retraction", "\u21a9\ufe0f"),
            ("qualification", "\U0001f4dd"),
            ("refinement", "\U0001f527"),
        ]

        for flip_type, expected_emoji in types_and_emojis:
            flip = FlipEvent(
                id="test",
                agent_name="agent",
                original_claim="A",
                new_claim="B",
                original_confidence=0.5,
                new_confidence=0.5,
                original_debate_id="d",
                new_debate_id="d2",
                original_position_id="p",
                new_position_id="p2",
                similarity_score=0.5,
                flip_type=flip_type,
            )
            formatted = format_flip_for_ui(flip)
            assert formatted["type_emoji"] == expected_emoji

    def test_format_consistency_for_ui_high(self):
        """Test formatting high consistency score."""
        score = AgentConsistencyScore(
            agent_name="reliable_agent",
            total_positions=100,
            total_flips=2,
            contradictions=0,
            refinements=2,
        )

        formatted = format_consistency_for_ui(score)

        assert formatted["agent"] == "reliable_agent"
        assert formatted["consistency_class"] == "high"
        assert formatted["total_positions"] == 100
        assert "breakdown" in formatted

    def test_format_consistency_for_ui_medium(self):
        """Test formatting medium consistency score."""
        score = AgentConsistencyScore(
            agent_name="avg_agent",
            total_positions=100,
            total_flips=30,
            contradictions=30,
        )

        formatted = format_consistency_for_ui(score)
        assert formatted["consistency_class"] == "medium"

    def test_format_consistency_for_ui_low(self):
        """Test formatting low consistency score."""
        score = AgentConsistencyScore(
            agent_name="unreliable_agent",
            total_positions=100,
            total_flips=60,
            contradictions=60,
        )

        formatted = format_consistency_for_ui(score)
        assert formatted["consistency_class"] == "low"

    def test_format_consistency_problem_domains(self):
        """Test that problem domains are limited to 3."""
        score = AgentConsistencyScore(
            agent_name="agent",
            domains_with_flips=["tech", "science", "health", "finance", "law"],
        )

        formatted = format_consistency_for_ui(score)
        assert len(formatted["problem_domains"]) == 3
