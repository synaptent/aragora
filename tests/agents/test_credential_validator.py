"""Tests for agent credential validation."""

import os
from unittest.mock import patch

import pytest

from aragora.agents.credential_validator import (
    AGENT_CREDENTIAL_MAP,
    CredentialStatus,
    filter_available_agents,
    get_available_agent_types,
    get_credential_status,
    get_missing_credentials_summary,
    validate_agent_credentials,
)


class TestValidateAgentCredentials:
    """Tests for validate_agent_credentials function."""

    def test_local_agents_always_available(self):
        """Local agents (ollama, lm-studio) should always be available."""
        assert validate_agent_credentials("ollama") is True
        assert validate_agent_credentials("lm-studio") is True
        assert validate_agent_credentials("local") is True
        assert validate_agent_credentials("demo") is True

    def test_unknown_agent_returns_true(self):
        """Unknown agent types should return True (no known requirements)."""
        assert validate_agent_credentials("unknown-agent-xyz") is True

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}, clear=False)
    def test_anthropic_with_key(self):
        """Anthropic agents should be available when key is set."""
        # Need to clear secrets cache
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
        assert validate_agent_credentials("anthropic-api") is True
        assert validate_agent_credentials("claude") is True

    @patch.dict(os.environ, {}, clear=True)
    def test_anthropic_without_key(self):
        """Anthropic agents should be unavailable without key."""
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
        # Set ARAGORA_USE_SECRETS_MANAGER to false to avoid AWS
        os.environ["ARAGORA_USE_SECRETS_MANAGER"] = "false"
        assert validate_agent_credentials("anthropic-api") is False

    @patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False)
    def test_openrouter_models_with_fallback(self):
        """OpenRouter models should be available via OpenRouter key."""
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
        assert validate_agent_credentials("deepseek") is True
        assert validate_agent_credentials("llama") is True
        assert validate_agent_credentials("qwen") is True


class TestGetCredentialStatus:
    """Tests for get_credential_status function."""

    def test_local_agent_status(self):
        """Local agents should have no requirements."""
        status = get_credential_status("ollama")
        assert status.is_available is True
        assert status.required_vars == []
        assert status.missing_vars == []
        assert status.available_via == "no_credentials_required"

    @patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}, clear=False)
    def test_gemini_with_key(self):
        """Gemini should show available with correct key."""
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
        status = get_credential_status("gemini")
        assert status.is_available is True
        assert status.config_present is True
        assert status.live_ready is False
        assert status.status == "configured"
        assert status.next_action
        assert status.available_via == "GEMINI_API_KEY"

    def test_status_dataclass_fields(self):
        """CredentialStatus should have all expected fields."""
        status = get_credential_status("demo")
        assert hasattr(status, "agent_type")
        assert hasattr(status, "is_available")
        assert hasattr(status, "required_vars")
        assert hasattr(status, "missing_vars")
        assert hasattr(status, "available_via")


class TestFilterAvailableAgents:
    """Tests for filter_available_agents function."""

    def test_filter_keeps_local_agents(self):
        """Local agents should always pass through filter."""
        from aragora.agents.spec import AgentSpec

        specs = [
            AgentSpec(provider="ollama", name="ollama-1"),
            AgentSpec(provider="demo", name="demo-1"),
        ]
        available, filtered = filter_available_agents(specs, log_filtered=False)
        assert len(available) == 2
        assert len(filtered) == 0

    def test_filter_raises_if_below_minimum(self):
        """Should raise ValueError if fewer than min_agents remain."""
        from aragora.agents.spec import AgentSpec
        from aragora.config.secrets import reset_secret_manager

        specs = [
            AgentSpec(provider="anthropic-api", name="claude-1"),
            AgentSpec(provider="openai-api", name="gpt-1"),
        ]
        # Force unavailable by clearing all relevant API keys and disabling
        # OpenRouter fallback (anthropic-api and openai-api are fallback-eligible)
        with patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "",
                "OPENAI_API_KEY": "",
                "OPENROUTER_API_KEY": "",
                "ARAGORA_OPENROUTER_FALLBACK_ENABLED": "false",
                "ARAGORA_USE_SECRETS_MANAGER": "false",
            },
            clear=False,
        ):
            reset_secret_manager()
            with pytest.raises(ValueError, match="agents have valid credentials"):
                filter_available_agents(specs, log_filtered=False, min_agents=2)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "key1", "OPENAI_API_KEY": "key2"}, clear=False)
    def test_filter_with_available_agents(self):
        """Should keep agents with valid credentials."""
        from aragora.agents.spec import AgentSpec
        from aragora.config.secrets import reset_secret_manager

        reset_secret_manager()
        specs = [
            AgentSpec(provider="anthropic-api", name="claude-1"),
            AgentSpec(provider="openai-api", name="gpt-1"),
        ]
        available, filtered = filter_available_agents(specs, log_filtered=False)
        assert len(available) == 2
        assert len(filtered) == 0


class TestAgentCredentialMap:
    """Tests for AGENT_CREDENTIAL_MAP constant."""

    def test_map_has_common_agents(self):
        """Map should include all common agent types."""
        assert "anthropic-api" in AGENT_CREDENTIAL_MAP
        assert "openai-api" in AGENT_CREDENTIAL_MAP
        assert "gemini" in AGENT_CREDENTIAL_MAP
        assert "ollama" in AGENT_CREDENTIAL_MAP
        assert "openrouter" in AGENT_CREDENTIAL_MAP

    def test_local_agents_have_no_requirements(self):
        """Local agents should have empty requirement lists."""
        assert AGENT_CREDENTIAL_MAP["ollama"] == []
        assert AGENT_CREDENTIAL_MAP["lm-studio"] == []
        assert AGENT_CREDENTIAL_MAP["demo"] == []

    def test_openrouter_models_have_fallback(self):
        """OpenRouter models should list both direct and OpenRouter keys."""
        assert "OPENROUTER_API_KEY" in AGENT_CREDENTIAL_MAP["deepseek"]
        assert "DEEPSEEK_API_KEY" in AGENT_CREDENTIAL_MAP["deepseek"]

    def test_kimi_runtime_and_legacy_credentials_are_distinct(self):
        assert AGENT_CREDENTIAL_MAP["kimi"] == ["OPENROUTER_API_KEY"]
        assert AGENT_CREDENTIAL_MAP["kimi-k3"] == ["OPENROUTER_API_KEY"]
        assert AGENT_CREDENTIAL_MAP["kimi-thinking"] == ["OPENROUTER_API_KEY"]
        assert AGENT_CREDENTIAL_MAP["kimi-legacy"] == ["KIMI_API_KEY"]


class TestGetAvailableAgentTypes:
    """Tests for get_available_agent_types function."""

    def test_always_includes_local_agents(self):
        """Should always include local agents regardless of env."""
        available = get_available_agent_types()
        assert "ollama" in available
        assert "lm-studio" in available
        assert "demo" in available

    def test_returns_list(self):
        """Should return a list of strings."""
        available = get_available_agent_types()
        assert isinstance(available, list)
        assert all(isinstance(a, str) for a in available)


class TestGetMissingCredentialsSummary:
    """Tests for get_missing_credentials_summary function."""

    def test_returns_dict(self):
        """Should return a dictionary."""
        summary = get_missing_credentials_summary()
        assert isinstance(summary, dict)

    def test_local_agents_not_in_summary(self):
        """Local agents should not appear in missing summary."""
        summary = get_missing_credentials_summary()
        assert "ollama" not in summary
        assert "lm-studio" not in summary
        assert "demo" not in summary
