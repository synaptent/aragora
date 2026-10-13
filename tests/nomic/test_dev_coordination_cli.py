"""Characterizes the ``python -m aragora.nomic.dev_coordination`` CLI.

The argparse parser and the command dispatch live in
``aragora.nomic.dev_coordination.cli``; ``core.main`` builds the store and hands
off to the dispatch, so ``python -m aragora.nomic.dev_coordination``,
``python -m aragora.nomic.dev_coordination.core`` and ``core.main`` keep working.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aragora
from aragora.nomic import dev_coordination
from aragora.nomic.dev_coordination import cli, core

REPO_ROOT = Path(aragora.__file__).resolve().parents[1]


def _git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _run_module(module: str, repo: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", module, "--repo", str(repo), "--db", str(repo / "dc.db"), *argv],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        check=False,
    )


def _main(monkeypatch: pytest.MonkeyPatch, repo: Path, *argv: str) -> int:
    monkeypatch.setattr(
        sys, "argv", ["dev_coordination", "--repo", str(repo), "--db", str(repo / "dc.db"), *argv]
    )
    return core.main()


def test_parser_and_dispatch_live_in_the_cli_module() -> None:
    assert core._build_parser is cli._build_parser
    assert dev_coordination._build_parser is cli._build_parser
    assert core._run_command is cli._run_command
    assert dev_coordination.main is core.main
    assert core.main.__module__ == core.__name__


def test_package_module_entry_point_prints_status_json(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    result = _run_module("aragora.nomic.dev_coordination", repo, "status", "--json")
    assert result.returncode == 0, result.stderr
    counts = json.loads(result.stdout)["counts"]
    assert counts["active_leases"] == 0
    assert counts["open_developer_tasks"] == 0


def test_core_module_entry_point_prints_status_text(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path)
    result = _run_module("aragora.nomic.dev_coordination.core", repo, "status")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == (
        "active_leases=0 pending_integrations=0 open_salvage_candidates=0 open_developer_tasks=0"
    )


def test_claim_heartbeat_conflict_and_reap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _git_repo(tmp_path)
    claim = (
        "claim",
        "--task-id",
        "t-1",
        "--title",
        "Lane one",
        "--agent",
        "codex",
        "--session-id",
        "s-1",
        "--branch",
        "codex/one",
        "--worktree",
        str(tmp_path / "wt-1"),
        "--claimed-path",
        "aragora/x.py",
    )
    assert _main(monkeypatch, repo, *claim, "--json") == 0
    lease = json.loads(capsys.readouterr().out)["lease"]
    assert lease["task_id"] == "t-1"

    assert _main(monkeypatch, repo, "heartbeat", "--lease-id", lease["lease_id"]) == 0
    assert capsys.readouterr().out.strip() == lease["lease_id"]

    conflicting = list(claim)
    conflicting[conflicting.index("s-1")] = "s-2"
    conflicting[conflicting.index("codex/one")] = "codex/two"
    assert _main(monkeypatch, repo, *conflicting, "--json") == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["conflicts"]

    assert _main(monkeypatch, repo, "tasks", "--json") == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    assert _main(monkeypatch, repo, "reap", "--json") == 0
    reaped = json.loads(capsys.readouterr().out)
    assert reaped["ok"] is True
    assert reaped["count"] == reaped["expired"] + reaped["stale"]


def test_missing_subcommand_exits_with_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _git_repo(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        _main(monkeypatch, repo)
    assert excinfo.value.code == 2
