"""
Tests for the Agent Telemetry Decorator module.

Tests cover:
- AgentTelemetry dataclass
- TelemetryContext context manager
- with_telemetry decorator (sync and async)
- Telemetry collector registration/unregistration
- Default collectors (Prometheus, ImmuneSystem, Blackbox)
- Token estimation
- Error handling
- get_telemetry_stats and reset_telemetry functions
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Test module exports."""

    def test_can_import_module(self):
        """Module can be imported."""
        from aragora.agents import telemetry

        assert telemetry is not None

    def test_agent_telemetry_in_all(self):
        """AgentTelemetry is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "AgentTelemetry" in __all__

    def test_telemetry_context_in_all(self):
        """TelemetryContext is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "TelemetryContext" in __all__

    def test_with_telemetry_in_all(self):
        """with_telemetry is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "with_telemetry" in __all__

    def test_register_telemetry_collector_in_all(self):
        """register_telemetry_collector is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "register_telemetry_collector" in __all__

    def test_unregister_telemetry_collector_in_all(self):
        """unregister_telemetry_collector is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "unregister_telemetry_collector" in __all__

    def test_setup_default_collectors_in_all(self):
        """setup_default_collectors is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "setup_default_collectors" in __all__

    def test_get_telemetry_stats_in_all(self):
        """get_telemetry_stats is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "get_telemetry_stats" in __all__

    def test_reset_telemetry_in_all(self):
        """reset_telemetry is exported in __all__."""
        from aragora.agents.telemetry import __all__

        assert "reset_telemetry" in __all__


# =============================================================================
# AgentTelemetry Tests
# =============================================================================


class TestAgentTelemetryInit:
    """Test AgentTelemetry initialization."""

    def test_default_values(self):
        """AgentTelemetry initializes with correct defaults."""
        from aragora.agents.telemetry import AgentTelemetry

        telemetry = AgentTelemetry(
            agent_name="test_agent",
            operation="generate",
            start_time=time.time(),
        )

        assert telemetry.agent_name == "test_agent"
        assert telemetry.operation == "generate"
        assert telemetry.end_time == 0.0
        assert telemetry.duration_ms == 0.0
        assert telemetry.input_tokens == 0
        assert telemetry.output_tokens == 0
        assert telemetry.input_chars == 0
        assert telemetry.output_chars == 0
        assert telemetry.success is True
        assert telemetry.error_type is None
        assert telemetry.error_message is None
        assert telemetry.metadata == {}

    def test_custom_values(self):
        """AgentTelemetry can be initialized with custom values."""
        from aragora.agents.telemetry import AgentTelemetry

        start = time.time()
        telemetry = AgentTelemetry(
            agent_name="claude",
            operation="critique",
            start_time=start,
            input_tokens=100,
            output_tokens=50,
            metadata={"model": "claude-3-opus"},
        )

        assert telemetry.agent_name == "claude"
        assert telemetry.operation == "critique"
        assert telemetry.start_time == start
        assert telemetry.input_tokens == 100
        assert telemetry.output_tokens == 50
        assert telemetry.metadata == {"model": "claude-3-opus"}


class TestAgentTelemetryComplete:
    """Test AgentTelemetry.complete method."""

    def test_complete_success(self):
        """complete() marks operation as successful."""
        from aragora.agents.telemetry import AgentTelemetry

        start_time = time.time()
        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=start_time,
        )

        time.sleep(0.01)  # Small delay to ensure measurable duration
        telemetry.complete(success=True)

        assert telemetry.success is True
        assert telemetry.end_time > start_time
        assert telemetry.duration_ms > 0
        assert telemetry.error_type is None
        assert telemetry.error_message is None

    def test_complete_failure_with_error(self):
        """complete() records error details on failure."""
        from aragora.agents.telemetry import AgentTelemetry

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )

        error = ValueError("Invalid input")
        telemetry.complete(success=False, error=error)

        assert telemetry.success is False
        assert telemetry.error_type == "ValueError"
        assert telemetry.error_message == "Invalid input"

    def test_complete_truncates_long_error_message(self):
        """complete() truncates long error messages to 200 chars."""
        from aragora.agents.telemetry import AgentTelemetry

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )

        long_message = "x" * 500
        error = RuntimeError(long_message)
        telemetry.complete(success=False, error=error)

        assert len(telemetry.error_message) == 200

    def test_complete_calculates_duration(self):
        """complete() calculates duration in milliseconds."""
        from aragora.agents.telemetry import AgentTelemetry

        start = time.time()
        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=start,
        )

        time.sleep(0.05)  # 50ms delay
        telemetry.complete()

        assert telemetry.duration_ms >= 40  # Allow some tolerance


class TestAgentTelemetryToDict:
    """Test AgentTelemetry.to_dict method."""

    def test_to_dict_contains_all_fields(self):
        """to_dict returns all expected fields."""
        from aragora.agents.telemetry import AgentTelemetry

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="vote",
            start_time=time.time(),
            input_tokens=50,
            output_tokens=25,
        )
        telemetry.complete()

        result = telemetry.to_dict()

        assert "agent_name" in result
        assert "operation" in result
        assert "start_time" in result
        assert "end_time" in result
        assert "duration_ms" in result
        assert "input_tokens" in result
        assert "output_tokens" in result
        assert "input_chars" in result
        assert "output_chars" in result
        assert "success" in result
        assert "error_type" in result
        assert "error_message" in result
        assert "metadata" in result

    def test_to_dict_values_correct(self):
        """to_dict returns correct values."""
        from aragora.agents.telemetry import AgentTelemetry

        telemetry = AgentTelemetry(
            agent_name="claude",
            operation="generate",
            start_time=1000.0,
            input_tokens=100,
            output_tokens=200,
        )

        result = telemetry.to_dict()

        assert result["agent_name"] == "claude"
        assert result["operation"] == "generate"
        assert result["input_tokens"] == 100
        assert result["output_tokens"] == 200


class TestAgentTelemetryEstimateTokens:
    """Test AgentTelemetry.estimate_tokens static method."""

    def test_estimate_tokens_empty_string(self):
        """estimate_tokens returns 0 for empty string."""
        from aragora.agents.telemetry import AgentTelemetry

        result = AgentTelemetry.estimate_tokens("")

        assert result == 0

    def test_estimate_tokens_none(self):
        """estimate_tokens returns 0 for None."""
        from aragora.agents.telemetry import AgentTelemetry

        result = AgentTelemetry.estimate_tokens(None)

        assert result == 0

    def test_estimate_tokens_calculation(self):
        """estimate_tokens uses ~4 chars per token."""
        from aragora.agents.telemetry import AgentTelemetry

        # 20 chars should be ~5 tokens
        text = "a" * 20
        result = AgentTelemetry.estimate_tokens(text)

        assert result == 5

    def test_estimate_tokens_rounds_down(self):
        """estimate_tokens rounds down to integer."""
        from aragora.agents.telemetry import AgentTelemetry

        # 7 chars should be 1 token (7 // 4 = 1)
        text = "abcdefg"
        result = AgentTelemetry.estimate_tokens(text)

        assert result == 1


# =============================================================================
# Collector Registration Tests
# =============================================================================


class TestCollectorRegistration:
    """Test telemetry collector registration."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def test_register_collector(self):
        """Collector can be registered."""
        from aragora.agents.telemetry import (
            get_telemetry_stats,
            register_telemetry_collector,
        )

        def my_collector(t):
            pass

        register_telemetry_collector(my_collector)
        stats = get_telemetry_stats()

        assert stats["collectors_count"] == 1
        assert "my_collector" in stats["collectors"]

    def test_register_collector_prevents_duplicates(self):
        """Same collector cannot be registered twice."""
        from aragora.agents.telemetry import (
            get_telemetry_stats,
            register_telemetry_collector,
        )

        def my_collector(t):
            pass

        register_telemetry_collector(my_collector)
        register_telemetry_collector(my_collector)
        stats = get_telemetry_stats()

        assert stats["collectors_count"] == 1

    def test_unregister_collector(self):
        """Collector can be unregistered."""
        from aragora.agents.telemetry import (
            get_telemetry_stats,
            register_telemetry_collector,
            unregister_telemetry_collector,
        )

        def my_collector(t):
            pass

        register_telemetry_collector(my_collector)
        unregister_telemetry_collector(my_collector)
        stats = get_telemetry_stats()

        assert stats["collectors_count"] == 0

    def test_unregister_nonexistent_collector(self):
        """Unregistering nonexistent collector is safe."""
        from aragora.agents.telemetry import unregister_telemetry_collector

        def my_collector(t):
            pass

        # Should not raise
        unregister_telemetry_collector(my_collector)


