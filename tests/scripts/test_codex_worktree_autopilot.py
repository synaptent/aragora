"""Unit tests for scripts/codex_worktree_autopilot.py."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"


@pytest.fixture(autouse=True)
def _setup_path():
    sys.path.insert(0, str(SCRIPTS_DIR))
    yield
    sys.path.remove(str(SCRIPTS_DIR))


def test_parse_worktree_porcelain_includes_branch_and_detached():
    import codex_worktree_autopilot as mod

    porcelain = (
        "worktree /repo\n"
        "HEAD abc\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/.worktrees/codex-auto/s1\n"
        "HEAD def\n"
        "branch refs/heads/codex/s1\n"
        "\n"
        "worktree /repo/.worktrees/codex-auto/s2\n"
        "HEAD 123\n"
        "detached\n"
        "\n"
    )
    entries = mod._parse_worktree_porcelain(porcelain)
    assert len(entries) == 3
    assert entries[0].branch == "main"
    assert entries[1].branch == "codex/s1"
    assert entries[2].detached is True
    assert entries[2].branch is None


def test_prune_stale_state_removes_inactive_paths(tmp_path):
    import codex_worktree_autopilot as mod

    a_path = tmp_path / "a"
    b_path = tmp_path / "b"
    a_path.mkdir()
    b_path.mkdir()

    state = {
        "sessions": [
            {"session_id": "a", "path": str(a_path)},
            {"session_id": "b", "path": str(b_path)},
        ]
    }
    active = {str(b_path)}
    pruned, removed = mod._prune_stale_state(state, active)
    assert removed == 1
    assert len(pruned["sessions"]) == 1
    assert pruned["sessions"][0]["session_id"] == "b"


def test_choose_reusable_session_prefers_latest_last_seen():
    import codex_worktree_autopilot as mod

    state = {
        "sessions": [
            {
                "agent": "codex",
                "session_id": "old",
                "path": "/repo/.worktrees/codex-auto/old",
                "last_seen_at": "2026-02-24T00:00:00+00:00",
            },
            {
                "agent": "codex",
                "session_id": "new",
                "path": "/repo/.worktrees/codex-auto/new",
                "last_seen_at": "2026-02-24T01:00:00+00:00",
            },
        ]
    }
    chosen = mod._choose_reusable_session(
        state,
        agent="codex",
        session_id=None,
        active_paths={
            "/repo/.worktrees/codex-auto/old",
            "/repo/.worktrees/codex-auto/new",
        },
    )
    assert chosen is not None
    assert chosen["session_id"] == "new"


def test_choose_reusable_session_honors_session_id_filter():
    import codex_worktree_autopilot as mod

    state = {
        "sessions": [
            {"agent": "codex", "session_id": "a", "path": "/repo/.worktrees/codex-auto/a"},
            {"agent": "codex", "session_id": "b", "path": "/repo/.worktrees/codex-auto/b"},
        ]
    }
    chosen = mod._choose_reusable_session(
        state,
        agent="codex",
        session_id="a",
        active_paths={
            "/repo/.worktrees/codex-auto/a",
            "/repo/.worktrees/codex-auto/b",
        },
    )
    assert chosen is not None
    assert chosen["session_id"] == "a"


def test_cleanup_parser_defaults_to_delete_branches():
    import codex_worktree_autopilot as mod

    parser = mod._build_parser()
    args = parser.parse_args(["cleanup"])
    assert args.delete_branches is True


def test_ensure_parser_defaults_to_ff_only_strategy():
    import codex_worktree_autopilot as mod

    parser = mod._build_parser()
    args = parser.parse_args(["ensure"])
    assert args.strategy == "ff-only"


def test_reconcile_parser_defaults_to_ff_only_strategy():
    import codex_worktree_autopilot as mod

    parser = mod._build_parser()
    args = parser.parse_args(["reconcile"])
    assert args.strategy == "ff-only"


def test_cleanup_parser_allows_no_delete_branches_toggle():
    import codex_worktree_autopilot as mod

    parser = mod._build_parser()
    args = parser.parse_args(["cleanup", "--no-delete-branches"])
    assert args.delete_branches is False


def test_maintain_parser_allows_no_delete_branches_toggle():
    import codex_worktree_autopilot as mod

    parser = mod._build_parser()
    args = parser.parse_args(["maintain", "--no-delete-branches"])
    assert args.delete_branches is False


def test_maintain_parser_defaults_to_ff_only_strategy():
    import codex_worktree_autopilot as mod

    parser = mod._build_parser()
    args = parser.parse_args(["maintain"])
    assert args.strategy == "ff-only"


def test_parse_ts_normalizes_naive_timestamp_to_utc():
    import codex_worktree_autopilot as mod

    parsed = mod._parse_ts("2026-02-24T12:00:00")
    assert parsed is not None
    assert parsed.tzinfo == timezone.utc


def test_cmd_cleanup_keeps_session_when_worktree_remove_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    active_path = tmp_path / "active-wt"
    active_path.mkdir()
    state = {
        "sessions": [
            {
                "session_id": "s1",
                "agent": "codex",
                "branch": "codex/s1",
                "path": str(active_path),
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
    }
    saved_state: dict[str, object] = {}

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.WorktreeEntry(path=active_path, branch="codex/s1")],
    )
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_branch_ahead_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(mod, "_remove_worktree", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(mod, "_delete_branch", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        mod,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "worktree", "prune"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        mod, "_save_state", lambda _state_file, payload: saved_state.update(payload)
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        base="main",
        ttl_hours=0,
        force_unmerged=False,
        delete_branches=True,
        json=True,
    )
    rc = mod.cmd_cleanup(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 0
    assert payload["kept"] == 1
    assert payload["failed_worktree_removals"] == 1
    assert payload["failed_branch_deletions"] == 0
    assert len(saved_state["sessions"]) == 1


def test_cmd_cleanup_reports_failed_branch_deletions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    stale_path = tmp_path / "stale-wt"
    state = {
        "sessions": [
            {
                "session_id": "s2",
                "agent": "codex",
                "branch": "codex/s2",
                "path": str(stale_path),
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
    }
    saved_state: dict[str, object] = {}

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(mod, "_get_worktree_entries", lambda _repo: [])
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_delete_branch", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        mod,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "worktree", "prune"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        mod, "_save_state", lambda _state_file, payload: saved_state.update(payload)
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        base="main",
        ttl_hours=24,
        force_unmerged=False,
        delete_branches=True,
        json=True,
    )
    rc = mod.cmd_cleanup(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 1
    assert payload["kept"] == 0
    assert payload["failed_worktree_removals"] == 0
    assert payload["failed_branch_deletions"] == 1
    assert saved_state["sessions"] == []


def test_cmd_cleanup_skips_worktree_with_active_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    leased_path = tmp_path / "leased-wt"
    leased_path.mkdir()
    state = {
        "sessions": [
            {
                "session_id": "lease1",
                "agent": "codex",
                "branch": "codex/lease1",
                "path": str(leased_path),
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
    }
    saved_state: dict[str, object] = {}

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.WorktreeEntry(path=leased_path, branch="codex/lease1")],
    )
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(
        mod,
        "_lease_snapshot",
        lambda _repo_root, _path: {
            "lease_id": "lease-1",
            "lease_status": "active",
            "last_heartbeat_at": "2026-02-24T00:00:00+00:00",
            "lease_expires_at": "2026-02-24T08:00:00+00:00",
            "owner_agent": "codex",
            "owner_session_id": "sess-1",
            "branch": "codex/lease1",
            "title": "leased",
            "has_live_lease": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "worktree", "prune"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        mod, "_save_state", lambda _state_file, payload: saved_state.update(payload)
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        base="main",
        ttl_hours=0,
        force_unmerged=False,
        delete_branches=True,
        json=True,
    )
    rc = mod.cmd_cleanup(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["removed"] == 0
    assert payload["kept"] == 1
    assert payload["skipped_grace"] == 1
    assert payload["skipped_active_session"] == 0
    assert payload["results"][0]["status"] == "skipped_grace"
    assert payload["results"][0]["lifecycle_state"] == "grace"
    assert saved_state["sessions"] == state["sessions"]


def test_has_active_session_detects_codex_lock_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import codex_worktree_autopilot as mod

    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".codex_session_active").write_text("pid=1234\n", encoding="utf-8")

    def _fake_kill(pid: int, sig: int) -> None:
        if pid == 1234:
            return
        raise ProcessLookupError

    monkeypatch.setattr(mod.os, "kill", _fake_kill)
    assert mod._has_active_session(worktree) is True


def test_cmd_reconcile_skips_active_session_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    active_path = tmp_path / "active-wt"
    active_path.mkdir()
    state = {
        "sessions": [
            {
                "session_id": "s1",
                "agent": "codex",
                "branch": "codex/s1",
                "path": str(active_path),
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
    }
    saved_state: dict[str, object] = {}

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.WorktreeEntry(path=active_path, branch="codex/s1")],
    )
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_has_active_session", lambda _path: True)
    monkeypatch.setattr(
        mod,
        "_integrate_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not reconcile")),
    )
    monkeypatch.setattr(
        mod, "_save_state", lambda _state_file, payload: saved_state.update(payload)
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        base="main",
        strategy="ff-only",
        all=True,
        path=None,
        json=True,
    )
    rc = mod.cmd_reconcile(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["skipped_active_session"] == 1
    assert payload["results"][0]["status"] == "skipped_active_session"
    assert saved_state["sessions"][0]["reconcile_status"] == "skipped_active_session"


def test_cmd_reconcile_skips_grace_lane_with_live_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    grace_path = tmp_path / "grace-wt"
    grace_path.mkdir()
    state = {
        "sessions": [
            {
                "session_id": "grace-1",
                "agent": "codex",
                "branch": "codex/grace-1",
                "path": str(grace_path),
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
    }
    saved_state: dict[str, object] = {}

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.WorktreeEntry(path=grace_path, branch="codex/grace-1")],
    )
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(
        mod,
        "_lease_snapshot",
        lambda _repo_root, _path: {
            "lease_id": "lease-1",
            "lease_status": "active",
            "last_heartbeat_at": "2026-02-24T00:00:00+00:00",
            "lease_expires_at": "2026-02-24T08:00:00+00:00",
            "owner_agent": "codex",
            "owner_session_id": "sess-1",
            "branch": "codex/grace-1",
            "title": "grace",
            "has_live_lease": True,
        },
    )
    monkeypatch.setattr(
        mod,
        "_integrate_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not reconcile")),
    )
    monkeypatch.setattr(
        mod, "_save_state", lambda _state_file, payload: saved_state.update(payload)
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        base="main",
        strategy="ff-only",
        ttl_hours=24,
        all=True,
        path=None,
        json=True,
    )
    rc = mod.cmd_reconcile(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["skipped_grace"] == 1
    assert payload["results"][0]["status"] == "skipped_grace"
    assert payload["results"][0]["lifecycle_state"] == "grace"
    assert saved_state["sessions"][0]["reconcile_status"] == "skipped_grace"


def test_cmd_cleanup_archives_before_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    stale_path = tmp_path / "stale-wt"
    stale_path.mkdir()
    state = {
        "sessions": [
            {
                "session_id": "stale-1",
                "agent": "codex",
                "branch": "codex/stale-1",
                "path": str(stale_path),
                "created_at": "2026-02-01T00:00:00+00:00",
            }
        ]
    }
    saved_state: dict[str, object] = {}
    removed_paths: list[Path] = []

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(
        mod,
        "_get_worktree_entries",
        lambda _repo: [mod.WorktreeEntry(path=stale_path, branch="codex/stale-1")],
    )
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_has_active_session", lambda _path: False)
    monkeypatch.setattr(
        mod,
        "_lease_snapshot",
        lambda _repo_root, _path: {
            "lease_id": None,
            "lease_status": None,
            "last_heartbeat_at": None,
            "lease_expires_at": None,
            "owner_agent": None,
            "owner_session_id": None,
            "branch": None,
            "title": None,
            "has_live_lease": False,
        },
    )
    monkeypatch.setattr(mod, "_worktree_status", lambda *_args, **_kwargs: {"dirty": False})
    monkeypatch.setattr(mod, "_branch_ahead_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(
        mod,
        "_archive_session",
        lambda _repo_root, _session, _metadata: (True, "/tmp/archive/stale-1"),
    )
    monkeypatch.setattr(
        mod,
        "_remove_worktree",
        lambda _repo_root, path: removed_paths.append(path) or True,
    )
    monkeypatch.setattr(mod, "_delete_branch", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        mod,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "worktree", "prune"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        mod, "_save_state", lambda _state_file, payload: saved_state.update(payload)
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        base="main",
        ttl_hours=0,
        force_unmerged=False,
        delete_branches=True,
        json=True,
    )
    rc = mod.cmd_cleanup(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["archived"] == 1
    assert payload["removed"] == 1
    assert payload["failed_archives"] == 0
    assert payload["results"][0]["archive_path"] == "/tmp/archive/stale-1"
    assert removed_paths == [stale_path]
    assert saved_state["sessions"] == []


def test_cmd_status_reports_lifecycle_and_lock_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import codex_worktree_autopilot as mod

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state = {
        "sessions": [
            {
                "session_id": "s1",
                "agent": "codex",
                "branch": "codex/s1",
                "path": str(tmp_path / "active"),
                "created_at": "2026-02-01T00:00:00+00:00",
            },
            {
                "session_id": "s2",
                "agent": "codex",
                "branch": "codex/s2",
                "path": str(tmp_path / "safe"),
                "created_at": "2026-02-01T00:00:00+00:00",
            },
        ]
    }

    metadata_rows = iter(
        [
            {
                "lifecycle_state": "active",
                "cleanup_lock": True,
                "cleanup_lock_reason": "active_session",
                "base_branch": "main",
                "base_sha": "abc123",
                "last_heartbeat_at": "2026-02-24T00:00:00+00:00",
                "lease_status": "active",
                "lease_expires_at": "2026-02-24T08:00:00+00:00",
            },
            {
                "lifecycle_state": "safe-to-clean",
                "cleanup_lock": False,
                "cleanup_lock_reason": None,
                "base_branch": "main",
                "base_sha": "def456",
                "last_heartbeat_at": None,
                "lease_status": None,
                "lease_expires_at": None,
            },
        ]
    )

    monkeypatch.setattr(mod, "_repo_root_from", lambda _path: repo_root)
    monkeypatch.setattr(mod, "_load_state", lambda _state_file: state)
    monkeypatch.setattr(mod, "_get_worktree_entries", lambda _repo: [])
    monkeypatch.setattr(
        mod,
        "_annotate_session",
        lambda *_args, **_kwargs: next(metadata_rows),
    )

    args = argparse.Namespace(
        repo=".",
        managed_dir=".worktrees/codex-auto",
        ttl_hours=24,
        json=True,
    )
    rc = mod.cmd_status(args)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sessions"][0]["lifecycle_state"] == "active"
    assert payload["sessions"][0]["cleanup_lock_reason"] == "active_session"
    assert payload["sessions"][1]["lifecycle_state"] == "safe-to-clean"
