"""
Unit tests for agent implementations.

Tests agent components in isolation without making API calls:
- Message formatting (_build_context_prompt, _build_full_prompt)
- Response parsing (_extract_*_response methods)
- CLI argument sanitization
- Error detection and classification
- Circuit breaker integration
- Fallback model mapping
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from aragora.core import Message, Critique


# =============================================================================
# CLI Agent Base Tests
# =============================================================================


class TestCLIAgentSanitization:
    """Tests for CLI argument sanitization."""

    def test_sanitize_removes_null_bytes(self):
        """Test that null bytes are removed from CLI arguments."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._sanitize_cli_arg("hello\x00world")
        assert result == "helloworld"
        assert "\x00" not in result

    def test_sanitize_removes_control_characters(self):
        """Test that control characters (except newlines/tabs) are removed."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        # \x01 through \x08, \x0b-\x0c, \x0e-\x1f, \x7f should be removed
        result = agent._sanitize_cli_arg("test\x01\x08\x0b\x0c\x0e\x1f\x7fvalue")
        assert result == "testvalue"

    def test_sanitize_preserves_newlines_and_tabs(self):
        """Test that newlines and tabs are preserved."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._sanitize_cli_arg("line1\nline2\tvalue")
        assert result == "line1\nline2\tvalue"

    def test_sanitize_preserves_unicode(self):
        """Test that Unicode characters are preserved."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._sanitize_cli_arg("Hello 世界 🚀")
        assert result == "Hello 世界 🚀"

    def test_sanitize_handles_empty_string(self):
        """Test sanitization of empty string."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._sanitize_cli_arg("")
        assert result == ""

    def test_sanitize_handles_non_string(self):
        """Test sanitization converts non-strings to strings."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._sanitize_cli_arg(12345)
        assert result == "12345"

    def test_sanitize_handles_only_null_bytes(self):
        """Test string containing only null bytes."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._sanitize_cli_arg("\x00\x00\x00")
        assert result == ""


class TestCLIAgentContextBuilding:
    """Tests for context prompt building."""

    def test_build_context_prompt_empty(self):
        """Test building context with no messages."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        result = agent._build_context_prompt(context=None)
        assert result == ""

    def test_build_context_prompt_single_message(self):
        """Test building context with single message."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        context = [Message(role="proposer", agent="alice", content="Hello world")]
        result = agent._build_context_prompt(context=context)
        assert "alice" in result
        assert "Hello world" in result

    def test_build_context_prompt_multiple_messages(self):
        """Test building context with multiple messages."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        context = [
            Message(role="proposer", agent="alice", content="First message"),
            Message(role="critic", agent="bob", content="Second message"),
        ]
        result = agent._build_context_prompt(context=context)
        assert "alice" in result
        assert "bob" in result
        assert "First message" in result
        assert "Second message" in result

    def test_build_context_prompt_sanitizes_content(self):
        """Test that context content is sanitized."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        context = [Message(role="proposer", agent="alice", content="Hello\x00world")]
        result = agent._build_context_prompt(context=context)
        assert "\x00" not in result
        assert "Helloworld" in result

    def test_build_full_prompt_with_context(self):
        """Test building full prompt with context."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        context = [Message(role="proposer", agent="alice", content="Previous")]
        result = agent._build_full_prompt("New prompt", context=context)
        assert "alice" in result
        assert "Previous" in result
        assert "New prompt" in result

    def test_build_full_prompt_with_system_prompt(self):
        """Test building full prompt with system prompt."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        agent.system_prompt = "You are a helpful assistant"
        result = agent._build_full_prompt("User prompt")
        assert "System context: You are a helpful assistant" in result
        assert "User prompt" in result


# =============================================================================
# Response Extraction Tests
# =============================================================================