class TestTelemetryEmission:
    """Test telemetry emission to collectors."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def test_emit_to_registered_collectors(self):
        """Telemetry is emitted to all registered collectors."""
        from aragora.agents.telemetry import (
            _emit_telemetry,
            AgentTelemetry,
            register_telemetry_collector,
        )

        received = []

        def collector1(t):
            received.append(("c1", t))

        def collector2(t):
            received.append(("c2", t))

        register_telemetry_collector(collector1)
        register_telemetry_collector(collector2)

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )
        _emit_telemetry(telemetry)

        assert len(received) == 2
        assert received[0][0] == "c1"
        assert received[1][0] == "c2"

    def test_collector_error_does_not_stop_others(self):
        """Error in one collector does not prevent other collectors."""
        from aragora.agents.telemetry import (
            _emit_telemetry,
            AgentTelemetry,
            register_telemetry_collector,
        )

        received = []

        def bad_collector(t):
            raise RuntimeError("Collector error")

        def good_collector(t):
            received.append(t)

        register_telemetry_collector(bad_collector)
        register_telemetry_collector(good_collector)

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )
        _emit_telemetry(telemetry)

        # Good collector should still receive telemetry
        assert len(received) == 1


# =============================================================================
# TelemetryContext Tests
# =============================================================================


class TestTelemetryContextInit:
    """Test TelemetryContext initialization."""

    def test_init_creates_telemetry(self):
        """TelemetryContext creates AgentTelemetry on init."""
        from aragora.agents.telemetry import TelemetryContext

        ctx = TelemetryContext("claude", "generate")

        assert ctx.telemetry.agent_name == "claude"
        assert ctx.telemetry.operation == "generate"
        assert ctx.telemetry.start_time > 0

    def test_init_with_model(self):
        """TelemetryContext stores model in metadata."""
        from aragora.agents.telemetry import TelemetryContext

        ctx = TelemetryContext("claude", "generate", model="claude-3-opus")

        assert ctx.telemetry.metadata["model"] == "claude-3-opus"


class TestTelemetryContextSetters:
    """Test TelemetryContext setter methods."""

    def test_set_input(self):
        """set_input sets input chars and tokens."""
        from aragora.agents.telemetry import TelemetryContext

        ctx = TelemetryContext("test", "generate")
        ctx.set_input("Hello world!")  # 12 chars

        assert ctx.telemetry.input_chars == 12
        assert ctx.telemetry.input_tokens == 3  # 12 // 4

    def test_set_output(self):
        """set_output sets output chars and tokens."""
        from aragora.agents.telemetry import TelemetryContext

        ctx = TelemetryContext("test", "generate")
        ctx.set_output("Response text here")  # 18 chars

        assert ctx.telemetry.output_chars == 18
        assert ctx.telemetry.output_tokens == 4  # 18 // 4

    def test_set_error(self):
        """set_error records error details."""
        from aragora.agents.telemetry import TelemetryContext

        ctx = TelemetryContext("test", "generate")
        ctx.set_error(ValueError("Bad input"))

        assert ctx.telemetry.error_type == "ValueError"
        assert ctx.telemetry.error_message == "Bad input"


class TestTelemetryContextManager:
    """Test TelemetryContext as context manager."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def test_context_manager_success(self):
        """Context manager completes telemetry on success."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            TelemetryContext,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        with TelemetryContext("test", "generate") as ctx:
            ctx.set_output("result")

        assert len(received) == 1
        assert received[0].success is True
        assert received[0].output_chars == 6

    def test_context_manager_error(self):
        """Context manager records error on exception."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            TelemetryContext,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        with pytest.raises(ValueError):
            with TelemetryContext("test", "generate"):
                raise ValueError("Test error")

        assert len(received) == 1
        assert received[0].success is False
        assert received[0].error_type == "ValueError"

    def test_context_manager_emits_telemetry(self):
        """Context manager emits telemetry on exit."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            TelemetryContext,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        with TelemetryContext("claude", "critique"):
            pass

        assert len(received) == 1
        assert received[0].agent_name == "claude"
        assert received[0].operation == "critique"


# =============================================================================
# with_telemetry Decorator Tests
# =============================================================================


class MockAgent:
    """Mock agent for testing decorators."""

    def __init__(self, name: str = "test_agent", model: str = "test-model"):
        self.name = name
        self.model = model


class TestWithTelemetryAsync:
    """Test with_telemetry decorator on async functions."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    @pytest.mark.asyncio
    async def test_async_decorator_success(self):
        """Async decorator records successful operation."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                return "Response"

        agent = MyAgent(name="claude", model="opus")
        result = await agent.generate("Hello")

        assert result == "Response"
        assert len(received) == 1
        assert received[0].agent_name == "claude"
        assert received[0].operation == "generate"
        assert received[0].success is True

    @pytest.mark.asyncio
    async def test_async_decorator_error(self):
        """Async decorator records error."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                raise RuntimeError("API error")

        agent = MyAgent(name="gpt", model="4")

        with pytest.raises(RuntimeError):
            await agent.generate("Hello")

        assert len(received) == 1
        assert received[0].success is False
        assert received[0].error_type == "RuntimeError"

    @pytest.mark.asyncio
    async def test_async_decorator_extracts_model(self):
        """Async decorator extracts model from self."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                return "Done"

        agent = MyAgent(name="test", model="gpt-4-turbo")
        await agent.generate("prompt")

        assert received[0].metadata["model"] == "gpt-4-turbo"

    @pytest.mark.asyncio
    async def test_async_decorator_records_string_output_tokens(self):
        """Async decorator records output tokens for string result."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                return "A" * 40  # 40 chars = 10 tokens

        agent = MyAgent()
        await agent.generate("prompt")

        assert received[0].output_chars == 40
        assert received[0].output_tokens == 10


