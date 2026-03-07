"""Tests for OpenRouter universal fallback in playground agent selection.

Covers:
- Only OPENROUTER_API_KEY set -> returns 3+ diverse agents via OpenRouter models
- All primary keys set -> returns primary providers
- No keys at all -> raises ValueError mentioning OPENROUTER_API_KEY
- Mix of primary + OpenRouter -> primary first, OpenRouter fills remaining
- _resolve_playground_agents converts tags correctly
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from aragora.server.handlers.playground import (
    OPENROUTER_PLAYGROUND_MODELS,
    _get_available_live_agents,
    _resolve_playground_agents,
)


def _make_key_lookup(keys: dict[str, str | None]):
    """Return a side_effect function for _get_api_key that uses the given dict."""

    def _lookup(name: str) -> str | None:
        return keys.get(name)

    return _lookup


# ---------------------------------------------------------------------------
# _get_available_live_agents
# ---------------------------------------------------------------------------


class TestGetAvailableLiveAgentsOpenRouterOnly:
    """When only OPENROUTER_API_KEY is set."""

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_returns_diverse_openrouter_agents(self, mock_key):
        mock_key.side_effect = _make_key_lookup({"OPENROUTER_API_KEY": "or-key"})
        agents = _get_available_live_agents(3)

        assert len(agents) == 3
        assert all(a.startswith("openrouter:") for a in agents)

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_agents_use_different_models(self, mock_key):
        mock_key.side_effect = _make_key_lookup({"OPENROUTER_API_KEY": "or-key"})
        agents = _get_available_live_agents(3)

        models = [a.split(":", 1)[1] for a in agents]
        assert len(set(models)) == 3, "All 3 agents should use different models"

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_can_provide_up_to_five(self, mock_key):
        mock_key.side_effect = _make_key_lookup({"OPENROUTER_API_KEY": "or-key"})
        agents = _get_available_live_agents(5)

        assert len(agents) == 5
        models = [a.split(":", 1)[1] for a in agents]
        assert len(set(models)) == 5, "All 5 agents should use different models"

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_models_match_constant(self, mock_key):
        mock_key.side_effect = _make_key_lookup({"OPENROUTER_API_KEY": "or-key"})
        agents = _get_available_live_agents(5)

        expected_models = [model for _role, model in OPENROUTER_PLAYGROUND_MODELS]
        actual_models = [a.split(":", 1)[1] for a in agents]
        assert actual_models == expected_models


class TestGetAvailableLiveAgentsAllPrimary:
    """When all primary API keys are set."""

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_returns_primary_providers(self, mock_key):
        mock_key.side_effect = _make_key_lookup(
            {
                "ANTHROPIC_API_KEY": "ant-key",
                "OPENAI_API_KEY": "oai-key",
                "MISTRAL_API_KEY": "mis-key",
                "OPENROUTER_API_KEY": "or-key",
            }
        )
        agents = _get_available_live_agents(3)

        assert agents == ["anthropic-api", "openai-api", "mistral-api"]

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_no_openrouter_tags_when_primary_sufficient(self, mock_key):
        mock_key.side_effect = _make_key_lookup(
            {
                "ANTHROPIC_API_KEY": "ant-key",
                "OPENAI_API_KEY": "oai-key",
                "MISTRAL_API_KEY": "mis-key",
            }
        )
        agents = _get_available_live_agents(3)

        assert not any(a.startswith("openrouter:") for a in agents)


class TestGetAvailableLiveAgentsNoKeys:
    """When no API keys are set at all."""

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_raises_value_error(self, mock_key):
        mock_key.return_value = None
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            _get_available_live_agents(3)

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_error_message_mentions_universal_access(self, mock_key):
        mock_key.return_value = None
        with pytest.raises(ValueError, match="universal access"):
            _get_available_live_agents(3)


class TestGetAvailableLiveAgentsMixed:
    """When some primary keys + OpenRouter are available."""

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_primary_first_then_openrouter(self, mock_key):
        mock_key.side_effect = _make_key_lookup(
            {
                "ANTHROPIC_API_KEY": "ant-key",
                "OPENROUTER_API_KEY": "or-key",
            }
        )
        agents = _get_available_live_agents(3)

        assert len(agents) == 3
        assert agents[0] == "anthropic-api"
        assert agents[1].startswith("openrouter:")
        assert agents[2].startswith("openrouter:")

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_openrouter_fills_remaining_with_diverse_models(self, mock_key):
        mock_key.side_effect = _make_key_lookup(
            {
                "OPENAI_API_KEY": "oai-key",
                "OPENROUTER_API_KEY": "or-key",
            }
        )
        agents = _get_available_live_agents(4)

        assert len(agents) == 4
        assert agents[0] == "openai-api"
        or_agents = [a for a in agents if a.startswith("openrouter:")]
        assert len(or_agents) == 3
        or_models = [a.split(":", 1)[1] for a in or_agents]
        assert len(set(or_models)) == 3, "OpenRouter slots should use different models"

    @patch("aragora.server.handlers.playground._get_api_key")
    def test_single_primary_padded_without_openrouter(self, mock_key):
        """One primary key, no OpenRouter -> pads by repeating."""
        mock_key.side_effect = _make_key_lookup(
            {
                "ANTHROPIC_API_KEY": "ant-key",
            }
        )
        agents = _get_available_live_agents(3)

        assert len(agents) == 3
        assert all(a == "anthropic-api" for a in agents)


# ---------------------------------------------------------------------------
# _resolve_playground_agents
# ---------------------------------------------------------------------------


class TestResolvePlaygroundAgents:
    """Verify tag-to-string conversion for DebateFactory."""

    def test_openrouter_tags_converted(self):
        tags = [
            "openrouter:anthropic/claude-sonnet-4",
            "openrouter:openai/gpt-4o",
            "openrouter:google/gemini-2.0-flash-001",
        ]
        result = _resolve_playground_agents(tags)
        expected = (
            "openrouter/anthropic/claude-sonnet-4,"
            "openrouter/openai/gpt-4o,"
            "openrouter/google/gemini-2.0-flash-001"
        )
        assert result == expected

    def test_primary_tags_pass_through(self):
        tags = ["anthropic-api", "openai-api", "mistral-api"]
        result = _resolve_playground_agents(tags)
        assert result == "anthropic-api,openai-api,mistral-api"

    def test_mixed_tags(self):
        tags = ["anthropic-api", "openrouter:openai/gpt-4o", "openrouter:deepseek/deepseek-chat"]
        result = _resolve_playground_agents(tags)
        assert result == "anthropic-api,openrouter/openai/gpt-4o,openrouter/deepseek/deepseek-chat"

    def test_empty_list(self):
        assert _resolve_playground_agents([]) == ""


# ---------------------------------------------------------------------------
# OPENROUTER_PLAYGROUND_MODELS constant
# ---------------------------------------------------------------------------


class TestOpenRouterPlaygroundModels:
    """Verify the constant has expected structure."""

    def test_has_at_least_three_models(self):
        assert len(OPENROUTER_PLAYGROUND_MODELS) >= 3

    def test_each_entry_is_role_model_tuple(self):
        for role, model in OPENROUTER_PLAYGROUND_MODELS:
            assert isinstance(role, str)
            assert isinstance(model, str)
            assert "/" in model, f"Model {model} should contain provider/name format"

    def test_all_models_unique(self):
        models = [model for _role, model in OPENROUTER_PLAYGROUND_MODELS]
        assert len(models) == len(set(models)), "All models should be unique"
