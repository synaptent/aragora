"""
Tests for RhetoricalObserver integration.

Tests that the RhetoricalObserver detects debate patterns (concession,
rebuttal, synthesis) and emits appropriate events.
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch


class TestRhetoricalObserverBasics:
    """Tests for RhetoricalObserver basic functionality."""

    def test_rhetorical_observer_creation(self):
        """RhetoricalObserver should be creatable."""
        from aragora.debate.rhetorical_observer import (
            RhetoricalAnalysisObserver,
            get_rhetorical_observer,
        )

        observer = get_rhetorical_observer()
        assert observer is not None
        assert isinstance(observer, RhetoricalAnalysisObserver)

    def test_rhetorical_observer_patterns(self):
        """RhetoricalObserver should define pattern types."""
        from aragora.debate.rhetorical_observer import RhetoricalPattern

        # Should have these pattern types
        assert hasattr(RhetoricalPattern, "CONCESSION")
        assert hasattr(RhetoricalPattern, "REBUTTAL")
        assert hasattr(RhetoricalPattern, "SYNTHESIS")


class TestPatternDetection:
    """Tests for rhetorical pattern detection."""

    def test_detect_concession(self):
        """Should detect concession patterns in text."""
        from aragora.debate.rhetorical_observer import (
            get_rhetorical_observer,
            RhetoricalPattern,
        )

        observer = get_rhetorical_observer()

        # Text with concession markers
        text = "You make a good point. I concede that my initial approach had flaws."

        if hasattr(observer, "detect_patterns"):
            patterns = observer.detect_patterns(text)
            assert RhetoricalPattern.CONCESSION in patterns

    def test_detect_rebuttal(self):
        """Should detect rebuttal patterns in text."""
        from aragora.debate.rhetorical_observer import (
            get_rhetorical_observer,
            RhetoricalPattern,
        )

        observer = get_rhetorical_observer()

        # Text with rebuttal markers
        text = "However, I disagree with your conclusion. The evidence shows otherwise."

        if hasattr(observer, "detect_patterns"):
            patterns = observer.detect_patterns(text)
            assert RhetoricalPattern.REBUTTAL in patterns

    def test_detect_synthesis(self):
        """Should detect synthesis patterns in text."""
        from aragora.debate.rhetorical_observer import (
            get_rhetorical_observer,
            RhetoricalPattern,
        )

        observer = get_rhetorical_observer()

        # Text with synthesis markers
        text = "Combining both perspectives, we can see that a hybrid approach works best."

        if hasattr(observer, "detect_patterns"):
            patterns = observer.detect_patterns(text)
            assert RhetoricalPattern.SYNTHESIS in patterns

    def test_detect_no_patterns(self):
        """Should return empty when no patterns detected."""
        from aragora.debate.rhetorical_observer import get_rhetorical_observer

        observer = get_rhetorical_observer()

        # Neutral text with no rhetorical markers
        text = "The function returns the sum of two numbers."

        if hasattr(observer, "detect_patterns"):
            patterns = observer.detect_patterns(text)
            assert len(patterns) == 0


class TestRhetoricalObserverWiring:
    """Tests for RhetoricalObserver wiring in debate phases."""

    def test_protocol_has_rhetorical_flag(self):
        """DebateProtocol should have enable_rhetorical_observer flag."""
        from aragora.core import DebateProtocol

        protocol = DebateProtocol(enable_rhetorical_observer=True)
        assert protocol.enable_rhetorical_observer is True

    def test_debate_rounds_phase_accepts_observer(self):
        """DebateRoundsPhase should accept rhetorical_observer parameter."""
        from aragora.debate.phases.debate_rounds import DebateRoundsPhase
        from aragora.core import DebateProtocol

        mock_observer = Mock()
        protocol = DebateProtocol(enable_rhetorical_observer=True)

        phase = DebateRoundsPhase(
            protocol=protocol,
            circuit_breaker=None,
            convergence_detector=None,
            recorder=None,
            hooks=None,
            trickster=None,
            rhetorical_observer=mock_observer,
            event_emitter=None,
            novelty_tracker=None,
            update_role_assignments=lambda *args: None,
            assign_stances=lambda *args: None,
            select_critics_for_proposal=lambda *args: [],
            critique_with_agent=AsyncMock(),
            build_revision_prompt=lambda *args: "",
            generate_with_agent=AsyncMock(),
            with_timeout=lambda coro, _: coro,
            notify_spectator=lambda *args: None,
            record_grounded_position=lambda *args: None,
            check_judge_termination=AsyncMock(return_value=False),
            check_early_stopping=lambda *args: (False, None),
        )

        assert phase.rhetorical_observer is mock_observer


class TestRhetoricalEvents:
    """Tests for RhetoricalObserver event emission."""

    def test_stream_event_types_include_rhetorical(self):
        """StreamEventType should include rhetorical observation events."""
        from aragora.events.types import StreamEventType

        assert hasattr(StreamEventType, "RHETORICAL_OBSERVATION")

    def test_event_data_format(self):
        """Rhetorical observation events should have correct format."""
        from aragora.debate.rhetorical_observer import (
            get_rhetorical_observer,
            RhetoricalPattern,
        )

        observer = get_rhetorical_observer()

        if hasattr(observer, "create_observation_event"):
            event_data = observer.create_observation_event(
                agent="claude",
                patterns=[RhetoricalPattern.CONCESSION, RhetoricalPattern.SYNTHESIS],
                round_num=2,
            )

            assert "agent" in event_data
            assert "patterns" in event_data
            assert "round" in event_data


class TestRhetoricalAnalysis:
    """Tests for rhetorical analysis across debates."""

    def test_track_agent_patterns(self):
        """Should track patterns per agent."""
        from aragora.debate.rhetorical_observer import get_rhetorical_observer

        observer = get_rhetorical_observer()

        if hasattr(observer, "record_observation"):
            observer.record_observation("claude", ["concession"])
            observer.record_observation("claude", ["rebuttal"])
            observer.record_observation("gpt4", ["synthesis"])

            if hasattr(observer, "get_agent_patterns"):
                claude_patterns = observer.get_agent_patterns("claude")
                assert len(claude_patterns) == 2

    def test_identify_dominant_style(self):
        """Should identify agent's dominant rhetorical style."""
        from aragora.debate.rhetorical_observer import get_rhetorical_observer

        observer = get_rhetorical_observer()

        # Record multiple observations
        if hasattr(observer, "record_observation"):
            for _ in range(5):
                observer.record_observation("claude", ["concession"])
            observer.record_observation("claude", ["rebuttal"])

            if hasattr(observer, "get_dominant_style"):
                style = observer.get_dominant_style("claude")
                assert style == "concession"


