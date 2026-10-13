"""
Tests for arena integration hooks for event emission.

Tests wrap_agent_for_streaming and create_arena_hooks functions.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, call

from aragora.server.stream.arena_hooks import (
    create_arena_hooks,
    wrap_agent_for_streaming,
)
from aragora.server.stream.emitter import SyncEventEmitter
from aragora.events.types import StreamEvent, StreamEventType


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def emitter():
    """Create a SyncEventEmitter for testing."""
    return SyncEventEmitter()


@pytest.fixture
def mock_emitter():
    """Create a mock emitter with captured events."""
    emitter = MagicMock(spec=SyncEventEmitter)
    emitter.events = []

    def capture_emit(event):
        emitter.events.append(event)

    emitter.emit.side_effect = capture_emit
    return emitter


# =============================================================================
# Test create_arena_hooks
# =============================================================================


class TestCreateArenaHooks:
    """Tests for create_arena_hooks function."""

    def test_returns_all_hooks(self, emitter):
        """Should return dict with all expected hook names."""
        hooks = create_arena_hooks(emitter)

        expected_hooks = {
            "on_debate_start",
            "on_round_start",
            "on_message",
            "on_critique",
            "on_vote",
            "on_consensus",
            "on_synthesis",
            "on_debate_end",
            "on_agent_error",
            "on_phase_progress",
            "on_heartbeat",
        }
        assert expected_hooks.issubset(set(hooks.keys()))

    def test_hooks_are_callable(self, emitter):
        """All hooks should be callable functions."""
        hooks = create_arena_hooks(emitter)

        for name, hook in hooks.items():
            assert callable(hook), f"Hook {name} should be callable"

    def test_on_debate_start_emits_event(self, mock_emitter):
        """on_debate_start should emit DEBATE_START event."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_debate_start"](
            task="Test question",
            agents=["agent1", "agent2"],
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.DEBATE_START
        assert event.data["task"] == "Test question"
        assert event.data["agents"] == ["agent1", "agent2"]

    def test_on_round_start_emits_event(self, mock_emitter):
        """on_round_start should emit ROUND_START event."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_round_start"](round_num=2)

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.ROUND_START
        assert event.data["round"] == 2
        assert event.round == 2

    def test_on_message_emits_event(self, mock_emitter):
        """on_message should emit AGENT_MESSAGE event."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_message"](
            agent="claude",
            content="This is my response",
            role="assistant",
            round_num=1,
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.AGENT_MESSAGE
        assert event.data["content"] == "This is my response"
        assert event.data["role"] == "assistant"
        assert event.agent == "claude"
        assert event.round == 1

    def test_on_critique_emits_event(self, mock_emitter):
        """on_critique should emit CRITIQUE event with all data."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_critique"](
            agent="gpt4",
            target="claude",
            issues=["Issue 1", "Issue 2"],
            severity=0.7,
            round_num=2,
            full_content="Full critique content",
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.CRITIQUE
        assert event.data["target"] == "claude"
        assert event.data["issues"] == ["Issue 1", "Issue 2"]
        assert event.data["severity"] == 0.7
        assert event.data["content"] == "Full critique content"
        assert event.agent == "gpt4"
        assert event.round == 2

    def test_on_critique_formats_issues_without_full_content(self, mock_emitter):
        """on_critique should format issues when full_content not provided."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_critique"](
            agent="gpt4",
            target="claude",
            issues=["Issue A", "Issue B"],
            severity=0.5,
            round_num=1,
        )

        event = mock_emitter.events[0]
        assert "• Issue A" in event.data["content"]
        assert "• Issue B" in event.data["content"]

    def test_on_vote_emits_event(self, mock_emitter):
        """on_vote should emit VOTE event."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_vote"](
            agent="claude",
            vote="approve",
            confidence=0.85,
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.VOTE
        assert event.data["vote"] == "approve"
        assert event.data["confidence"] == 0.85
        assert event.agent == "claude"

    def test_on_consensus_emits_event(self, mock_emitter):
        """on_consensus should emit CONSENSUS event."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_consensus"](
            reached=True,
            confidence=0.92,
            answer="The consensus answer is yes",
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.CONSENSUS
        assert event.data["reached"] is True
        assert event.data["confidence"] == 0.92
        assert event.data["answer"] == "The consensus answer is yes"
        assert event.data["status"] == ""
        assert event.data["agent_failures"] == {}

    def test_on_consensus_with_synthesis_fallback(self, mock_emitter):
        """on_consensus should include synthesis as fallback."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_consensus"](
            reached=True,
            confidence=0.92,
            answer="The consensus answer is yes",
            synthesis="This is the synthesized conclusion.",
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.CONSENSUS
        assert event.data["synthesis"] == "This is the synthesized conclusion."

    def test_on_consensus_with_status_and_failures(self, mock_emitter):
        """on_consensus should forward status and agent failures."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_consensus"](
            reached=False,
            confidence=0.1,
            answer="No consensus",
            status="insufficient_participation",
            agent_failures={
                "agent1": [
                    {
                        "phase": "proposal",
                        "error_type": "timeout",
                        "message": "Agent response was empty",
                    }
                ]
            },
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.data["status"] == "insufficient_participation"
        assert "agent1" in event.data["agent_failures"]

    def test_on_synthesis_emits_event(self, mock_emitter):
        """on_synthesis should emit SYNTHESIS event with content and confidence."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_synthesis"](
            content="After thorough discussion, the agents concluded...",
            confidence=0.95,
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.SYNTHESIS
        assert event.data["content"] == "After thorough discussion, the agents concluded..."
        assert event.data["confidence"] == 0.95
        assert event.data["agent"] == "synthesis-agent"
        assert event.agent == "synthesis-agent"

    def test_on_synthesis_with_default_confidence(self, mock_emitter):
        """on_synthesis should use default confidence of 0.0."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_synthesis"](content="Synthesis content only")

        event = mock_emitter.events[0]
        assert event.data["confidence"] == 0.0

    def test_on_debate_end_emits_event(self, mock_emitter):
        """on_debate_end should emit DEBATE_END event."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_debate_end"](
            duration=123.45,
            rounds=3,
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.DEBATE_END
        assert event.data["duration"] == 123.45
        assert event.data["rounds"] == 3

    def test_on_agent_error_emits_event(self, mock_emitter):
        """on_agent_error should emit AGENT_ERROR event with error details."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_agent_error"](
            agent="mistral",
            error_type="timeout",
            message="Agent timed out after 180s",
            recoverable=True,
            phase="proposal",
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.AGENT_ERROR
        assert event.data["error_type"] == "timeout"
        assert event.data["message"] == "Agent timed out after 180s"
        assert event.data["recoverable"] is True
        assert event.data["phase"] == "proposal"
        assert event.agent == "mistral"

    def test_on_phase_progress_emits_event(self, mock_emitter):
        """on_phase_progress should emit PHASE_PROGRESS event with progress info."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_phase_progress"](
            phase="critique",
            completed=3,
            total=8,
            current_agent="claude",
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.PHASE_PROGRESS
        assert event.data["phase"] == "critique"
        assert event.data["completed"] == 3
        assert event.data["total"] == 8
        assert event.data["current_agent"] == "claude"

    def test_on_heartbeat_emits_event(self, mock_emitter):
        """on_heartbeat should emit HEARTBEAT event with status."""
        hooks = create_arena_hooks(mock_emitter)

        hooks["on_heartbeat"](
            phase="round_2",
            status="alive",
        )

        assert len(mock_emitter.events) == 1
        event = mock_emitter.events[0]
        assert event.type == StreamEventType.HEARTBEAT
        assert event.data["phase"] == "round_2"
        assert event.data["status"] == "alive"

    def test_full_debate_lifecycle(self, mock_emitter):
        """Should emit events in order for a complete debate."""
        hooks = create_arena_hooks(mock_emitter)

        # Simulate debate lifecycle
        hooks["on_debate_start"]("Test task", ["a1", "a2"])
        hooks["on_round_start"](1)
        hooks["on_message"]("a1", "Response 1", "assistant", 1)
        hooks["on_message"]("a2", "Response 2", "assistant", 1)
        hooks["on_critique"]("a2", "a1", ["Issue"], 0.5, 1)
        hooks["on_vote"]("a1", "approve", 0.8)
        hooks["on_vote"]("a2", "approve", 0.9)
        hooks["on_consensus"](True, 0.85, "Final answer")
        hooks["on_synthesis"]("Synthesized conclusion from the debate.", 0.85)
        hooks["on_debate_end"](30.0, 1)

        # Verify event order
        event_types = [e.type for e in mock_emitter.events]
        assert event_types == [
            StreamEventType.DEBATE_START,
            StreamEventType.ROUND_START,
            StreamEventType.AGENT_MESSAGE,
            StreamEventType.AGENT_MESSAGE,
            StreamEventType.CRITIQUE,
            StreamEventType.VOTE,
            StreamEventType.VOTE,
            StreamEventType.CONSENSUS,
            StreamEventType.SYNTHESIS,
            StreamEventType.DEBATE_END,
        ]


# =============================================================================
# Test wrap_agent_for_streaming
# =============================================================================


class TestWrapAgentForStreaming:
    """Tests for wrap_agent_for_streaming function."""

    def test_returns_agent_without_streaming(self, mock_emitter):
        """Agent without generate_stream should be returned unchanged."""
        # Use spec to prevent auto-attribute creation
        agent = MagicMock(spec=["name", "generate"])
        agent.name = "test_agent"

        result = wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        assert result is agent
        # No events should be emitted
        assert len(mock_emitter.events) == 0

    def test_wraps_agent_with_streaming(self, mock_emitter):
        """Agent with generate_stream should have generate replaced."""
        agent = MagicMock()
        agent.name = "test_agent"
        agent.generate_stream = AsyncMock(return_value=iter(["token1", "token2"]))
        original_generate = agent.generate

        result = wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        assert result is agent
        # generate method should be replaced
        assert agent.generate != original_generate

    @pytest.mark.asyncio
    async def test_streaming_generate_emits_events(self, mock_emitter):
        """Streaming generate should emit TOKEN_START, TOKEN_DELTA, TOKEN_END."""
        agent = MagicMock()
        agent.name = "streaming_agent"

        async def mock_stream(prompt, context=None):
            for token in ["Hello", " ", "World"]:
                yield token

        agent.generate_stream = mock_stream
        agent.generate = AsyncMock(return_value="Fallback")

        wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        # Call the wrapped generate
        result = await agent.generate("Test prompt")

        assert result == "Hello World"

        # Verify events
        event_types = [e.type for e in mock_emitter.events]
        assert StreamEventType.TOKEN_START in event_types
        assert StreamEventType.TOKEN_END in event_types
        # TOKEN_DELTA should appear for each token
        delta_count = event_types.count(StreamEventType.TOKEN_DELTA)
        assert delta_count == 3

    @pytest.mark.asyncio
    async def test_streaming_token_start_event_data(self, mock_emitter):
        """TOKEN_START event should include agent and debate info."""
        agent = MagicMock()
        agent.name = "test_agent"

        async def mock_stream(prompt, context=None):
            yield "token"

        agent.generate_stream = mock_stream
        agent.generate = AsyncMock()

        wrap_agent_for_streaming(agent, mock_emitter, "debate-xyz")

        await agent.generate("Test")

        start_event = next(e for e in mock_emitter.events if e.type == StreamEventType.TOKEN_START)
        assert start_event.data["debate_id"] == "debate-xyz"
        assert start_event.data["agent"] == "test_agent"
        assert start_event.agent == "test_agent"

    @pytest.mark.asyncio
    async def test_streaming_token_delta_event_data(self, mock_emitter):
        """TOKEN_DELTA events should include token content."""
        agent = MagicMock()
        agent.name = "test_agent"

        async def mock_stream(prompt, context=None):
            yield "Hello"

        agent.generate_stream = mock_stream
        agent.generate = AsyncMock()

        wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        await agent.generate("Test")

        delta_event = next(e for e in mock_emitter.events if e.type == StreamEventType.TOKEN_DELTA)
        assert delta_event.data["token"] == "Hello"
        assert delta_event.data["debate_id"] == "debate-123"
        assert delta_event.data["agent"] == "test_agent"

    @pytest.mark.asyncio
    async def test_streaming_token_end_event_data(self, mock_emitter):
        """TOKEN_END event should include full response."""
        agent = MagicMock()
        agent.name = "test_agent"

        async def mock_stream(prompt, context=None):
            yield "Hello"
            yield " World"

        agent.generate_stream = mock_stream
        agent.generate = AsyncMock()

        wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        await agent.generate("Test")

        end_event = next(e for e in mock_emitter.events if e.type == StreamEventType.TOKEN_END)
        assert end_event.data["full_response"] == "Hello World"

    @pytest.mark.asyncio
    async def test_streaming_error_falls_back(self, mock_emitter):
        """Error during streaming should fall back to original generate."""
        agent = MagicMock()
        agent.name = "test_agent"
        agent.generate = AsyncMock(return_value="Fallback response")

        async def failing_stream(prompt, context=None):
            yield "Partial"
            raise RuntimeError("Stream failed")

        agent.generate_stream = failing_stream

        wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        result = await agent.generate("Test")

        # Should return partial response since some content was streamed
        assert result == "Partial"

        # TOKEN_END should have error info
        end_event = next(e for e in mock_emitter.events if e.type == StreamEventType.TOKEN_END)
        assert "error" in end_event.data
        assert end_event.data["full_response"] == "Partial"

    @pytest.mark.asyncio
    async def test_streaming_error_with_no_content_falls_back(self, mock_emitter):
        """Error with no content should use original generate fallback."""
        agent = MagicMock()
        agent.name = "test_agent"
        agent.generate = AsyncMock(return_value="Fallback response")

        async def failing_immediately_stream(prompt, context=None):
            raise RuntimeError("Immediate failure")
            yield  # Never reached

        agent.generate_stream = failing_immediately_stream

        wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        result = await agent.generate("Test")

        # Should fall back to original generate
        assert result == "Fallback response"

    @pytest.mark.asyncio
    async def test_streaming_passes_context(self, mock_emitter):
        """Streaming should pass context to generate_stream."""
        agent = MagicMock()
        agent.name = "test_agent"
        received_context = []

        async def mock_stream(prompt, context=None):
            received_context.append(context)
            yield "token"

        agent.generate_stream = mock_stream
        agent.generate = AsyncMock()

        wrap_agent_for_streaming(agent, mock_emitter, "debate-123")

        await agent.generate("Test", {"key": "value"})

        assert received_context == [{"key": "value"}]


# =============================================================================
# Integration Tests
# =============================================================================


class TestArenaHooksIntegration:
    """Integration tests for arena hooks with real emitter."""

    def test_hooks_with_real_emitter(self):
        """Hooks should work with real SyncEventEmitter."""
        emitter = SyncEventEmitter()
        hooks = create_arena_hooks(emitter)

        # Emit events
        hooks["on_debate_start"]("Test", ["a1"])
        hooks["on_round_start"](1)
        hooks["on_debate_end"](10.0, 1)

        # Drain events
        events = list(emitter.drain())
        assert len(events) == 3
        assert events[0].type == StreamEventType.DEBATE_START
        assert events[1].type == StreamEventType.ROUND_START
        assert events[2].type == StreamEventType.DEBATE_END

    def test_concurrent_hook_calls(self):
        """Multiple rapid hook calls should not lose events."""
        import threading

        emitter = SyncEventEmitter()
        hooks = create_arena_hooks(emitter)

        def emit_messages():
            for i in range(10):
                hooks["on_message"](f"agent-{i}", f"msg-{i}", "assistant", 1)

        threads = [threading.Thread(target=emit_messages) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        events = list(emitter.drain())
        assert len(events) == 50  # 5 threads * 10 messages
