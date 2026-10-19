"""
Tests for OpenRouter Agent and Provider-Specific Subclasses.

Tests the OpenRouter agent functionality including:
- Initialization and configuration
- Context prompt building
- Fallback model chain
- Rate limiting integration
- Provider-specific subclasses (DeepSeek, Llama, Mistral, etc.)
- Agent registry integration
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =============================================================================
# Fallback Model Chain Tests
# =============================================================================


class TestFallbackModelChain:
    """Test OPENROUTER_FALLBACK_MODELS configuration."""

    def test_fallback_chain_exists(self):
        """Test fallback model chain is defined."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert isinstance(OPENROUTER_FALLBACK_MODELS, dict)
        assert len(OPENROUTER_FALLBACK_MODELS) > 0

    def test_deepseek_has_fallback(self):
        """Test DeepSeek models have fallbacks."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert "deepseek/deepseek-v4-pro-0813" in OPENROUTER_FALLBACK_MODELS
        # Retargeted off the retired openai/gpt-5.5 to the live cheap/bulk
        # OpenAI route (frontier-model-refresh final review #3): a fallback
        # target is only useful if a live request to it succeeds.
        assert OPENROUTER_FALLBACK_MODELS["deepseek/deepseek-v4-pro-0813"] == "openai/gpt-5.6-terra"

    def test_qwen_has_fallback(self):
        """Test Qwen models have fallbacks."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert (
            OPENROUTER_FALLBACK_MODELS["qwen/qwen3.8-2.4t-a95b"] == "deepseek/deepseek-v4-pro-0813"
        )
        assert "qwen/qwen-2.5-72b-instruct" in OPENROUTER_FALLBACK_MODELS
        assert (
            OPENROUTER_FALLBACK_MODELS["qwen/qwen-2.5-72b-instruct"]
            == "deepseek/deepseek-v4-pro-0813"
        )

    def test_legacy_default_keys_keep_fallback(self):
        """Renamed defaults keep their legacy keys as aliases (#9073 P2):
        callers still pinning the old ids must not lose retry fallback."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert OPENROUTER_FALLBACK_MODELS["qwen/qwen3-max"] == "deepseek/deepseek-v4-pro-0813"
        assert OPENROUTER_FALLBACK_MODELS["qwen/qwen3.7-max"] == "deepseek/deepseek-v4-pro-0813"
        assert OPENROUTER_FALLBACK_MODELS["qwen/qwen3-235b-a22b"] == "deepseek/deepseek-v4-pro-0813"
        assert (
            OPENROUTER_FALLBACK_MODELS["qwen/qwen3.5-plus-02-15"] == "deepseek/deepseek-v4-pro-0813"
        )
        assert OPENROUTER_FALLBACK_MODELS["moonshotai/kimi-k2.6"] == "anthropic/claude-opus-5"
        assert OPENROUTER_FALLBACK_MODELS["moonshotai/kimi-k2.7-code"] == "anthropic/claude-opus-5"

    def test_kimi_has_fallback(self):
        """Test Kimi models have fallbacks."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert OPENROUTER_FALLBACK_MODELS["moonshotai/kimi-k3"] == "anthropic/claude-opus-5"
        assert "moonshotai/kimi-k2.7-code" in OPENROUTER_FALLBACK_MODELS
        assert OPENROUTER_FALLBACK_MODELS["moonshotai/kimi-k2.7-code"] == "anthropic/claude-opus-5"

    def test_llama_has_fallback(self):
        """Test Llama models have fallbacks."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert "meta-llama/llama-3.3-70b-instruct" in OPENROUTER_FALLBACK_MODELS


# =============================================================================
# OpenRouterAgent Initialization Tests
# =============================================================================


class TestOpenRouterAgentInit:
    """Test OpenRouterAgent initialization."""

    def test_init_minimal(self):
        """Test minimal initialization."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent()

            assert agent.name == "openrouter"
            assert agent.model == "deepseek/deepseek-v4-pro-0813"
            assert agent.agent_type == "openrouter"

    def test_init_with_custom_model(self):
        """Test initialization with custom model."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent(model="meta-llama/llama-3.3-70b-instruct")

            assert agent.model == "meta-llama/llama-3.3-70b-instruct"

    def test_init_with_custom_name(self):
        """Test initialization with custom name."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent(name="my-agent")

            assert agent.name == "my-agent"

    def test_init_with_custom_role(self):
        """Test initialization with custom role."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent(role="critic")

            assert agent.role == "critic"

    def test_init_with_custom_system_prompt(self):
        """Test initialization with custom system prompt."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent(system_prompt="Custom prompt")

            assert agent.system_prompt == "Custom prompt"

    def test_init_with_generation_params(self):
        """Test initialization with generation parameters."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent(
                temperature=0.7,
                top_p=0.9,
                max_tokens=2048,
            )

            assert agent.temperature == 0.7
            assert agent.top_p == 0.9
            assert agent.max_tokens == 2048

    def test_init_base_url(self):
        """Test base URL is set correctly."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent()

            assert agent.base_url == "https://openrouter.ai/api/v1"


