"""
Tests for CLI-based agent implementations.

Tests the CLIAgent base class and specific implementations:
- Initialization and configuration
- Circuit breaker integration
- OpenRouter fallback on errors
- Subprocess management with semaphore
- Context prompt building
- Critique functionality
- Specific agent implementations (Codex, Claude, Gemini, Grok, Qwen, Deepseek, KiloCode)
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Message
from aragora.agents.cli_agents import CLIAgent as _CLIAgent


class DummyCLIAgent(_CLIAgent):
    """Concrete CLIAgent for testing base behavior."""

    async def generate(self, prompt: str, context=None) -> str:  # type: ignore[override]
        return "ok"


# =============================================================================
# CLIAgent Base Class Tests
# =============================================================================


class TestCLIAgentInit:
    """Test CLIAgent initialization."""

    def test_init_minimal(self):
        """Test minimal initialization."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        assert agent.name == "test-agent"
        assert agent.model == "test-model"
        assert agent.role == "proposer"  # default
        assert agent.timeout == 300  # default
        assert agent.enable_circuit_breaker is True

    def test_init_with_custom_role(self):
        """Test initialization with custom role."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", role="critic")

        assert agent.role == "critic"

    def test_init_with_custom_timeout(self):
        """Test initialization with custom timeout."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", timeout=600)

        assert agent.timeout == 600

    def test_init_with_fallback_enabled(self):
        """Test initialization with fallback explicitly enabled."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", enable_fallback=True)

        assert agent.enable_fallback is True

    def test_init_with_fallback_disabled(self):
        """Test initialization with fallback explicitly disabled."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", enable_fallback=False)

        assert agent.enable_fallback is False

    def test_init_with_circuit_breaker_disabled(self):
        """Test initialization with circuit breaker disabled."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", enable_circuit_breaker=False)

        assert agent.enable_circuit_breaker is False
        assert agent._circuit_breaker is None

    def test_init_with_prefer_api(self):
        """Test initialization with prefer_api flag."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", prefer_api=True)

        assert agent.prefer_api is True


class TestCLIAgentCircuitBreaker:
    """Test circuit breaker integration."""

    def test_circuit_breaker_property(self):
        """Test circuit_breaker property."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        assert agent.circuit_breaker is not None

    def test_circuit_breaker_with_custom_instance(self):
        """Test initialization with custom circuit breaker."""
        from aragora.agents.cli_agents import CLIAgent
        from aragora.resilience import CircuitBreaker

        custom_cb = CircuitBreaker(name="custom", failure_threshold=5)
        agent = DummyCLIAgent(name="test-agent", model="test-model", circuit_breaker=custom_cb)

        assert agent._circuit_breaker is custom_cb

    def test_is_circuit_open_returns_false_when_healthy(self):
        """Test is_circuit_open returns False when circuit is healthy."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        assert agent.is_circuit_open() is False

    def test_is_circuit_open_without_breaker(self):
        """Test is_circuit_open returns False when no breaker."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", enable_circuit_breaker=False)

        assert agent.is_circuit_open() is False


class TestCLIAgentFallback:
    """Test OpenRouter fallback functionality."""

    def test_get_fallback_agent_when_disabled(self):
        """Test _get_fallback_agent returns None when disabled."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", enable_fallback=False)

        assert agent._get_fallback_agent() is None

    def test_get_fallback_agent_without_api_key(self):
        """Test _get_fallback_agent returns None without API key."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", enable_fallback=True)

        with patch.dict("os.environ", {}, clear=True):
            with patch("os.environ.get", return_value=None):
                result = agent._get_fallback_agent()

        assert result is None

    def test_get_fallback_agent_with_api_key(self):
        """Test _get_fallback_agent creates agent with API key."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="claude", enable_fallback=True)

        with patch.dict(
            "os.environ",
            {"ARAGORA_SECRETS_STRICT": "false", "OPENROUTER_API_KEY": "test-api-key"},
            clear=True,
        ):
            fallback = agent._get_fallback_agent()

        assert fallback is not None
        assert "fallback" in fallback.name

    def test_openrouter_model_mapping(self):
        """Test OPENROUTER_MODEL_MAP has expected mappings."""
        from aragora.agents.cli_agents import CLIAgent

        assert "claude" in CLIAgent.OPENROUTER_MODEL_MAP
        assert "gpt-4o" in CLIAgent.OPENROUTER_MODEL_MAP
        assert "gemini-3-pro" in CLIAgent.OPENROUTER_MODEL_MAP
        assert "grok-4" in CLIAgent.OPENROUTER_MODEL_MAP