class TestWithTelemetrySync:
    """Test with_telemetry decorator on sync functions."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def test_sync_decorator_success(self):
        """Sync decorator records successful operation."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("vote")
            def vote(self, proposals: dict) -> str:
                return "agent_a"

        agent = MyAgent(name="voter")
        result = agent.vote({"a": "prop_a"})

        assert result == "agent_a"
        assert len(received) == 1
        assert received[0].operation == "vote"
        assert received[0].success is True

    def test_sync_decorator_error(self):
        """Sync decorator records error."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("vote")
            def vote(self, proposals: dict) -> str:
                raise ValueError("No proposals")

        agent = MyAgent()

        with pytest.raises(ValueError):
            agent.vote({})

        assert len(received) == 1
        assert received[0].success is False
        assert received[0].error_type == "ValueError"


class TestWithTelemetryInputExtraction:
    """Test with_telemetry input extraction."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    @pytest.mark.asyncio
    async def test_extract_input_function(self):
        """Input extraction function is called."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("critique", extract_input=lambda self, text: text)
            async def critique(self, text: str) -> str:
                return "critique"

        agent = MyAgent()
        await agent.critique("This is the proposal text")  # 25 chars

        assert received[0].input_chars == 25
        assert received[0].input_tokens == 6

    @pytest.mark.asyncio
    async def test_extract_input_error_handled(self):
        """Error in extract_input is handled gracefully."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        def bad_extractor(*args, **kwargs):
            raise KeyError("missing key")

        class MyAgent(MockAgent):
            @with_telemetry("generate", extract_input=bad_extractor)
            async def generate(self, prompt: str) -> str:
                return "result"

        agent = MyAgent()
        result = await agent.generate("prompt")

        # Should complete successfully despite extraction error
        assert result == "result"
        assert len(received) == 1
        assert received[0].input_chars == 0  # Default when extraction fails


