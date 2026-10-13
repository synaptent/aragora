"""Environment-variable fixtures (pytest plugin)."""

import pytest


@pytest.fixture(autouse=True)
def isolate_odr_signing_environment(monkeypatch):
    """ODR custody is opt-in per test, never inherited from the operator."""
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_FILE", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_SECRET", raising=False)
    monkeypatch.delenv("ARAGORA_ODR_SIGNING_KEY_STRICT_MODE", raising=False)
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")


@pytest.fixture
def clean_env(monkeypatch):
    """Clear API key environment variables for testing.

    Use this fixture when testing code that checks for API keys
    to ensure consistent behavior.
    """
    env_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "ARAGORA_API_TOKEN",
        "SUPABASE_URL",
        "SUPABASE_KEY",
    ]
    for var in env_vars:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


@pytest.fixture
def mock_api_keys(monkeypatch):
    """Set mock API keys for testing.

    Use this fixture when testing code that requires API keys
    but shouldn't make real API calls.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    return monkeypatch
