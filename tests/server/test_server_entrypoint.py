from __future__ import annotations

import logging
import os
import subprocess
import sys

import pytest

from aragora.config.secrets import SecretSourceError
from aragora.server.__main__ import (
    LOCAL_DEMO_HANDLER_TIERS,
    _configure_runtime_environment,
    _run_main,
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


def _custody_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if "secret custody is unusable" in line]


def test_unusable_custody_exits_with_one_line(monkeypatch, capsys):
    def failing_main():
        try:
            raise SecretSourceError("ARAGORA_SECRETS_DIR must be an absolute directory")
        except SecretSourceError as exc:
            raise RuntimeError("Invalid ARAGORA_API_TOKEN custody configuration.") from exc

    monkeypatch.setattr("aragora.server.__main__.main", failing_main)

    assert _run_main() == 1

    captured = capsys.readouterr()
    assert _custody_lines(captured.err) == [
        "aragora: secret custody is unusable: ARAGORA_SECRETS_DIR must be an absolute directory"
    ]
    assert "Traceback" not in captured.err


def test_clean_server_exit_returns_zero(monkeypatch):
    monkeypatch.setattr("aragora.server.__main__.main", lambda: None)

    assert _run_main() == 0


def test_unrelated_server_errors_still_propagate(monkeypatch):
    def failing_main():
        raise RuntimeError("unrelated failure")

    monkeypatch.setattr("aragora.server.__main__.main", failing_main)

    with pytest.raises(RuntimeError, match="unrelated failure"):
        _run_main()


def test_fresh_process_exits_with_one_line(tmp_path):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "PYTHONPATH": os.pathsep.join(entry for entry in sys.path if entry),
        "ARAGORA_DATA_DIR": str(tmp_path / "data"),
        "AWS_EC2_METADATA_DISABLED": "true",
        "ARAGORA_SECRETS_DIR": "relative/secrets",
        "ARAGORA_SECRETS_STRICT": "false",
    }
    # --help keeps the process from binding a port if custody were ever accepted.
    result = subprocess.run(
        [sys.executable, "-m", "aragora.server", "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert result.returncode == 1
    assert _custody_lines(result.stderr) == [
        "aragora: secret custody is unusable: ARAGORA_SECRETS_DIR must be an absolute directory"
    ]
    assert "Traceback" not in result.stderr
