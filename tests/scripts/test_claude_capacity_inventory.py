import json
import stat
from pathlib import Path

import pytest

from scripts import claude_capacity_inventory as cli

_OBSERVED = {"observations": [{"state": "observed"}], "admission_authorized": False}


def test_cli_writes_new_private_report_and_refuses_overwrite(monkeypatch, tmp_path, capsys):
    report = {"observations": [{"state": "observed"}], "admission_authorized": False}
    monkeypatch.setattr(cli, "discover", lambda *args: [])
    monkeypatch.setattr(cli, "collect", lambda *args, **kwargs: report)
    path = tmp_path / "capacity.json"
    assert cli.main(["--output", str(path)]) == 0
    assert json.loads(path.read_text()) == report
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert cli.main(["--output", str(path)]) == 2
    assert json.loads(path.read_text()) == report
    assert str(path) not in capsys.readouterr().err


def test_cli_never_treats_exit_zero_as_ready(monkeypatch, capsys):
    monkeypatch.setattr(cli, "discover", lambda *args: [])
    monkeypatch.setattr(
        cli,
        "collect",
        lambda *args, **kwargs: {
            "observations": [{"state": "rate_limited"}],
            "admission_authorized": False,
        },
    )
    assert cli.main([]) == 0
    assert json.loads(capsys.readouterr().out)["admission_authorized"] is False


def test_invalid_time_budget_returns_sanitized_error(capsys, tmp_path):
    assert (
        cli.main(
            ["--profile-root", str(tmp_path), "--proxy-auth-dir", str(tmp_path), "--timeout", "nan"]
        )
        == 2
    )
    assert "Traceback" not in capsys.readouterr().err


def _roots_seen_by_discovery(monkeypatch, tmp_path, argv):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    seen = {}

    def fake_discover(profile_root, proxy_root):
        seen.update(profile_root=profile_root, proxy_root=proxy_root)
        return []

    monkeypatch.setattr(cli, "discover", fake_discover)
    monkeypatch.setattr(cli, "collect", lambda *args, **kwargs: _OBSERVED)
    assert cli.main(argv) == 0
    return seen


def test_profile_root_defaults_under_home_when_env_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_PROFILE_ROOT", raising=False)
    assert _roots_seen_by_discovery(monkeypatch, tmp_path, []) == {
        "profile_root": tmp_path / "home" / ".aragora-claude",
        "proxy_root": tmp_path / "home" / ".cli-proxy-api",
    }


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_profile_root_env_falls_back_to_default(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CLAUDE_PROFILE_ROOT", value)
    seen = _roots_seen_by_discovery(monkeypatch, tmp_path, [])
    assert seen["profile_root"] == tmp_path / "home" / ".aragora-claude"


def test_profile_root_env_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROFILE_ROOT", str(tmp_path / "env-root"))
    assert _roots_seen_by_discovery(monkeypatch, tmp_path, []) == {
        "profile_root": tmp_path / "env-root",
        "proxy_root": tmp_path / "home" / ".cli-proxy-api",
    }


@pytest.mark.parametrize("value", ["relative/profiles", "~/profiles"])
def test_profile_root_env_is_used_literally_like_sibling_scripts(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CLAUDE_PROFILE_ROOT", value)
    seen = _roots_seen_by_discovery(monkeypatch, tmp_path, [])
    assert seen["profile_root"] == Path(value)


def test_explicit_profile_root_wins_over_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PROFILE_ROOT", str(tmp_path / "env-root"))
    argv = ["--profile-root", str(tmp_path / "flag-root")]
    seen = _roots_seen_by_discovery(monkeypatch, tmp_path, argv)
    assert seen["profile_root"] == tmp_path / "flag-root"