class TestCLIAgentSanitization:
    """Test CLI argument sanitization."""

    def test_sanitize_cli_arg_removes_null_bytes(self):
        """Test null bytes are removed."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        result = agent._sanitize_cli_arg("hello\x00world")

        assert result == "helloworld"
        assert "\x00" not in result

    def test_sanitize_cli_arg_removes_control_characters(self):
        """Test control characters are removed."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        result = agent._sanitize_cli_arg("hello\x01\x02\x03world")

        assert result == "helloworld"

    def test_sanitize_cli_arg_preserves_newlines_and_tabs(self):
        """Test newlines and tabs are preserved."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        result = agent._sanitize_cli_arg("hello\nworld\there")

        assert "\n" in result
        assert "\t" in result

    def test_sanitize_cli_arg_handles_non_string(self):
        """Test non-string input is converted."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        result = agent._sanitize_cli_arg(123)

        assert result == "123"


class TestCLIAgentPromptBuilding:
    """Test context and prompt building."""

    def test_build_full_prompt_without_context(self):
        """Test building prompt without context."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        result = agent._build_full_prompt("Hello, world!")

        assert result == "Hello, world!"

    def test_build_full_prompt_with_system_prompt(self):
        """Test building prompt with system prompt."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")
        agent.system_prompt = "You are a helpful assistant."

        result = agent._build_full_prompt("Hello")

        assert "System context:" in result
        assert "helpful assistant" in result
        assert "Hello" in result

    def test_build_full_prompt_with_context(self):
        """Test building prompt with message context."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")
        context = [Message(agent="other", role="proposer", content="Previous message")]

        result = agent._build_full_prompt("New prompt", context)

        assert "Previous message" in result
        assert "New prompt" in result

    def test_is_prompt_too_large_for_argv(self):
        """Test prompt size check."""
        from aragora.agents.cli_agents import CLIAgent, MAX_CLI_PROMPT_CHARS

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        small_prompt = "x" * 1000
        large_prompt = "x" * (MAX_CLI_PROMPT_CHARS + 1000)

        assert agent._is_prompt_too_large_for_argv(small_prompt) is False
        assert agent._is_prompt_too_large_for_argv(large_prompt) is True


class TestCLIAgentErrorClassification:
    """Test error classification for fallback."""

    def test_is_fallback_error_rate_limit(self):
        """Test rate limit errors trigger fallback."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        error = RuntimeError("Rate limit exceeded for this API key")
        assert agent._is_fallback_error(error) is True

    def test_is_fallback_error_timeout(self):
        """Test timeout errors trigger fallback."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        error = TimeoutError("Request timed out")
        assert agent._is_fallback_error(error) is True

    def test_is_fallback_error_quota(self):
        """Test quota errors trigger fallback."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        error = RuntimeError("Quota exceeded - please upgrade your plan")
        assert agent._is_fallback_error(error) is True


# =============================================================================
# Specific Agent Implementation Tests
# =============================================================================