class TestCodexResponseExtraction:
    """Tests for Codex response extraction."""

    def test_extract_codex_response_with_header(self):
        """Test extraction with standard codex header."""
        from aragora.agents.cli_agents import CodexAgent

        agent = CodexAgent(name="test", model="gpt-4.1-codex")
        raw_output = """codex
This is the actual response.
tokens used: 150"""
        result = agent._extract_codex_response(raw_output)
        assert result == "This is the actual response."

    def test_extract_codex_response_no_header(self):
        """Test extraction when no codex header present."""
        from aragora.agents.cli_agents import CodexAgent

        agent = CodexAgent(name="test", model="gpt-4.1-codex")
        raw_output = "Direct response without header"
        result = agent._extract_codex_response(raw_output)
        assert result == "Direct response without header"

    def test_extract_codex_response_multiline(self):
        """Test extraction with multiline response."""
        from aragora.agents.cli_agents import CodexAgent

        agent = CodexAgent(name="test", model="gpt-4.1-codex")
        raw_output = """codex
Line 1
Line 2
Line 3
tokens used: 200"""
        result = agent._extract_codex_response(raw_output)
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result
        assert "tokens used" not in result


class TestGeminiResponseExtraction:
    """Tests for Gemini response extraction."""

    def test_extract_gemini_filters_yolo_message(self):
        """Test that YOLO mode message is filtered out."""
        from aragora.agents.cli_agents import GeminiCLIAgent

        agent = GeminiCLIAgent(name="test", model="gemini-3.1-pro-preview")
        raw_output = """YOLO mode is enabled
Actual response content"""
        result = agent._extract_gemini_response(raw_output)
        assert "YOLO" not in result
        assert "Actual response content" in result

    def test_extract_gemini_preserves_normal_response(self):
        """Test that normal responses are preserved."""
        from aragora.agents.cli_agents import GeminiCLIAgent

        agent = GeminiCLIAgent(name="test", model="gemini-3.1-pro-preview")
        raw_output = "Normal response without YOLO"
        result = agent._extract_gemini_response(raw_output)
        assert result == "Normal response without YOLO"


class TestGrokResponseExtraction:
    """Tests for Grok CLI response extraction."""

    def test_extract_grok_json_output(self):
        """Test extraction from Grok JSON output."""
        from aragora.agents.cli_agents import GrokCLIAgent

        agent = GrokCLIAgent(name="test", model="grok-4")
        raw_output = """{"role": "assistant", "content": "This is the response"}"""
        result = agent._extract_grok_response(raw_output)
        assert result == "This is the response"

    def test_extract_grok_skips_tool_messages(self):
        """Test that tool use messages are skipped."""
        from aragora.agents.cli_agents import GrokCLIAgent

        agent = GrokCLIAgent(name="test", model="grok-4")
        raw_output = """{"role": "assistant", "content": "Using tools..."}
{"role": "assistant", "content": "Final answer"}"""
        result = agent._extract_grok_response(raw_output)
        assert result == "Final answer"

    def test_extract_grok_non_json(self):
        """Test extraction when output is not JSON."""
        from aragora.agents.cli_agents import GrokCLIAgent

        agent = GrokCLIAgent(name="test", model="grok-4")
        raw_output = "Plain text response"
        result = agent._extract_grok_response(raw_output)
        assert result == "Plain text response"


