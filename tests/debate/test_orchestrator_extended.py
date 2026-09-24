"""
Extended tests for Arena orchestrator covering edge cases and integration.

Tests cover:
- Arena initialization parameters validation
- Protocol configuration validation
- Event emission interface
- Error handling patterns

Note: Full integration tests require API keys and are in test_orchestrator.py.
These tests focus on unit testing and interface validation.
"""

import pytest
from unittest.mock import MagicMock, patch

from aragora.debate.protocol import DebateProtocol


# ============================================================================
# Protocol Configuration Tests
# ============================================================================


class TestProtocolConfiguration:
    """Tests for DebateProtocol configuration validation."""

    def test_default_protocol_values(self):
        """Protocol has sensible defaults."""
        protocol = DebateProtocol()

        assert protocol.rounds >= 1
        assert protocol.consensus in ["majority", "unanimous", "judge", "none", "hybrid"]

    def test_protocol_rounds_validation(self):
        """Protocol rounds must be positive."""
        protocol = DebateProtocol(rounds=1)
        assert protocol.rounds == 1

        protocol = DebateProtocol(rounds=10)
        assert protocol.rounds == 10

    def test_all_consensus_modes_valid(self):
        """All consensus modes can be set."""
        valid_modes = ["majority", "unanimous", "judge", "none"]

        for mode in valid_modes:
            protocol = DebateProtocol(consensus=mode)
            assert protocol.consensus == mode

    def test_early_stopping_config(self):
        """Early stopping configuration works."""
        protocol = DebateProtocol(
            rounds=5,
            early_stopping=True,
        )

        assert protocol.early_stopping is True

    def test_convergence_detection_config(self):
        """Convergence detection configuration works."""
        protocol = DebateProtocol(
            convergence_detection=True,
        )

        assert protocol.convergence_detection is True

    def test_protocol_serialization(self):
        """Protocol can be serialized to dict."""
        protocol = DebateProtocol(
            rounds=3,
            consensus="majority",
        )

        # Protocol should have to_dict or similar
        if hasattr(protocol, "to_dict"):
            data = protocol.to_dict()
            assert "rounds" in data
        else:
            # At minimum, protocol attributes should be accessible
            assert protocol.rounds == 3


class TestProtocolCombinations:
    """Tests for valid protocol combinations."""

    def test_judge_consensus_requires_agents(self):
        """Judge consensus mode is valid."""
        protocol = DebateProtocol(
            rounds=2,
            consensus="judge",
        )
        assert protocol.consensus == "judge"

    def test_unanimous_with_early_stopping(self):
        """Unanimous with early stopping is valid."""
        protocol = DebateProtocol(
            rounds=5,
            consensus="unanimous",
            early_stopping=True,
        )

        assert protocol.consensus == "unanimous"
        assert protocol.early_stopping is True


# ============================================================================
# Arena Interface Tests (Without Full Initialization)
# ============================================================================


class TestArenaInterface:
    """Tests for Arena interface without requiring full initialization."""

    def test_arena_class_exists(self):
        """Arena class is importable."""
        from aragora.debate.orchestrator import Arena

        assert Arena is not None

    def test_arena_has_run_method(self):
        """Arena has run method."""
        from aragora.debate.orchestrator import Arena

        assert hasattr(Arena, "run")
        assert callable(Arena.run)

    def test_arena_has_from_config(self):
        """Arena has from_config class method."""
        from aragora.debate.orchestrator import Arena

        assert hasattr(Arena, "from_config")

    def test_arena_accepts_event_emitter_param(self):
        """Arena constructor accepts event_emitter parameter."""
        from aragora.debate.orchestrator import Arena
        import inspect

        sig = inspect.signature(Arena.__init__)
        params = sig.parameters

        # Should accept event_emitter
        assert "event_emitter" in params or "kwargs" in params


# ============================================================================
# Environment Tests
# ============================================================================


class TestEnvironmentConfiguration:
    """Tests for Environment configuration."""

    def test_environment_creation(self):
        """Environment can be created with task."""
        from aragora.core import Environment

        env = Environment(task="Test task")
        assert env.task == "Test task"

    def test_environment_with_context(self):
        """Environment accepts context."""
        from aragora.core import Environment

        env = Environment(task="Test", context="Background info")
        assert env.context == "Background info"

    def test_environment_with_max_rounds(self):
        """Environment accepts max_rounds."""
        from aragora.core import Environment

        env = Environment(task="Test", max_rounds=5)
        assert env.max_rounds == 5


# ============================================================================
# Core Type Tests
# ============================================================================