class TestCodexAgent:
    """Test CodexAgent implementation."""

    def test_codex_agent_exists(self):
        """Test CodexAgent class exists."""
        from aragora.agents.cli_agents import CodexAgent

        assert CodexAgent is not None

    def test_codex_agent_inherits_from_cli_agent(self):
        """Test CodexAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, CodexAgent

        assert issubclass(CodexAgent, CLIAgent)

    def test_codex_agent_init(self):
        """Test CodexAgent initialization."""
        from aragora.agents.cli_agents import CodexAgent

        agent = CodexAgent(name="codex-test", model="gpt-4.1-codex")

        assert agent.name == "codex-test"
        assert agent.model == "gpt-4.1-codex"

    def test_extract_codex_response_filters_header(self):
        """Test response extraction filters header."""
        from aragora.agents.cli_agents import CodexAgent

        agent = CodexAgent(name="codex-test", model="gpt-4.1-codex")

        output = "codex\nActual response text\ntokens used: 100"
        result = agent._extract_codex_response(output)

        assert result == "Actual response text"

    def test_extract_codex_response_handles_plain_output(self):
        """Test response extraction handles plain output."""
        from aragora.agents.cli_agents import CodexAgent

        agent = CodexAgent(name="codex-test", model="gpt-4.1-codex")

        output = "Plain response text"
        result = agent._extract_codex_response(output)

        assert result == "Plain response text"


class TestClaudeAgent:
    """Test ClaudeAgent implementation."""

    def test_claude_agent_exists(self):
        """Test ClaudeAgent class exists."""
        from aragora.agents.cli_agents import ClaudeAgent

        assert ClaudeAgent is not None

    def test_claude_agent_inherits_from_cli_agent(self):
        """Test ClaudeAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, ClaudeAgent

        assert issubclass(ClaudeAgent, CLIAgent)

    def test_claude_agent_init(self):
        """Test ClaudeAgent initialization."""
        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="claude-test", model="claude-sonnet-4")

        assert agent.name == "claude-test"

    @pytest.mark.asyncio
    async def test_claude_agent_pins_model_on_cli_command(self):
        """The CLI call must carry --model so receipts match the model that ran.

        Without the flag the CLI answers with the active profile's default
        while self.model is recorded — a silent misattribution (#9075 review).
        """
        from unittest.mock import AsyncMock, patch

        from aragora.agents.cli_agents import ClaudeAgent

        agent = ClaudeAgent(name="claude-test", model="claude-fable-5")
        captured: dict = {}

        async def fake_generate(command, *args, **kwargs):
            captured["command"] = command
            return "ok"

        with (
            patch.object(agent, "_generate_with_fallback", AsyncMock(side_effect=fake_generate)),
            patch(
                "aragora.agents.cli_agents.build_claude_command",
                side_effect=lambda cmd: (cmd, None),
            ),
        ):
            result = await agent.generate("hello")

        assert result == "ok"
        command = captured["command"]
        assert "--model" in command
        assert command[command.index("--model") + 1] == "claude-fable-5"


class TestGeminiCLIAgent:
    """Test GeminiCLIAgent implementation."""

    def test_gemini_agent_exists(self):
        """Test GeminiCLIAgent class exists."""
        from aragora.agents.cli_agents import GeminiCLIAgent

        assert GeminiCLIAgent is not None

    def test_gemini_agent_inherits_from_cli_agent(self):
        """Test GeminiCLIAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, GeminiCLIAgent

        assert issubclass(GeminiCLIAgent, CLIAgent)

    def test_extract_gemini_response_filters_yolo(self):
        """Test YOLO mode message is filtered."""
        from aragora.agents.cli_agents import GeminiCLIAgent

        agent = GeminiCLIAgent(name="gemini-test", model="gemini-3-pro")

        output = "YOLO mode is enabled\nActual response"
        result = agent._extract_gemini_response(output)

        assert "YOLO" not in result
        assert "Actual response" in result


class TestGrokCLIAgent:
    """Test GrokCLIAgent implementation."""

    def test_grok_agent_exists(self):
        """Test GrokCLIAgent class exists."""
        from aragora.agents.cli_agents import GrokCLIAgent

        assert GrokCLIAgent is not None

    def test_grok_agent_inherits_from_cli_agent(self):
        """Test GrokCLIAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, GrokCLIAgent

        assert issubclass(GrokCLIAgent, CLIAgent)

    def test_extract_grok_response_extracts_assistant(self):
        """Test assistant response is extracted from JSON."""
        from aragora.agents.cli_agents import GrokCLIAgent

        agent = GrokCLIAgent(name="grok-test", model="grok-4")

        output = '{"role": "assistant", "content": "Hello from Grok"}'
        result = agent._extract_grok_response(output)

        assert result == "Hello from Grok"

    def test_extract_grok_response_handles_plain_output(self):
        """Test plain text output is returned as-is."""
        from aragora.agents.cli_agents import GrokCLIAgent

        agent = GrokCLIAgent(name="grok-test", model="grok-4")

        output = "Plain text response"
        result = agent._extract_grok_response(output)

        assert result == "Plain text response"