class TestKiloCodeResponseExtraction:
    """Tests for KiloCode response extraction."""

    def test_extract_kilocode_assistant_response(self):
        """Test extraction of assistant response from JSON."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test", provider_id="gemini-explorer")
        raw_output = '{"role": "assistant", "content": "Analysis complete"}'
        result = agent._extract_kilocode_response(raw_output)
        assert result == "Analysis complete"

    def test_extract_kilocode_text_type(self):
        """Test extraction from text type messages."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test", provider_id="gemini-explorer")
        raw_output = '{"type": "text", "text": "Some text content"}'
        result = agent._extract_kilocode_response(raw_output)
        assert result == "Some text content"

    def test_extract_kilocode_multiple_responses(self):
        """Test extraction with multiple assistant responses."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test", provider_id="gemini-explorer")
        raw_output = """{"role": "assistant", "content": "Part 1"}
{"role": "assistant", "content": "Part 2"}"""
        result = agent._extract_kilocode_response(raw_output)
        assert "Part 1" in result
        assert "Part 2" in result


class TestOpenAIResponseExtraction:
    """Tests for OpenAI CLI response extraction."""

    def test_extract_openai_json_response(self):
        """Test extraction from OpenAI JSON response."""
        from aragora.agents.cli_agents import OpenAIAgent

        agent = OpenAIAgent(name="test", model="gpt-4o")
        raw_output = '{"choices": [{"message": {"content": "API response"}}]}'
        result = agent._extract_openai_response(raw_output)
        assert result == "API response"

    def test_extract_openai_no_choices(self):
        """Test extraction when no choices in response."""
        from aragora.agents.cli_agents import OpenAIAgent

        agent = OpenAIAgent(name="test", model="gpt-4o")
        raw_output = '{"data": "something"}'
        result = agent._extract_openai_response(raw_output)
        assert result == '{"data": "something"}'

    def test_extract_openai_invalid_json(self):
        """Test extraction when response is not JSON."""
        from aragora.agents.cli_agents import OpenAIAgent

        agent = OpenAIAgent(name="test", model="gpt-4o")
        raw_output = "Plain text response"
        result = agent._extract_openai_response(raw_output)
        assert result == "Plain text response"


# =============================================================================
# Error Detection Tests
# =============================================================================


class TestFallbackErrorDetection:
    """Tests for error classification and fallback detection."""

    def test_detects_rate_limit_errors(self):
        """Test detection of rate limit errors."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")

        assert agent._is_fallback_error(Exception("rate limit exceeded"))
        assert agent._is_fallback_error(Exception("429 Too Many Requests"))
        assert agent._is_fallback_error(Exception("RateLimitError"))

    def test_detects_quota_errors(self):
        """Test detection of quota/billing errors."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")

        assert agent._is_fallback_error(Exception("quota exceeded"))
        assert agent._is_fallback_error(Exception("credit balance is too low"))
        assert agent._is_fallback_error(Exception("billing issue"))

    def test_detects_network_errors(self):
        """Test detection of network errors."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")

        assert agent._is_fallback_error(Exception("ECONNREFUSED"))
        assert agent._is_fallback_error(Exception("network is unreachable"))
        assert agent._is_fallback_error(Exception("connection reset"))

    def test_detects_timeout_errors(self):
        """Test detection of timeout errors."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")

        assert agent._is_fallback_error(TimeoutError("Request timed out"))
        assert agent._is_fallback_error(Exception("timed out"))

    def test_ignores_regular_errors(self):
        """Test that regular errors are not classified as fallback errors."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")

        assert not agent._is_fallback_error(Exception("invalid argument"))
        assert not agent._is_fallback_error(Exception("syntax error"))
        assert not agent._is_fallback_error(ValueError("bad value"))


# =============================================================================
# Circuit Breaker Integration Tests
# =============================================================================


class TestCircuitBreakerIntegration:
    """Tests for circuit breaker integration."""

    def test_circuit_breaker_created_by_default(self):
        """Test that circuit breaker is created by default."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        assert agent.circuit_breaker is not None
        assert agent.enable_circuit_breaker is True

    def test_circuit_breaker_can_be_disabled(self):
        """Test that circuit breaker can be disabled."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude", enable_circuit_breaker=False)
        assert agent.circuit_breaker is None

    def test_circuit_breaker_can_be_injected(self):
        """Test that circuit breaker can be injected."""
        from aragora.agents.cli_agents import ClaudeAgent
        from aragora.resilience import CircuitBreaker

        custom_cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30)
        agent = ClaudeAgent(name="test", model="claude", circuit_breaker=custom_cb)
        assert agent.circuit_breaker is custom_cb

    def test_is_circuit_open_false_initially(self):
        """Test circuit is closed initially."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        assert agent.is_circuit_open() is False

    def test_is_circuit_open_without_breaker(self):
        """Test is_circuit_open returns False when breaker disabled."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude", enable_circuit_breaker=False)
        assert agent.is_circuit_open() is False


