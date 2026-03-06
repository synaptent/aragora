"""Worktree Stall Watchdog.

Monitors active worktree sessions for stalls and abandoned state.
Detects when a session has no git activity for a configurable timeout,
identifies abandoned worktrees with no process holding locks, and
performs auto-recovery (kill stalled processes, clean up abandoned worktrees).

Thread-safe session registry allows concurrent registration and heartbeat
from multiple worktree sessions.

Usage:
    from aragora.nomic.worktree_watchdog import WorktreeWatchdog, WatchdogConfig

    watchdog = WorktreeWatchdog(repo_path=Path("."))

    # Register a session when worktree work begins
    session_id = watchdog.register_session(
        branch_name="dev/sme-dashboard-0224",
        worktree_path=Path(".worktrees/dev-sme-dashboard-0224"),
        track="sme",
        pid=os.getpid(),
    )

    # Heartbeat periodically during execution
    watchdog.heartbeat(session_id)

    # Check health of all sessions
    report = watchdog.check_health()

    # Recover stalled sessions
    recovered = watchdog.recover_stalled()

    # Clean up abandoned worktrees
    cleaned = watchdog.cleanup_abandoned()
"""

from __future__ import annotations

import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WatchdogConfig:
    """Configuration for WorktreeWatchdog."""

    # Seconds without heartbeat before a session is considered stalled
    stall_timeout_seconds: float = 600.0  # 10 minutes
    # Seconds without any activity before a worktree is considered abandoned
    abandon_timeout_seconds: float = 3600.0  # 1 hour
    # Whether to auto-kill stalled processes
    auto_kill_stalled: bool = True
    # Whether to auto-remove abandoned worktrees via git
    auto_cleanup_abandoned: bool = True
    # Signal to send to stalled processes (SIGTERM for graceful shutdown)
    kill_signal: int = signal.SIGTERM
    # Seconds to wait after SIGTERM before SIGKILL
    kill_grace_seconds: float = 10.0
    # Emit events via EventBus
    emit_events: bool = True


@dataclass
class WorktreeSession:
    """Tracked worktree session."""

    session_id: str
    branch_name: str
    worktree_path: Path
    track: str
    pid: int | None = None
    registered_at: float = field(default_factory=time.monotonic)
    last_heartbeat: float = field(default_factory=time.monotonic)
    heartbeat_count: int = 0
    status: str = "active"  # active | stalled | recovered | abandoned | completed


@dataclass
class HealthReport:
    """Health report for all tracked sessions."""

    timestamp: str
    total_sessions: int
    active_sessions: int
    stalled_sessions: int
    abandoned_sessions: int
    completed_sessions: int
    sessions: list[dict[str, Any]]


