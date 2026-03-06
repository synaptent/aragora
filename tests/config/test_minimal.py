"""Tests for minimal-mode provider requirement detection."""

from __future__ import annotations

import os
from unittest.mock import patch

from aragora.config.minimal import check_minimal_requirements


def _clean_env() -> dict[str, str]:
    return {
        k: v
        for k, v in os.environ.items()
        if k
        not in {
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "MISTRAL_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "XAI_API_KEY",
            "GROK_API_KEY",
        }
    }


def test_openrouter_only_counts_as_ai_provider() -> None:
    env = {**_clean_env(), "OPENROUTER_API_KEY": "or-test-key-12345"}
    with patch.dict(os.environ, env, clear=True):
        requirements = check_minimal_requirements()

    assert requirements["openrouter_key"] is True
    assert requirements["has_ai_provider"] is True


def test_google_and_grok_aliases_count_as_ai_providers() -> None:
    env = {
        **_clean_env(),
        "GOOGLE_API_KEY": "google-test-key-12345",
        "GROK_API_KEY": "grok-test-key-12345",
    }
    with patch.dict(os.environ, env, clear=True):
        requirements = check_minimal_requirements()

    assert requirements["gemini_key"] is True
    assert requirements["xai_key"] is True
    assert requirements["has_ai_provider"] is True