# =============================================================================
# Context Prompt Building Tests
# =============================================================================


class TestContextPromptBuilding:
    """Test _build_context_prompt method."""

    @pytest.fixture
    def agent(self):
        """Create agent for testing."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            return OpenRouterAgent()

    def test_empty_context(self, agent):
        """Test empty context returns empty string."""
        result = agent._build_context_prompt(context=None)

        assert result == ""

    def test_empty_list_context(self, agent):
        """Test empty list returns empty string."""
        result = agent._build_context_prompt(context=[])

        assert result == ""

    def test_single_message_context(self, agent):
        """Test single message in context."""
        from aragora.agents.api_agents.common import Message

        message = Message(
            agent="claude",
            role="proposer",
            content="This is a proposal",
        )

        result = agent._build_context_prompt(context=[message])

        assert "Previous discussion:" in result
        assert "claude" in result
        assert "proposer" in result
        assert "This is a proposal" in result

    def test_context_limits_to_five_messages(self, agent):
        """Test context is limited to 5 most recent messages."""
        from aragora.agents.api_agents.common import Message

        messages = [
            Message(agent=f"agent-{i}", role="proposer", content=f"Message {i}") for i in range(10)
        ]

        result = agent._build_context_prompt(context=messages)

        # Should only contain last 5 messages (5-9)
        assert "agent-5" in result
        assert "agent-9" in result
        # Should not contain first 5 messages (0-4)
        assert "agent-0" not in result
        assert "agent-4" not in result

    def test_context_truncates_long_messages(self, agent):
        """Test long messages are truncated to 500 chars."""
        from aragora.agents.api_agents.common import Message

        long_content = "A" * 1000
        message = Message(
            agent="claude",
            role="proposer",
            content=long_content,
        )

        result = agent._build_context_prompt(context=[message])

        # Should be truncated
        assert "A" * 500 + "..." in result
        assert "A" * 1000 not in result


# =============================================================================
# Provider-Specific Agent Tests
# =============================================================================


class TestProviderSpecificAgents:
    """Test provider-specific agent subclasses."""

    def test_deepseek_agent_exists(self):
        """Test DeepSeekAgent class exists."""
        from aragora.agents.api_agents.openrouter import DeepSeekAgent

        assert DeepSeekAgent is not None

    def test_deepseek_agent_model(self):
        """Test DeepSeekAgent uses correct model."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import DeepSeekAgent

            agent = DeepSeekAgent()

            assert "deepseek" in agent.model.lower()

    def test_llama_agent_exists(self):
        """Test LlamaAgent class exists."""
        from aragora.agents.api_agents.openrouter import LlamaAgent

        assert LlamaAgent is not None

    def test_mistral_agent_exists(self):
        """Test MistralAgent class exists."""
        from aragora.agents.api_agents.openrouter import MistralAgent

        assert MistralAgent is not None

    def test_qwen_agent_exists(self):
        """Test QwenAgent class exists."""
        from aragora.agents.api_agents.openrouter import QwenAgent

        assert QwenAgent is not None

    def test_kimi_agent_exists(self):
        """Test KimiK3Agent and its compatibility alias exist."""
        from aragora.agents.api_agents.openrouter import KimiK2Agent, KimiK3Agent

        assert KimiK2Agent is KimiK3Agent


# =============================================================================
# Agent Registry Integration Tests
# =============================================================================