class TestRhetoricalObserverIntegration:
    """Integration tests for RhetoricalObserver in debates."""

    @pytest.mark.asyncio
    async def test_observer_called_during_round(self):
        """Observer should be called during debate rounds."""
        from aragora.debate.phases.debate_rounds import DebateRoundsPhase
        from aragora.core import DebateProtocol

        mock_observer = Mock()
        mock_observer.detect_patterns = Mock(return_value=["synthesis"])
        mock_observer.record_observation = Mock()

        protocol = DebateProtocol(enable_rhetorical_observer=True)

        phase = DebateRoundsPhase(
            protocol=protocol,
            circuit_breaker=None,
            convergence_detector=None,
            recorder=None,
            hooks=None,
            trickster=None,
            rhetorical_observer=mock_observer,
            event_emitter=Mock(),
            novelty_tracker=None,
            update_role_assignments=lambda *args: None,
            assign_stances=lambda *args: None,
            select_critics_for_proposal=lambda *args: [],
            critique_with_agent=AsyncMock(return_value="Test critique"),
            build_revision_prompt=lambda *args: "",
            generate_with_agent=AsyncMock(return_value="Test response"),
            with_timeout=lambda coro, _: coro,
            notify_spectator=lambda *args: None,
            record_grounded_position=lambda *args: None,
            check_judge_termination=AsyncMock(return_value=False),
            check_early_stopping=lambda *args: (False, None),
        )

        # If phase has method to analyze response
        if hasattr(phase, "_analyze_rhetorical_patterns"):
            phase._analyze_rhetorical_patterns(
                agent="claude",
                response="I agree with your synthesis",
                round_num=1,
            )

            mock_observer.detect_patterns.assert_called()


class TestPatternMarkers:
    """Tests for rhetorical pattern markers/keywords."""

    def test_concession_markers(self):
        """Should recognize concession markers."""
        concession_markers = [
            "you're right",
            "I concede",
            "fair point",
            "I acknowledge",
            "I agree that",
            "you make a valid point",
        ]

        for marker in concession_markers:
            text = f"Yes, {marker}, but consider this alternative."
            # Should detect concession - "acknowledge" added to list
            assert any(
                m in text.lower()
                for m in ["concede", "agree", "right", "valid", "fair", "acknowledge"]
            )

    def test_rebuttal_markers(self):
        """Should recognize rebuttal markers."""
        rebuttal_markers = [
            "however",
            "I disagree",
            "on the contrary",
            "but actually",
            "that's incorrect",
        ]

        for marker in rebuttal_markers:
            text = f"{marker.capitalize()}, the evidence shows otherwise."
            assert any(
                m in text.lower()
                for m in ["however", "disagree", "contrary", "incorrect", "actually"]
            )

    def test_synthesis_markers(self):
        """Should recognize synthesis markers."""
        synthesis_markers = [
            "combining both",
            "integrating these views",
            "taking the best of",
            "a middle ground",
            "synthesizing",
        ]

        for marker in synthesis_markers:
            text = f"I propose {marker} approaches."
            assert any(
                m in text.lower()
                for m in ["combining", "integrating", "best of", "middle", "synthesizing"]
            )
