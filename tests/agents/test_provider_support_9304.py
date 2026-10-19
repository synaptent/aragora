"""Secured-provider support + failure-text classification (issue #9304)."""

from __future__ import annotations

import pytest


class TestBaseUrlOverride:
    def test_anthropic_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        from aragora.agents.api_agents.anthropic import _resolve_base_url

        assert (
            _resolve_base_url("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
            == "https://api.anthropic.com/v1"
        )

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("http://127.0.0.1:8317", "http://127.0.0.1:8317/v1"),
            ("http://127.0.0.1:8317/", "http://127.0.0.1:8317/v1"),
            ("https://gw.example/v1", "https://gw.example/v1"),
        ],
    )
    def test_anthropic_override_normalizes(
        self, monkeypatch: pytest.MonkeyPatch, value: str, expected: str
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", value)
        from aragora.agents.api_agents.anthropic import _resolve_base_url

        assert _resolve_base_url("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1") == expected

    def test_openai_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", "https://litellm.internal")
        from aragora.agents.api_agents.openai import _resolve_openai_base_url

        assert _resolve_openai_base_url() == "https://litellm.internal/v1"

    def test_grok_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XAI_BASE_URL", "https://gateway.example/xai")
        from aragora.agents.api_agents.grok import _resolve_base_url

        assert _resolve_base_url("XAI_BASE_URL", "https://api.x.ai/v1") == (
            "https://gateway.example/xai/v1"
        )

    def test_mistral_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_BASE_URL", "https://gateway.example/mistral")
        from aragora.agents.api_agents.mistral import _resolve_base_url

        assert _resolve_base_url("MISTRAL_BASE_URL", "https://api.mistral.ai/v1") == (
            "https://gateway.example/mistral/v1"
        )


class TestEndpointGatedRetiredModelUpgrade:
    """upgrade_retired_model_id() (common.py) must only rewrite an explicit
    retired/dead model id when the agent targets its provider's OFFICIAL
    endpoint. A custom base URL (BYOK gateway/proxy, issue #9304) may serve
    that id under its own meaning, so the constructor-time rewrite must not
    fire — see the 2026-09-05 merge-gate finding on #9989."""

    def test_anthropic_custom_base_url_keeps_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example/anthropic")
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent

        agent = AnthropicAPIAgent(model="claude-3-opus", api_key="test-key")
        assert agent.model == "claude-3-opus"

    def test_anthropic_default_endpoint_upgrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        from aragora.agents.api_agents.anthropic import AnthropicAPIAgent
        from aragora.config.model_pins import FABLE_51_DIRECT

        agent = AnthropicAPIAgent(model="claude-3-opus", api_key="test-key")
        assert agent.model == FABLE_51_DIRECT

    def test_openai_custom_base_url_keeps_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/openai")
        from aragora.agents.api_agents.openai import OpenAIAPIAgent

        agent = OpenAIAPIAgent(model="gpt-5.5", api_key="test-key")
        assert agent.model == "gpt-5.5"

    def test_openai_default_endpoint_upgrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
        from aragora.agents.api_agents.openai import OpenAIAPIAgent
        from aragora.config.model_pins import GPT6_ASTRA_DIRECT

        agent = OpenAIAPIAgent(model="gpt-5.5", api_key="test-key")
        assert agent.model == GPT6_ASTRA_DIRECT

    def test_grok_custom_base_url_keeps_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XAI_BASE_URL", "https://gateway.example/xai")
        from aragora.agents.api_agents.grok import GrokAgent

        agent = GrokAgent(model="grok-2", api_key="test-key")
        assert agent.model == "grok-2"

    def test_grok_default_endpoint_upgrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XAI_BASE_URL", raising=False)
        from aragora.agents.api_agents.grok import GrokAgent
        from aragora.config.model_pins import GROK_46_DIRECT

        agent = GrokAgent(model="grok-2", api_key="test-key")
        assert agent.model == GROK_46_DIRECT

    def test_mistral_custom_base_url_keeps_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MISTRAL_BASE_URL", "https://gateway.example/mistral")
        from aragora.agents.api_agents.mistral import MistralAPIAgent

        agent = MistralAPIAgent(model="mistral-large-2411", api_key="test-key")
        assert agent.model == "mistral-large-2411"

    def test_mistral_default_endpoint_upgrades(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISTRAL_BASE_URL", raising=False)
        from aragora.agents.api_agents.mistral import MistralAPIAgent
        from aragora.config.model_pins import MISTRAL_LARGE_DIRECT

        agent = MistralAPIAgent(model="mistral-large-2411", api_key="test-key")
        assert agent.model == MISTRAL_LARGE_DIRECT


class TestExit0ProviderErrors:
    def test_strong_markers_match_live_wall_texts(self) -> None:
        from aragora.agents.cli_agents import _EXIT0_STRONG_ERROR_MARKERS

        live = [
            "Free tier users do not have access to this model",
            "You're out of usage credits. Run /usage-credits",
        ]
        for text in live:
            assert any(m in text.lower() for m in _EXIT0_STRONG_ERROR_MARKERS), text

    def test_generic_phrases_only_classify_one_liners(self) -> None:
        from aragora.agents.cli_agents import (
            _EXIT0_WEAK_ERROR_MARKERS,
            _EXIT0_WEAK_MAX_CHARS,
        )

        answer = (
            "Recommendation: return 401 when the session is not logged in, and "
            "surface 'quota exceeded' to callers with a retry-after header so "
            "clients can back off correctly instead of hammering the API."
        )
        assert len(answer) >= _EXIT0_WEAK_MAX_CHARS  # substantive answers exceed the bound
        assert any(m in answer.lower() for m in _EXIT0_WEAK_ERROR_MARKERS)
        # the length bound is what protects it — pinned here
