from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import scripts.auto_revert_main_required_failures as auto_revert
from scripts.auto_revert_main_required_failures import (
    ensure_git_identity,
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


def _completed(cmd: list[str], returncode: int, stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def test_ensure_git_identity_sets_bot_identity_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        calls.append(cmd)
        if len(cmd) == 3:  # read: git config <key> — unset on CI runners
            return _completed(cmd, 1)
        return _completed(cmd, 0)

    monkeypatch.setattr(auto_revert, "_run", fake_run)

    ok, msg = ensure_git_identity(tmp_path)

    assert ok is True
    assert msg == "ok"
    assert ["git", "config", "user.name", auto_revert.GIT_BOT_NAME] in calls
    assert ["git", "config", "user.email", auto_revert.GIT_BOT_EMAIL] in calls


def test_ensure_git_identity_preserves_existing_identity(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        calls.append(cmd)
        return _completed(cmd, 0, stdout="Existing User\n")

    monkeypatch.setattr(auto_revert, "_run", fake_run)

    ok, _ = ensure_git_identity(tmp_path)

    assert ok is True
    assert all(len(cmd) == 3 for cmd in calls)  # reads only, no writes


def test_ensure_git_identity_reports_failure_to_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return _completed(cmd, 1)

    monkeypatch.setattr(auto_revert, "_run", fake_run)

    ok, msg = ensure_git_identity(tmp_path)

    assert ok is False
    assert "user.name" in msg
