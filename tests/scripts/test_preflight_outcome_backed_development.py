from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import scripts.preflight_outcome_backed_development as cli
from aragora.evaluation.outcome_backed_preflight import DevelopmentPreflightReport


HEAD = "a" * 40


def test_cli_help_runs_from_checkout() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/preflight_outcome_backed_development.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "without making model calls" in result.stdout


def _report(*, ready: bool) -> DevelopmentPreflightReport:
    from aragora.evaluation.outcome_backed_preflight import PreflightBlocker

    blockers = () if ready else (PreflightBlocker("blocked", "not ready"),)
    return DevelopmentPreflightReport(
        implementation_sha=HEAD,
        corpus_sha256="b" * 64,
        packet_set_sha256="c" * 64,
        roster_sha256="d" * 64,
        case_ids=tuple(f"case-{index:02d}" for index in range(16)),
        condition_ids=("claude-single", "openai-single", "gemini-single", "aragora-team"),
        prompt_set_sha256="e" * 64,
        transport_readiness=(),
        budget={"remaining_usd": "25"},
        blockers=blockers,
    )


def test_cli_writes_ready_artifact_atomically(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        cli, "preflight_development_run", lambda *_args, **_kwargs: _report(ready=True)
    )
    output = tmp_path / "proof" / "preflight.json"

    result = cli.main(["--implementation-sha", HEAD, "--output", str(output)])

    assert result == 0
    payload = json.loads(output.read_text())
    assert payload["ok"] is True
    assert payload["ready"] is True
    assert json.loads(capsys.readouterr().out) == payload
    assert not output.with_suffix(".json.tmp").exists()


def test_cli_returns_one_for_truthful_blocker(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "preflight_development_run", lambda *_args, **_kwargs: _report(ready=False)
    )

    result = cli.main(["--implementation-sha", HEAD])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["blockers"] == [{"code": "blocked", "message": "not ready"}]


def test_cli_rejects_invalid_sha(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "_current_head", lambda: "invalid")

    result = cli.main([])

    assert result == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False