class TestCoreTypes:
    """Tests for core debate types."""

    def test_vote_type_exists(self):
        """Vote type is importable."""
        from aragora.core import Vote

        assert Vote is not None

    def test_critique_type_exists(self):
        """Critique type is importable."""
        from aragora.core import Critique

        assert Critique is not None

    def test_debate_result_type_exists(self):
        """DebateResult type is importable."""
        from aragora.core import DebateResult

        assert DebateResult is not None


# ============================================================================
# Agent Base Tests
# ============================================================================


class TestAgentBase:
    """Tests for agent base class interface."""

    def test_agent_factory_exists(self):
        """create_agent factory is importable."""
        from aragora.agents.base import create_agent

        assert create_agent is not None

    def test_agent_types_available(self):
        """Common agent types are registered."""
        from aragora.config import ALLOWED_AGENT_TYPES

        # Should have at least some agent types
        assert len(ALLOWED_AGENT_TYPES) > 0
        assert "mock" in ALLOWED_AGENT_TYPES or "anthropic-api" in ALLOWED_AGENT_TYPES


# ============================================================================
# Event Emission Interface Tests
# ============================================================================


class TestEventEmissionInterface:
    """Tests for event emission interface."""

    def test_stream_event_type_exists(self):
        """StreamEventType enum exists."""
        from aragora.events.types import StreamEventType

        # Should have common event types
        assert hasattr(StreamEventType, "DEBATE_START")
        assert hasattr(StreamEventType, "DEBATE_END")

    def test_stream_event_exists(self):
        """StreamEvent dataclass exists."""
        from aragora.events.types import StreamEvent

        event = StreamEvent(
            type=MagicMock(),
            data={"test": True},
            loop_id="test-loop",
        )
        assert event.data == {"test": True}

    def test_sync_event_emitter_exists(self):
        """SyncEventEmitter class exists."""
        from aragora.server.stream.emitter import SyncEventEmitter

        emitter = SyncEventEmitter()
        assert hasattr(emitter, "emit")


# ============================================================================
# Consensus Detection Interface Tests
# ============================================================================


class TestConsensusInterface:
    """Tests for consensus detection interfaces."""

    def test_convergence_detector_exists(self):
        """ConvergenceDetector is importable."""
        from aragora.debate.convergence import ConvergenceDetector

        assert ConvergenceDetector is not None

    def test_consensus_proof_exists(self):
        """ConsensusProof type exists."""
        from aragora.debate.consensus import ConsensusProof

        assert ConsensusProof is not None


# ============================================================================
# Error Handling Pattern Tests
# ============================================================================


class TestErrorHandlingPatterns:
    """Tests for error handling patterns in debate module."""

    def test_safe_error_message_exists(self):
        """safe_error_message utility exists."""
        from aragora.server.errors import safe_error_message

        result = safe_error_message(Exception("test"), "context")
        assert isinstance(result, str)
        assert "test" not in result  # Should sanitize

    def test_debate_timeout_constant_exists(self):
        """DEBATE_TIMEOUT_SECONDS is defined."""
        from aragora.config import DEBATE_TIMEOUT_SECONDS

        assert isinstance(DEBATE_TIMEOUT_SECONDS, (int, float))
        assert DEBATE_TIMEOUT_SECONDS > 0


# ============================================================================
# Memory Integration Interface Tests
# ============================================================================


class TestMemoryInterface:
    """Tests for memory integration interfaces."""

    def test_continuum_memory_importable(self):
        """ContinuumMemory is importable."""
        from aragora.memory.continuum import ContinuumMemory

        assert ContinuumMemory is not None

    def test_consensus_memory_importable(self):
        """ConsensusMemory is importable."""
        from aragora.memory.consensus import ConsensusMemory

        assert ConsensusMemory is not None


# ============================================================================
# Phase System Tests
# ============================================================================


class TestPhaseSystem:
    """Tests for debate phase system."""

    def test_phase_modules_exist(self):
        """Phase modules are importable."""
        from aragora.debate.phases import consensus_phase

        assert consensus_phase is not None

    def test_debate_context_exists(self):
        """DebateContext is importable."""
        from aragora.debate.context import DebateContext

        assert DebateContext is not None


# ============================================================================
# Rate Limiting Tests
# ============================================================================


class TestRateLimiting:
    """Tests for rate limiting in debate handlers."""

    def test_token_bucket_exists(self):
        """TokenBucket rate limiter exists."""
        from aragora.server.stream.emitter import TokenBucket

        bucket = TokenBucket(rate_per_minute=10.0, burst_size=5)
        assert bucket is not None

    def test_token_bucket_consume(self):
        """TokenBucket consume works."""
        from aragora.server.stream.emitter import TokenBucket

        bucket = TokenBucket(rate_per_minute=60.0, burst_size=3)

        # Should allow burst
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True
        assert bucket.consume(1) is True

        # Bucket exhausted
        assert bucket.consume(1) is False
