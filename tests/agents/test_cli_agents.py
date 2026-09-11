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

        with patch("os.environ.get", return_value="test-api-key"):
            with patch(
                "aragora.agents.api_agents.openrouter.get_api_key",
                return_value="test-api-key",
            ):
                fallback = agent._get_fallback_agent()

        assert fallback is not None
        assert "fallback" in fallback.name

    def test_openrouter_model_mapping(self):
        """CLIAgent has no static OPENROUTER_MODEL_MAP: _get_fallback_agent()
        resolves the current model through the catalog and upgrade map
        instead (frontier-model-refresh, 2026-09-04), so legacy CLI model
        spellings still upgrade to a valid OpenRouter id."""
        from aragora.agents.cli_agents import CLIAgent

        assert not hasattr(CLIAgent, "OPENROUTER_MODEL_MAP")

        for legacy_model in ("gpt-4o", "gemini-3-pro", "grok-4"):
            agent = DummyCLIAgent(name="test-agent", model=legacy_model, enable_fallback=True)
            with patch("os.environ.get", return_value="test-api-key"):
                with patch(
                    "aragora.agents.api_agents.openrouter.get_api_key",
                    return_value="test-api-key",
                ):
                    fallback = agent._get_fallback_agent()
            assert fallback is not None
            assert "/" in fallback.model


class TestCLIAgentFamilyAwareFallback:
    """A CLI model pin must never fall back cross-family.

    Removing the hand-written OPENROUTER_MODEL_MAPs sent eight real CLI
    spellings (Codex model names, a seeded DeepSeek agent id, ...) to the
    *Anthropic* frontier, because the last resort was one Anthropic constant.
    An explicit model pin is exactly the thing that must keep its provider.
    """

    @staticmethod
    def _fallback_model(agent):
        with patch("os.environ.get", return_value="test-api-key"):
            with patch(
                "aragora.agents.api_agents.openrouter.get_api_key",
                return_value="test-api-key",
            ):
                fallback = agent._get_fallback_agent()
        assert fallback is not None
        return fallback.model

    @pytest.mark.parametrize(
        ("agent_cls_name", "model", "expected"),
        [
            ("CodexAgent", "gpt-5.3-codex", "openai/gpt-6-astra"),
            ("CodexAgent", "gpt-4.1-codex", "openai/gpt-6-astra"),
            ("CodexAgent", "gpt-5.3-chat-latest", "openai/gpt-6-astra"),
            ("GrokCLIAgent", "grok-4-1-fast", "x-ai/grok-4.6"),
            ("DeepseekCLIAgent", "deepseek-coder", "deepseek/deepseek-v4-pro-0813"),
            ("DeepseekCLIAgent", "deepseek-v3.2", "deepseek/deepseek-v4-pro-0813"),
            ("QwenCLIAgent", "qwen-2.5-coder", "qwen/qwen3.8-2.4t-a95b"),
        ],
    )
    def test_legacy_cli_spelling_stays_in_family(self, agent_cls_name, model, expected):
        import aragora.agents.cli_agents as cli_agents

        agent_cls = getattr(cli_agents, agent_cls_name)
        agent = agent_cls(name="test-agent", model=model, enable_fallback=True)
        assert self._fallback_model(agent) == expected

    def test_codestral_latest_falls_back_to_agents_own_family(self):
        """``codestral-latest`` is a live Mistral SKU, not an UPGRADES entry
        (aragora/models/upgrade_map.py), and the catalog carries no
        Codestral row either. From a non-Mistral CLI agent it must NOT
        resolve to Mistral -- it falls back to THIS agent class's own
        family frontier via ``_family_frontier_openrouter_id`` (the same
        family-aware last resort as ``test_unknown_model_falls_back_to_own_family_frontier``)."""
        import aragora.agents.cli_agents as cli_agents
        from aragora.models.catalog import spec_or_none
        from aragora.models.upgrade_map import resolve_model_id

        assert spec_or_none(resolve_model_id("codestral-latest")) is None, (
            "fixture assumption: codestral-latest must stay unresolvable via "
            "the catalog/upgrade map"
        )

        agent = cli_agents.CodexAgent(
            name="test-agent", model="codestral-latest", enable_fallback=True
        )
        assert self._fallback_model(agent) == "openai/gpt-6-astra"

    @pytest.mark.parametrize(
        ("agent_cls_name", "expected"),
        [
            ("CodexAgent", "openai/gpt-6-astra"),
            ("OpenAIAgent", "openai/gpt-6-astra"),
            ("ClaudeAgent", "anthropic/claude-fable-5.1"),
            ("GeminiCLIAgent", "google/gemini-3.1-pro-preview"),
            ("GrokCLIAgent", "x-ai/grok-4.6"),
            ("GrokBuildAgent", "x-ai/grok-4.6"),
            ("QwenCLIAgent", "qwen/qwen3.8-2.4t-a95b"),
            ("DeepseekCLIAgent", "deepseek/deepseek-v4-pro-0813"),
            ("KimiCLIAgent", "moonshotai/kimi-k3"),
            ("AntigravityAgent", "google/gemini-3.1-pro-preview"),
        ],
    )
    def test_unknown_model_falls_back_to_own_family_frontier(self, agent_cls_name, expected):
        """A spelling neither the catalog nor the upgrade map knows resolves
        to THIS agent class's family frontier."""
        import aragora.agents.cli_agents as cli_agents
        from aragora.models.catalog import spec_or_none
        from aragora.models.upgrade_map import resolve_model_id

        unknown = "totally-unknown-model-xyz"
        assert spec_or_none(resolve_model_id(unknown)) is None, "fixture id must stay unknown"

        agent_cls = getattr(cli_agents, agent_cls_name)
        # Not every CLI subclass forwards enable_fallback through __init__
        # (e.g. OpenAIAgent narrows the signature); set it after construction.
        agent = agent_cls(name="test-agent", model=unknown)
        agent.enable_fallback = True
        assert self._fallback_model(agent) == expected

    def test_class_with_no_family_falls_back_to_fable(self):
        """Only a class that declares no family lands on the Anthropic
        frontier (kilocode brokers several providers)."""
        from aragora.config.model_pins import FABLE_51_VIA_OPENROUTER

        agent = DummyCLIAgent(
            name="test-agent", model="totally-unknown-model-xyz", enable_fallback=True
        )
        assert agent.MODEL_FAMILY == ""
        assert self._fallback_model(agent) == FABLE_51_VIA_OPENROUTER


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


