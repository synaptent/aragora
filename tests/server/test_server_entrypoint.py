from __future__ import annotations

import logging
import os

import pytest

from aragora.server.__main__ import (
    LOCAL_DEMO_HANDLER_TIERS,
    _configure_runtime_environment,
    _detect_api_keys,
    _hydrate_runtime_secrets,
)


_RUNTIME_ENV_KEYS = (
    "ARAGORA_OFFLINE",
    "ARAGORA_DEMO_MODE",
    "ARAGORA_DB_BACKEND",
    "ARAGORA_ENV",
    "ARAGORA_HANDLER_TIERS",
)


@pytest.fixture(autouse=True)
def restore_runtime_environment():
    """Keep runtime defaults set by one entrypoint test out of later tests."""
    original = {key: os.environ[key] for key in _RUNTIME_ENV_KEYS if key in os.environ}
    yield
    for key in _RUNTIME_ENV_KEYS:
        os.environ.pop(key, None)
    os.environ.update(original)


def test_offline_mode_keeps_optional_handlers(monkeypatch):
    monkeypatch.delenv("ARAGORA_OFFLINE", raising=False)
    monkeypatch.delenv("ARAGORA_DEMO_MODE", raising=False)
    monkeypatch.delenv("ARAGORA_DB_BACKEND", raising=False)
    monkeypatch.delenv("ARAGORA_ENV", raising=False)
    monkeypatch.delenv("ARAGORA_HANDLER_TIERS", raising=False)

    _configure_runtime_environment(True, [], logging.getLogger("test"))

    assert LOCAL_DEMO_HANDLER_TIERS == "core,extended,optional"
    assert LOCAL_DEMO_HANDLER_TIERS == os.environ["ARAGORA_HANDLER_TIERS"]
    assert os.environ["ARAGORA_OFFLINE"] == "true"
    assert os.environ["ARAGORA_DEMO_MODE"] == "true"
    assert os.environ["ARAGORA_DB_BACKEND"] == "sqlite"
    assert os.environ["ARAGORA_ENV"] == "development"


def test_demo_mode_without_api_keys_keeps_optional_handlers(monkeypatch):
    monkeypatch.delenv("ARAGORA_DEMO_MODE", raising=False)
    monkeypatch.delenv("ARAGORA_DB_BACKEND", raising=False)
    monkeypatch.delenv("ARAGORA_HANDLER_TIERS", raising=False)

    _configure_runtime_environment(False, [], logging.getLogger("test"))

    assert os.environ["ARAGORA_DEMO_MODE"] == "true"
    assert os.environ["ARAGORA_DB_BACKEND"] == "sqlite"
    assert os.environ["ARAGORA_HANDLER_TIERS"] == LOCAL_DEMO_HANDLER_TIERS


def test_explicit_handler_tiers_are_not_overwritten(monkeypatch):
    monkeypatch.setenv("ARAGORA_HANDLER_TIERS", "core,extended")

    _configure_runtime_environment(True, [], logging.getLogger("test"))

    assert os.environ["ARAGORA_HANDLER_TIERS"] == "core,extended"


def test_hydrate_runtime_secrets_injects_mounted_database_and_redis(tmp_path, monkeypatch):
    from aragora.config.secrets import SecretManager, SecretsConfig

    for name, value in {
        "DATABASE_URL": "postgresql://mounted",
        "REDIS_URL": "redis://mounted",
    }.items():
        path = tmp_path / name
        path.write_text(value, encoding="utf-8")
        path.chmod(0o600)
    manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
    monkeypatch.setattr("aragora.config.secrets._manager", manager)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)

    _hydrate_runtime_secrets()

    assert os.environ["DATABASE_URL"] == "postgresql://mounted"
    assert os.environ["REDIS_URL"] == "redis://mounted"


def test_detect_api_keys_accepts_mounted_custody(tmp_path, monkeypatch):
    from aragora.config.secrets import SecretManager, SecretsConfig

    secret_path = tmp_path / "OPENAI_API_KEY"
    secret_path.write_text("mounted-openai-key", encoding="utf-8")
    secret_path.chmod(0o600)
    manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
    monkeypatch.setattr("aragora.config.secrets._manager", manager)

    assert _detect_api_keys() == ["OPENAI_API_KEY"]


def test_api_key_mode_leaves_demo_defaults_unset(monkeypatch):
    monkeypatch.delenv("ARAGORA_DEMO_MODE", raising=False)
    monkeypatch.delenv("ARAGORA_HANDLER_TIERS", raising=False)
    monkeypatch.delenv("ARAGORA_DB_BACKEND", raising=False)

    _configure_runtime_environment(False, ["OPENAI_API_KEY"], logging.getLogger("test"))

    assert "ARAGORA_DEMO_MODE" not in os.environ
    assert "ARAGORA_HANDLER_TIERS" not in os.environ
    assert "ARAGORA_DB_BACKEND" not in os.environ