# =============================================================================
# OpenRouter Model Mapping Tests
# =============================================================================


class TestOpenRouterModelMapping:
    """Tests for OpenRouter model mapping in fallback.

    CLIAgent no longer carries a static OPENROUTER_MODEL_MAP:
    _get_fallback_agent() resolves the current model through the catalog
    and upgrade map instead (frontier-model-refresh, 2026-09-04). Each test
    below exercises that resolution directly via _get_fallback_agent().
    """

    @staticmethod
    def _fallback_model(agent):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                mock_or.return_value = MagicMock()
                agent._get_fallback_agent()
                return mock_or.call_args[1]["model"]

    def test_claude_model_mapping(self):
        """Test Claude models map to OpenRouter correctly."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude-opus-4-5-20251101", enable_fallback=True)
        assert self._fallback_model(agent).startswith("anthropic/claude")

    def test_gpt_model_mapping(self):
        """Test GPT models map to OpenRouter correctly."""
        from aragora.agents.cli_agents import CodexAgent

        # gpt-4o preserves its value tier (round-4 re-review of finding
        # C-P3 on #9989); a flagship-line spelling still reaches Astra.
        agent = CodexAgent(name="test", model="gpt-4o", enable_fallback=True)
        assert self._fallback_model(agent) == "openai/gpt-5.6-terra"
        flagship = CodexAgent(name="test", model="gpt-5.5", enable_fallback=True)
        assert self._fallback_model(flagship) == "openai/gpt-6-astra"

    def test_gemini_model_mapping(self):
        """Test Gemini models map to OpenRouter correctly."""
        from aragora.agents.cli_agents import GeminiCLIAgent

        agent = GeminiCLIAgent(name="test", model="gemini-3.1-pro-preview", enable_fallback=True)
        assert self._fallback_model(agent) == "google/gemini-3.1-pro-preview"

        agent2 = GeminiCLIAgent(name="test", model="gemini-3.1-pro", enable_fallback=True)
        assert self._fallback_model(agent2) == "google/gemini-3.1-pro-preview"

    def test_grok_model_mapping(self):
        """Test Grok models map to OpenRouter correctly."""
        from aragora.agents.cli_agents import GrokCLIAgent

        agent = GrokCLIAgent(name="test", model="grok-4", enable_fallback=True)
        assert self._fallback_model(agent).startswith("x-ai/")


# =============================================================================
# API Agent Tests
# =============================================================================


class TestAnthropicAgentInitialization:
    """Tests for Anthropic API agent initialization."""

    def test_initialization_with_api_key(self):
        """Test agent initialization with API key."""
        from aragora.agents.api_agents import AnthropicAPIAgent

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            agent = AnthropicAPIAgent(name="test")
            assert agent.agent_type == "anthropic"
            assert agent.name == "test"

    def test_initialization_with_explicit_key(self):
        """Test agent initialization with explicit API key."""
        from aragora.agents.api_agents import AnthropicAPIAgent

        agent = AnthropicAPIAgent(name="test", api_key="explicit-key")
        assert agent.api_key == "explicit-key"

    def test_fallback_enabled_by_default(self):
        """Test that fallback follows the shared fallback-enabled setting."""
        from aragora.agents.api_agents import AnthropicAPIAgent

        with (
            patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}),
            patch("aragora.agents.fallback.get_default_fallback_enabled", return_value=False),
        ):
            agent = AnthropicAPIAgent(name="test")
            assert agent.enable_fallback is False

    def test_fallback_can_be_disabled(self):
        """Test that fallback can be disabled."""
        from aragora.agents.api_agents import AnthropicAPIAgent

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            agent = AnthropicAPIAgent(name="test", enable_fallback=False)
            assert agent.enable_fallback is False


class TestOpenAIAPIAgentInitialization:
    """Tests for OpenAI API agent initialization."""

    def test_initialization_with_api_key(self):
        """Test agent initialization with API key."""
        from aragora.agents.api_agents import OpenAIAPIAgent

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            agent = OpenAIAPIAgent(name="test")
            assert agent.agent_type == "openai"

    def test_default_model(self):
        """Test default model is set correctly."""
        from aragora.agents.api_agents import OpenAIAPIAgent

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            agent = OpenAIAPIAgent(name="test")
            assert "gpt" in agent.model.lower()


class TestGeminiAgentInitialization:
    """Tests for Gemini API agent initialization."""

    def test_initialization_with_api_key(self):
        """Test agent initialization with API key."""
        from aragora.agents.api_agents import GeminiAgent

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            agent = GeminiAgent(name="test")
            assert agent.agent_type == "gemini"


class TestGrokAgentInitialization:
    """Tests for Grok API agent initialization."""

    def test_initialization_with_api_key(self):
        """Test agent initialization with API key."""
        from aragora.agents.api_agents import GrokAgent

        with patch.dict("os.environ", {"XAI_API_KEY": "test-key"}):
            agent = GrokAgent(name="test")
            assert agent.agent_type == "grok"


class TestOpenRouterAgentInitialization:
    """Tests for OpenRouter API agent initialization."""

    def test_initialization_with_api_key(self):
        """Test agent initialization with API key."""
        from aragora.agents.api_agents import OpenRouterAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent(name="test")
            assert agent.agent_type == "openrouter"

    def test_custom_model(self):
        """Test custom model can be specified."""
        from aragora.agents.api_agents import OpenRouterAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = OpenRouterAgent(name="test", model="anthropic/claude-3-opus")
            assert agent.model == "anthropic/claude-3-opus"


# =============================================================================
# Quota Fallback Mixin Tests
# =============================================================================


class TestQuotaFallbackMixin:
    """Tests for the QuotaFallbackMixin."""

    def test_is_quota_error_429(self):
        """Test 429 status is detected as quota error."""
        from aragora.agents.fallback import QuotaFallbackMixin

        mixin = QuotaFallbackMixin()
        assert mixin.is_quota_error(429, "") is True

    def test_is_quota_error_403_with_quota_keyword(self):
        """Test 403 with quota keyword is detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        mixin = QuotaFallbackMixin()
        assert mixin.is_quota_error(403, "quota exceeded") is True
        assert mixin.is_quota_error(403, "billing issue") is True

    def test_is_quota_error_403_without_keyword(self):
        """Test 403 without quota keyword is not detected."""
        from aragora.agents.fallback import QuotaFallbackMixin

        mixin = QuotaFallbackMixin()
        assert mixin.is_quota_error(403, "access denied") is False

    def test_is_quota_error_keywords_in_message(self):
        """Test quota keywords in error message."""
        from aragora.agents.fallback import QuotaFallbackMixin

        mixin = QuotaFallbackMixin()
        assert mixin.is_quota_error(500, "rate limit exceeded") is True
        assert mixin.is_quota_error(500, "credit balance is too low") is True

    def test_get_fallback_model_with_mapping(self):
        """get_fallback_model() resolves the current model through the
        catalog/upgrade map (frontier-model-refresh, 2026-09-04 review fix
        round 1, item 3), not the (vestigial) OPENROUTER_MODEL_MAP class
        attribute: "test-model" isn't a real model id, so it falls back to
        DEFAULT_FALLBACK_MODEL regardless of what OPENROUTER_MODEL_MAP
        says."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestMixin(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {"test-model": "mapped/model"}
            DEFAULT_FALLBACK_MODEL = "default/model"
            model = "test-model"

        mixin = TestMixin()
        assert mixin.get_fallback_model() == "default/model"

    def test_get_fallback_model_default(self):
        """Test fallback model retrieval with no mapping."""
        from aragora.agents.fallback import QuotaFallbackMixin

        class TestMixin(QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {}
            DEFAULT_FALLBACK_MODEL = "default/model"
            model = "unmapped-model"

        mixin = TestMixin()
        assert mixin.get_fallback_model() == "default/model"


# =============================================================================
# Agent Fallback Chain Tests
# =============================================================================


class TestAgentFallbackChain:
    """Tests for AgentFallbackChain."""

    def test_initialization(self):
        """Test fallback chain initialization."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(
            providers=["openai", "openrouter", "anthropic"],
            max_retries=3,
        )
        assert chain.providers == ["openai", "openrouter", "anthropic"]
        assert chain.max_retries == 3

    def test_register_provider(self):
        """Test registering provider factories."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["test"])
        chain.register_provider("test", lambda: MagicMock())

        assert "test" in chain._provider_factories

    def test_get_available_providers_no_circuit_breaker(self):
        """Test available providers without circuit breaker."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["a", "b", "c"])
        assert chain.get_available_providers() == ["a", "b", "c"]

    def test_get_status(self):
        """Test getting chain status."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["openai", "openrouter"])
        status = chain.get_status()

        assert "providers" in status
        assert "metrics" in status
        assert "limits" in status

    def test_reset_metrics(self):
        """Test resetting metrics."""
        from aragora.agents.fallback import AgentFallbackChain

        chain = AgentFallbackChain(providers=["test"])
        chain.metrics.primary_attempts = 10
        chain.reset_metrics()

        assert chain.metrics.primary_attempts == 0


class TestFallbackMetrics:
    """Tests for FallbackMetrics."""

    def test_record_primary_attempt_success(self):
        """Test recording successful primary attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=True)

        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 1
        assert metrics.total_failures == 0

    def test_record_primary_attempt_failure(self):
        """Test recording failed primary attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_primary_attempt(success=False)

        assert metrics.primary_attempts == 1
        assert metrics.primary_successes == 0
        assert metrics.total_failures == 1

    def test_record_fallback_attempt(self):
        """Test recording fallback attempt."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.record_fallback_attempt("openrouter", success=True)

        assert metrics.fallback_attempts == 1
        assert metrics.fallback_successes == 1
        assert metrics.fallback_providers_used == {"openrouter": 1}

    def test_fallback_rate_calculation(self):
        """Test fallback rate calculation."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.primary_attempts = 8
        metrics.fallback_attempts = 2

        assert metrics.fallback_rate == 0.2

    def test_fallback_rate_zero_attempts(self):
        """Test fallback rate with zero attempts."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        assert metrics.fallback_rate == 0.0

    def test_success_rate_calculation(self):
        """Test success rate calculation."""
        from aragora.agents.fallback import FallbackMetrics

        metrics = FallbackMetrics()
        metrics.primary_attempts = 10
        metrics.primary_successes = 7
        metrics.fallback_attempts = 3
        metrics.fallback_successes = 2

        # 9 successes out of 13 attempts
        assert metrics.success_rate == 9 / 13


