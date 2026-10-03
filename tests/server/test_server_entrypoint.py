from __future__ import annotations

import logging
import os

import pytest

from aragora.server.__main__ import (
    LOCAL_DEMO_HANDLER_TIERS,
    _configure_runtime_environment,
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


def test_api_key_mode_leaves_demo_defaults_unset(monkeypatch):
    monkeypatch.delenv("ARAGORA_DEMO_MODE", raising=False)
    monkeypatch.delenv("ARAGORA_HANDLER_TIERS", raising=False)
    monkeypatch.delenv("ARAGORA_DB_BACKEND", raising=False)

    _configure_runtime_environment(False, ["OPENAI_API_KEY"], logging.getLogger("test"))

    assert "ARAGORA_DEMO_MODE" not in os.environ
    assert "ARAGORA_HANDLER_TIERS" not in os.environ
    assert "ARAGORA_DB_BACKEND" not in os.environ