class TestAgentRegistryIntegration:
    """Test agent registry integration."""

    def test_openrouter_agent_registered(self):
        """Test OpenRouterAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        # Force registration by importing the module
        import aragora.agents.api_agents.openrouter  # noqa: F401

        registry = AgentRegistry.list_all()

        assert "openrouter" in registry

    def test_deepseek_agent_registered(self):
        """Test DeepSeekAgent is registered."""
        from aragora.agents.registry import AgentRegistry

        import aragora.agents.api_agents.openrouter  # noqa: F401

        registry = AgentRegistry.list_all()

        # Check if any registered agent name contains 'deepseek'
        assert "deepseek" in registry or any("deepseek" in name for name in registry)


# =============================================================================
# Inheritance Tests
# =============================================================================


class TestInheritance:
    """Test class inheritance hierarchy."""

    def test_openrouter_inherits_from_api_agent(self):
        """Test OpenRouterAgent inherits from APIAgent."""
        from aragora.agents.api_agents.base import APIAgent
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        assert issubclass(OpenRouterAgent, APIAgent)

    def test_deepseek_inherits_from_openrouter(self):
        """Test DeepSeekAgent inherits from OpenRouterAgent."""
        from aragora.agents.api_agents.openrouter import (
            DeepSeekAgent,
            OpenRouterAgent,
        )

        assert issubclass(DeepSeekAgent, OpenRouterAgent)

    def test_llama_inherits_from_openrouter(self):
        """Test LlamaAgent inherits from OpenRouterAgent."""
        from aragora.agents.api_agents.openrouter import (
            LlamaAgent,
            OpenRouterAgent,
        )

        assert issubclass(LlamaAgent, OpenRouterAgent)


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Test module exports."""

    def test_openrouter_agent_exportable(self):
        """Test OpenRouterAgent can be imported."""
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        assert OpenRouterAgent is not None

    def test_fallback_models_exportable(self):
        """Test OPENROUTER_FALLBACK_MODELS can be imported."""
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert OPENROUTER_FALLBACK_MODELS is not None

    def test_all_provider_agents_exportable(self):
        """Test all provider agents can be imported."""
        from aragora.agents.api_agents.openrouter import (
            DeepSeekAgent,
            KimiK2Agent,
            KimiK3Agent,
            LlamaAgent,
            MistralAgent,
            QwenAgent,
        )

        assert DeepSeekAgent is not None
        assert KimiK2Agent is KimiK3Agent
        assert LlamaAgent is not None
        assert MistralAgent is not None
        assert QwenAgent is not None


# =============================================================================
# Function Signature Tests
# =============================================================================


class TestFunctionSignatures:
    """Test function signatures."""

    def test_init_signature(self):
        """Test __init__ signature."""
        import inspect

        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        sig = inspect.signature(OpenRouterAgent.__init__)
        params = list(sig.parameters.keys())

        assert "name" in params
        assert "role" in params
        assert "model" in params
        assert "system_prompt" in params
        assert "timeout" in params
        assert "temperature" in params
        assert "top_p" in params
        assert "max_tokens" in params

    def test_generate_signature(self):
        """Test generate method signature."""
        import inspect

        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        sig = inspect.signature(OpenRouterAgent.generate)
        params = list(sig.parameters.keys())

        assert "prompt" in params
        assert "context" in params

    def test_build_context_prompt_signature(self):
        """Test _build_context_prompt signature."""
        import inspect

        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        sig = inspect.signature(OpenRouterAgent._build_context_prompt)
        params = list(sig.parameters.keys())

        assert "context" in params
        assert "truncate" in params
        assert "sanitize_fn" in params


# =============================================================================
# Has Required Methods Tests
# =============================================================================


class TestRequiredMethods:
    """Test required methods exist."""

    def test_has_generate_method(self):
        """Test agent has generate method."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent()

            assert hasattr(agent, "generate")
            assert callable(agent.generate)

    def test_has_build_context_prompt_method(self):
        """Test agent has _build_context_prompt method."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent()

            assert hasattr(agent, "_build_context_prompt")
            assert callable(agent._build_context_prompt)

    def test_has_generate_with_model_method(self):
        """Test agent has _generate_with_model method."""
        with patch(
            "aragora.agents.api_agents.openrouter.get_api_key",
            return_value="test-key",
        ):
            from aragora.agents.api_agents.openrouter import OpenRouterAgent

            agent = OpenRouterAgent()

            assert hasattr(agent, "_generate_with_model")
            assert callable(agent._generate_with_model)