# =============================================================================
# Critique Parsing Tests
# =============================================================================


class TestCritiqueParsing:
    """Tests for critique response parsing."""

    def test_parse_critique_structured_format(self):
        """Test parsing structured critique response."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        response = """ISSUES:
- Issue one
- Issue two

SUGGESTIONS:
- Suggestion one

SEVERITY: 0.7
REASONING: This is the reasoning."""

        critique = agent._parse_critique(response, "proposal", "test proposal")
        assert critique is not None
        # Critique.severity uses 0-10 scale (see aragora/core.py)
        # Input "SEVERITY: 0.7" is detected as 0-1 scale and converted to 7.0
        assert critique.severity >= 0.0
        assert critique.severity <= 10.0
        assert len(critique.issues) >= 1

    def test_parse_critique_minimal_format(self):
        """Test parsing minimal critique response."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        response = "This is good overall."

        critique = agent._parse_critique(response, "proposal", "test proposal")
        assert critique is not None


# =============================================================================
# Fallback Agent Creation Tests
# =============================================================================


class TestFallbackAgentCreation:
    """Tests for fallback agent creation."""

    def test_get_fallback_agent_no_api_key(self):
        """Test fallback agent is None when no API key."""
        from aragora.agents.cli_agents import ClaudeAgent
        import os

        # Remove API key temporarily
        original = os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            agent = ClaudeAgent(name="test", model="claude", enable_fallback=True)
            fallback = agent._get_fallback_agent()
            assert fallback is None
        finally:
            if original:
                os.environ["OPENROUTER_API_KEY"] = original

    def test_get_fallback_agent_with_api_key(self):
        """Test fallback agent is created when API key available and fallback enabled."""
        from aragora.agents.cli_agents import ClaudeAgent
        import os

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = ClaudeAgent(name="test", model="claude", enable_fallback=True)
            fallback = agent._get_fallback_agent()
            assert fallback is not None
            assert "fallback" in fallback.name

    def test_get_fallback_agent_disabled(self):
        """Test fallback agent is None when disabled."""
        from aragora.agents.cli_agents import ClaudeAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = ClaudeAgent(name="test", model="claude", enable_fallback=False)
            fallback = agent._get_fallback_agent()
            assert fallback is None

    def test_fallback_agent_inherits_system_prompt(self):
        """Test fallback agent inherits system prompt when fallback enabled."""
        from aragora.agents.cli_agents import ClaudeAgent

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            agent = ClaudeAgent(name="test", model="claude", enable_fallback=True)
            agent.system_prompt = "Custom system prompt"
            fallback = agent._get_fallback_agent()
            assert fallback is not None
            assert fallback.system_prompt == "Custom system prompt"


