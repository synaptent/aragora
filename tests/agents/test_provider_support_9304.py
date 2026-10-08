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
