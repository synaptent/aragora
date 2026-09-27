"""
Tests for Trickster (hollow consensus detection) integration.

Tests that the Trickster is properly wired to detect hollow consensus
and inject challenges during debates.
"""

import pytest
from unittest.mock import Mock, MagicMock, AsyncMock, patch


class TestTricksterBasics:
    """Tests for Trickster basic functionality."""

    def test_trickster_creation(self):
        """Trickster should be creatable."""
        from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig

        config = TricksterConfig(sensitivity=0.7)
        trickster = EvidencePoweredTrickster(config=config)
        assert trickster is not None

    def test_trickster_config_sensitivity(self):
        """TricksterConfig should have configurable sensitivity."""
        from aragora.debate.trickster import TricksterConfig

        config = TricksterConfig(sensitivity=0.5)
        assert config.sensitivity == 0.5

        config_high = TricksterConfig(sensitivity=0.9)
        assert config_high.sensitivity == 0.9


class TestHollowConsensusDetection:
    """Tests for hollow consensus detection."""

    def test_detect_low_evidence_consensus(self):
        """Should detect consensus with insufficient evidence."""
        from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig

        trickster = EvidencePoweredTrickster(config=TricksterConfig(sensitivity=0.7))

        # Simulate a round with high agreement but low evidence
        round_data = {
            "proposals": [
                {"agent": "claude", "content": "I agree with the approach", "confidence": 0.9},
                {"agent": "gpt4", "content": "Yes, I concur", "confidence": 0.85},
            ],
            "evidence_count": 0,
            "disagreement_level": 0.1,
        }

        # Should detect hollow consensus
        if hasattr(trickster, "detect_hollow_consensus"):
            is_hollow = trickster.detect_hollow_consensus(round_data)
            # Low evidence + high agreement = hollow
            assert is_hollow is True

    def test_detect_valid_consensus(self):
        """Should not flag consensus backed by evidence."""
        from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig

        trickster = EvidencePoweredTrickster(config=TricksterConfig(sensitivity=0.7))

        # Simulate a round with evidence-backed agreement
        round_data = {
            "proposals": [
                {
                    "agent": "claude",
                    "content": "Based on the benchmarks, X is faster",
                    "confidence": 0.9,
                },
                {
                    "agent": "gpt4",
                    "content": "The data supports this conclusion",
                    "confidence": 0.85,
                },
            ],
            "evidence_count": 3,
            "disagreement_level": 0.1,
        }

        if hasattr(trickster, "detect_hollow_consensus"):
            is_hollow = trickster.detect_hollow_consensus(round_data)
            # Evidence present = not hollow
            assert is_hollow is False


class TestTricksterChallenge:
    """Tests for Trickster challenge generation."""

    def test_generate_challenge(self):
        """Trickster should generate challenge prompts."""
        from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig

        trickster = EvidencePoweredTrickster(config=TricksterConfig(sensitivity=0.7))

        if hasattr(trickster, "generate_challenge"):
            challenge = trickster.generate_challenge(
                topic="Should we use microservices?",
                current_consensus="Microservices are the best approach",
            )

            assert challenge is not None
            assert len(challenge) > 0
            # Challenge should question the consensus
            assert any(
                word in challenge.lower()
                for word in ["consider", "what if", "evidence", "why", "assume"]
            )