# =============================================================================
# Prefer API Mode Tests
# =============================================================================


class TestPreferAPIMode:
    """Tests for prefer_api mode (skip CLI)."""

    def test_prefer_api_default_false(self):
        """Test prefer_api is False by default."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude")
        assert agent.prefer_api is False

    def test_prefer_api_can_be_enabled(self):
        """Test prefer_api can be set to True."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="test", model="claude", prefer_api=True)
        assert agent.prefer_api is True


# =============================================================================
# KiloCode Agent Tests
# =============================================================================


class TestKiloCodeAgentConfiguration:
    """Tests for KiloCode agent configuration."""

    def test_default_provider_id(self):
        """Test default provider ID."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test")
        assert agent.provider_id == "google/gemini-3.1-pro-preview"

    def test_custom_provider_id(self):
        """Test custom provider ID."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test", provider_id="grok-explorer")
        assert agent.provider_id == "grok-explorer"

    def test_default_mode(self):
        """Test default mode is architect."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test")
        assert agent.mode == "architect"

    def test_custom_mode(self):
        """Test custom mode."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test", mode="code")
        assert agent.mode == "code"

    def test_longer_default_timeout(self):
        """Test KiloCode has longer default timeout."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="test")
        assert agent.timeout == 600  # 10 minutes


# =============================================================================
# Agent Registry Tests
# =============================================================================


class TestAgentRegistration:
    """Tests for agent registration in the registry."""

    def test_codex_registered(self):
        """Test CodexAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        all_agents = AgentRegistry.list_all()
        assert "codex" in all_agents
        assert all_agents["codex"]["type"] == "CLI"

    def test_claude_registered(self):
        """Test ClaudeAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        all_agents = AgentRegistry.list_all()
        assert "claude" in all_agents
        assert all_agents["claude"]["type"] == "CLI"

    def test_anthropic_api_registered(self):
        """Test AnthropicAPIAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        all_agents = AgentRegistry.list_all()
        assert "anthropic-api" in all_agents
        assert all_agents["anthropic-api"]["type"] == "API"

    def test_list_available_agents(self):
        """Test listing available agents."""
        from aragora.agents.registry import AgentRegistry

        agents = AgentRegistry.list_all()
        assert len(agents) > 0
        # Should have both CLI and API agents
        agent_types = set(a.get("type") for a in agents.values())
        assert "CLI" in agent_types
        assert "API" in agent_types