class TestGrokBuildAgent:
    """Test GrokBuildAgent (xAI Grok Build subscription CLI)."""

    def test_exists_and_inherits(self):
        from aragora.agents.cli_agents import CLIAgent, GrokBuildAgent

        assert issubclass(GrokBuildAgent, CLIAgent)

    def test_resolve_bin_defaults_to_install_path(self, monkeypatch):
        import os

        from aragora.agents.cli_agents import _resolve_grok_build_bin

        monkeypatch.delenv("ARAGORA_GROK_BUILD_BIN", raising=False)
        # Must resolve the Grok Build install path, NOT the bare `grok` on PATH
        # (which is the unrelated/deprecated legacy grok-cli).
        assert _resolve_grok_build_bin() == os.path.expanduser("~/.grok/bin/grok")
        assert _resolve_grok_build_bin() != "grok"

    def test_resolve_bin_honors_override(self, monkeypatch):
        from aragora.agents.cli_agents import _resolve_grok_build_bin

        monkeypatch.setenv("ARAGORA_GROK_BUILD_BIN", "/custom/path/grok")
        assert _resolve_grok_build_bin() == "/custom/path/grok"

    def test_generate_invokes_grok_build_not_legacy(self, monkeypatch):
        import os
        from unittest.mock import patch

        from aragora.agents.cli_agents import GrokBuildAgent

        monkeypatch.delenv("ARAGORA_GROK_BUILD_BIN", raising=False)
        agent = GrokBuildAgent(
            name="grok-build-test",
            model="grok-build",
            enable_fallback=False,
            enable_circuit_breaker=False,
        )
        with patch.object(agent, "_run_cli", new=AsyncMock(return_value="OK")) as m:
            out = asyncio.run(agent.generate("review this PR"))
        assert out == "OK"
        cmd = m.call_args.args[0]
        assert cmd[0] == os.path.expanduser("~/.grok/bin/grok")
        assert cmd[0] != "grok"  # never the legacy PATH binary
        assert "--no-plan" in cmd and "-p" in cmd
        assert cmd[-1] == "review this PR"


class TestAntigravityAgent:
    """Test AntigravityAgent (Google Antigravity `agy` subscription CLI)."""

    def test_exists_and_inherits(self):
        from aragora.agents.cli_agents import AntigravityAgent, CLIAgent

        assert issubclass(AntigravityAgent, CLIAgent)

    def test_resolve_bin_defaults_to_install_path(self, monkeypatch):
        import os

        from aragora.agents.cli_agents import _resolve_antigravity_bin

        monkeypatch.delenv("ARAGORA_ANTIGRAVITY_BIN", raising=False)
        assert _resolve_antigravity_bin() == os.path.expanduser("~/.antigravity/bin/agy")
        assert _resolve_antigravity_bin() != "agy"

    def test_resolve_bin_honors_override(self, monkeypatch):
        from aragora.agents.cli_agents import _resolve_antigravity_bin

        monkeypatch.setenv("ARAGORA_ANTIGRAVITY_BIN", "/custom/path/agy")
        assert _resolve_antigravity_bin() == "/custom/path/agy"

    def test_generate_invokes_agy_print_mode(self):
        import os
        from unittest.mock import patch

        from aragora.agents.cli_agents import AntigravityAgent

        agent = AntigravityAgent(
            name="agy-test",
            model="gemini-3.5-flash",
            enable_fallback=False,
            enable_circuit_breaker=False,
        )
        with patch.object(agent, "_run_cli", new=AsyncMock(return_value="OK")) as m:
            out = asyncio.run(agent.generate("review this PR"))
        assert out == "OK"
        cmd = m.call_args.args[0]
        assert cmd[0] == os.path.expanduser("~/.antigravity/bin/agy")
        assert cmd[0] != "agy"
        assert "-p" in cmd
        assert cmd[-1] == "review this PR"


class TestKimiCLIAgent:
    """Test KimiCLIAgent (Moonshot Kimi, cheap-tier subscription/API family)."""

    def test_exists_and_inherits(self):
        from aragora.agents.cli_agents import CLIAgent, KimiCLIAgent

        assert issubclass(KimiCLIAgent, CLIAgent)

    def test_generate_invokes_kimi_cli(self):
        from unittest.mock import patch

        from aragora.agents.cli_agents import KimiCLIAgent

        agent = KimiCLIAgent(
            name="kimi-test",
            model="kimi-k2",
            enable_fallback=False,
            enable_circuit_breaker=False,
        )
        with patch.object(agent, "_run_cli", new=AsyncMock(return_value="OK")) as m:
            out = asyncio.run(agent.generate("review this PR"))
        assert out == "OK"
        cmd = m.call_args.args[0]
        assert cmd[0] == "kimi" and "-p" in cmd
        assert cmd[-1] == "review this PR"

    def test_kimi_not_registered_by_default(self):
        # kimi-cli's headless contract is unverified (ACP, not `-p`), so it must
        # be opt-in via ARAGORA_ENABLE_KIMI_CLI, never a default agent.
        from aragora.agents.registry import AgentRegistry

        assert AgentRegistry.is_registered("kimi-cli") is False


