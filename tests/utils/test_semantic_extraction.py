"""Tests for shared semantic extraction helpers."""

from __future__ import annotations

import importlib
import sys

import pytest

from aragora.agents.semantic_extraction import (
    ExtractionProvider,
    extract_json_object_llm_first,
)


def test_legacy_semantic_extraction_path_warns_and_aliases_module():
    """The old utils path remains a warning alias for monkeypatch compatibility."""
    canonical = importlib.import_module("aragora.agents.semantic_extraction")
    sys.modules.pop("aragora.utils.semantic_extraction", None)
    with pytest.warns(DeprecationWarning, match=r"aragora\.utils\.semantic_extraction"):
        legacy = importlib.import_module("aragora.utils.semantic_extraction")

    assert legacy is canonical


class _DummyAgent:
    def __init__(self, response: str | Exception) -> None:
        self._response = response

    async def generate(self, prompt: str) -> str:
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


class _WebSearchAwareDummyAgent:
    def __init__(self) -> None:
        self.enable_web_search = True
        self.web_search_enabled_during_generate: bool | None = None

    async def generate(self, prompt: str) -> str:
        self.web_search_enabled_during_generate = self.enable_web_search
        return '{"result":"ok"}'


@pytest.mark.asyncio
async def test_extract_json_object_llm_first_falls_back_to_second_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter")

    providers = (
        ExtractionProvider(agent_type="anthropic-api", env_vars=("ANTHROPIC_API_KEY",)),
        ExtractionProvider(agent_type="openrouter", env_vars=("OPENROUTER_API_KEY",)),
    )

    def fake_create_agent(model_type: str, **kwargs):
        if model_type == "anthropic-api":
            return _DummyAgent("not json")
        return _DummyAgent('```json\n{"result":"ok"}\n```')

    monkeypatch.setattr("aragora.agents.base.create_agent", fake_create_agent)

    result = await extract_json_object_llm_first(
        "Summarize this issue.",
        providers=providers,
        normalizer=lambda data: str(data.get("result", "")) or None,
    )

    assert result.value == "ok"
    assert result.source == "openrouter"
    assert result.provider is not None
    assert result.provider.agent_type == "openrouter"
    assert result.error is None


@pytest.mark.asyncio
async def test_extract_json_object_llm_first_returns_no_available_providers(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = await extract_json_object_llm_first(
        "Summarize this issue.",
        providers=(ExtractionProvider(agent_type="openai-api", env_vars=("OPENAI_API_KEY",)),),
        normalizer=lambda data: data,
    )

    assert result.value is None
    assert result.source == "none"
    assert result.error == "no_available_providers"


@pytest.mark.asyncio
async def test_extract_json_object_llm_first_reports_normalization_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    monkeypatch.setattr(
        "aragora.agents.base.create_agent",
        lambda model_type, **kwargs: _DummyAgent('{"action":"unsupported"}'),
    )

    result = await extract_json_object_llm_first(
        "Summarize this issue.",
        providers=(ExtractionProvider(agent_type="openai-api", env_vars=("OPENAI_API_KEY",)),),
        normalizer=lambda data: None,
    )

    assert result.value is None
    assert result.source == "openai-api"
    assert result.raw_response == '{"action":"unsupported"}'
    assert result.error == "openai-api:normalization_failed"


@pytest.mark.asyncio
async def test_extract_json_object_llm_first_disables_web_search_when_requested(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")

    agent = _WebSearchAwareDummyAgent()
    monkeypatch.setattr(
        "aragora.agents.base.create_agent",
        lambda model_type, **kwargs: agent,
    )

    result = await extract_json_object_llm_first(
        "Parse https://github.com/synaptent/aragora/issues/4883",
        providers=(
            ExtractionProvider(
                agent_type="anthropic-api",
                env_vars=("ANTHROPIC_API_KEY",),
                disable_web_search=True,
            ),
        ),
        normalizer=lambda data: str(data.get("result", "")) or None,
    )

    assert result.value == "ok"
    assert agent.web_search_enabled_during_generate is False
