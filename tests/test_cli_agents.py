"""
Tests for CLI Agent implementations.

Tests cover:
- CLIAgent base class (_run_cli, _parse_critique, context building)
- CodexAgent, ClaudeAgent, GeminiCLIAgent, KiloCodeAgent
- GrokCLIAgent, QwenCLIAgent, DeepseekCLIAgent, OpenAIAgent
- create_agent() factory function
- list_available_agents() utility
"""

import asyncio
import json
import signal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.agents.cli_agents as cli_agents_mod
from aragora.agents.cli_agents import (
    CLIAgent,
    ClaudeAgent,
    CodexAgent,
    DeepseekCLIAgent,
    GeminiCLIAgent,
    GrokCLIAgent,
    KiloCodeAgent,
    OpenAIAgent,
    QwenCLIAgent,
    MAX_CONTEXT_CHARS,
    MAX_MESSAGE_CHARS,
)
from aragora.agents.base import create_agent, list_available_agents
from aragora.agents.errors.exceptions import CLISubprocessError, AgentStreamError
from aragora.core import Critique, Message


# =============================================================================
# CLIAgent Base Class Tests
# =============================================================================


class TestCLIAgentRunCli:
    """Tests for CLIAgent._run_cli() method."""

    @pytest.fixture
    def agent(self):
        """Create a CodexAgent for testing."""
        return CodexAgent(name="test", model="test-model", timeout=5)

    @pytest.mark.asyncio
    async def test_successful_command_execution(self, agent):
        """Should execute command and return stdout."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"Hello World", b""))
            mock_exec.return_value = mock_proc

            result = await agent._run_cli(["echo", "test"])

            assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_command_with_stdin_input(self, agent):
        """Should pass input_text to stdin."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"Received", b""))
            mock_exec.return_value = mock_proc

            result = await agent._run_cli(["cat"], input_text="Test input")

            mock_proc.communicate.assert_called_once()
            call_kwargs = mock_proc.communicate.call_args
            assert call_kwargs[1]["input"] == b"Test input"

    @pytest.mark.asyncio
    async def test_command_sanitizes_arguments(self, agent):
        """Should sanitize command arguments."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"ok", b""))
            mock_exec.return_value = mock_proc

            # Command with null byte
            await agent._run_cli(["echo", "Hello\x00World"])

            # Check sanitized command was used
            call_args = mock_exec.call_args[0]
            assert "\x00" not in call_args[1]

    @pytest.mark.asyncio
    async def test_timeout_raises_timeout_error(self, agent):
        """Should raise TimeoutError on timeout."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = None
            mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            with pytest.raises(TimeoutError, match="timed out"):
                await agent._run_cli(["sleep", "100"])

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, agent):
        """Should kill process on timeout."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = None
            mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            with pytest.raises(TimeoutError):
                await agent._run_cli(["sleep", "100"])

            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancelled_error_kills_process(self, agent):
        """Should kill process when coroutine is cancelled."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.pid = 4242
            mock_proc.returncode = None
            mock_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError())
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            with pytest.raises(asyncio.CancelledError):
                await agent._run_cli(["sleep", "100"])

            mock_proc.kill.assert_called_once()
            mock_proc.wait.assert_called_once()
            assert 4242 not in cli_agents_mod._tracked_cli_pids

    @pytest.mark.asyncio
    async def test_error_kills_process(self, agent):
        """Should kill process on error."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = None
            mock_proc.communicate = AsyncMock(side_effect=OSError("Test error"))
            mock_proc.kill = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc

            with pytest.raises(OSError, match="Test error"):
                await agent._run_cli(["bad", "command"])

            mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_runtime_error(self, agent):
        """Should raise RuntimeError on non-zero exit."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Error message"))
            mock_exec.return_value = mock_proc

            with pytest.raises(CLISubprocessError, match="CLI command failed"):
                await agent._run_cli(["false"])

    @pytest.mark.asyncio
    async def test_stderr_captured_in_error(self, agent):
        """Should include stderr in error message."""
        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Specific error details"))
            mock_exec.return_value = mock_proc

            with pytest.raises(CLISubprocessError, match="Specific error details"):
                await agent._run_cli(["bad"])


class TestCLIAgentBuildContextPrompt:
    """Tests for CLIAgent._build_context_prompt() method."""

    @pytest.fixture
    def agent(self):
        return CodexAgent(name="test", model="test")

    def test_limits_to_last_10_messages(self, agent):
        """Should only include last 10 messages."""
        messages = [
            Message(role="proposer", agent=f"agent{i}", content=f"Message {i}", round=i)
            for i in range(15)
        ]
        result = agent._build_context_prompt(messages)

        # Should have messages 5-14 (last 10)
        assert "Message 5" in result
        assert "Message 14" in result
        # Should not have earlier messages
        assert "Message 0" not in result
        assert "Message 4" not in result

    def test_truncates_individual_long_messages(self, agent):
        """Should truncate messages exceeding MAX_MESSAGE_CHARS."""
        long_content = "x" * (MAX_MESSAGE_CHARS + 1000)
        messages = [Message(role="proposer", agent="test", content=long_content, round=1)]

        result = agent._build_context_prompt(messages)

        # Should be truncated
        assert len(result) < len(long_content)
        assert "truncated" in result.lower()

    def test_truncates_total_context(self, agent):
        """Should truncate when total context exceeds MAX_CONTEXT_CHARS."""
        # Create many messages that together exceed limit
        large_content = "y" * 15000
        messages = [
            Message(role="proposer", agent=f"a{i}", content=large_content, round=i)
            for i in range(10)
        ]

        result = agent._build_context_prompt(messages)

        # Total should not exceed limit significantly
        assert len(result) <= MAX_CONTEXT_CHARS + 1000