class TestSamplingParamStripOnFallback:
    """Opus 4.7+ reject temperature/top_p/top_k with a 400.

    The strip must key off the model actually being SENT, not ``self.model``:
    on the quota-fallback path a non-Claude primary is re-sent as Claude Opus 5
    while ``self.model`` still names the primary. Regression test requested by
    the merge-quorum review on #9588 (round 4).
    """

    def test_non_claude_primary_keeps_sampling_params(self) -> None:
        from aragora.models.compat import strip_sampling_params

        payload = {"model": "moonshotai/kimi-k2.7-code", "temperature": 0.7, "top_p": 0.9}
        model = payload["model"]
        assert isinstance(model, str)
        strip_sampling_params(payload, model)
        assert payload["temperature"] == 0.7, "non-Claude routing must be unchanged"
        assert payload["top_p"] == 0.9

    def test_non_claude_primary_falling_back_to_opus5_is_stripped(self) -> None:
        """The exact bug: Kimi agent (temperature set) falls back to Opus 5."""
        from aragora.models.compat import strip_sampling_params

        # self.model is still the Kimi primary...
        self_model = "moonshotai/kimi-k2.7-code"
        # ...but the payload is being re-sent as the Opus 5 fallback target.
        payload = {"model": "anthropic/claude-opus-5", "temperature": 0.7, "top_p": 0.9}

        # Keying off self.model would leave the params in place and 400.
        strip_sampling_params(payload, self_model)
        assert "temperature" in payload, "guard-rail: self.model is the wrong key"

        # Keying off the payload's own model strips them correctly.
        model = payload["model"]
        assert isinstance(model, str)
        strip_sampling_params(payload, model)
        assert "temperature" not in payload
        assert "top_p" not in payload

    def test_both_openrouter_payload_sites_key_off_payload_model(self) -> None:
        """Pin the call shape so a future edit cannot reintroduce self.model."""
        from pathlib import Path

        import aragora.agents.api_agents.openrouter as mod

        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert src.count('strip_sampling_params(payload, payload["model"])') == 2
        assert "strip_sampling_params(payload, self.model)" not in src


class TestRetiredSpellingKeepsItsFallback:
    """Finding C-P2 on #9989: ``OpenRouterAgent`` performs no retired-id
    upgrade at construction, so a caller (or a stored config, or the PDB
    panel) pinning a retired OpenRouter slug reached the fallback lookup with
    that exact spelling. Dropping its key therefore did not merely lose a
    convenience -- it turned retry exhaustion from "fall back" into "raise".
    """

    def test_retired_deepseek_slug_has_a_key_again(self) -> None:
        from aragora.agents.api_agents.openrouter import OPENROUTER_FALLBACK_MODELS

        assert (
            OPENROUTER_FALLBACK_MODELS["deepseek/deepseek-v4-pro"]
            == "deepseek/deepseek-v4-pro-0813"
        )

    def test_lookup_resolves_a_retired_spelling_with_no_key_of_its_own(self) -> None:
        """A spelling with no key at all still finds its successor's entry."""
        from aragora.agents.api_agents.openrouter import (
            OPENROUTER_FALLBACK_MODELS,
            fallback_model_for,
        )

        assert "openai/gpt-5.5" not in OPENROUTER_FALLBACK_MODELS
        # openai/gpt-5.5 -> gpt-6-astra -> openai/gpt-6-astra's entry.
        assert fallback_model_for("openai/gpt-5.5") == "anthropic/claude-fable-5.1"

    def test_lookup_never_returns_the_model_itself(self) -> None:
        from aragora.agents.api_agents.openrouter import fallback_model_for

        assert fallback_model_for("deepseek/deepseek-v4-pro-0813") == "openai/gpt-5.6-terra"
        assert fallback_model_for("") is None
        assert fallback_model_for("no-such-vendor/no-such-model") is None

    @pytest.mark.asyncio
    async def test_agent_pinned_to_the_retired_slug_actually_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end on the real generate() path: the primary exhausts its
        retries and the live successor slug is the one re-sent."""
        from aragora.agents.api_agents.common import AgentTimeoutError
        from aragora.agents.api_agents.openrouter import OpenRouterAgent

        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
        agent = OpenRouterAgent(model="deepseek/deepseek-v4-pro")
        sent: list[str] = []

        async def fake_generate(model: str, prompt: str, context=None) -> str:
            sent.append(model)
            if model == "deepseek/deepseek-v4-pro":
                raise AgentTimeoutError("exhausted", agent_name=agent.name)
            return "ok"

        agent._generate_with_model = fake_generate  # type: ignore[method-assign]
        assert await agent.generate("hi") == "ok"
        assert sent == ["deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro-0813"]