class TestWithTelemetryOutputExtraction:
    """Test with_telemetry output extraction."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    @pytest.mark.asyncio
    async def test_extract_output_function(self):
        """Output extraction function is called."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class MyAgent(MockAgent):
            @with_telemetry("generate", extract_output=lambda r: r["text"])
            async def generate(self, prompt: str) -> dict:
                return {"text": "output text here"}  # 16 chars

        agent = MyAgent()
        await agent.generate("prompt")

        assert received[0].output_chars == 16
        assert received[0].output_tokens == 4

    @pytest.mark.asyncio
    async def test_extract_output_error_handled(self):
        """Error in extract_output is handled gracefully."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        def bad_extractor(result):
            raise AttributeError("no attribute")

        class MyAgent(MockAgent):
            @with_telemetry("generate", extract_output=bad_extractor)
            async def generate(self, prompt: str) -> dict:
                return {"data": "value"}

        agent = MyAgent()
        result = await agent.generate("prompt")

        assert result == {"data": "value"}
        assert len(received) == 1
        assert received[0].output_chars == 0  # Default when extraction fails


# =============================================================================
# Default Collectors Tests
# =============================================================================


class TestDefaultPrometheusCollector:
    """Test default Prometheus collector."""

    def test_prometheus_collector_handles_import_error(self):
        """Prometheus collector handles ImportError gracefully."""
        from aragora.agents.telemetry import (
            _default_prometheus_collector,
            AgentTelemetry,
        )

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )
        telemetry.complete()

        # Should not raise even if Prometheus is unavailable
        with patch.dict("sys.modules", {"aragora.observability.prometheus": None}):
            _default_prometheus_collector(telemetry)

    def test_prometheus_collector_records_generation(self):
        """Prometheus collector records agent generation metrics."""
        from aragora.agents.telemetry import (
            _default_prometheus_collector,
            AgentTelemetry,
        )

        telemetry = AgentTelemetry(
            agent_name="claude",
            operation="generate",
            start_time=time.time(),
            metadata={"model": "opus"},
        )
        telemetry.complete()

        mock_record_gen = MagicMock()
        mock_record_fail = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.prometheus": MagicMock(
                    record_agent_generation=mock_record_gen,
                    record_agent_failure=mock_record_fail,
                )
            },
        ):
            _default_prometheus_collector(telemetry)

        mock_record_gen.assert_called_once()
        call_args = mock_record_gen.call_args
        assert call_args.kwargs["agent_type"] == "claude"
        assert call_args.kwargs["model"] == "opus"


class TestDefaultImmuneSystemCollector:
    """Test default immune system collector."""

    def test_immune_collector_handles_import_error(self):
        """Immune system collector handles ImportError gracefully."""
        from aragora.agents.telemetry import (
            _default_immune_system_collector,
            AgentTelemetry,
        )

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )
        telemetry.complete()

        # Should not raise
        with patch.dict("sys.modules", {"aragora.debate.immune_system": None}):
            _default_immune_system_collector(telemetry)


class TestDefaultBlackboxCollector:
    """Test default blackbox collector."""

    def test_blackbox_collector_handles_import_error(self):
        """Blackbox collector handles ImportError gracefully."""
        from aragora.agents.telemetry import (
            _default_blackbox_collector,
            AgentTelemetry,
        )

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )
        telemetry.complete()

        # Should not raise
        with patch.dict("sys.modules", {"aragora.debate.blackbox": None}):
            _default_blackbox_collector(telemetry)


class TestSetupDefaultCollectors:
    """Test setup_default_collectors function."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def test_setup_registers_three_collectors(self):
        """setup_default_collectors registers Prometheus, Immune, Blackbox."""
        from aragora.agents.telemetry import (
            get_telemetry_stats,
            setup_default_collectors,
        )

        setup_default_collectors()
        stats = get_telemetry_stats()

        assert stats["collectors_count"] == 3
        assert "_default_prometheus_collector" in stats["collectors"]
        assert "_default_immune_system_collector" in stats["collectors"]
        assert "_default_blackbox_collector" in stats["collectors"]