class TestQwenCLIAgent:
    """Test QwenCLIAgent implementation."""

    def test_qwen_agent_exists(self):
        """Test QwenCLIAgent class exists."""
        from aragora.agents.cli_agents import QwenCLIAgent

        assert QwenCLIAgent is not None

    def test_qwen_agent_inherits_from_cli_agent(self):
        """Test QwenCLIAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, QwenCLIAgent

        assert issubclass(QwenCLIAgent, CLIAgent)


class TestDeepseekCLIAgent:
    """Test DeepseekCLIAgent implementation."""

    def test_deepseek_agent_exists(self):
        """Test DeepseekCLIAgent class exists."""
        from aragora.agents.cli_agents import DeepseekCLIAgent

        assert DeepseekCLIAgent is not None

    def test_deepseek_agent_inherits_from_cli_agent(self):
        """Test DeepseekCLIAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, DeepseekCLIAgent

        assert issubclass(DeepseekCLIAgent, CLIAgent)


class TestKiloCodeAgent:
    """Test KiloCodeAgent implementation."""

    def test_kilocode_agent_exists(self):
        """Test KiloCodeAgent class exists."""
        from aragora.agents.cli_agents import KiloCodeAgent

        assert KiloCodeAgent is not None

    def test_kilocode_agent_inherits_from_cli_agent(self):
        """Test KiloCodeAgent inherits from CLIAgent."""
        from aragora.agents.cli_agents import CLIAgent, KiloCodeAgent

        assert issubclass(KiloCodeAgent, CLIAgent)

    def test_kilocode_agent_init(self):
        """Test KiloCodeAgent initialization with provider_id."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="kilo-test", provider_id="gemini-explorer")

        assert agent.name == "kilo-test"
        assert agent.provider_id == "gemini-explorer"
        assert agent.mode == "architect"  # default

    def test_kilocode_agent_init_custom_mode(self):
        """Test KiloCodeAgent initialization with custom mode."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="kilo-test", provider_id="gemini-explorer", mode="code")

        assert agent.mode == "code"

    def test_extract_kilocode_response_extracts_assistant(self):
        """Test assistant response is extracted from JSON output."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="kilo-test", provider_id="gemini-explorer")

        output = '{"role": "assistant", "content": "Analysis result"}'
        result = agent._extract_kilocode_response(output)

        assert "Analysis result" in result

    def test_extract_kilocode_response_handles_text_type(self):
        """Test text type messages are extracted."""
        from aragora.agents.cli_agents import KiloCodeAgent

        agent = KiloCodeAgent(name="kilo-test", provider_id="gemini-explorer")

        output = '{"type": "text", "text": "Some text output"}'
        result = agent._extract_kilocode_response(output)

        assert "Some text output" in result


# =============================================================================
# Agent Registry Integration Tests
# =============================================================================


class TestAgentRegistryIntegration:
    """Test agent registry integration."""

    def test_codex_registered(self):
        """Test CodexAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        import aragora.agents.cli_agents  # noqa: F401

        registry = AgentRegistry.list_all()

        assert "codex" in registry

    def test_claude_registered(self):
        """Test ClaudeAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        import aragora.agents.cli_agents  # noqa: F401

        registry = AgentRegistry.list_all()

        assert "claude" in registry

    def test_gemini_cli_registered(self):
        """Test GeminiCLIAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        import aragora.agents.cli_agents  # noqa: F401

        registry = AgentRegistry.list_all()

        assert "gemini-cli" in registry

    def test_grok_cli_registered(self):
        """Test GrokCLIAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        import aragora.agents.cli_agents  # noqa: F401

        registry = AgentRegistry.list_all()

        assert "grok-cli" in registry


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Test module exports."""

    def test_cli_agent_exportable(self):
        """Test CLIAgent can be imported."""
        from aragora.agents.cli_agents import CLIAgent

        assert CLIAgent is not None

    def test_all_agents_exportable(self):
        """Test all agent classes can be imported."""
        from aragora.agents.cli_agents import (
            ClaudeAgent,
            CodexAgent,
            DeepseekCLIAgent,
            GeminiCLIAgent,
            GrokCLIAgent,
            KiloCodeAgent,
            QwenCLIAgent,
        )

        assert CodexAgent is not None
        assert ClaudeAgent is not None
        assert GeminiCLIAgent is not None
        assert GrokCLIAgent is not None
        assert QwenCLIAgent is not None
        assert DeepseekCLIAgent is not None
        assert KiloCodeAgent is not None

    def test_constants_exportable(self):
        """Test constants can be imported."""
        from aragora.agents.cli_agents import (
            MAX_CLI_PROMPT_CHARS,
            MAX_CONTEXT_CHARS,
            MAX_MESSAGE_CHARS,
            RATE_LIMIT_PATTERNS,
        )

        assert MAX_CLI_PROMPT_CHARS > 0
        assert MAX_CONTEXT_CHARS > 0
        assert MAX_MESSAGE_CHARS > 0
        assert isinstance(RATE_LIMIT_PATTERNS, (list, tuple, frozenset))


