"""Unit tests for scripts/safe_worktree_cleanup.py."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


@pytest.fixture(autouse=True)
def _setup_path():
    sys.path.insert(0, str(SCRIPTS_DIR))
    yield
    sys.path.remove(str(SCRIPTS_DIR))


def test_inspect_reports_open_pr_blocker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.autopilot.WorktreeEntry(path=worktree, branch="codex/test")],
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (0, False))
    monkeypatch.setattr(
        mod,
        "_lookup_open_prs",
        lambda _repo, _branch: (
            [{"number": 1361, "title": "Open PR", "url": "https://example.com/pr/1361"}],
            False,
        ),
    )

    inspection = mod.inspect_worktree(repo_root, worktree)

    assert inspection.tracked_worktree is True
    assert inspection.branch == "codex/test"
    assert inspection.dirty is False
    assert inspection.unique_commits_ahead == 0
    assert inspection.blockers == ["open_pr"]


def test_remove_refuses_blocked_worktree_without_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[{"number": 1361, "title": "Open PR", "url": "https://example.com/pr/1361"}],
        pr_lookup_failed=False,
        blockers=["open_pr"],
    )
    monkeypatch.setattr(
        mod,
        "inspect_worktree",
        lambda _repo, _path, branch_override=None: inspection,
    )
    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)

    args = argparse.Namespace(
        repo=".",
        path=str(worktree),
        branch=None,
        delete_branch=False,
        purge_path=False,
        force=False,
        json=True,
    )

    rc = mod.cmd_remove(args)
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["status"] == "blocked"
    assert payload["blockers"] == ["open_pr"]


def test_inspect_accepts_branch_override_for_orphaned_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    orphan_path = tmp_path / "manual-orphan"
    orphan_path.mkdir()

    monkeypatch.setattr(mod, "_get_worktree_entries", lambda _repo: [])
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (0, False))
    monkeypatch.setattr(
        mod,
        "_lookup_open_prs",
        lambda _repo, branch: (
            [{"number": 2000, "title": branch, "url": "https://example.com/pr/2000"}],
            False,
        ),
    )

    inspection = mod.inspect_worktree(
        repo_root,
        orphan_path,
        branch_override="codex/orphaned-branch",
    )

    assert inspection.tracked_worktree is False
    assert inspection.branch == "codex/orphaned-branch"
    assert inspection.blockers == ["open_pr"]


def test_branch_detection_requires_local_git_metadata(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    orphan_path = tmp_path / "orphan"
    orphan_path.mkdir()

    assert mod._branch_for_path(orphan_path, None) is None


def test_branch_detection_timeout_returns_preservation_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    orphan_path = tmp_path / "orphan"
    orphan_path.mkdir()
    (orphan_path / ".git").mkdir()

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod._branch_for_path(orphan_path, None) == mod.BRANCH_LOOKUP_FAILED


def test_open_pr_lookup_timeout_is_lookup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    open_prs, failed = mod._lookup_open_prs(tmp_path, "codex/test")

    assert open_prs == []
    assert failed is True


def test_status_timeout_blocks_cleanup_as_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    worktree = tmp_path / "wt"
    worktree.mkdir()

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    assert mod._worktree_is_dirty(worktree) is True


@pytest.mark.parametrize(
    ("returncode", "stdout", "dirty"),
    [(0, "", False), (0, "?? untracked.txt\n", True), (1, "", True), (128, "", True)],
)
def test_status_result_requires_successful_clean_inspection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    dirty: bool,
) -> None:
    import safe_worktree_cleanup as mod

    def fake_run(cmd, **kwargs):
        assert cmd == ["git", "status", "--porcelain", "--untracked-files=all"]
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(cmd, returncode, stdout, "fatal" if returncode else "")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._worktree_is_dirty(tmp_path) is dirty


@pytest.mark.parametrize("error", [FileNotFoundError("git missing"), PermissionError("denied")])
def test_status_launch_failure_blocks_cleanup_as_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    import safe_worktree_cleanup as mod

    def fake_run(*args, **kwargs):
        raise error

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod._worktree_is_dirty(tmp_path) is True


def test_corrupt_index_blocks_real_worktree_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    (tmp_path / ".git" / "index").write_bytes(b"invalid index")
    status = subprocess.run(["git", "status", "--short"], cwd=tmp_path, capture_output=True)
    assert status.returncode != 0
    assert mod._worktree_is_dirty(tmp_path) is True

    monkeypatch.setattr(
        mod,
        "_get_worktree_entry",
        lambda *_args: mod.autopilot.WorktreeEntry(tmp_path, "codex/test"),
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda *_args: (0, False))
    monkeypatch.setattr(mod, "_lookup_open_prs", lambda *_args: ([], False))
    inspection = mod.inspect_worktree(tmp_path, tmp_path)
    assert inspection.dirty is True
    assert "dirty_worktree" in inspection.blockers
    assert mod.cleanup_safety(inspection)["removable"] is False


def test_status_detects_untracked_files_despite_local_git_config(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "config", "--local", "status.showUntrackedFiles", "no"], cwd=tmp_path, check=True
    )
    (tmp_path / "recoverable.txt").write_text("local work\n")
    assert mod._worktree_is_dirty(tmp_path) is True


def test_remove_purges_residual_path_after_failed_git_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    residual = worktree / "aragora" / "live" / ".next"
    residual.mkdir(parents=True)

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=["git", "worktree", "remove"],
            returncode=255,
            stdout="",
            stderr="Directory not empty",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.autopilot, "_branch_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "remove_failed_path_purged"
    assert result["removed"] is False
    assert result["path_purged"] is True
    assert result["git_remove_failed"] is True
    assert "git worktree remove failed" in result["recovery_action"]
    assert worktree.exists() is False


def test_remove_refuses_untracked_residue_without_purge_path_with_recovery(
    tmp_path: Path,
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "anchor-residue"
    worktree.mkdir()
    (worktree / ".claude-session-anchor").write_text("session anchor\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=False,
        branch=None,
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=False,
        force=False,
    )

    assert result["status"] == "untracked_path"
    assert result["removed"] is False
    assert result["path_purged"] is False
    assert result["requires_purge_path"] is True
    assert "--purge-path" in result["recovery_action"]
    assert worktree.exists() is True


def test_remove_purge_path_deletes_anchor_only_untracked_residue(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "anchor-residue"
    worktree.mkdir()
    (worktree / ".claude-session-anchor").write_text("session anchor\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=False,
        branch=None,
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "purged"
    assert result["removed"] is True
    assert result["path_purged"] is True
    assert result["residual_paths"] == []
    assert worktree.exists() is False


def test_remove_purge_path_reports_incomplete_when_anchor_residue_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "anchor-residue"
    worktree.mkdir()
    (worktree / ".claude-session-anchor").write_text("session anchor\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=False,
        branch=None,
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_args, **_kwargs: None)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "purge_incomplete"
    assert result["removed"] is False
    assert result["path_purged"] is False
    assert result["residual_paths"] == [".claude-session-anchor"]
    assert "not fully removed" in result["recovery_action"]
    assert worktree.exists() is True


def test_tracked_remove_purge_failure_reports_not_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-residue"
    residual = worktree / "build" / "cache"
    residual.mkdir(parents=True)
    (residual / "leftover.txt").write_text("residue\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_args, **_kwargs: None)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "purge_incomplete"
    assert result["removed"] is False
    assert result["git_worktree_removed"] is True
    assert result["path_purged"] is False
    assert "build" in result["residual_paths"]
    assert "not fully removed" in result["recovery_action"]


def test_failed_git_remove_and_failed_purge_preserve_both_signals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-residue"
    worktree.mkdir()
    (worktree / "leftover.txt").write_text("residue\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=255,
            stdout="",
            stderr="Directory not empty",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_args, **_kwargs: None)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "remove_failed_purge_incomplete"
    assert result["git_remove_failed"] is True
    assert result["stderr"] == "Directory not empty"
    assert "not fully removed" in result["recovery_action"]
    assert result["removed"] is False
    assert result["path_purged"] is False
    assert result["residual_paths"] == ["leftover.txt"]


def test_failed_git_remove_without_purge_has_recovery_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-residue"
    worktree.mkdir()

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=255,
            stdout="",
            stderr="Directory not empty",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=False,
        force=False,
    )

    assert result["status"] == "remove_failed"
    assert result["git_remove_failed"] is True
    assert "rerun inspect" in result["recovery_action"]


def test_cmd_remove_reports_failed_git_remove_even_after_path_purge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-residue"
    worktree.mkdir()
    (worktree / "leftover.txt").write_text("residue\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=255,
            stdout="",
            stderr="Directory not empty",
        )

    monkeypatch.setattr(mod, "inspect_worktree", lambda *_args, **_kwargs: inspection)
    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    args = argparse.Namespace(
        repo=".",
        path=str(worktree),
        branch=None,
        delete_branch=True,
        purge_path=True,
        force=False,
        json=True,
    )

    rc = mod.cmd_remove(args)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["status"] == "remove_failed_path_purged"
    assert payload["git_remove_failed"] is True
    assert payload["path_purged"] is True
    assert payload["removed"] is False
    assert payload["branch_deleted"] is False


def test_cmd_remove_returns_nonzero_for_tracked_residue_purge_incomplete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-residue"
    residual = worktree / "build" / "cache"
    residual.mkdir(parents=True)
    (residual / "leftover.txt").write_text("residue\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(mod, "inspect_worktree", lambda *_args, **_kwargs: inspection)
    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_args, **_kwargs: None)

    args = argparse.Namespace(
        repo=".",
        path=str(worktree),
        branch=None,
        delete_branch=False,
        purge_path=True,
        force=False,
        json=True,
    )

    rc = mod.cmd_remove(args)
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["status"] == "purge_incomplete"
    assert payload["git_worktree_removed"] is True
    assert payload["path_purged"] is False
    assert payload["removed"] is False


def test_git_remove_timeout_sets_failure_flag_and_recovery_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-timeout"
    worktree.mkdir()

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def timeout_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(mod.subprocess, "run", timeout_run)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "remove_failed"
    assert result["git_remove_failed"] is True
    assert result["git_worktree_removed"] is False
    assert "timed out" in result["stderr"]
    assert "rerun inspect" in result["recovery_action"]


def test_purge_race_success_clears_stale_purge_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "anchor-residue"
    worktree.mkdir()

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=False,
        branch=None,
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )

    def race_remove(path: Path) -> None:
        path.rmdir()
        raise OSError("path disappeared during purge")

    monkeypatch.setattr(mod.shutil, "rmtree", race_remove)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=False,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "purged"
    assert result["path_purged"] is True
    assert result["purge_error"] is None
    assert result["residual_paths"] == []


def test_purge_incomplete_does_not_delete_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "tracked-residue"
    worktree.mkdir()
    (worktree / "leftover.txt").write_text("residue\n")

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )
    branch_delete_calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        command = list(args[0])
        if command[:3] == ["git", "branch", "-D"]:
            branch_delete_calls.append(command)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod.autopilot, "_branch_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda *_args, **_kwargs: None)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=True,
        purge_path=True,
        force=False,
    )

    assert result["status"] == "purge_incomplete"
    assert result["branch_deleted"] is False
    assert branch_delete_calls == []


def test_residual_paths_are_bounded_without_rglob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    residue = tmp_path / "large-residue"
    residue.mkdir()
    for index in range(60):
        (residue / f"leftover-{index:02d}.txt").write_text("x")

    def fail_rglob(*_args, **_kwargs):
        raise AssertionError("residual lookup must not traverse with rglob")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    residuals = mod._residual_paths(residue, limit=50)

    assert len(residuals) == 51
    assert residuals[-1] == "..."


def test_residual_paths_name_file_targets(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    residue = tmp_path / "leftover.log"
    residue.write_text("residue\n")

    assert mod._residual_paths(residue) == ["leftover.log"]


def test_remove_deletes_branch_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=False,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[],
        pr_lookup_failed=False,
        blockers=[],
    )
    monkeypatch.setattr(mod.autopilot, "_branch_exists", lambda *_args, **_kwargs: True)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="Deleted branch codex/test\n",
            stderr="",
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)

    result = mod.remove_worktree(
        repo_root,
        inspection,
        delete_branch=True,
        purge_path=True,
        force=False,
    )

    assert result["branch_deleted"] is True
    assert result["status"] == "purged"


def test_inspect_blocks_dirty_and_ahead_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.autopilot.WorktreeEntry(path=worktree, branch="codex/test")],
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: True)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (2, False))
    monkeypatch.setattr(mod, "_lookup_open_prs", lambda _repo, _branch: ([], False))

    inspection = mod.inspect_worktree(repo_root, worktree)

    assert inspection.dirty is True
    assert inspection.unique_commits_ahead == 2
    assert inspection.blockers == ["dirty_worktree", "branch_ahead_of_origin_main"]
    safety = mod.cleanup_safety(inspection)
    assert safety["classification"] == "unsafe_to_delete"
    assert safety["decision"] == "preserve"
    assert [row["category"] for row in safety["blocker_details"]] == [
        "unsafe_to_delete",
        "unsafe_to_delete",
    ]


def test_inspect_allows_pr_lookup_failure_for_branch_with_no_unique_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.autopilot.WorktreeEntry(path=worktree, branch="codex/merged")],
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (0, False))
    monkeypatch.setattr(mod, "_lookup_open_prs", lambda _repo, _branch: ([], True))

    inspection = mod.inspect_worktree(repo_root, worktree)

    assert inspection.pr_lookup_failed is True
    assert inspection.unique_commits_ahead == 0
    assert inspection.blockers == []
    safety = mod.cleanup_safety(inspection)
    assert safety["classification"] == "stale_or_merged"
    assert safety["decision"] == "cleanup_candidate"
    assert safety["removable"] is True


def test_inspect_allows_patch_equivalent_branch_when_pr_lookup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.autopilot.WorktreeEntry(path=worktree, branch="codex/replayed")],
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (4, False))
    monkeypatch.setattr(mod, "_patch_equivalent_to_main", lambda _repo, _branch: (True, False))
    monkeypatch.setattr(mod, "_lookup_open_prs", lambda _repo, _branch: ([], True))

    inspection = mod.inspect_worktree(repo_root, worktree)

    assert inspection.pr_lookup_failed is True
    assert inspection.unique_commits_ahead == 4
    assert inspection.patch_equivalent_to_origin_main is True
    assert inspection.blockers == []
    safety = mod.cleanup_safety(inspection)
    assert safety["classification"] == "harvested_or_duplicate"
    assert safety["decision"] == "cleanup_candidate"
    assert safety["signals"]["patch_equivalent_to_origin_main"] is True


def test_inspect_reports_stale_lock_files_without_blocking_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".codex_session_active").write_text("pid=12345\n")

    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.autopilot.WorktreeEntry(path=worktree, branch="codex/test")],
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (0, False))
    monkeypatch.setattr(mod, "_lookup_open_prs", lambda _repo, _branch: ([], False))

    inspection = mod.inspect_worktree(repo_root, worktree)

    assert inspection.lock_files == [".codex_session_active"]
    assert inspection.active_session is False
    assert inspection.blockers == []


def test_inspect_blocks_active_session_and_history_lookup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import safe_worktree_cleanup as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".codex_session_active").write_text("active\n")

    monkeypatch.setattr(mod.autopilot, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.autopilot.WorktreeEntry(path=worktree, branch="codex/test")],
    )
    monkeypatch.setattr(mod.autopilot, "_has_active_session", lambda _path: True)
    monkeypatch.setattr(mod, "_worktree_is_dirty", lambda _path: False)
    monkeypatch.setattr(mod, "_unique_commits_ahead_of_main", lambda _repo, _branch: (0, True))
    monkeypatch.setattr(mod, "_lookup_open_prs", lambda _repo, _branch: ([], False))

    inspection = mod.inspect_worktree(repo_root, worktree)

    assert inspection.lock_files == [".codex_session_active"]
    assert inspection.active_session is True
    assert inspection.ahead_lookup_failed is True
    assert inspection.blockers == ["active_session", "ahead_lookup_failed"]
    safety = mod.cleanup_safety(inspection)
    assert safety["classification"] == "owned"
    assert safety["decision"] == "preserve"
    assert [row["category"] for row in safety["blocker_details"]] == ["owned", "unknown"]
    assert safety["blocker_details"][0]["next_action"] == (
        "preserve and route cleanup through the live owner"
    )


def test_inspect_json_includes_cleanup_safety_payload(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import safe_worktree_cleanup as mod

    worktree = tmp_path / "wt"
    worktree.mkdir()
    inspection = mod.WorktreeInspection(
        path=str(worktree),
        exists=True,
        tracked_worktree=True,
        branch="codex/test",
        active_session=False,
        lock_files=[],
        dirty=False,
        unique_commits_ahead=0,
        ahead_lookup_failed=False,
        patch_equivalent_to_origin_main=False,
        patch_equivalence_lookup_failed=False,
        open_prs=[{"number": 1361, "title": "Open PR", "url": "https://example.com/pr/1361"}],
        pr_lookup_failed=False,
        blockers=["open_pr"],
    )

    mod._print_inspection(inspection, as_json=True)

    payload = json.loads(capsys.readouterr().out)
    assert payload["removable"] is False
    assert payload["cleanup_safety"]["classification"] == "referenced_preserve"
    assert payload["cleanup_safety"]["decision"] == "preserve"
    assert payload["cleanup_safety"]["blocker_details"] == [
        {
            "blocker": "open_pr",
            "category": "referenced",
            "reason": "A live open PR references this branch.",
            "next_action": "preserve until the PR is merged, closed, or explicitly superseded",
        }
    ]


def test_worktree_is_not_dirty_for_empty_nested_wrapper(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    wrapper = tmp_path / "wrapper"
    nested = wrapper / ".worktrees" / "preflight-preflight-20260418-184346"
    nested.mkdir(parents=True)
    (nested / ".claude-session-anchor").write_text("")
    second_nested = wrapper / ".worktrees" / "preflight-preflight-20260418-201113"
    second_nested.mkdir(parents=True)
    (second_nested / ".claude-session-anchor").write_text("")

    assert mod._is_empty_nested_wrapper(wrapper) is True
    assert mod._worktree_is_dirty(wrapper) is False


def test_worktree_is_dirty_when_wrapper_has_real_files(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    wrapper = tmp_path / "wrapper"
    nested = wrapper / ".worktrees" / "preflight-preflight-20260418-184346"
    nested.mkdir(parents=True)
    (nested / ".claude-session-anchor").write_text("")
    (wrapper / "real_file.py").write_text("print('hello')")

    assert mod._is_empty_nested_wrapper(wrapper) is False


def test_worktree_is_not_dirty_for_flat_anchor_only_wrapper(tmp_path: Path) -> None:
    import safe_worktree_cleanup as mod

    wrapper = tmp_path / "wrapper"
    wrapper.mkdir()
    (wrapper / ".claude-session-anchor").write_text("session anchor\n")

    assert mod._is_empty_nested_wrapper(wrapper) is True
    assert mod._worktree_is_dirty(wrapper) is False
