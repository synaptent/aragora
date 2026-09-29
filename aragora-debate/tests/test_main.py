"""The version self-check must not replace the offline debate runner."""

from importlib import metadata
import subprocess
import sys

import pytest

from aragora_debate import __main__ as cli


def test_version_uses_installed_metadata_without_running_demo(monkeypatch, capsys):
    def version(distribution):
        assert distribution == "aragora-debate"
        return "1.2.3+test"

    monkeypatch.setattr(metadata, "version", version)
    monkeypatch.setattr(sys, "argv", ["aragora_debate", "--version"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "aragora-debate 1.2.3+test"


def test_uninstalled_source_tree_can_still_run_demo(monkeypatch):
    def missing(distribution):
        raise metadata.PackageNotFoundError(distribution)

    calls = []

    async def demo(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(metadata, "version", missing)
    monkeypatch.setattr(cli, "_run_demo", demo)
    monkeypatch.setattr(sys, "argv", ["aragora_debate", "--topic", "Offline source demo"])
    cli.main()
    assert calls[0][0][0] == "Offline source demo"


@pytest.mark.parametrize("flag", ["--version", "--help"])
def test_module_self_checks(flag):
    result = subprocess.run(
        [sys.executable, "-m", "aragora_debate", flag],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    if flag == "--version":
        assert metadata.version("aragora-debate") in result.stdout.split()
    else:
        assert "usage:" in result.stdout and "--version" in result.stdout
        assert "--topic" in result.stdout and "--trickster" in result.stdout


def test_offline_demo_still_runs():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "aragora_debate",
            "--topic",
            "Queues or streams?",
            "--rounds",
            "1",
            "--trickster",
            "--convergence",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "Queues or streams?" in result.stdout
    assert "Decision Receipt" in result.stdout
    assert "Debate complete" in result.stdout