# =============================================================================
# Async Operation Tests
# =============================================================================


class TestCLIAgentAsyncOps:
    """Test async CLI operations."""

    @pytest.mark.asyncio
    async def test_run_cli_timeout_handling(self):
        """Test CLI timeout raises TimeoutError."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model", timeout=1)

        with pytest.raises(TimeoutError):
            await agent._run_cli(["sleep", "10"])

    @pytest.mark.asyncio
    async def test_run_cli_success(self):
        """Test successful CLI execution."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        result = await agent._run_cli(["echo", "hello"])

        assert "hello" in result

    @pytest.mark.asyncio
    async def test_run_cli_records_success_to_circuit_breaker(self):
        """Test successful call records to circuit breaker."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")
        initial_state = agent._circuit_breaker.can_proceed()

        await agent._run_cli(["echo", "test"])

        # Circuit should still be open after success
        assert agent._circuit_breaker.can_proceed() is True

    @pytest.mark.asyncio
    async def test_run_cli_surfaces_stdout_when_stderr_empty(self):
        """When CLI writes error to stdout (not stderr), the error message includes it."""
        from aragora.agents.errors import CLISubprocessError

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        # Simulate a process that writes error to stdout only (like Claude CLI
        # "Credit balance is too low")
        with pytest.raises(CLISubprocessError, match="Credit balance is too low"):
            await agent._run_cli(["bash", "-c", "echo 'Credit balance is too low' && exit 1"])

    @pytest.mark.asyncio
    async def test_run_cli_prefers_stderr_over_stdout(self):
        """When both stderr and stdout have content, error message uses stderr."""
        from aragora.agents.errors import CLISubprocessError

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        with pytest.raises(CLISubprocessError, match="real error") as exc_info:
            await agent._run_cli(
                ["bash", "-c", "echo 'stdout noise'; echo 'real error' >&2; exit 1"]
            )
        # Should NOT contain stdout noise
        assert "stdout noise" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_run_cli_no_output_message(self):
        """When both stderr and stdout are empty, error says 'no output'."""
        from aragora.agents.errors import CLISubprocessError

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        with pytest.raises(CLISubprocessError, match="no output"):
            await agent._run_cli(["bash", "-c", "exit 1"])


# =============================================================================
# Critique Functionality Tests
# =============================================================================


class TestCLIAgentCritique:
    """Test critique functionality."""

    def test_build_critique_prompt(self):
        """Test critique prompt building."""
        from aragora.agents.cli_agents import CLIAgent

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        prompt = agent._build_critique_prompt("My proposal", "Design a system")

        assert "Design a system" in prompt
        assert "My proposal" in prompt
        assert "ISSUES" in prompt
        assert "SEVERITY" in prompt

    @pytest.mark.asyncio
    async def test_critique_returns_critique_object(self):
        """Test critique method returns Critique object."""
        from aragora.agents.cli_agents import CLIAgent
        from aragora.core import Critique

        agent = DummyCLIAgent(name="test-agent", model="test-model")

        with patch.object(
            agent,
            "generate",
            return_value="ISSUES: None\nSUGGESTIONS: None\nSEVERITY: 2\nREASONING: Good",
        ):
            result = await agent.critique("Proposal text", "Task description")

        assert isinstance(result, Critique)