class TestRefreshedCLIAgentsPinTheirModel:
    """A refreshed registry default has to reach the CLI on the wire.

    Four command builders updated their registry default to a frontier pin
    but never passed ``self.model`` to the CLI, so the local CLI's own
    default answered while Aragora recorded the refreshed id (finding O-P2b,
    openai reviewer, #9989 round 4). Each flag below was verified against the
    installed CLI's ``--help`` on 2026-09-05.
    """

    # registry name -> (module attribute, the CLI's own model flag)
    CASES = {
        "codex": ("CodexAgent", "-m"),
        "gemini-cli": ("GeminiCLIAgent", "-m"),
        "grok-cli": ("GrokCLIAgent", "-m"),
        # `agy --help` spells it --model with no short form.
        "antigravity": ("AntigravityAgent", "--model"),
    }

    # Registered CLI agents that deliberately do NOT put self.model on the
    # wire, and why. Keeping this explicit is what makes the reverse test
    # below meaningful.
    #
    #   qwen-cli / deepseek-cli  their registry defaults were NOT refreshed:
    #                            both stayed on the CLI's own native
    #                            pre-refresh model code because the catalog
    #                            rows are OpenRouter rows (see the comments
    #                            on their registrations). No behaviour of
    #                            theirs changed in this PR.
    #   kimi-cli                 same, and only registered under
    #                            ARAGORA_ENABLE_KIMI_CLI; its headless
    #                            invocation is documented as unverified.
    #   grok-build               "grok-build" names the CLI product, not a
    #                            model id, so there is no pin to send.
    #   kilocode                 brokers several providers and sends
    #                            provider_id via --model, not self.model.
    NO_WIRE_MODEL = {"qwen-cli", "deepseek-cli", "kimi-cli", "grok-build", "kilocode"}

    @staticmethod
    async def _capture_command(agent, prompt: str) -> list[str]:
        from unittest.mock import AsyncMock, patch

        captured: dict = {}

        async def fake_generate(command, *args, **kwargs):
            captured["command"] = list(command)
            return "ok"

        with (
            patch.object(agent, "_generate_with_fallback", AsyncMock(side_effect=fake_generate)),
            patch(
                "aragora.agents.cli_agents.build_claude_command",
                side_effect=lambda cmd: (cmd, None),
            ),
        ):
            await agent.generate(prompt)
        return captured["command"]

    @pytest.mark.parametrize("registry_name", sorted(CASES))
    @pytest.mark.asyncio
    async def test_argv_path_carries_the_model_flag(self, registry_name):
        import aragora.agents.cli_agents as cli_agents

        attr, flag = self.CASES[registry_name]
        agent = getattr(cli_agents, attr)(name=f"{registry_name}-test", model="pinned-model-x")
        command = await self._capture_command(agent, "hello")

        assert flag in command, f"{registry_name} never passed its model flag: {command}"
        assert command[command.index(flag) + 1] == "pinned-model-x"

    @pytest.mark.parametrize("registry_name", sorted(CASES))
    @pytest.mark.asyncio
    async def test_stdin_path_carries_the_model_flag(self, registry_name):
        """The large-prompt branch is a separate command array and was the
        half a partial fix would miss."""
        import aragora.agents.cli_agents as cli_agents

        attr, flag = self.CASES[registry_name]
        agent = getattr(cli_agents, attr)(name=f"{registry_name}-test", model="pinned-model-x")
        huge = "x" * (1024 * 1024)
        command = await self._capture_command(agent, huge)

        assert flag in command, f"{registry_name} stdin path dropped the pin: {command}"
        assert command[command.index(flag) + 1] == "pinned-model-x"
        assert command[-1] == "-", command

    @pytest.mark.asyncio
    async def test_every_registered_cli_agent_sends_its_model_or_is_exempt(self):
        """Reverse completeness: a future refreshed pin cannot quietly stop
        at the registry."""
        import aragora.agents.cli_agents as cli_agents
        from aragora.agents.registry import AgentRegistry

        offenders: list[str] = []
        stale_exemptions: list[str] = []
        for name, spec in sorted(AgentRegistry._registry.items()):
            if getattr(spec, "agent_type", None) != "CLI":
                continue
            cls = getattr(spec, "agent_class", None)
            default_model = getattr(spec, "default_model", None)
            if cls is None or cls.__module__ != cli_agents.__name__:
                continue
            if name in self.NO_WIRE_MODEL:
                if default_model is None:
                    continue
                agent = cls(name=f"{name}-test", model=default_model)
                command = await self._capture_command(agent, "hello")
                if default_model in command:
                    stale_exemptions.append(name)
                continue
            assert default_model, f"{name} is not exempt but has no default model"
            agent = cls(name=f"{name}-test", model=default_model)
            command = await self._capture_command(agent, "hello")
            if default_model not in command:
                offenders.append(f"{name} -> {command}")

        assert not offenders, (
            "registered CLI agents record a model the CLI is never told:\n" + "\n".join(offenders)
        )
        assert not stale_exemptions, (
            f"these agents now send their model and must leave NO_WIRE_MODEL: {stale_exemptions}"
        )


