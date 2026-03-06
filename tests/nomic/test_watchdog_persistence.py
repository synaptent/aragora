"""Tests for WorktreeWatchdog disk persistence and crash recovery."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.nomic.worktree_watchdog import (
    WatchdogConfig,
    WorktreeWatchdog,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def persist_file(tmp_path: Path) -> Path:
    """Return a path for the persistence JSON file."""
    return tmp_path / "watchdog_sessions.json"


@pytest.fixture
def watchdog(tmp_path: Path, persist_file: Path) -> WorktreeWatchdog:
    """Create a watchdog with persistence enabled and short timeouts."""
    config = WatchdogConfig(
        stall_timeout_seconds=1.0,
        abandon_timeout_seconds=3.0,
        auto_kill_stalled=False,
        auto_cleanup_abandoned=False,
        emit_events=False,
    )
    return WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)


@pytest.fixture
def worktree_path(tmp_path: Path) -> Path:
    """Create a mock worktree directory."""
    wt = tmp_path / ".worktrees" / "dev-sme-1"
    wt.mkdir(parents=True)
    return wt


# =============================================================================
# Session Persistence to Disk
# =============================================================================


class TestSessionPersistence:
    """Tests that sessions are written to disk after state changes."""

    def test_persist_on_register(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """Registering a session should write to disk."""
        watchdog.register_session(
            branch_name="dev/sme-1",
            worktree_path=worktree_path,
            track="sme",
        )

        assert persist_file.exists()
        data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert data["version"] == 1
        assert len(data["sessions"]) == 1
        assert data["sessions"][0]["branch_name"] == "dev/sme-1"
        assert data["sessions"][0]["status"] == "active"

    def test_persist_on_heartbeat(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """Heartbeat should update the persisted file."""
        sid = watchdog.register_session(
            branch_name="dev/sme-1",
            worktree_path=worktree_path,
            track="sme",
        )

        old_data = json.loads(persist_file.read_text(encoding="utf-8"))
        old_ts = old_data["updated_at"]

        watchdog.heartbeat(sid)

        new_data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert new_data["sessions"][0]["heartbeat_count"] == 1
        # Timestamp should have been refreshed
        assert new_data["updated_at"] >= old_ts

    def test_persist_on_complete(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """Completing a session should persist the status change."""
        sid = watchdog.register_session(
            branch_name="dev/sme-1",
            worktree_path=worktree_path,
            track="sme",
        )

        watchdog.complete_session(sid)

        data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert data["sessions"][0]["status"] == "completed"

    def test_persist_on_abandon(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """Abandoning a session should persist the status change."""
        sid = watchdog.register_session(
            branch_name="dev/sme-1",
            worktree_path=worktree_path,
            track="sme",
        )

        watchdog.abandon_session(sid)

        data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert data["sessions"][0]["status"] == "abandoned"

    def test_persist_on_check_health(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """check_health() status transitions should be persisted."""
        sid = watchdog.register_session(
            branch_name="dev/sme-1",
            worktree_path=worktree_path,
            track="sme",
        )

        # Push heartbeat into the past (beyond stall timeout)
        session = watchdog.get_session(sid)
        assert session is not None
        session.last_heartbeat = time.monotonic() - 2.0

        watchdog.check_health()

        data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert data["sessions"][0]["status"] == "stalled"

    def test_persist_multiple_sessions(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """Multiple sessions should all be persisted."""
        watchdog.register_session(branch_name="dev/sme-1", worktree_path=worktree_path, track="sme")
        watchdog.register_session(branch_name="dev/qa-1", worktree_path=worktree_path, track="qa")

        data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert len(data["sessions"]) == 2
        tracks = {s["track"] for s in data["sessions"]}
        assert tracks == {"sme", "qa"}

    def test_persist_session_counter(
        self, watchdog: WorktreeWatchdog, worktree_path: Path, persist_file: Path
    ) -> None:
        """Session counter should be persisted for monotonicity."""
        watchdog.register_session(branch_name="dev/sme-1", worktree_path=worktree_path, track="sme")
        watchdog.register_session(branch_name="dev/qa-1", worktree_path=worktree_path, track="qa")

        data = json.loads(persist_file.read_text(encoding="utf-8"))
        assert data["session_counter"] == 2


# =============================================================================
# Crash Recovery
# =============================================================================


class TestCrashRecovery:
    """Tests for reloading sessions from disk and reconciling PID state."""

    def test_reload_with_alive_pid(
        self, tmp_path: Path, persist_file: Path, worktree_path: Path
    ) -> None:
        """Session with alive PID should be marked active on reload."""
        current_pid = os.getpid()
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_counter": 5,
                    "updated_at": "2026-03-05T00:00:00+00:00",
                    "sessions": [
                        {
                            "session_id": "wt-1-12345",
                            "branch_name": "dev/test-1",
                            "worktree_path": str(worktree_path),
                            "track": "sme",
                            "pid": current_pid,
                            "registered_at": 100.0,
                            "last_heartbeat": 100.0,
                            "heartbeat_count": 10,
                            "status": "active",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)

        session = wd.get_session("wt-1-12345")
        assert session is not None
        assert session.status == "active"
        assert session.branch_name == "dev/test-1"
        # last_heartbeat should be refreshed to current monotonic time
        assert session.last_heartbeat > 100.0

    def test_reload_with_dead_pid(
        self, tmp_path: Path, persist_file: Path, worktree_path: Path
    ) -> None:
        """Session with dead PID should be marked abandoned on reload."""
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_counter": 3,
                    "updated_at": "2026-03-05T00:00:00+00:00",
                    "sessions": [
                        {
                            "session_id": "wt-2-99999",
                            "branch_name": "dev/dead-branch",
                            "worktree_path": str(worktree_path),
                            "track": "qa",
                            "pid": 4194304,  # Very high PID, unlikely to exist
                            "registered_at": 50.0,
                            "last_heartbeat": 50.0,
                            "heartbeat_count": 5,
                            "status": "active",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        config = WatchdogConfig(emit_events=False)
        with patch.object(WorktreeWatchdog, "_is_process_alive", return_value=False):
            wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)

        session = wd.get_session("wt-2-99999")
        assert session is not None
        assert session.status == "abandoned"
        assert session.track == "qa"

    def test_reload_preserves_completed_sessions(
        self, tmp_path: Path, persist_file: Path, worktree_path: Path
    ) -> None:
        """Completed sessions should keep their status on reload."""
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_counter": 1,
                    "updated_at": "2026-03-05T00:00:00+00:00",
                    "sessions": [
                        {
                            "session_id": "wt-done-1",
                            "branch_name": "dev/finished",
                            "worktree_path": str(worktree_path),
                            "track": "core",
                            "pid": 4194304,
                            "registered_at": 10.0,
                            "last_heartbeat": 10.0,
                            "heartbeat_count": 20,
                            "status": "completed",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)

        session = wd.get_session("wt-done-1")
        assert session is not None
        assert session.status == "completed"

    def test_reload_preserves_recovered_sessions(
        self, tmp_path: Path, persist_file: Path, worktree_path: Path
    ) -> None:
        """Recovered sessions should keep their status on reload."""
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_counter": 1,
                    "updated_at": "2026-03-05T00:00:00+00:00",
                    "sessions": [
                        {
                            "session_id": "wt-rec-1",
                            "branch_name": "dev/recovered",
                            "worktree_path": str(worktree_path),
                            "track": "core",
                            "pid": 4194304,
                            "registered_at": 10.0,
                            "last_heartbeat": 10.0,
                            "heartbeat_count": 3,
                            "status": "recovered",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)

        session = wd.get_session("wt-rec-1")
        assert session is not None
        assert session.status == "recovered"

    def test_reload_restores_session_counter(
        self, tmp_path: Path, persist_file: Path, worktree_path: Path
    ) -> None:
        """Session counter should be restored to avoid ID collisions."""
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_counter": 42,
                    "updated_at": "2026-03-05T00:00:00+00:00",
                    "sessions": [],
                }
            ),
            encoding="utf-8",
        )

        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)

        # Register a new session -- counter should start above 42
        sid = wd.register_session(branch_name="dev/new", worktree_path=worktree_path, track="sme")
        assert sid.startswith("wt-43-")

    def test_reload_handles_corrupt_json(self, tmp_path: Path, persist_file: Path) -> None:
        """Corrupt JSON should not crash initialization."""
        persist_file.parent.mkdir(parents=True, exist_ok=True)
        persist_file.write_text("NOT VALID JSON {{{{", encoding="utf-8")

        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=persist_file)

        assert wd.list_sessions() == []

    def test_reload_handles_missing_file(self, tmp_path: Path) -> None:
        """Missing persist file should result in empty state."""
        missing = tmp_path / "nonexistent" / "sessions.json"
        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=missing)

        assert wd.list_sessions() == []


# =============================================================================
# Lock File Name Recognition
# =============================================================================


class TestLockFileNames:
    """Tests that _has_active_session recognizes .nomic-session-active."""

    def test_nomic_lock_file_recognized(self, tmp_path: Path) -> None:
        """The .nomic-session-active lock file should be recognized."""
        from scripts.codex_worktree_autopilot import _has_active_session

        lock_file = tmp_path / ".nomic-session-active"
        lock_file.write_text(
            json.dumps({"pid": os.getpid(), "timestamp": "2026-03-05T00:00:00"}),
            encoding="utf-8",
        )

        assert _has_active_session(tmp_path) is True

    def test_nomic_lock_file_dead_pid(self, tmp_path: Path) -> None:
        """Dead PID in .nomic-session-active should not block."""
        from scripts.codex_worktree_autopilot import _has_active_session

        lock_file = tmp_path / ".nomic-session-active"
        lock_file.write_text(
            json.dumps({"pid": 4194304, "timestamp": "2026-03-05T00:00:00"}),
            encoding="utf-8",
        )

        with patch("scripts.codex_worktree_autopilot._pid_alive", return_value=False):
            assert _has_active_session(tmp_path) is False

    def test_claude_lock_still_recognized(self, tmp_path: Path) -> None:
        """Existing .claude-session-active lock should still work."""
        from scripts.codex_worktree_autopilot import _has_active_session

        lock_file = tmp_path / ".claude-session-active"
        lock_file.write_text(
            json.dumps({"pid": os.getpid(), "timestamp": "2026-03-05T00:00:00"}),
            encoding="utf-8",
        )

        assert _has_active_session(tmp_path) is True

    def test_codex_lock_still_recognized(self, tmp_path: Path) -> None:
        """Existing .codex_session_active lock should still work."""
        from scripts.codex_worktree_autopilot import _has_active_session

        lock_file = tmp_path / ".codex_session_active"
        lock_file.write_text(f"pid={os.getpid()}\n", encoding="utf-8")

        assert _has_active_session(tmp_path) is True

    def test_no_lock_files_means_inactive(self, tmp_path: Path) -> None:
        """No lock files should mean the session is not active."""
        from scripts.codex_worktree_autopilot import _has_active_session

        assert _has_active_session(tmp_path) is False


# =============================================================================
# Clean State on Fresh Init
# =============================================================================


class TestCleanState:
    """Tests that a fresh watchdog starts with clean state."""

    def test_fresh_init_no_sessions(self, tmp_path: Path) -> None:
        """Fresh watchdog with no persist file should have no sessions."""
        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(
            repo_path=tmp_path,
            config=config,
            persist_path=tmp_path / "fresh_sessions.json",
        )

        assert wd.list_sessions() == []
        report = wd.check_health()
        assert report.total_sessions == 0

    def test_fresh_init_creates_persist_on_first_register(
        self, tmp_path: Path, worktree_path: Path
    ) -> None:
        """Persist file should be created on first session registration."""
        pf = tmp_path / "subdir" / "sessions.json"
        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=pf)

        assert not pf.exists()

        wd.register_session(
            branch_name="dev/first",
            worktree_path=worktree_path,
            track="core",
        )

        assert pf.exists()
        data = json.loads(pf.read_text(encoding="utf-8"))
        assert len(data["sessions"]) == 1

    def test_default_persist_path_under_aragora_beads(self, tmp_path: Path) -> None:
        """Default persist_path should be under .aragora_beads/."""
        config = WatchdogConfig(emit_events=False)
        wd = WorktreeWatchdog(repo_path=tmp_path, config=config)

        expected = tmp_path / ".aragora_beads" / "watchdog_sessions.json"
        assert wd._persist_path == expected

    def test_roundtrip_persist_and_reload(self, tmp_path: Path, worktree_path: Path) -> None:
        """Sessions persisted by one watchdog should be loadable by another."""
        pf = tmp_path / "roundtrip.json"
        config = WatchdogConfig(emit_events=False)

        # First watchdog: register and complete
        wd1 = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=pf)
        sid = wd1.register_session(
            branch_name="dev/roundtrip",
            worktree_path=worktree_path,
            track="dev",
            pid=os.getpid(),
        )
        wd1.heartbeat(sid)
        wd1.heartbeat(sid)
        wd1.complete_session(sid)

        # Second watchdog: reload
        wd2 = WorktreeWatchdog(repo_path=tmp_path, config=config, persist_path=pf)
        session = wd2.get_session(sid)
        assert session is not None
        assert session.status == "completed"
        assert session.heartbeat_count == 2
        assert session.branch_name == "dev/roundtrip"