class TestTrackedCLISubprocessCleanup:
    """Tests for tracked subprocess cleanup helpers."""

    def test_terminate_tracked_cli_processes_noop_when_empty(self):
        """Cleanup should return zeroed summary when nothing is tracked."""
        with cli_agents_mod._tracked_cli_pids_lock:
            cli_agents_mod._tracked_cli_pids.clear()
        summary = cli_agents_mod.terminate_tracked_cli_processes(grace_seconds=0.0)
        assert summary == {"tracked": 0, "terminated": 0, "killed": 0, "remaining": 0}

    def test_terminate_tracked_cli_processes_sends_term_then_kill(self, monkeypatch):
        """Cleanup should send SIGTERM then SIGKILL for stuck processes."""
        with cli_agents_mod._tracked_cli_pids_lock:
            cli_agents_mod._tracked_cli_pids.clear()
            cli_agents_mod._tracked_cli_pids.add(11111)

        alive = {"value": True}
        calls: list[tuple[int, int]] = []

        def _fake_kill(pid: int, sig: int) -> None:
            calls.append((pid, sig))
            if sig == 0:
                if alive["value"]:
                    return
                raise ProcessLookupError()
            if sig == signal.SIGTERM:
                return
            if sig == signal.SIGKILL:
                alive["value"] = False
                return
            raise AssertionError(f"Unexpected signal {sig}")

        monkeypatch.setattr(cli_agents_mod.os, "kill", _fake_kill)
        monkeypatch.setattr(cli_agents_mod.time, "sleep", lambda _s: None)

        summary = cli_agents_mod.terminate_tracked_cli_processes(grace_seconds=0.0)

        assert summary["tracked"] == 1
        assert summary["terminated"] == 1
        assert summary["killed"] == 1
        assert summary["remaining"] == 0
        assert (11111, signal.SIGTERM) in calls
        assert (11111, signal.SIGKILL) in calls


class TestCLIAgentParseCritique:
    """Tests for CLIAgent._parse_critique() method."""

    @pytest.fixture
    def agent(self):
        return CodexAgent(name="test", model="test")

    def test_parses_structured_format(self, agent):
        """Should parse structured critique with issues and suggestions."""
        # Note: Item text must not contain 'issue', 'problem', 'suggest', etc.
        # as those trigger section detection instead of item addition
        response = """
ISSUES:
- First error found
- Second error found

SUGGESTIONS:
- Fix the first one
- Fix the second one

SEVERITY: 0.7
REASONING: This needs work because of X and Y.
"""
        critique = agent._parse_critique(response, "target", "content")

        assert isinstance(critique, Critique)
        assert len(critique.issues) == 2
        assert "First error found" in critique.issues
        assert len(critique.suggestions) == 2
        assert "Fix the first one" in critique.suggestions

    def test_parses_severity_from_text(self, agent):
        """Should extract severity value on 0-10 scale."""
        response = "SEVERITY: 0.8\nSome other text"
        critique = agent._parse_critique(response, "target", "content")
        # 0.8 <= 1.0, so it gets scaled to 0-10: 0.8 * 10 = 8.0
        assert critique.severity == pytest.approx(8.0, abs=0.01)

    def test_handles_0_to_10_scale_conversion(self, agent):
        """Values > 1 are kept on the 0-10 scale and clamped to [0, 10].

        The severity system now uses a 0-10 scale natively. Values > 1.0
        are treated as already on the 0-10 scale and clamped via
        min(10.0, max(0.0, value)).
        """
        response = "SEVERITY: 7\nSome issues here"
        critique = agent._parse_critique(response, "target", "content")
        # Value 7 > 1.0, stays as-is on 0-10 scale
        assert critique.severity == pytest.approx(7.0, abs=0.01)

    def test_handles_unstructured_response(self, agent):
        """Should handle plain text without structure."""
        response = "This is not great. There are problems. Consider fixing it."
        critique = agent._parse_critique(response, "target", "content")

        assert isinstance(critique, Critique)
        assert len(critique.issues) > 0 or len(critique.reasoning) > 0

    def test_limits_to_5_issues(self, agent):
        """Should limit issues to 5."""
        response = """
ISSUES:
- Issue 1
- Issue 2
- Issue 3
- Issue 4
- Issue 5
- Issue 6
- Issue 7
"""
        critique = agent._parse_critique(response, "target", "content")
        assert len(critique.issues) <= 5

    def test_limits_to_5_suggestions(self, agent):
        """Should limit suggestions to 5."""
        response = """
SUGGESTIONS:
- Suggestion 1
- Suggestion 2
- Suggestion 3
- Suggestion 4
- Suggestion 5
- Suggestion 6
- Suggestion 7
"""
        critique = agent._parse_critique(response, "target", "content")
        assert len(critique.suggestions) <= 5

    def test_extracts_reasoning(self, agent):
        """Should extract reasoning text."""
        response = "Some content here that explains the reasoning in detail."
        critique = agent._parse_critique(response, "target", "content")
        assert len(critique.reasoning) > 0


# =============================================================================
# CodexAgent Tests
# =============================================================================


