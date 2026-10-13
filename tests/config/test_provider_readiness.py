from __future__ import annotations

from aragora.config import provider_readiness as mod


def test_discovery_ignores_empty_env(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    assert not report.any_configured
    anthropic = next(status for status in report.providers if status.provider == "anthropic")
    assert anthropic.configured is False
    assert anthropic.status == "missing_config"


def test_discovery_reports_configured_provider(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    assert report.any_configured
    assert report.configured_providers == ("openai",)
    assert mod.agent_type_has_configured_provider("openai-api", report)
    assert mod.agent_type_has_configured_provider("demo", report)
    assert not mod.agent_type_has_configured_provider("anthropic-api", report)


def test_discovery_uses_secret_hydrator(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)

    def fake_hydrate(names, overwrite=False):
        assert overwrite is False
        assert "ANTHROPIC_API_KEY" in names
        monkeypatch.setenv("ANTHROPIC_API_KEY", "hydrated-key")
        return {"ANTHROPIC_API_KEY": "hydrated-key"}

    monkeypatch.setattr("aragora.config.secrets.hydrate_env_from_secrets", fake_hydrate)

    report = mod.discover_provider_credentials(hydrate=True, load_dotenv=False)

    assert report.configured_providers == ("anthropic",)
    assert report.hydrated_env_vars == ("ANTHROPIC_API_KEY",)


def test_discovery_hydrates_missing_secrets_when_unrelated_provider_env_exists(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("GROK_API_KEY", "configured-grok-key")

    def fake_hydrate(names, overwrite=False):
        assert overwrite is False
        assert "ANTHROPIC_API_KEY" in names
        assert "GROK_API_KEY" not in names
        monkeypatch.setenv("ANTHROPIC_API_KEY", "hydrated-key")
        return {"ANTHROPIC_API_KEY": "hydrated-key"}

    monkeypatch.setattr("aragora.config.secrets.hydrate_env_from_secrets", fake_hydrate)

    report = mod.discover_provider_credentials(hydrate=True, load_dotenv=False)

    assert "anthropic" in report.configured_providers
    assert "xai" in report.configured_providers
    assert report.hydrated_env_vars == ("ANTHROPIC_API_KEY",)


def test_cli_agent_is_usable_when_cli_command_is_available(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setattr(mod, "_cli_command_available", lambda command: command == "codex")

    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    assert mod.agent_type_has_configured_provider("codex", report)
    assert not mod.agent_type_has_configured_provider("claude", report)
    assert not mod.agent_type_has_configured_provider("anthropic-api", report)


def test_cli_agent_is_usable_with_fallback_provider_credentials(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(mod, "_cli_command_available", lambda _command: False)

    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    assert mod.agent_type_has_configured_provider("codex", report)
    assert mod.agent_type_has_configured_provider("claude", report)
    assert not mod.agent_type_has_configured_provider("gemini-cli", report)


def test_kimi_runtime_requires_openrouter_but_legacy_accepts_moonshot(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv("KIMI_API_KEY", "test-moonshot-key")

    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    assert mod.agent_type_has_configured_provider("kimi-legacy", report)
    assert not mod.agent_type_has_configured_provider("kimi", report)
    assert not mod.agent_type_has_configured_provider("kimi-thinking", report)

    monkeypatch.delenv("KIMI_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    assert mod.agent_type_has_configured_provider("kimi", report)
    assert mod.agent_type_has_configured_provider("kimi-thinking", report)
    assert not mod.agent_type_has_configured_provider("kimi-legacy", report)


def test_bootstrap_error_is_actionable(monkeypatch):
    for spec in mod.PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.delenv(env_var, raising=False)
    report = mod.discover_provider_credentials(hydrate=False, load_dotenv=False)

    message = mod.format_provider_bootstrap_error(report)

    assert "No usable AI provider credential" in message
    assert "ANTHROPIC_API_KEY" in message
    assert "aragora validate-env --smoke --agents <agent> --verbose" in message