class WorktreeWatchdog:
    """Monitors worktree sessions for stalls and abandonment.

    Thread-safe: all session operations are guarded by a lock,
    allowing concurrent heartbeat and health check calls from
    multiple worktree execution threads.
    """

    def __init__(
        self,
        repo_path: Path | None = None,
        config: WatchdogConfig | None = None,
        persist_path: Path | str | None = None,
    ):
        self.repo_path = repo_path or Path.cwd()
        self.config = config or WatchdogConfig()
        self._sessions: dict[str, WorktreeSession] = {}
        self._lock = threading.Lock()
        self._session_counter = 0
        self._event_bus: Any | None = None

        # Persistence
        if persist_path is not None:
            self._persist_path: Path | None = Path(persist_path)
        else:
            self._persist_path = self.repo_path / ".aragora_beads" / "watchdog_sessions.json"

        self._load_persisted_sessions()

    def _persist_sessions(self) -> None:
        """Write all sessions to JSON for crash recovery.

        Called after every state change (register/heartbeat/complete/abandon).
        The caller must NOT hold ``self._lock`` when calling this method.
        """
        if self._persist_path is None:
            return

        with self._lock:
            payload: list[dict[str, Any]] = []
            for session in self._sessions.values():
                payload.append(
                    {
                        "session_id": session.session_id,
                        "branch_name": session.branch_name,
                        "worktree_path": str(session.worktree_path),
                        "track": session.track,
                        "pid": session.pid,
                        "registered_at": session.registered_at,
                        "last_heartbeat": session.last_heartbeat,
                        "heartbeat_count": session.heartbeat_count,
                        "status": session.status,
                    }
                )
            counter = self._session_counter

        data = {
            "version": 1,
            "session_counter": counter,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "sessions": payload,
        }

        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self._persist_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp_path.replace(self._persist_path)
        except OSError as exc:
            logger.warning("watchdog_persist_failed: %s", exc)

    def _load_persisted_sessions(self) -> None:
        """Reload sessions from disk and reconcile PID liveness.

        For each persisted session:
        - If the PID is alive: mark active, refresh last_heartbeat to now.
        - If the PID is dead: mark abandoned.
        - Completed/recovered sessions are preserved as-is.
        """
        if self._persist_path is None or not self._persist_path.exists():
            return

        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning("watchdog_load_failed: %s", exc)
            return

        if not isinstance(data, dict):
            return

        sessions_data = data.get("sessions", [])
        if not isinstance(sessions_data, list):
            return

        now = time.monotonic()
        counter = data.get("session_counter", 0)

        with self._lock:
            for entry in sessions_data:
                if not isinstance(entry, dict):
                    continue
                session_id = entry.get("session_id", "")
                if not session_id:
                    continue

                pid = entry.get("pid")
                status = entry.get("status", "active")

                # For terminal states, preserve as-is
                if status in ("completed", "recovered"):
                    pass
                elif pid is not None and self._is_process_alive(pid):
                    status = "active"
                else:
                    status = "abandoned"

                session = WorktreeSession(
                    session_id=session_id,
                    branch_name=entry.get("branch_name", ""),
                    worktree_path=Path(entry.get("worktree_path", "")),
                    track=entry.get("track", "unknown"),
                    pid=pid,
                    registered_at=entry.get("registered_at", now),
                    last_heartbeat=now if status == "active" else entry.get("last_heartbeat", now),
                    heartbeat_count=entry.get("heartbeat_count", 0),
                    status=status,
                )
                self._sessions[session_id] = session

            if counter > self._session_counter:
                self._session_counter = counter

        logger.info(
            "watchdog_sessions_loaded count=%d from=%s",
            len(sessions_data),
            self._persist_path,
        )

    def _get_event_bus(self) -> Any | None:
        """Lazily create EventBus for cross-worktree events."""
        if self._event_bus is None and self.config.emit_events:
            try:
                from aragora.nomic.event_bus import EventBus

                self._event_bus = EventBus(repo_root=self.repo_path)
            except ImportError:
                logger.debug("EventBus not available for watchdog events")
        return self._event_bus

    def _emit_event(self, event_type: str, track: str, **data: Any) -> None:
        """Emit a watchdog event via the EventBus."""
        bus = self._get_event_bus()
        if bus is not None:
            try:
                bus.publish(
                    event_type=event_type,
                    track=track,
                    data={"source": "worktree_watchdog", **data},
                )
            except (OSError, ValueError) as e:
                logger.debug("Failed to emit watchdog event: %s", e)

    def register_session(
        self,
        branch_name: str,
        worktree_path: Path,
        track: str = "unknown",
        pid: int | None = None,
    ) -> str:
        """Register a new worktree session for monitoring.

        Args:
            branch_name: Git branch name for the worktree.
            worktree_path: Filesystem path to the worktree directory.
            track: Development track (sme, qa, developer, etc.).
            pid: Process ID of the agent working in this worktree.

        Returns:
            A unique session ID for heartbeat and status tracking.
        """
        with self._lock:
            self._session_counter += 1
            session_id = f"wt-{self._session_counter}-{int(time.time())}"

            session = WorktreeSession(
                session_id=session_id,
                branch_name=branch_name,
                worktree_path=worktree_path,
                track=track,
                pid=pid or os.getpid(),
            )
            self._sessions[session_id] = session

        logger.info(
            "watchdog_session_registered id=%s branch=%s track=%s pid=%s",
            session_id,
            branch_name,
            track,
            session.pid,
        )

        self._emit_event(
            "task_claimed",
            track=track,
            session_id=session_id,
            branch_name=branch_name,
        )

        self._persist_sessions()

        return session_id

    def heartbeat(self, session_id: str) -> bool:
        """Record a heartbeat for an active session.

        Args:
            session_id: The session ID returned by register_session().

        Returns:
            True if the heartbeat was recorded, False if session not found.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            session.last_heartbeat = time.monotonic()
            session.heartbeat_count += 1

            # A heartbeat can revive a stalled session
            if session.status == "stalled":
                session.status = "active"
                logger.info(
                    "watchdog_session_revived id=%s branch=%s",
                    session_id,
                    session.branch_name,
                )

        self._persist_sessions()

        return True

    def complete_session(self, session_id: str) -> bool:
        """Mark a session as completed (normal termination).

        Args:
            session_id: The session ID to complete.

        Returns:
            True if the session was found and marked complete.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            session.status = "completed"

        logger.info(
            "watchdog_session_completed id=%s branch=%s heartbeats=%d",
            session_id,
            session.branch_name,
            session.heartbeat_count,
        )

        self._emit_event(
            "task_completed",
            track=session.track,
            session_id=session_id,
            branch_name=session.branch_name,
        )

        self._persist_sessions()

        return True

    def abandon_session(self, session_id: str) -> bool:
        """Mark a session as abandoned explicitly.

        Args:
            session_id: The session ID to mark as abandoned.

        Returns:
            True if the session was found and marked abandoned.
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False

            session.status = "abandoned"

        logger.info(
            "watchdog_session_abandoned id=%s branch=%s",
            session_id,
            session.branch_name,
        )

        self._persist_sessions()

        return True

    def get_session(self, session_id: str) -> WorktreeSession | None:
        """Get a session by ID (thread-safe snapshot)."""
        with self._lock:
            return self._sessions.get(session_id)

    def list_sessions(self) -> list[WorktreeSession]:
        """List all tracked sessions (thread-safe snapshot)."""
        with self._lock:
            return list(self._sessions.values())

    def check_health(self) -> HealthReport:
        """Check health of all tracked sessions.

        Updates session statuses based on heartbeat timing:
        - active: heartbeat within stall_timeout
        - stalled: no heartbeat within stall_timeout
        - abandoned: no heartbeat within abandon_timeout

        Returns:
            HealthReport with session counts and details.
        """
        now = time.monotonic()
        stall_threshold = now - self.config.stall_timeout_seconds
        abandon_threshold = now - self.config.abandon_timeout_seconds

        with self._lock:
            for session in self._sessions.values():
                if session.status in ("completed", "recovered"):
                    continue

                if session.last_heartbeat < abandon_threshold:
                    if session.status != "abandoned":
                        session.status = "abandoned"
                        logger.warning(
                            "watchdog_session_abandoned id=%s branch=%s last_heartbeat_ago=%.0fs",
                            session.session_id,
                            session.branch_name,
                            now - session.last_heartbeat,
                        )
                elif session.last_heartbeat < stall_threshold:
                    if session.status != "stalled":
                        session.status = "stalled"
                        logger.warning(
                            "watchdog_session_stalled id=%s branch=%s "
                            "last_heartbeat_ago=%.0fs pid=%s",
                            session.session_id,
                            session.branch_name,
                            now - session.last_heartbeat,
                            session.pid,
                        )
                else:
                    if session.status == "stalled":
                        session.status = "active"

            # Build report snapshot
            sessions_data = []
            counts = {"active": 0, "stalled": 0, "abandoned": 0, "completed": 0}
            for session in self._sessions.values():
                status = session.status
                counts[status] = counts.get(status, 0) + 1
                sessions_data.append(
                    {
                        "session_id": session.session_id,
                        "branch_name": session.branch_name,
                        "track": session.track,
                        "pid": session.pid,
                        "status": status,
                        "heartbeat_count": session.heartbeat_count,
                        "last_heartbeat_ago_seconds": round(now - session.last_heartbeat, 1),
                        "registered_ago_seconds": round(now - session.registered_at, 1),
                    }
                )

        self._persist_sessions()

        return HealthReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_sessions=len(sessions_data),
            active_sessions=counts.get("active", 0),
            stalled_sessions=counts.get("stalled", 0),
            abandoned_sessions=counts.get("abandoned", 0),
            completed_sessions=counts.get("completed", 0),
            sessions=sessions_data,
        )

    def _is_process_alive(self, pid: int) -> bool:
        """Check if a process is still running."""
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False
        except OSError:
            return False

    def recover_stalled(self) -> list[str]:
        """Recover stalled sessions by killing their processes.

        First runs check_health() to update statuses, then kills
        processes for stalled sessions.

        Returns:
            List of session IDs that were recovered.
        """
        # Update statuses first
        self.check_health()

        recovered: list[str] = []

        with self._lock:
            stalled = [s for s in self._sessions.values() if s.status == "stalled"]

        for session in stalled:
            if not self.config.auto_kill_stalled:
                logger.info(
                    "watchdog_stall_detected id=%s pid=%s (auto_kill disabled)",
                    session.session_id,
                    session.pid,
                )
                continue

            if session.pid is None:
                logger.warning(
                    "watchdog_stall_no_pid id=%s branch=%s",
                    session.session_id,
                    session.branch_name,
                )
                continue

            if not self._is_process_alive(session.pid):
                # Process already dead, just mark as recovered
                with self._lock:
                    session.status = "recovered"
                recovered.append(session.session_id)
                logger.info(
                    "watchdog_stall_process_dead id=%s pid=%s",
                    session.session_id,
                    session.pid,
                )
                continue

            # Send kill signal
            try:
                os.kill(session.pid, self.config.kill_signal)
                logger.warning(
                    "watchdog_stall_killed id=%s pid=%s signal=%s",
                    session.session_id,
                    session.pid,
                    self.config.kill_signal,
                )

                with self._lock:
                    session.status = "recovered"
                recovered.append(session.session_id)

                self._emit_event(
                    "error",
                    track=session.track,
                    session_id=session.session_id,
                    reason="stall_recovered",
                    pid=session.pid,
                )

            except (ProcessLookupError, PermissionError) as e:
                logger.warning(
                    "watchdog_kill_failed id=%s pid=%s: %s",
                    session.session_id,
                    session.pid,
                    e,
                )

        if recovered:
            logger.info("watchdog_recovered count=%d ids=%s", len(recovered), recovered)

        return recovered

    def cleanup_abandoned(self) -> list[str]:
        """Clean up abandoned worktrees.

        Removes git worktrees for sessions that have been abandoned
        (no heartbeat within abandon_timeout and process no longer running).

        Returns:
            List of session IDs whose worktrees were cleaned up.
        """
        import subprocess

        # Update statuses first
        self.check_health()

        cleaned: list[str] = []

        with self._lock:
            abandoned = [s for s in self._sessions.values() if s.status == "abandoned"]

        for session in abandoned:
            # Verify process is truly dead before cleanup
            if session.pid is not None and self._is_process_alive(session.pid):
                logger.info(
                    "watchdog_abandon_skipped id=%s pid=%s (process still alive)",
                    session.session_id,
                    session.pid,
                )
                continue

            if not self.config.auto_cleanup_abandoned:
                logger.info(
                    "watchdog_abandon_detected id=%s (auto_cleanup disabled)",
                    session.session_id,
                )
                continue

            # Remove the worktree via git
            worktree_path = session.worktree_path
            if worktree_path.exists():
                try:
                    result = subprocess.run(  # noqa: S603 -- subprocess with fixed args, no shell
                        ["git", "worktree", "remove", "--force", str(worktree_path)],  # noqa: S607 -- fixed command
                        cwd=self.repo_path,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if result.returncode == 0:
                        logger.info(
                            "watchdog_worktree_removed id=%s path=%s",
                            session.session_id,
                            worktree_path,
                        )
                    else:
                        logger.warning(
                            "watchdog_worktree_remove_failed id=%s: %s",
                            session.session_id,
                            result.stderr.strip(),
                        )
                except OSError as e:
                    logger.warning(
                        "watchdog_worktree_remove_error id=%s: %s",
                        session.session_id,
                        e,
                    )

            cleaned.append(session.session_id)

            # Remove from tracking
            with self._lock:
                self._sessions.pop(session.session_id, None)

            self._emit_event(
                "error",
                track=session.track,
                session_id=session.session_id,
                reason="abandoned_cleanup",
                branch_name=session.branch_name,
            )

        # Prune stale git worktree entries
        if cleaned:
            try:
                subprocess.run(
                    ["git", "worktree", "prune"],  # noqa: S607 -- fixed command
                    cwd=self.repo_path,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                pass

            logger.info("watchdog_cleanup count=%d ids=%s", len(cleaned), cleaned)

        return cleaned

    def unregister_session(self, session_id: str) -> bool:
        """Remove a session from tracking entirely.

        Args:
            session_id: The session ID to unregister.

        Returns:
            True if the session was found and removed.
        """
        with self._lock:
            return self._sessions.pop(session_id, None) is not None


__all__ = [
    "WorktreeWatchdog",
    "WatchdogConfig",
    "WorktreeSession",
    "HealthReport",
]
