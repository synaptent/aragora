import json
import stat

from scripts import claude_capacity_inventory as cli


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