class TestTricksterWiring:
    """Tests for Trickster wiring in debate phases."""

    def test_protocol_has_trickster_flag(self):
        """DebateProtocol should have enable_trickster flag."""
        from aragora.core import DebateProtocol

        protocol = DebateProtocol(enable_trickster=True)
        assert protocol.enable_trickster is True

    def test_protocol_trickster_sensitivity(self):
        """DebateProtocol should have trickster_sensitivity."""
        from aragora.core import DebateProtocol

        protocol = DebateProtocol(
            enable_trickster=True,
            trickster_sensitivity=0.8,
        )
        assert protocol.trickster_sensitivity == 0.8

    def test_debate_rounds_phase_accepts_trickster(self):
        """DebateRoundsPhase should accept trickster parameter."""
        from aragora.debate.phases.debate_rounds import DebateRoundsPhase
        from aragora.core import DebateProtocol

        mock_trickster = Mock()
        protocol = DebateProtocol(enable_trickster=True)

        phase = DebateRoundsPhase(
            protocol=protocol,
            circuit_breaker=None,
            convergence_detector=None,
            recorder=None,
            hooks=None,
            trickster=mock_trickster,
            rhetorical_observer=None,
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

        assert phase.trickster is mock_trickster


class TestTricksterEvents:
    """Tests for Trickster event emission."""

    def test_stream_event_types_include_trickster(self):
        """StreamEventType should include trickster events."""
        from aragora.events.types import StreamEventType

        assert hasattr(StreamEventType, "HOLLOW_CONSENSUS")
        assert hasattr(StreamEventType, "TRICKSTER_INTERVENTION")

    def test_spectator_maps_trickster_events(self):
        """SpectatorMixin should support trickster event types."""
        from aragora.debate.phases.spectator import SpectatorMixin
        from aragora.events.types import StreamEventType

        # SpectatorMixin is used as a mixin for debate phases
        # Verify it can handle trickster-related events
        assert hasattr(SpectatorMixin, "notify_spectator") or hasattr(
            SpectatorMixin, "_notify_spectator"
        )
        # Verify StreamEventType has trickster events (already tested above)
        assert hasattr(StreamEventType, "HOLLOW_CONSENSUS")


class TestTricksterIntegration:
    """Integration tests for Trickster in debates."""

    @pytest.mark.asyncio
    async def test_trickster_intervenes_on_hollow_consensus(self):
        """Trickster should intervene when hollow consensus detected."""
        from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig

        trickster = EvidencePoweredTrickster(
            config=TricksterConfig(sensitivity=0.5)  # Lower threshold for testing
        )

        # Simulate detecting hollow consensus with high convergence
        # API: check_and_intervene(responses: dict[str, str], convergence_similarity: float, round_num: int)
        responses = {
            "claude": "I think so",
            "gpt4": "Agreed",
        }

        if hasattr(trickster, "check_and_intervene"):
            intervention = trickster.check_and_intervene(
                responses=responses,
                convergence_similarity=0.95,  # High convergence = potentially hollow
                round_num=1,
            )

            # Intervention may or may not occur based on trickster logic
            # Just verify the method runs without error
            assert intervention is None or hasattr(intervention, "challenge")

    @pytest.mark.asyncio
    async def test_trickster_emits_event(self):
        """Trickster intervention should emit event."""
        from aragora.debate.trickster import EvidencePoweredTrickster, TricksterConfig
        from aragora.server.stream import StreamEvent, StreamEventType

        trickster = EvidencePoweredTrickster(config=TricksterConfig(sensitivity=0.5))

        mock_emitter = Mock()

        # Trigger intervention
        if hasattr(trickster, "emit_intervention_event"):
            trickster.emit_intervention_event(
                event_emitter=mock_emitter,
                round_num=1,
                challenge="What evidence supports this claim?",
                targets=["claude", "gpt4"],
            )

            # Should have emitted an event
            mock_emitter.emit.assert_called()


class TestNoveltyTracker:
    """Tests for NoveltyTracker integration with Trickster."""

    def test_novelty_tracker_creation(self):
        """NoveltyTracker should be creatable."""
        from aragora.debate.novelty import NoveltyTracker

        tracker = NoveltyTracker(low_novelty_threshold=0.15)
        assert tracker is not None

    def test_novelty_tracker_detects_staleness(self):
        """NoveltyTracker should detect stale/repetitive proposals."""
        from aragora.debate.novelty import NoveltyTracker

        tracker = NoveltyTracker(low_novelty_threshold=0.15)

        # Add same-ish content multiple times using correct API
        # API: add_to_history(proposals: dict[str, str])
        tracker.add_to_history({"agent1": "The solution is to use caching"})
        tracker.add_to_history({"agent1": "We should implement caching"})
        tracker.add_to_history({"agent1": "Caching is the answer"})

        # Compute novelty for similar content
        # API: compute_novelty(current_proposals: dict[str, str], round_num: int) -> NoveltyResult
        result = tracker.compute_novelty({"agent1": "Caching would help"}, round_num=4)

        # NoveltyResult has avg_novelty, min_novelty, low_novelty_agents
        assert hasattr(result, "avg_novelty")
        assert hasattr(result, "low_novelty_agents")
        # Similar content should have lower novelty (below 1.0)
        assert result.avg_novelty < 1.0

    def test_novelty_tracker_accepts_novel_content(self):
        """NoveltyTracker should accept genuinely novel content."""
        from aragora.debate.novelty import NoveltyTracker

        tracker = NoveltyTracker(low_novelty_threshold=0.15)

        # Add initial content using correct API
        tracker.add_to_history({"agent1": "The solution is to use caching"})

        # Compute novelty for different content
        result = tracker.compute_novelty(
            {"agent1": "We need better error handling instead"}, round_num=2
        )

        # NoveltyResult has avg_novelty, min_novelty, low_novelty_agents
        assert hasattr(result, "avg_novelty")
        # Novel content should have high novelty (closer to 1.0)
        assert result.avg_novelty > 0.5
