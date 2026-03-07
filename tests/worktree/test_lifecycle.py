"""Tests for shared worktree lifecycle service."""

from __future__ import annotations

import argparse
import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aragora.worktree.lifecycle import WorktreeLifecycleService


def test_discover_managed_dirs_defaults(tmp_path: Path) -> None:
    base = tmp_path / ".worktrees"
    (base / "codex-auto").mkdir(parents=True)
    (base / "codex-auto-ci").mkdir(parents=True)
    (base / "codex-auto-debate").mkdir(parents=True)

    service = WorktreeLifecycleService(repo_root=tmp_path)
    found = service.discover_managed_dirs()

    assert ".worktrees/codex-auto" in found
    assert ".worktrees/codex-auto-ci" in found
    assert ".worktrees/codex-auto-debate" in found


@pytest.mark.parametrize(
    "lock_name",
    [".claude-session-active", ".codex_session_active", ".nomic-session-active"],
)
def test_maintain_managed_dirs_skips_active_and_missing(tmp_path: Path, lock_name: str) -> None:
    active_dir = tmp_path / ".worktrees" / "codex-auto-active"
    ok_dir = tmp_path / ".worktrees" / "codex-auto-ok"
    active_dir.mkdir(parents=True)
    ok_dir.mkdir(parents=True)
    (active_dir / lock_name).write_text("1\n", encoding="utf-8")

    service = WorktreeLifecycleService(repo_root=tmp_path)
    service.run_autopilot_action = MagicMock(
        return_value=argparse.Namespace(returncode=0, stdout='{"ok": true}', stderr="")
    )

    summary = service.maintain_managed_dirs(
        managed_dirs=[
            ".worktrees/codex-auto-active",
            ".worktrees/codex-auto-ok",
            ".worktrees/codex-auto-missing",
        ],
        reconcile_only=True,
    )

    assert summary["ok"] is True
    assert summary["directories_total"] == 3
    assert summary["processed"] == 1
    assert summary["skipped_active"] == 1
    assert summary["skipped_missing"] == 1
    assert summary["failures"] == 0
    assert any(r.get("action") == "reconcile" for r in summary["results"] if r["status"] == "ok")


def test_maintain_managed_dirs_tracks_failures(tmp_path: Path) -> None:
    managed = tmp_path / ".worktrees" / "codex-auto"
    managed.mkdir(parents=True)

    service = WorktreeLifecycleService(repo_root=tmp_path)
    service.run_autopilot_action = MagicMock(
        return_value=argparse.Namespace(returncode=2, stdout='{"ok": false}', stderr="conflict")
    )

    summary = service.maintain_managed_dirs(
        managed_dirs=[".worktrees/codex-auto"],
        reconcile_only=False,
    )

    assert summary["ok"] is False
    assert summary["processed"] == 1
    assert summary["failures"] == 1
    row = summary["results"][0]
    assert row["status"] == "failed"
    assert row["action"] == "maintain"


def test_create_worktree_uses_git_runner() -> None:
    service = WorktreeLifecycleService(repo_root=Path("/tmp/repo"))
    git_runner = MagicMock(return_value=argparse.Namespace(returncode=0, stdout="ok", stderr=""))

    result = service.create_worktree(
        worktree_path=Path("/tmp/repo/.worktrees/dev-test"),
        ref="main",
        branch="dev/test",
        git_runner=git_runner,
    )

    assert result.success is True
    git_runner.assert_called_once()
    call = git_runner.call_args
    assert call.args[:4] == ("worktree", "add", "-b", "dev/test")
    assert call.kwargs["check"] is False


def test_remove_worktree_force_uses_git_runner() -> None:
    service = WorktreeLifecycleService(repo_root=Path("/tmp/repo"))
    git_runner = MagicMock(return_value=argparse.Namespace(returncode=0, stdout="", stderr=""))

    result = service.remove_worktree(
        worktree_path=Path("/tmp/repo/.worktrees/dev-test"),
        force=True,
        git_runner=git_runner,
    )

    assert result.success is True
    call = git_runner.call_args
    assert "--force" in call.args


def test_ensure_managed_worktree_success(tmp_path: Path) -> None:
    managed_path = tmp_path / ".worktrees" / "codex-auto" / "session-1"
    managed_path.mkdir(parents=True)

    payload = {
        "ok": True,
        "created": True,
        "session": {
            "session_id": "session-1",
            "agent": "codex",
            "branch": "codex/session-1",
            "path": str(managed_path),
            "reconcile_status": "up_to_date",
        },
    }

    service = WorktreeLifecycleService(repo_root=tmp_path)
    service.run_autopilot_action = MagicMock(
        return_value=argparse.Namespace(returncode=0, stdout=json.dumps(payload), stderr="")
    )

    session = service.ensure_managed_worktree(
        managed_dir=".worktrees/codex-auto",
        base_branch="main",
        agent="codex",
        session_id="session-1",
        reconcile=True,
        strategy="merge",
    )

    assert session.session_id == "session-1"
    assert session.branch == "codex/session-1"
    assert session.path == managed_path.resolve()
    assert session.created is True
    assert session.reconcile_status == "up_to_date"
    call = service.run_autopilot_action.call_args
    assert call.args[0].action == "ensure"
    assert call.args[0].managed_dir == ".worktrees/codex-auto"
    assert call.args[0].json_output is True


def test_ensure_managed_worktree_failure_raises(tmp_path: Path) -> None:
    service = WorktreeLifecycleService(repo_root=tmp_path)
    service.run_autopilot_action = MagicMock(
        return_value=argparse.Namespace(returncode=2, stdout='{"ok": false}', stderr="boom")
    )

    with pytest.raises(RuntimeError, match="autopilot ensure failed"):
        service.ensure_managed_worktree(managed_dir=".worktrees/codex-auto")


def test_ensure_managed_worktree_missing_session_payload_raises(tmp_path: Path) -> None:
    service = WorktreeLifecycleService(repo_root=tmp_path)
    service.run_autopilot_action = MagicMock(
        return_value=argparse.Namespace(returncode=0, stdout='{"ok": true}', stderr="")
    )

    with pytest.raises(RuntimeError, match="missing session payload"):
        service.ensure_managed_worktree(managed_dir=".worktrees/codex-auto")


def test_worktree_lifecycle_defaults_to_ff_only_strategy(tmp_path: Path) -> None:
    service = WorktreeLifecycleService(repo_root=tmp_path)
    ensure_sig = inspect.signature(service.ensure_managed_worktree)
    maintain_sig = inspect.signature(service.maintain_managed_dirs)
    assert ensure_sig.parameters["strategy"].default == "ff-only"
    assert maintain_sig.parameters["strategy"].default == "ff-only"
