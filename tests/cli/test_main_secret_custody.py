"""The aragora CLI exits with one line when configured secret custody is unusable."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from unittest.mock import Mock

import pytest

from aragora.cli.main import main
from aragora.config.secrets import SecretSourceError, reset_secret_manager

RELATIVE_DIR_LINE = (
    "aragora: secret custody is unusable: ARAGORA_SECRETS_DIR must be an absolute directory"
)


@pytest.fixture(autouse=True)
def fresh_secret_manager():
    reset_secret_manager()
    yield
    reset_secret_manager()


def _route_to(monkeypatch, command) -> None:
    fake_args = argparse.Namespace(
        command="secrets", secrets_command="health", verbose=False, func=command
    )
    fake_parser = Mock()
    fake_parser.parse_args.return_value = fake_args
    monkeypatch.setattr("aragora.cli.main._try_review_queue_fast_path", lambda _argv: None)
    monkeypatch.setattr(
        "aragora.server.webhook_store_registration.register_webhook_store", lambda: None
    )
    monkeypatch.setattr("aragora.modes.register_all_builtins", lambda: None)
    monkeypatch.setattr("aragora.cli.parser.build_parser", lambda: fake_parser)


def _custody_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if "secret custody is unusable" in line]


def test_unusable_mounted_directory_exits_with_one_line(monkeypatch, capsys):
    monkeypatch.setenv("ARAGORA_SECRETS_DIR", "relative/secrets")
    monkeypatch.setenv("ARAGORA_SECRETS_STRICT", "false")
    _route_to(monkeypatch, lambda _args: pytest.fail("the command must not run"))

    assert main() == 1

    captured = capsys.readouterr()
    assert _custody_lines(captured.err) == [RELATIVE_DIR_LINE]
    assert "Traceback" not in captured.err


def test_explicitly_chained_custody_error_exits_with_one_line(monkeypatch, capsys):
    monkeypatch.setattr("aragora.cli.main._hydrate_startup_secrets", lambda: None)

    def command(_args):
        try:
            raise SecretSourceError(
                "Mounted secret 'ARAGORA_API_TOKEN' must use owner-readable, owner-only permissions"
            )
        except SecretSourceError as exc:
            raise RuntimeError("Invalid ARAGORA_API_TOKEN custody configuration.") from exc

    _route_to(monkeypatch, command)

    assert main() == 1

    assert _custody_lines(capsys.readouterr().err) == [
        "aragora: secret custody is unusable: Mounted secret 'ARAGORA_API_TOKEN' must use "
        "owner-readable, owner-only permissions"
    ]


def test_unrelated_errors_still_propagate(monkeypatch):
    monkeypatch.setattr("aragora.cli.main._hydrate_startup_secrets", lambda: None)

    def command(_args):
        raise RuntimeError("unrelated failure")

    _route_to(monkeypatch, command)

    with pytest.raises(RuntimeError, match="unrelated failure"):
        main()


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
    result = subprocess.run(
        [sys.executable, "-m", "aragora.cli.main", "secrets", "health", "--json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )

    assert result.returncode == 1
    assert _custody_lines(result.stderr) == [RELATIVE_DIR_LINE]
    assert "Traceback" not in result.stderr
