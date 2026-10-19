"""Tests for the Control Plane AgentFactory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.control_plane.agent_factory import (
    PROVIDER_TO_AGENT_TYPE,
    AgentCreationResult,
    AgentFactory,
    AgentFactoryConfig,
    get_agent_factory,
    reset_agent_factory,
)


# Mock AgentInfo for testing (to avoid circular imports)
@dataclass
class MockAgentInfo:
    """Mock AgentInfo for testing."""

    agent_id: str
    capabilities: set[str]
    provider: str = "unknown"
    model: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


class TestProviderMapping:
    """Test provider name resolution."""

    def test_retired_yi_provider_fails_at_resolution_not_creation(self):
        """2026-09-05 merge-gate fix wave, finding O-P2b on #9989.

        The PR removed the "yi" agent registration/allowlist/credential row
        but left ``PROVIDER_TO_AGENT_TYPE["yi"] = "yi"``, so an existing
        ``AgentInfo(provider="yi")`` resolved cleanly and then failed deep
        inside ``create_agent()`` with an unknown-agent-type error. It must
        fail at the resolution boundary with a message naming the provider.
        """
        assert "yi" not in PROVIDER_TO_AGENT_TYPE
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="yi-1",
            capabilities={"debate"},
            provider="yi",
            model="yi-large",
        )
        assert factory.resolve_agent_type(info) is None

        result = factory.create_from_info(info)
        assert result.success is False
        assert result.agent is None
        assert result.error is not None
        assert "yi" in result.error
        assert "Cannot resolve provider" in result.error
        # Not a credentials problem: the provider itself is gone.
        assert result.credentials_missing is False

    def test_anthropic_provider(self):
        """Anthropic provider should map to anthropic-api."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="anthropic",
            model="claude-3-opus",
        )
        assert factory.resolve_agent_type(info) == "anthropic-api"

    def test_openai_provider(self):
        """OpenAI provider should map to openai-api."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="openai",
            model="gpt-4o",
        )
        assert factory.resolve_agent_type(info) == "openai-api"

    def test_google_provider(self):
        """Google/Gemini provider should map to gemini."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="google",
            model="gemini-pro",
        )
        assert factory.resolve_agent_type(info) == "gemini"

    def test_gemini_provider(self):
        """Gemini provider should map to gemini."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="gemini",
            model="gemini-1.5-pro",
        )
        assert factory.resolve_agent_type(info) == "gemini"

    def test_grok_provider(self):
        """Grok/xAI provider should map to grok."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="xai",
            model="grok-2",
        )
        assert factory.resolve_agent_type(info) == "grok"

    def test_mistral_provider(self):
        """Mistral provider should map to mistral-api."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="mistral",
            model="mistral-large",
        )
        assert factory.resolve_agent_type(info) == "mistral-api"

    def test_deepseek_provider(self):
        """DeepSeek provider should map to deepseek."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="deepseek",
            model="deepseek-v4-pro",
        )
        assert factory.resolve_agent_type(info) == "deepseek"

    def test_model_heuristic_fallback_claude(self):
        """Unknown provider with claude model should map to anthropic-api."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="unknown",
            model="claude-3-sonnet",
        )
        assert factory.resolve_agent_type(info) == "anthropic-api"

    def test_model_heuristic_fallback_gpt(self):
        """Unknown provider with gpt model should map to openai-api."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="unknown",
            model="gpt-4-turbo",
        )
        assert factory.resolve_agent_type(info) == "openai-api"

    def test_model_heuristic_fallback_o1(self):
        """Unknown provider with o1 model should map to openai-api."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="unknown",
            model="o1-preview",
        )
        assert factory.resolve_agent_type(info) == "openai-api"

    def test_unknown_provider_returns_none(self):
        """Completely unknown provider and model should return None."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="unknown",
            model="unknown",
        )
        assert factory.resolve_agent_type(info) is None

    def test_explicit_metadata_override(self):
        """Explicit agent_type in metadata should take precedence."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="custom",
            model="custom-model",
            metadata={"agent_type": "anthropic-api"},
        )
        assert factory.resolve_agent_type(info) == "anthropic-api"

    def test_provider_overrides_in_config(self):
        """Custom provider overrides in config should work."""
        config = AgentFactoryConfig(provider_overrides={"my-custom-provider": "anthropic-api"})
        factory = AgentFactory(config)
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="my-custom-provider",
            model="custom-model",
        )
        assert factory.resolve_agent_type(info) == "anthropic-api"

    def test_demo_provider(self):
        """Demo provider should map to demo."""
        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="demo",
            model="demo",
        )
        assert factory.resolve_agent_type(info) == "demo"

    def test_local_providers(self):
        """Local providers (ollama, lm-studio) should map correctly."""
        factory = AgentFactory()

        info_ollama = MockAgentInfo(
            agent_id="a1", capabilities={"debate"}, provider="ollama", model="llama3"
        )
        assert factory.resolve_agent_type(info_ollama) == "ollama"

        info_lm = MockAgentInfo(
            agent_id="a2", capabilities={"debate"}, provider="lm-studio", model="local"
        )
        assert factory.resolve_agent_type(info_lm) == "lm-studio"


class TestAgentCreation:
    """Test agent creation from AgentInfo."""

    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    @patch("aragora.agents.base.create_agent")
    def test_successful_creation(self, mock_create, mock_validate):
        """Successful agent creation with valid credentials."""
        mock_validate.return_value = True
        mock_agent = MagicMock()
        mock_agent.name = "test-agent"
        mock_create.return_value = mock_agent

        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="claude-1",
            capabilities={"debate"},
            provider="anthropic",
            model="claude-3-opus",
        )
        result = factory.create_from_info(info)

        assert result.success
        assert result.agent is mock_agent
        assert result.error is None
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model_type"] == "anthropic-api"
        assert call_kwargs["name"] == "claude-1"

    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    def test_missing_credentials_no_fallback(self, mock_validate):
        """Missing credentials without fallback should fail."""
        mock_validate.return_value = False

        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=False))
        info = MockAgentInfo(
            agent_id="claude-1",
            capabilities={"debate"},
            provider="anthropic",
            model="claude-3-opus",
        )
        result = factory.create_from_info(info)

        assert not result.success
        assert result.credentials_missing is True
        assert "Credentials missing" in result.error

    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    @patch("aragora.agents.base.create_agent")
    def test_missing_credentials_with_demo_fallback(self, mock_create, mock_validate):
        """Missing credentials with demo fallback should create demo agent."""
        mock_validate.return_value = False
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=True))
        info = MockAgentInfo(
            agent_id="claude-1",
            capabilities={"debate"},
            provider="anthropic",
            model="claude-3-opus",
        )
        result = factory.create_from_info(info)

        assert result.success
        mock_create.assert_called_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model_type"] == "demo"

    def test_unknown_provider_no_fallback(self):
        """Unknown provider without fallback should fail."""
        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=False))
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="unknown",
            model="unknown",
        )
        result = factory.create_from_info(info)

        assert not result.success
        assert "Cannot resolve provider" in result.error

    @patch("aragora.agents.base.create_agent")
    def test_unknown_provider_with_fallback(self, mock_create):
        """Unknown provider with demo fallback should create demo agent."""
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=True))
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="unknown",
            model="unknown",
        )
        result = factory.create_from_info(info)

        assert result.success
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["model_type"] == "demo"

    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    @patch("aragora.agents.base.create_agent")
    def test_creation_failure_returns_error(self, mock_create, mock_validate):
        """Agent creation exception should return error result."""
        mock_validate.return_value = True
        mock_create.side_effect = ValueError("Invalid model")

        factory = AgentFactory()
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="anthropic",
            model="claude-3-opus",
        )
        result = factory.create_from_info(info)

        assert not result.success
        assert result.error  # Sanitized error message present

    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    @patch("aragora.agents.base.create_agent")
    def test_role_override(self, mock_create, mock_validate):
        """Role parameter should override default role."""
        mock_validate.return_value = True
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent

        factory = AgentFactory(AgentFactoryConfig(default_role="synthesizer"))
        info = MockAgentInfo(
            agent_id="a1",
            capabilities={"debate"},
            provider="anthropic",
            model="claude-3-opus",
        )

        # Use default role
        factory.create_from_info(info)
        assert mock_create.call_args[1]["role"] == "synthesizer"

        # Override role
        factory.create_from_info(info, role="critic")
        assert mock_create.call_args[1]["role"] == "critic"


class TestBatchCreation:
    """Test batch agent creation."""

    @pytest.mark.asyncio
    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    @patch("aragora.agents.base.create_agent")
    async def test_create_multiple_agents(self, mock_create, mock_validate):
        """Batch creation should create multiple agents."""
        mock_validate.return_value = True
        mock_create.return_value = MagicMock()

        factory = AgentFactory()
        infos = [
            MockAgentInfo(
                agent_id="a1",
                capabilities={"debate"},
                provider="anthropic",
                model="claude-3-opus",
            ),
            MockAgentInfo(
                agent_id="a2",
                capabilities={"debate"},
                provider="openai",
                model="gpt-4o",
            ),
        ]
        agents = await factory.create_agents(infos)

        assert len(agents) == 2
        assert mock_create.call_count == 2

    @pytest.mark.asyncio
    @patch("aragora.agents.credential_validator.validate_agent_credentials")
    @patch("aragora.agents.base.create_agent")
    async def test_partial_creation_skips_failures(self, mock_create, mock_validate):
        """Batch creation should skip agents that fail."""
        mock_validate.side_effect = [True, False, True]  # Second fails credentials
        mock_create.return_value = MagicMock()

        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=False))
        infos = [
            MockAgentInfo(
                agent_id="a1", capabilities={"debate"}, provider="anthropic", model="claude"
            ),
            MockAgentInfo(agent_id="a2", capabilities={"debate"}, provider="openai", model="gpt"),
            MockAgentInfo(
                agent_id="a3", capabilities={"debate"}, provider="gemini", model="gemini"
            ),
        ]
        agents = await factory.create_agents(infos)

        # One should fail due to credentials
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_min_agents_enforcement(self):
        """Batch creation should raise if min_agents not met."""
        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=False))
        infos = [
            MockAgentInfo(
                agent_id="a1",
                capabilities={"debate"},
                provider="unknown",
                model="unknown",
            ),
        ]

        with pytest.raises(RuntimeError, match="Only 0 agents created"):
            await factory.create_agents(infos, min_agents=2)

    @pytest.mark.asyncio
    @patch("aragora.agents.base.create_agent")
    async def test_min_agents_zero_allows_empty(self, mock_create):
        """min_agents=0 should allow empty result."""
        factory = AgentFactory(AgentFactoryConfig(fallback_to_demo=False))
        infos = [
            MockAgentInfo(
                agent_id="a1",
                capabilities={"debate"},
                provider="unknown",
                model="unknown",
            ),
        ]

        # Should not raise with min_agents=0
        agents = await factory.create_agents(infos, min_agents=0)
        assert len(agents) == 0


class TestSingleton:
    """Test factory singleton management."""

    def test_get_returns_same_instance(self):
        """get_agent_factory should return singleton."""
        reset_agent_factory()
        f1 = get_agent_factory()
        f2 = get_agent_factory()
        assert f1 is f2

    def test_reset_clears_singleton(self):
        """reset_agent_factory should clear singleton."""
        f1 = get_agent_factory()
        reset_agent_factory()
        f2 = get_agent_factory()
        assert f1 is not f2


class TestProviderToAgentTypeMapping:
    """Tests for the PROVIDER_TO_AGENT_TYPE constant."""

    def test_has_major_providers(self):
        """Map should include all major providers."""
        assert "anthropic" in PROVIDER_TO_AGENT_TYPE
        assert "openai" in PROVIDER_TO_AGENT_TYPE
        assert "google" in PROVIDER_TO_AGENT_TYPE
        assert "gemini" in PROVIDER_TO_AGENT_TYPE
        assert "xai" in PROVIDER_TO_AGENT_TYPE
        assert "grok" in PROVIDER_TO_AGENT_TYPE
        assert "mistral" in PROVIDER_TO_AGENT_TYPE
        assert "deepseek" in PROVIDER_TO_AGENT_TYPE
        assert "openrouter" in PROVIDER_TO_AGENT_TYPE

    def test_has_local_providers(self):
        """Map should include local providers."""
        assert "ollama" in PROVIDER_TO_AGENT_TYPE
        assert "lm-studio" in PROVIDER_TO_AGENT_TYPE
        assert "demo" in PROVIDER_TO_AGENT_TYPE

    def test_mapping_values_are_valid_agent_types(self):
        """All mapping values should be valid agent type names."""
        # These are the known valid agent types from the registry
        known_types = {
            "anthropic-api",
            "openai-api",
            "gemini",
            "grok",
            "mistral-api",
            "deepseek",
            "llama",
            "qwen",
            "kimi",
            "openrouter",
            "claude",
            "codex",
            "ollama",
            "lm-studio",
            "local",
            "demo",
        }

        for provider, agent_type in PROVIDER_TO_AGENT_TYPE.items():
            assert agent_type in known_types, (
                f"Provider '{provider}' maps to unknown type '{agent_type}'"
            )