# =============================================================================
# Utility Functions Tests
# =============================================================================


class TestGetTelemetryStats:
    """Test get_telemetry_stats function."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def test_returns_dict(self):
        """get_telemetry_stats returns a dictionary."""
        from aragora.agents.telemetry import get_telemetry_stats

        stats = get_telemetry_stats()

        assert isinstance(stats, dict)

    def test_contains_collectors_count(self):
        """get_telemetry_stats contains collectors_count."""
        from aragora.agents.telemetry import get_telemetry_stats

        stats = get_telemetry_stats()

        assert "collectors_count" in stats

    def test_contains_collectors_list(self):
        """get_telemetry_stats contains collectors list."""
        from aragora.agents.telemetry import get_telemetry_stats

        stats = get_telemetry_stats()

        assert "collectors" in stats
        assert isinstance(stats["collectors"], list)


class TestResetTelemetry:
    """Test reset_telemetry function."""

    def test_clears_collectors(self):
        """reset_telemetry clears all collectors."""
        from aragora.agents.telemetry import (
            get_telemetry_stats,
            register_telemetry_collector,
            reset_telemetry,
        )

        register_telemetry_collector(lambda t: None)
        register_telemetry_collector(lambda t: None)

        reset_telemetry()
        stats = get_telemetry_stats()

        assert stats["collectors_count"] == 0

    def test_reset_is_thread_safe(self):
        """reset_telemetry is thread-safe."""
        import threading

        from aragora.agents.telemetry import (
            get_telemetry_stats,
            register_telemetry_collector,
            reset_telemetry,
        )

        def add_collectors():
            for _ in range(10):
                register_telemetry_collector(lambda t: None)

        def reset_collectors():
            for _ in range(10):
                reset_telemetry()

        threads = [
            threading.Thread(target=add_collectors),
            threading.Thread(target=reset_collectors),
            threading.Thread(target=add_collectors),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        stats = get_telemetry_stats()
        assert "collectors_count" in stats


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestGetCallableName:
    """Test _get_callable_name helper."""

    def test_function_name(self):
        """Returns function name for regular functions."""
        from aragora.agents.telemetry import _get_callable_name

        def my_function():
            pass

        assert _get_callable_name(my_function) == "my_function"

    def test_lambda_name(self):
        """Returns <lambda> for lambda functions."""
        from aragora.agents.telemetry import _get_callable_name

        fn = lambda x: x  # noqa: E731

        assert _get_callable_name(fn) == "<lambda>"

    def test_class_instance(self):
        """Returns class name for callable instances."""
        from aragora.agents.telemetry import _get_callable_name

        class MyCallable:
            def __call__(self):
                pass

        obj = MyCallable()
        # Remove __name__ to simulate callable without it
        result = _get_callable_name(obj)

        assert "MyCallable" in result

    def test_partial_function(self):
        """Returns info for partial functions."""
        from functools import partial

        from aragora.agents.telemetry import _get_callable_name

        def my_func(a, b):
            return a + b

        partial_fn = partial(my_func, 1)
        result = _get_callable_name(partial_fn)

        assert "partial" in result


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        """Reset telemetry before each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    def teardown_method(self):
        """Reset telemetry after each test."""
        from aragora.agents.telemetry import reset_telemetry

        reset_telemetry()

    @pytest.mark.asyncio
    async def test_decorated_method_without_name_attr(self):
        """Decorator handles object without name attribute."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class NoNameAgent:
            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                return "result"

        agent = NoNameAgent()
        result = await agent.generate("prompt")

        assert result == "result"
        assert received[0].agent_name == "unknown"

    @pytest.mark.asyncio
    async def test_decorated_method_without_model_attr(self):
        """Decorator handles object without model attribute."""
        from aragora.agents.telemetry import (
            register_telemetry_collector,
            with_telemetry,
        )

        received = []
        register_telemetry_collector(lambda t: received.append(t))

        class NoModelAgent:
            name = "test"

            @with_telemetry("generate")
            async def generate(self, prompt: str) -> str:
                return "result"

        agent = NoModelAgent()
        await agent.generate("prompt")

        assert received[0].metadata["model"] == "unknown"

    def test_telemetry_complete_without_error(self):
        """Telemetry complete works without explicit error."""
        from aragora.agents.telemetry import AgentTelemetry

        telemetry = AgentTelemetry(
            agent_name="test",
            operation="generate",
            start_time=time.time(),
        )
        telemetry.complete(success=False)

        assert telemetry.success is False
        assert telemetry.error_type is None
        assert telemetry.error_message is None

    def test_multiple_operations_tracked(self):
        """Multiple operations can be tracked independently."""
        from aragora.agents.telemetry import AgentTelemetry

        t1 = AgentTelemetry("agent1", "generate", time.time())
        t2 = AgentTelemetry("agent2", "critique", time.time())

        t1.complete(success=True)
        t2.complete(success=False, error=ValueError("test"))

        assert t1.success is True
        assert t2.success is False
        assert t1.error_type is None
        assert t2.error_type == "ValueError"
