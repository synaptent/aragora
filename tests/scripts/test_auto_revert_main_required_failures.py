from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts.auto_revert_main_required_failures import (
    AUTO_REVERT_MARKER,
    _recent_auto_revert_exists,
    evaluate_required_contexts,
    select_latest_check_runs,
    should_skip_commit_message,
)


def test_select_latest_check_runs_picks_highest_run_id_per_context() -> None:
    runs = [
        {"id": 11, "name": "lint", "status": "completed", "conclusion": "failure"},
        {"id": 13, "name": "lint", "status": "completed", "conclusion": "success"},
        {"id": 12, "name": "typecheck", "status": "in_progress", "conclusion": None},
    ]

    latest = select_latest_check_runs(runs)

    assert latest["lint"]["id"] == 13
    assert latest["lint"]["conclusion"] == "success"
    assert latest["typecheck"]["id"] == 12


def test_evaluate_required_contexts_classifies_pass_pending_failed_missing() -> None:
    required = ["lint", "typecheck", "sdk-parity", "Generate & Validate"]
    runs = [
        {"id": 20, "name": "lint", "status": "completed", "conclusion": "success"},
        {
            "id": 21,
            "name": "typecheck",
            "status": "in_progress",
            "conclusion": None,
        },
        {
            "id": 22,
            "name": "sdk-parity",
            "status": "completed",
            "conclusion": "failure",
        },
    ]

    result = evaluate_required_contexts(required, runs)

    assert result["passed"] == ["lint"]
    assert result["pending"] == ["typecheck"]
    assert result["failed"] == ["sdk-parity:failure"]
    assert result["missing"] == ["Generate & Validate"]


def test_should_skip_commit_message_for_reverts_and_marked_commits() -> None:
    assert should_skip_commit_message('Revert "feat: add thing"') is True
    assert should_skip_commit_message("fix: x\n\n[auto-revert-required-checks]") is True
    assert should_skip_commit_message("feat: normal commit") is False


def test_recent_auto_revert_exists_greps_marker_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> CompletedProcess:
        calls.append(cmd)
        return CompletedProcess(cmd, 0, stdout="abc123 revert marker", stderr="")

    monkeypatch.setattr("scripts.auto_revert_main_required_failures._run", fake_run)

    assert _recent_auto_revert_exists(Path(".")) is True
    assert calls[0][:4] == ["git", "log", "--since=10 minutes ago", "-F"]
    assert calls[0][4:6] == ["--grep", AUTO_REVERT_MARKER]