class TestUnpinnedCLIAgentsDoNotClaimTheirModel:
    """An agent whose model never reaches the CLI must say so.

    qwen-cli, deepseek-cli and the opt-in kimi-cli each carry a native model
    code the CLI is never told about: qwen's own ``-m`` flag exists but its
    recorded id is a retired spelling with no native successor, and neither
    the deepseek nor the kimi CLI is installed on the machine this branch was
    built on, so no flag could be verified rather than guessed (see
    CLIAgent.SENDS_MODEL_ON_WIRE). They keep the requested pin, because
    pricing, fallback and the registry all need it, and declare
    ``metadata["model_pinned_on_wire"] = False`` so nothing downstream
    attributes the answer to a model the CLI never received (wave-6 ruling,
    agents, on #9989).
    """

    @pytest.mark.parametrize(
        ("attr", "model"),
        [
            ("QwenCLIAgent", "qwen3-coder"),
            ("DeepseekCLIAgent", "deepseek-v4-pro"),
            ("KimiCLIAgent", "kimi-k2"),
        ],
    )
    def test_unpinned_agent_flags_the_missing_wire_pin(self, attr, model):
        import aragora.agents.cli_agents as cli_agents

        agent = getattr(cli_agents, attr)(name=f"{attr}-test", model=model)
        assert agent.model == model, "the requested pin must still be carried"
        assert agent.metadata["model_pinned_on_wire"] is False

    @pytest.mark.parametrize(
        "attr",
        sorted(attr for attr, _flag in TestRefreshedCLIAgentsPinTheirModel.CASES.values()),
    )
    def test_a_pinned_agent_claims_its_wire_pin(self, attr):
        import aragora.agents.cli_agents as cli_agents

        agent = getattr(cli_agents, attr)(name=f"{attr}-test", model="pinned-model-x")
        assert agent.metadata["model_pinned_on_wire"] is True

    def test_the_wire_claim_agrees_with_the_command_builders(self):
        """The claim and the exemption list are two statements of one fact.

        ``TestRefreshedCLIAgentsPinTheirModel.NO_WIRE_MODEL`` is proven
        against the actual command arrays there; this asserts the class
        attribute never drifts from it, so a future builder that starts (or
        stops) sending its model cannot leave the metadata lying.
        """
        import aragora.agents.cli_agents as cli_agents
        from aragora.agents.registry import AgentRegistry

        exempt = TestRefreshedCLIAgentsPinTheirModel.NO_WIRE_MODEL
        mismatched = []
        for name, spec in sorted(AgentRegistry._registry.items()):
            if getattr(spec, "agent_type", None) != "CLI":
                continue
            cls = getattr(spec, "agent_class", None)
            if cls is None or cls.__module__ != cli_agents.__name__:
                continue
            expected = name not in exempt
            if cls.SENDS_MODEL_ON_WIRE is not expected:
                mismatched.append(f"{name}: SENDS_MODEL_ON_WIRE={cls.SENDS_MODEL_ON_WIRE}")
        assert not mismatched, (
            "SENDS_MODEL_ON_WIRE disagrees with the proven NO_WIRE_MODEL set: "
            + ", ".join(mismatched)
        )


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

    def test_resolve_effort_defaults_to_medium(self, monkeypatch):
        from aragora.agents.cli_agents import (
            ANTIGRAVITY_DEFAULT_EFFORT,
            _resolve_antigravity_effort,
        )

        monkeypatch.delenv("ARAGORA_ANTIGRAVITY_EFFORT", raising=False)
        assert ANTIGRAVITY_DEFAULT_EFFORT == "medium"
        assert _resolve_antigravity_effort() == "medium"

    def test_resolve_effort_honors_override(self, monkeypatch):
        from aragora.agents.cli_agents import _resolve_antigravity_effort

        monkeypatch.setenv("ARAGORA_ANTIGRAVITY_EFFORT", "high")
        assert _resolve_antigravity_effort() == "high"

    @pytest.mark.parametrize("bad", ["foo", "HIGHEST", "1", "medium high", "-"])
    def test_resolve_effort_rejects_an_unrecognised_level(self, monkeypatch, caplog, bad):
        """``agy`` accepts exactly low|medium|high, so passing anything else
        through made every antigravity call error out and fall back to
        OpenRouter -- the same silent failure --effort was added to prevent,
        now triggered by a typo (wave-6 re-review, minor 3)."""
        import logging

        from aragora.agents.cli_agents import _resolve_antigravity_effort

        monkeypatch.setenv("ARAGORA_ANTIGRAVITY_EFFORT", bad)
        with caplog.at_level(logging.WARNING, logger="aragora.agents.cli_agents"):
            assert _resolve_antigravity_effort() == "medium"
        assert [r for r in caplog.records if "ARAGORA_ANTIGRAVITY_EFFORT" in r.getMessage()]

    @pytest.mark.parametrize("level", ["low", "medium", "high"])
    def test_resolve_effort_accepts_every_documented_level(self, monkeypatch, level):
        from aragora.agents.cli_agents import _resolve_antigravity_effort

        monkeypatch.setenv("ARAGORA_ANTIGRAVITY_EFFORT", level)
        assert _resolve_antigravity_effort() == level

    @pytest.mark.parametrize(("spelled", "expected"), [("HIGH", "high"), (" Low ", "low")])
    def test_resolve_effort_normalizes_case_and_padding(self, monkeypatch, spelled, expected):
        """An operator writing HIGH means high, not "fall back to medium"."""
        from aragora.agents.cli_agents import _resolve_antigravity_effort

        monkeypatch.setenv("ARAGORA_ANTIGRAVITY_EFFORT", spelled)
        assert _resolve_antigravity_effort() == expected

    def test_a_rejected_level_still_reaches_the_command_line_as_medium(self, monkeypatch):
        """The end-to-end consequence: the argv is valid regardless."""
        from aragora.agents.cli_agents import _resolve_antigravity_effort

        monkeypatch.setenv("ARAGORA_ANTIGRAVITY_EFFORT", "foo")
        assert ["--effort", _resolve_antigravity_effort()] == ["--effort", "medium"]

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
        # `agy --model <id>` requires a companion `--effort` flag or the
        # call errors and silently falls back to OpenRouter (finding on
        # #9989 wave 6).
        assert cmd[1:5] == ["--model", "gemini-3.5-flash", "--effort", "medium"]

    def test_generate_stdin_path_also_carries_effort(self):
        """The large-prompt (stdin) branch is a separate command array and
        would be the half a partial fix missed."""
        from unittest.mock import patch

        from aragora.agents.cli_agents import AntigravityAgent

        agent = AntigravityAgent(
            name="agy-test",
            model="gemini-3.5-flash",
            enable_fallback=False,
            enable_circuit_breaker=False,
        )
        huge = "x" * (1024 * 1024)
        with patch.object(agent, "_run_cli", new=AsyncMock(return_value="OK")) as m:
            asyncio.run(agent.generate(huge))
        cmd = m.call_args.args[0]
        assert cmd[1:5] == ["--model", "gemini-3.5-flash", "--effort", "medium"]
        assert cmd[-2:] == ["-p", "-"]


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