class TestCodexAgent:
    """Tests for CodexAgent."""

    def test_initialization(self):
        """Should initialize with correct attributes."""
        agent = CodexAgent(name="codex", model="gpt-4.1-codex", role="proposer")
        assert agent.name == "codex"
        assert agent.model == "gpt-4.1-codex"
        assert agent.role == "proposer"
        assert agent.timeout == 300  # Default (increased for complex operations)

    def test_initialization_with_timeout(self):
        """Should accept custom timeout."""
        agent = CodexAgent(name="codex", model="test", timeout=300)
        assert agent.timeout == 300

    @pytest.mark.asyncio
    async def test_generate_builds_correct_command(self):
        """generate() should build correct codex command."""
        agent = CodexAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test prompt")

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert "codex" in cmd
            assert "exec" in cmd
            assert "Test prompt" in cmd

    @pytest.mark.asyncio
    async def test_generate_with_context(self):
        """generate() should include context in prompt."""
        agent = CodexAgent(name="test", model="test")
        context = [Message(role="proposer", agent="a", content="Previous", round=1)]

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test", context=context)

            cmd = mock_run.call_args[0][0]
            prompt = cmd[-1]  # Last arg is the prompt
            assert "Previous" in prompt

    @pytest.mark.asyncio
    async def test_generate_with_system_prompt(self):
        """generate() should include system prompt."""
        agent = CodexAgent(name="test", model="test")
        agent.set_system_prompt("You are helpful")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            prompt = cmd[-1]
            assert "You are helpful" in prompt

    @pytest.mark.asyncio
    async def test_generate_response_parsing(self):
        """generate() should parse response correctly."""
        agent = CodexAgent(name="test", model="test")
        raw_response = """codex
This is the actual response.
tokens used: 100"""

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = raw_response
            result = await agent.generate("Test")

            assert "This is the actual response" in result
            assert "codex" not in result.split("\n")[0]  # Header removed

    @pytest.mark.asyncio
    async def test_generate_skips_token_count(self):
        """generate() should skip token count lines."""
        agent = CodexAgent(name="test", model="test")
        raw_response = """codex
Response content
tokens used: 50"""

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = raw_response
            result = await agent.generate("Test")

            assert "tokens used" not in result

    @pytest.mark.asyncio
    async def test_generate_filters_collab_deprecation_noise(self):
        """generate() should filter known Codex deprecation warning lines."""
        agent = CodexAgent(name="test", model="test")
        raw_response = """`collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml.
See https://github.com/openai/codex/blob/main/docs/config.md#feature-flags for details.
codex
Actual model response.
tokens used: 123"""

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = raw_response
            result = await agent.generate("Test")

            assert result == "Actual model response."
            assert "`collab` is deprecated" not in result

    @pytest.mark.asyncio
    async def test_generate_filters_collab_deprecation_noise_without_header(self):
        """generate() should still filter warning lines when codex header is absent."""
        agent = CodexAgent(name="test", model="test")
        raw_response = """`collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml.
See https://github.com/openai/codex/blob/main/docs/config.md#feature-flags for details.
Plain response body without codex header."""

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = raw_response
            result = await agent.generate("Test")

            assert result == "Plain response body without codex header."
            assert "`collab` is deprecated" not in result

    @pytest.mark.asyncio
    async def test_generate_raises_when_codex_output_is_only_warning_noise(self):
        """generate() should fail fast when codex returns warning-only output."""
        agent = CodexAgent(name="test", model="test")
        raw_response = """`collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml.
See https://github.com/openai/codex/blob/main/docs/config.md#feature-flags for details."""

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = raw_response
            with pytest.raises(RuntimeError, match="unable to parse response"):
                await agent.generate("Test")

    @pytest.mark.asyncio
    async def test_critique_returns_critique_object(self):
        """critique() should return Critique object."""
        agent = CodexAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "ISSUES:\n- Problem\nSUGGESTIONS:\n- Fix"
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)
            assert result.agent == "test"


# =============================================================================
# ClaudeAgent Tests
# =============================================================================


class TestClaudeAgent:
    """Tests for ClaudeAgent."""

    def test_initialization(self):
        """Should initialize correctly."""
        agent = ClaudeAgent(name="claude", model="claude-sonnet-4")
        assert agent.name == "claude"
        assert agent.model == "claude-sonnet-4"

    @pytest.mark.asyncio
    async def test_generate_uses_stdin(self):
        """generate() should use stdin for prompt."""
        agent = ClaudeAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test prompt")

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args
            assert call_kwargs[1]["input_text"] is not None
            assert "Test prompt" in call_kwargs[1]["input_text"]

    @pytest.mark.asyncio
    async def test_generate_command_format(self):
        """generate() should use correct claude command."""
        agent = ClaudeAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "claude" in cmd
            assert "--print" in cmd
            assert "-p" in cmd

    @pytest.mark.asyncio
    async def test_generate_with_context(self):
        """generate() should include context."""
        agent = ClaudeAgent(name="test", model="test")
        context = [Message(role="critic", agent="b", content="Critique", round=1)]

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test", context=context)

            input_text = mock_run.call_args[1]["input_text"]
            assert "Critique" in input_text

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = ClaudeAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "ISSUES:\n- Issue\nSEVERITY: 0.5"
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# GeminiCLIAgent Tests
# =============================================================================


class TestGeminiCLIAgent:
    """Tests for GeminiCLIAgent."""

    def test_initialization(self):
        """Should initialize correctly."""
        agent = GeminiCLIAgent(name="gemini", model="gemini-3-pro")
        assert agent.name == "gemini"
        assert agent.model == "gemini-3-pro"

    @pytest.mark.asyncio
    async def test_generate_uses_yolo_flag(self):
        """generate() should use --yolo flag."""
        agent = GeminiCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "--yolo" in cmd

    @pytest.mark.asyncio
    async def test_generate_filters_yolo_message(self):
        """generate() should filter YOLO mode message."""
        agent = GeminiCLIAgent(name="test", model="test")
        response_with_yolo = "YOLO mode is enabled\nActual response here"

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = response_with_yolo
            result = await agent.generate("Test")

            assert "YOLO mode" not in result
            assert "Actual response here" in result

    @pytest.mark.asyncio
    async def test_generate_uses_text_output(self):
        """generate() should use text output format."""
        agent = GeminiCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "-o" in cmd
            assert "text" in cmd

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = GeminiCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Some critique response"
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# KiloCodeAgent Tests
# =============================================================================


class TestKiloCodeAgent:
    """Tests for KiloCodeAgent."""

    def test_initialization_with_provider(self):
        """Should initialize with provider_id."""
        agent = KiloCodeAgent(name="kilo", provider_id="gemini-explorer")
        assert agent.name == "kilo"
        assert agent.provider_id == "gemini-explorer"

    def test_initialization_with_mode(self):
        """Should initialize with mode."""
        agent = KiloCodeAgent(name="kilo", mode="code")
        assert agent.mode == "code"

    def test_default_mode_is_architect(self):
        """Default mode should be architect."""
        agent = KiloCodeAgent(name="kilo")
        assert agent.mode == "architect"

    @pytest.mark.asyncio
    async def test_generate_builds_correct_command(self):
        """generate() should build correct kilo run command."""
        agent = KiloCodeAgent(name="test", provider_id="test-provider", mode="ask")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = '{"role": "assistant", "content": "Response"}'
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "kilo" in cmd
            assert "run" in cmd
            assert "--auto" in cmd
            assert "--format" in cmd
            assert "json" in cmd
            assert "--model" in cmd
            assert "test-provider" in cmd

    def test_extract_kilocode_response_json_assistant(self):
        """Should extract assistant content from JSON."""
        agent = KiloCodeAgent(name="test")
        output = '{"role": "assistant", "content": "Hello from assistant"}'

        result = agent._extract_kilocode_response(output)
        assert result == "Hello from assistant"

    def test_extract_kilocode_response_text_type(self):
        """Should extract text from text-type messages."""
        agent = KiloCodeAgent(name="test")
        output = '{"type": "text", "text": "Text content here"}'

        result = agent._extract_kilocode_response(output)
        assert result == "Text content here"

    def test_extract_kilocode_response_multiple_lines(self):
        """Should handle multiple JSON lines."""
        agent = KiloCodeAgent(name="test")
        output = """{"role": "user", "content": "Question"}
{"role": "assistant", "content": "First response"}
{"role": "assistant", "content": "Second response"}"""

        result = agent._extract_kilocode_response(output)
        assert "First response" in result
        assert "Second response" in result

    def test_extract_kilocode_response_fallback(self):
        """Should fallback to raw output if no JSON."""
        agent = KiloCodeAgent(name="test")
        output = "Plain text response"

        result = agent._extract_kilocode_response(output)
        assert result == "Plain text response"

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = KiloCodeAgent(name="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = '{"role": "assistant", "content": "Issues found"}'
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# GrokCLIAgent Tests
# =============================================================================


class TestGrokCLIAgent:
    """Tests for GrokCLIAgent."""

    def test_initialization(self):
        """Should initialize correctly."""
        agent = GrokCLIAgent(name="grok", model="grok-4-latest")
        assert agent.name == "grok"
        assert agent.model == "grok-4-latest"

    @pytest.mark.asyncio
    async def test_generate_command_format(self):
        """generate() should use correct grok command."""
        agent = GrokCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "grok" in cmd
            assert "-p" in cmd

    def test_extract_grok_response_json_lines(self):
        """Should parse JSON lines format."""
        agent = GrokCLIAgent(name="test", model="test")
        output = """{"role": "user", "content": "Question"}
{"role": "assistant", "content": "Answer here"}"""

        result = agent._extract_grok_response(output)
        assert result == "Answer here"

    def test_extract_grok_response_skips_tool_messages(self):
        """Should skip 'Using tools...' messages."""
        agent = GrokCLIAgent(name="test", model="test")
        output = """{"role": "assistant", "content": "Using tools to search..."}
{"role": "assistant", "content": "Final answer"}"""

        result = agent._extract_grok_response(output)
        assert result == "Final answer"
        assert "Using tools" not in result

    def test_extract_grok_response_plain_text(self):
        """Should handle plain text response."""
        agent = GrokCLIAgent(name="test", model="test")
        output = "This is plain text response"

        result = agent._extract_grok_response(output)
        assert result == "This is plain text response"

    def test_extract_grok_response_extracts_final(self):
        """Should extract final assistant message."""
        agent = GrokCLIAgent(name="test", model="test")
        output = """{"role": "assistant", "content": "First response"}
{"role": "assistant", "content": "Updated response"}
{"role": "assistant", "content": "Final response"}"""

        result = agent._extract_grok_response(output)
        assert result == "Final response"

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = GrokCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = '{"role": "assistant", "content": "Issues"}'
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# QwenCLIAgent Tests
# =============================================================================


class TestQwenCLIAgent:
    """Tests for QwenCLIAgent."""

    def test_initialization(self):
        """Should initialize correctly."""
        agent = QwenCLIAgent(name="qwen", model="qwen3-coder")
        assert agent.name == "qwen"
        assert agent.model == "qwen3-coder"

    @pytest.mark.asyncio
    async def test_generate_command_format(self):
        """generate() should use correct qwen command."""
        agent = QwenCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "qwen" in cmd
            assert "-p" in cmd

    @pytest.mark.asyncio
    async def test_generate_with_context(self):
        """generate() should include context."""
        agent = QwenCLIAgent(name="test", model="test")
        context = [Message(role="proposer", agent="a", content="Prev", round=1)]

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test", context=context)

            cmd = mock_run.call_args[0][0]
            prompt = cmd[-1]
            assert "Prev" in prompt

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = QwenCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Some issues"
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# DeepseekCLIAgent Tests
# =============================================================================


class TestDeepseekCLIAgent:
    """Tests for DeepseekCLIAgent."""

    def test_initialization(self):
        """Should initialize correctly."""
        agent = DeepseekCLIAgent(name="deepseek", model="deepseek-v3")
        assert agent.name == "deepseek"
        assert agent.model == "deepseek-v3"

    @pytest.mark.asyncio
    async def test_generate_command_format(self):
        """generate() should use correct deepseek command."""
        agent = DeepseekCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "deepseek" in cmd
            assert "-p" in cmd

    @pytest.mark.asyncio
    async def test_generate_with_context(self):
        """generate() should include context."""
        agent = DeepseekCLIAgent(name="test", model="test")
        context = [Message(role="critic", agent="b", content="Review", round=2)]

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Response"
            await agent.generate("Test", context=context)

            cmd = mock_run.call_args[0][0]
            prompt = cmd[-1]
            assert "Review" in prompt

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = DeepseekCLIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Problems identified"
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# OpenAIAgent Tests
# =============================================================================


class TestOpenAIAgent:
    """Tests for OpenAIAgent."""

    def test_initialization_with_default_model(self):
        """Should use gpt-4.1 as default model."""
        agent = OpenAIAgent(name="openai")
        assert agent.model == "gpt-4.1"

    def test_initialization_with_custom_model(self):
        """Should accept custom model."""
        agent = OpenAIAgent(name="openai", model="gpt-5")
        assert agent.model == "gpt-5"

    @pytest.mark.asyncio
    async def test_generate_command_format(self):
        """generate() should use correct openai command."""
        agent = OpenAIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = '{"choices": [{"message": {"content": "Response"}}]}'
            await agent.generate("Test")

            cmd = mock_run.call_args[0][0]
            assert "openai" in cmd
            assert "api" in cmd
            assert "chat.completions.create" in cmd

    @pytest.mark.asyncio
    async def test_generate_json_response_parsing(self):
        """generate() should parse JSON response."""
        agent = OpenAIAgent(name="test", model="test")
        json_response = json.dumps({"choices": [{"message": {"content": "Parsed content"}}]})

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = json_response
            result = await agent.generate("Test")

            assert result == "Parsed content"

    @pytest.mark.asyncio
    async def test_generate_handles_non_json(self):
        """generate() should handle non-JSON response."""
        agent = OpenAIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Plain text response"
            result = await agent.generate("Test")

            assert result == "Plain text response"

    @pytest.mark.asyncio
    async def test_critique_returns_critique(self):
        """critique() should return Critique."""
        agent = OpenAIAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "ISSUES:\n- Problem"
            result = await agent.critique("proposal", "task")

            assert isinstance(result, Critique)


# =============================================================================
# create_agent() Factory Tests
# =============================================================================


class TestCreateAgentFactory:
    """Tests for create_agent() factory function."""

    def test_creates_codex_agent(self):
        """Should create CodexAgent."""
        agent = create_agent("codex")
        assert isinstance(agent, CodexAgent)
        assert agent.name == "codex"

    def test_creates_claude_agent(self):
        """Should create ClaudeAgent."""
        agent = create_agent("claude")
        assert isinstance(agent, ClaudeAgent)
        assert agent.name == "claude"

    def test_creates_openai_agent(self):
        """Should create OpenAIAgent."""
        agent = create_agent("openai")
        assert isinstance(agent, OpenAIAgent)
        assert agent.name == "openai"

    def test_creates_gemini_cli_agent(self):
        """Should create GeminiCLIAgent."""
        agent = create_agent("gemini-cli")
        assert isinstance(agent, GeminiCLIAgent)
        assert agent.name == "gemini-cli"

    def test_creates_grok_cli_agent(self):
        """Should create GrokCLIAgent."""
        agent = create_agent("grok-cli")
        assert isinstance(agent, GrokCLIAgent)
        assert agent.name == "grok-cli"

    def test_creates_qwen_cli_agent(self):
        """Should create QwenCLIAgent."""
        agent = create_agent("qwen-cli")
        assert isinstance(agent, QwenCLIAgent)
        assert agent.name == "qwen-cli"

    def test_creates_deepseek_cli_agent(self):
        """Should create DeepseekCLIAgent."""
        agent = create_agent("deepseek-cli")
        assert isinstance(agent, DeepseekCLIAgent)
        assert agent.name == "deepseek-cli"

    def test_creates_kilocode_agent(self):
        """Should create KiloCodeAgent."""
        agent = create_agent("kilocode")
        assert isinstance(agent, KiloCodeAgent)
        assert agent.name == "kilocode"

    def test_passes_custom_name(self):
        """Should pass custom name."""
        agent = create_agent("codex", name="my-codex")
        assert agent.name == "my-codex"

    def test_passes_custom_role(self):
        """Should pass custom role."""
        agent = create_agent("codex", role="critic")
        assert agent.role == "critic"

    def test_passes_custom_model(self):
        """Should pass custom model."""
        agent = create_agent("codex", model="gpt-5.5-codex")
        assert agent.model == "gpt-5.5-codex"

    def test_unknown_type_raises_value_error(self):
        """Unknown agent type should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown agent type"):
            create_agent("nonexistent-agent")


# =============================================================================
# list_available_agents() Tests
# =============================================================================


class TestListAvailableAgents:
    """Tests for list_available_agents() function."""

    def test_returns_dict(self):
        """Should return a dictionary."""
        result = list_available_agents()
        assert isinstance(result, dict)

    def test_contains_cli_agents(self):
        """Should contain CLI agent types."""
        result = list_available_agents()
        assert "codex" in result
        assert "claude" in result
        assert "openai" in result
        assert "gemini-cli" in result
        assert "grok-cli" in result

    def test_contains_api_agents(self):
        """Should contain API agent types."""
        result = list_available_agents()
        assert "gemini" in result
        assert "ollama" in result
        assert "anthropic-api" in result
        assert "openai-api" in result

    def test_each_entry_has_type(self):
        """Each entry should have 'type' field."""
        result = list_available_agents()
        for name, info in result.items():
            assert "type" in info, f"Missing 'type' for {name}"

    def test_each_entry_has_requires(self):
        """Each entry should have 'requires' field."""
        result = list_available_agents()
        for name, info in result.items():
            assert "requires" in info, f"Missing 'requires' for {name}"

    def test_each_entry_has_env_vars(self):
        """Each entry should have 'env_vars' field."""
        result = list_available_agents()
        for name, info in result.items():
            assert "env_vars" in info, f"Missing 'env_vars' for {name}"


# =============================================================================
# CLI Fallback Tests
# =============================================================================


class TestCLIAgentFallback:
    """Tests for CLI agent fallback to OpenRouter functionality."""

    def test_enable_fallback_default_false(self):
        """Should disable fallback by default (opt-in via ARAGORA_OPENROUTER_FALLBACK_ENABLED)."""
        agent = CodexAgent(name="test", model="test")
        assert agent.enable_fallback is False

    def test_enable_fallback_can_be_enabled(self):
        """Should allow enabling fallback explicitly."""
        agent = CodexAgent(name="test", model="test", enable_fallback=True)
        assert agent.enable_fallback is True

    def test_enable_fallback_can_be_disabled(self):
        """Should allow disabling fallback explicitly."""
        agent = CodexAgent(name="test", model="test", enable_fallback=False)
        assert agent.enable_fallback is False

    def test_fallback_agent_initially_none(self):
        """Should not create fallback agent until needed."""
        agent = CodexAgent(name="test", model="test")
        assert agent._fallback_agent is None

    def test_fallback_used_initially_false(self):
        """Should track fallback usage."""
        agent = CodexAgent(name="test", model="test")
        assert agent._fallback_used is False


class TestCLIAgentIsFallbackError:
    """Tests for _is_fallback_error() detection method."""

    @pytest.fixture
    def agent(self):
        return CodexAgent(name="test", model="test")

    def test_detects_rate_limit_pattern(self, agent):
        """Should detect rate limit errors."""
        error = RuntimeError("CLI command failed: rate limit exceeded")
        assert agent._is_fallback_error(error) is True

    def test_detects_429_pattern(self, agent):
        """Should detect 429 status code."""
        error = RuntimeError("CLI command failed: 429 Too Many Requests")
        assert agent._is_fallback_error(error) is True

    def test_detects_quota_exceeded(self, agent):
        """Should detect quota exceeded errors."""
        error = RuntimeError("CLI command failed: quota exceeded")
        assert agent._is_fallback_error(error) is True

    def test_detects_resource_exhausted(self, agent):
        """Should detect resource exhausted errors."""
        error = RuntimeError("CLI command failed: resource exhausted")
        assert agent._is_fallback_error(error) is True

    def test_detects_billing_error(self, agent):
        """Should detect billing errors."""
        error = RuntimeError("CLI command failed: billing issue")
        assert agent._is_fallback_error(error) is True

    def test_detects_timeout_error(self, agent):
        """Should detect TimeoutError."""
        error = TimeoutError("CLI command timed out")
        assert agent._is_fallback_error(error) is True

    def test_detects_asyncio_timeout(self, agent):
        """Should detect asyncio.TimeoutError."""
        error = asyncio.TimeoutError()
        assert agent._is_fallback_error(error) is True

    def test_detects_cli_command_failed(self, agent):
        """Should detect CLI command failures."""
        error = RuntimeError("cli command failed: process exited with 1")
        assert agent._is_fallback_error(error) is True

    def test_ignores_generic_errors(self, agent):
        """Should not trigger on generic errors."""
        error = ValueError("Invalid argument")
        assert agent._is_fallback_error(error) is False

    def test_ignores_key_errors(self, agent):
        """Should not trigger on key errors."""
        error = KeyError("missing_key")
        assert agent._is_fallback_error(error) is False


class TestCLIAgentGetFallbackAgent:
    """Tests for _get_fallback_agent() method."""

    @pytest.fixture
    def agent(self):
        # Enable fallback for testing fallback functionality
        return CodexAgent(name="test", model="gpt-4.1-codex", enable_fallback=True)

    def test_returns_none_when_disabled(self, agent):
        """Should return None when fallback is disabled."""
        agent.enable_fallback = False
        assert agent._get_fallback_agent() is None

    def test_returns_none_without_api_key(self, agent):
        """Should return None without OPENROUTER_API_KEY."""
        with patch.dict("os.environ", {}, clear=True):
            import os

            if "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]
            result = agent._get_fallback_agent()
            assert result is None

    def test_creates_openrouter_agent_with_api_key(self, agent):
        """Should create OpenRouterAgent when API key is set."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                mock_instance = MagicMock()
                mock_or.return_value = mock_instance

                result = agent._get_fallback_agent()

                assert result is mock_instance
                mock_or.assert_called_once()

    def test_maps_model_to_openrouter_format(self, agent):
        """Should map model to OpenRouter format."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                mock_or.return_value = MagicMock()

                agent._get_fallback_agent()

                call_kwargs = mock_or.call_args[1]
                # gpt-4.1-codex should map to openai/gpt-4.1
                assert call_kwargs["model"] == "openai/gpt-4.1"
                # Should not pass api_key (OpenRouterAgent reads from env)
                assert "api_key" not in call_kwargs

    def test_caches_fallback_agent(self, agent):
        """Should cache and reuse fallback agent."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                mock_instance = MagicMock()
                mock_or.return_value = mock_instance

                result1 = agent._get_fallback_agent()
                result2 = agent._get_fallback_agent()

                assert result1 is result2
                mock_or.assert_called_once()  # Only created once

    def test_copies_system_prompt_to_fallback(self, agent):
        """Should copy system prompt to fallback agent."""
        agent.set_system_prompt("You are helpful")

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                mock_instance = MagicMock()
                mock_or.return_value = mock_instance

                agent._get_fallback_agent()

                assert mock_instance.system_prompt == "You are helpful"


class TestCLIAgentFallbackIntegration:
    """Integration tests for CLI fallback behavior."""

    @pytest.mark.asyncio
    async def test_codex_falls_back_on_timeout(self):
        """CodexAgent should fallback on timeout when enabled."""
        agent = CodexAgent(name="test", model="test", enable_fallback=True)

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = TimeoutError("timed out")

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                    mock_fallback = AsyncMock()
                    mock_fallback.generate = AsyncMock(return_value="Fallback response")
                    mock_or.return_value = mock_fallback

                    result = await agent.generate("Test prompt")

                    assert result == "Fallback response"
                    assert agent._fallback_used is True

    @pytest.mark.asyncio
    async def test_claude_falls_back_on_rate_limit(self):
        """ClaudeAgent should fallback on rate limit when enabled."""
        agent = ClaudeAgent(name="test", model="test", enable_fallback=True)

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = RuntimeError("CLI command failed: rate limit exceeded")

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                    mock_fallback = AsyncMock()
                    mock_fallback.generate = AsyncMock(return_value="Fallback response")
                    mock_or.return_value = mock_fallback

                    result = await agent.generate("Test prompt")

                    assert result == "Fallback response"
                    assert agent._fallback_used is True

    @pytest.mark.asyncio
    async def test_gemini_falls_back_on_cli_failure(self):
        """GeminiCLIAgent should fallback on CLI failure when enabled."""
        agent = GeminiCLIAgent(name="test", model="test", enable_fallback=True)

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = RuntimeError("CLI command failed: process crashed")

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                    mock_fallback = AsyncMock()
                    mock_fallback.generate = AsyncMock(return_value="Fallback response")
                    mock_or.return_value = mock_fallback

                    result = await agent.generate("Test prompt")

                    assert result == "Fallback response"

    @pytest.mark.asyncio
    async def test_retries_openrouter_fallback_after_stream_error(self):
        """Transient OpenRouter payload/stream errors should be retried once."""
        agent = ClaudeAgent(name="test", model="test", enable_fallback=True)

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = TimeoutError("timed out")

            with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
                with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                    mock_fallback = MagicMock()
                    mock_fallback.generate = AsyncMock(
                        side_effect=[
                            AgentStreamError("stream interrupted", agent_name="test_fallback"),
                            "Recovered fallback response",
                        ]
                    )
                    mock_or.return_value = mock_fallback

                    result = await agent.generate("Test prompt")

                    assert result == "Recovered fallback response"
                    assert mock_fallback.generate.await_count == 2

    @pytest.mark.asyncio
    async def test_no_fallback_on_generic_error(self):
        """Should not fallback on generic errors."""
        agent = CodexAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = ValueError("Invalid argument")

            with pytest.raises(ValueError, match="Invalid argument"):
                await agent.generate("Test prompt")

            assert agent._fallback_used is False

    @pytest.mark.asyncio
    async def test_raises_if_no_fallback_available(self):
        """Should raise original error if no fallback available."""
        agent = CodexAgent(name="test", model="test", enable_fallback=False)

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = TimeoutError("timed out")

            with pytest.raises(TimeoutError, match="timed out"):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_raises_if_no_api_key(self):
        """Should raise original error if no API key set."""
        agent = CodexAgent(name="test", model="test")

        with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
            mock_cli.side_effect = TimeoutError("timed out")

            with patch.dict("os.environ", {}, clear=True):
                import os

                if "OPENROUTER_API_KEY" in os.environ:
                    del os.environ["OPENROUTER_API_KEY"]

                with pytest.raises(TimeoutError, match="timed out"):
                    await agent.generate("Test prompt")


class TestCLIAgentModelMapping:
    """Tests for model mapping to OpenRouter."""

    def test_claude_model_mapping(self):
        """Should map Claude models correctly."""
        agent = ClaudeAgent(name="test", model="claude-opus-4-6")
        assert agent.OPENROUTER_MODEL_MAP.get("claude-opus-4-6") == "anthropic/claude-opus-4.6"

    def test_codex_model_mapping(self):
        """Should map Codex models correctly."""
        agent = CodexAgent(name="test", model="gpt-4.1-codex")
        assert agent.OPENROUTER_MODEL_MAP.get("gpt-4.1-codex") == "openai/gpt-4.1"

    def test_gemini_model_mapping(self):
        """Should map Gemini models correctly."""
        agent = GeminiCLIAgent(name="test", model="gemini-3-pro")
        assert agent.OPENROUTER_MODEL_MAP.get("gemini-3-pro") == "google/gemini-3.1-pro-preview"

    def test_grok_model_mapping(self):
        """Should map Grok models correctly."""
        agent = GrokCLIAgent(name="test", model="grok-3")
        assert agent.OPENROUTER_MODEL_MAP.get("grok-3") == "x-ai/grok-4"

    def test_deepseek_model_mapping(self):
        """Should map Deepseek models correctly."""
        agent = DeepseekCLIAgent(name="test", model="deepseek-v3")
        assert agent.OPENROUTER_MODEL_MAP.get("deepseek-v3") == "deepseek/deepseek-chat"

    def test_qwen_model_mapping(self):
        """Should map Qwen models correctly."""
        agent = QwenCLIAgent(name="test", model="qwen-2.5-coder")
        assert (
            agent.OPENROUTER_MODEL_MAP.get("qwen-2.5-coder") == "qwen/qwen-2.5-coder-32b-instruct"
        )

    def test_unknown_model_uses_default(self):
        """Unknown models should use default fallback model."""
        agent = CodexAgent(name="test", model="unknown-model-xyz", enable_fallback=True)

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                mock_or.return_value = MagicMock()

                agent._get_fallback_agent()

                call_kwargs = mock_or.call_args[1]
                # Should default to claude-sonnet-4
                assert call_kwargs["model"] == "anthropic/claude-sonnet-4"


# =============================================================================
# Fallback Error Detection Tests
# =============================================================================


class TestFallbackErrorDetection:
    """Tests for CLIAgent._is_fallback_error() method.

    These tests verify that the fallback mechanism correctly identifies
    various error conditions that should trigger OpenRouter fallback.
    """

    @pytest.fixture
    def agent(self):
        """Create a CodexAgent for testing."""
        return CodexAgent(name="test", model="test-model")

    # --- Rate Limit Pattern Tests ---

    def test_detects_rate_limit_429(self, agent):
        """Should detect HTTP 429 rate limit errors."""
        error = RuntimeError("API returned 429 Too Many Requests")
        assert agent._is_fallback_error(error) is True

    def test_detects_rate_limit_text(self, agent):
        """Should detect rate limit in error text."""
        error = RuntimeError("Rate limit exceeded, please wait")
        assert agent._is_fallback_error(error) is True

    def test_detects_quota_exceeded(self, agent):
        """Should detect quota exceeded errors."""
        error = RuntimeError("Quota exceeded for model gpt-4")
        assert agent._is_fallback_error(error) is True

    def test_detects_resource_exhausted(self, agent):
        """Should detect resource exhausted errors."""
        error = RuntimeError("RESOURCE_EXHAUSTED: Model is busy")
        assert agent._is_fallback_error(error) is True

    def test_detects_billing_error(self, agent):
        """Should detect billing-related errors."""
        error = RuntimeError("Your credit balance is too low")
        assert agent._is_fallback_error(error) is True

    def test_detects_throttling(self, agent):
        """Should detect throttling errors."""
        error = RuntimeError("Request throttled, try again later")
        assert agent._is_fallback_error(error) is True

    # --- Service Unavailability Tests ---

    def test_detects_503_service_unavailable(self, agent):
        """Should detect HTTP 503 errors."""
        error = RuntimeError("HTTP 503 Service Unavailable")
        assert agent._is_fallback_error(error) is True

    def test_detects_502_bad_gateway(self, agent):
        """Should detect HTTP 502 errors."""
        error = RuntimeError("502 Bad Gateway")
        assert agent._is_fallback_error(error) is True

    def test_detects_overloaded_error(self, agent):
        """Should detect model overloaded errors."""
        error = RuntimeError("The model is currently overloaded")
        assert agent._is_fallback_error(error) is True

    def test_detects_capacity_error(self, agent):
        """Should detect capacity errors."""
        error = RuntimeError("Server at capacity, try later")
        assert agent._is_fallback_error(error) is True

    def test_detects_temporarily_unavailable(self, agent):
        """Should detect temporarily unavailable errors."""
        error = RuntimeError("Service temporarily unavailable")
        assert agent._is_fallback_error(error) is True

    def test_detects_high_demand(self, agent):
        """Should detect high demand errors."""
        error = RuntimeError("High demand on this model")
        assert agent._is_fallback_error(error) is True

    # --- Timeout Tests ---

    def test_detects_timeout_error(self, agent):
        """Should detect TimeoutError."""
        error = TimeoutError("Connection timed out")
        assert agent._is_fallback_error(error) is True

    def test_detects_asyncio_timeout_error(self, agent):
        """Should detect asyncio.TimeoutError."""
        error = asyncio.TimeoutError()
        assert agent._is_fallback_error(error) is True

    def test_detects_timeout_in_text(self, agent):
        """Should detect timeout in error text."""
        error = RuntimeError("Request timed out after 30s")
        assert agent._is_fallback_error(error) is True

    # --- Connection Error Tests ---

    def test_detects_connection_error(self, agent):
        """Should detect ConnectionError."""
        error = ConnectionError("Failed to connect")
        assert agent._is_fallback_error(error) is True

    def test_detects_connection_refused(self, agent):
        """Should detect ConnectionRefusedError."""
        error = ConnectionRefusedError("Connection refused")
        assert agent._is_fallback_error(error) is True

    def test_detects_connection_reset(self, agent):
        """Should detect ConnectionResetError."""
        error = ConnectionResetError("Connection reset by peer")
        assert agent._is_fallback_error(error) is True

    def test_detects_connection_refused_text(self, agent):
        """Should detect connection refused in error text."""
        error = RuntimeError("Connection refused by host")
        assert agent._is_fallback_error(error) is True

    def test_detects_network_error_text(self, agent):
        """Should detect network error in error text."""
        error = RuntimeError("Network error occurred")
        assert agent._is_fallback_error(error) is True

    # --- CLI Error Tests ---

    def test_detects_cli_command_failed(self, agent):
        """Should detect CLI command failure."""
        error = RuntimeError("CLI command failed: non-zero exit")
        assert agent._is_fallback_error(error) is True

    def test_detects_cli_in_error(self, agent):
        """Should detect CLI-related errors."""
        error = RuntimeError("cli error: unable to parse response")
        assert agent._is_fallback_error(error) is True

    def test_detects_api_error_runtime(self, agent):
        """Should detect API errors in RuntimeError."""
        error = RuntimeError("api error 500: internal server error")
        assert agent._is_fallback_error(error) is True

    def test_detects_http_error_runtime(self, agent):
        """Should detect HTTP errors in RuntimeError."""
        error = RuntimeError("http error: connection failed")
        assert agent._is_fallback_error(error) is True

    # --- Subprocess Error Tests ---

    def test_detects_subprocess_error(self, agent):
        """Should detect subprocess errors."""
        import subprocess

        error = subprocess.SubprocessError("Process failed")
        assert agent._is_fallback_error(error) is True

    # --- Negative Tests (should NOT trigger fallback) ---

    def test_ignores_value_error(self, agent):
        """Should not trigger fallback for ValueError."""
        error = ValueError("Invalid argument")
        assert agent._is_fallback_error(error) is False

    def test_ignores_key_error(self, agent):
        """Should not trigger fallback for KeyError."""
        error = KeyError("missing_key")
        assert agent._is_fallback_error(error) is False

    def test_ignores_type_error(self, agent):
        """Should not trigger fallback for TypeError."""
        error = TypeError("Invalid type")
        assert agent._is_fallback_error(error) is False

    def test_ignores_generic_runtime_error(self, agent):
        """Should not trigger fallback for generic RuntimeError."""
        error = RuntimeError("Something went wrong")
        assert agent._is_fallback_error(error) is False

    def test_ignores_attribute_error(self, agent):
        """Should not trigger fallback for AttributeError."""
        error = AttributeError("'object' has no attribute 'x'")
        assert agent._is_fallback_error(error) is False

    # --- Case Insensitivity Tests ---

    def test_case_insensitive_rate_limit(self, agent):
        """Should detect rate limit regardless of case."""
        error = RuntimeError("RATE LIMIT exceeded")
        assert agent._is_fallback_error(error) is True

    def test_case_insensitive_quota(self, agent):
        """Should detect quota exceeded regardless of case."""
        error = RuntimeError("QUOTA_EXCEEDED")
        assert agent._is_fallback_error(error) is True


class TestFallbackIntegration:
    """Integration tests for the fallback mechanism."""

    @pytest.fixture
    def agent(self):
        """Create a CodexAgent with fallback enabled."""
        return CodexAgent(name="test", model="gpt-4o", enable_fallback=True)

    @pytest.mark.asyncio
    async def test_fallback_triggered_on_rate_limit(self, agent):
        """Should use fallback agent when rate limited."""
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch.object(agent, "_run_cli") as mock_cli:
                mock_cli.side_effect = RuntimeError("429 Too Many Requests")

                with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                    mock_fallback = MagicMock()
                    mock_fallback.generate = AsyncMock(return_value="Fallback response")
                    mock_or.return_value = mock_fallback

                    result = await agent.generate("Test prompt")

                    assert result == "Fallback response"
                    assert agent._fallback_used is True

    @pytest.mark.asyncio
    async def test_fallback_not_triggered_when_disabled(self, agent):
        """Should not use fallback when disabled."""
        agent.enable_fallback = False

        with patch.object(agent, "_run_cli") as mock_cli:
            mock_cli.side_effect = RuntimeError("429 Too Many Requests")

            with pytest.raises(RuntimeError):
                await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_fallback_not_triggered_without_api_key(self, agent):
        """Should not use fallback without OPENROUTER_API_KEY."""
        with patch.dict("os.environ", {}, clear=True):
            with patch.object(agent, "_run_cli") as mock_cli:
                mock_cli.side_effect = RuntimeError("429 Too Many Requests")

                with pytest.raises(RuntimeError):
                    await agent.generate("Test prompt")

    @pytest.mark.asyncio
    async def test_prefer_api_skips_cli(self):
        """Should skip CLI and use OpenRouter directly when prefer_api=True."""
        agent = CodexAgent(name="test", model="gpt-4o", prefer_api=True, enable_fallback=True)

        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "test-key"}):
            with patch.object(agent, "_run_cli") as mock_cli:
                with patch("aragora.agents.api_agents.OpenRouterAgent") as mock_or:
                    mock_fallback = MagicMock()
                    mock_fallback.generate = AsyncMock(return_value="Direct API response")
                    mock_or.return_value = mock_fallback

                    result = await agent.generate("Test prompt")

                    # Should NOT call CLI at all
                    mock_cli.assert_not_called()
                    # Should use OpenRouter directly
                    assert result == "Direct API response"
                    assert agent._fallback_used is True

    @pytest.mark.asyncio
    async def test_prefer_api_falls_back_to_cli_without_key(self):
        """Should fall back to CLI when prefer_api=True but no API key."""
        agent = CodexAgent(name="test", model="gpt-4o", prefer_api=True)

        with patch.dict("os.environ", {}, clear=True):
            with patch.object(agent, "_run_cli", new_callable=AsyncMock) as mock_cli:
                mock_cli.return_value = "CLI response"

                result = await agent.generate("Test prompt")

                # Should fall through to CLI since no API key
                mock_cli.assert_called_once()
                assert result == "CLI response"
