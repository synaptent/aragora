"""Shared fleet status and coordination primitives for worktree sessions."""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
import uuid

ACTIVE_QUEUE_STATUSES = {"queued", "in_progress", "validating", "integrating"}
MERGE_QUEUE_STATUS_ORDER = {
    "queued": 0,
    "validating": 1,
    "integrating": 2,
    "needs_human": 3,
    "blocked": 4,
    "failed": 5,
    "merged": 6,
}
MERGE_QUEUE_ALLOWED_STATUSES = set(MERGE_QUEUE_STATUS_ORDER)
SUPPORTED_ORCHESTRATORS = {
    "gastown",
    "langchain",
    "crewai",
    "langgraph",
    "autogen",
    "openclaw",
    "nomic",
    "generic",
}
_COORDINATION_DB_BUSY_TIMEOUT_MS = 60_000


def _has_wildcard(pattern: str) -> bool:
    return any(token in pattern for token in ("*", "?", "["))


def _path_matches_claim(path: str, pattern: str) -> bool:
    clean_path = path.strip().strip("/")
    clean_pattern = pattern.strip().strip("/")
    if not clean_path or not clean_pattern:
        return False
    if _has_wildcard(clean_pattern):
        if clean_pattern.endswith("/**"):
            prefix = clean_pattern[:-3].rstrip("/")
            return clean_path == prefix or clean_path.startswith(f"{prefix}/")
        return PurePosixPath(clean_path).match(clean_pattern)
    return clean_path == clean_pattern or clean_path.startswith(f"{clean_pattern}/")


def _claims_overlap(first: str, second: str) -> bool:
    left = first.strip().strip("/")
    right = second.strip().strip("/")
    if not left or not right:
        return False
    if left == right:
        return True
    left_wild = _has_wildcard(left)
    right_wild = _has_wildcard(right)
    if not left_wild and not right_wild:
        return left.startswith(f"{right}/") or right.startswith(f"{left}/")
    if not left_wild:
        return _path_matches_claim(left, right)
    if not right_wild:
        return _path_matches_claim(right, left)
    left_prefix = left.split("*", 1)[0]
    right_prefix = right.split("*", 1)[0]
    if left_prefix and right_prefix:
        return left_prefix.startswith(right_prefix) or right_prefix.startswith(left_prefix)
    return False


def resolve_repo_root(path_hint: Path) -> Path:
    """Resolve git repo root from any path inside a repository."""
    proc = subprocess.run(
        ["git", "-C", str(path_hint), "rev-parse", "--show-toplevel"],  # fixed command
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return path_hint.resolve()


def _list_git_worktrees(repo_root: Path) -> list[dict[str, str | bool | None]]:
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],  # fixed command
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    rows: list[dict[str, str | bool | None]] = []
    current: dict[str, str | bool | None] | None = None
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if not line:
            if current:
                rows.append(current)
            current = None
            continue
        if line.startswith("worktree "):
            if current:
                rows.append(current)
            current = {"path": line[len("worktree ") :], "branch": None, "detached": False}
            continue
        if current is None:
            continue
        if line.startswith("branch refs/heads/"):
            current["branch"] = line[len("branch refs/heads/") :]
            continue
        if line == "detached":
            current["detached"] = True

    if current:
        rows.append(current)
    return rows


def _parse_lock_file(lock_path: Path) -> dict[str, str]:
    if not lock_path.exists():
        return {}
    parsed: dict[str, str] = {}
    try:
        raw_text = lock_path.read_text(encoding="utf-8")
        stripped = raw_text.strip()
        if not stripped:
            return {}
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            for key, value in payload.items():
                if value is None:
                    continue
                parsed[str(key).strip()] = str(value).strip()
            return parsed
        for raw in stripped.splitlines():
            if "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            parsed[key.strip()] = value.strip()
    except OSError:
        return {}
    return parsed


def _tail_file(path: Path, line_count: int) -> list[str]:
    if line_count <= 0 or not path.exists():
        return []
    ring: deque[str] = deque(maxlen=line_count)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                ring.append(line.rstrip("\n"))
    except OSError:
        return []
    return list(ring)


def _pid_alive(raw_pid: str | None) -> bool:
    if not raw_pid:
        return False
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _parse_iso_dt(raw_value: Any) -> datetime | None:
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _git_common_dir(repo_root: Path) -> Path | None:
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return Path(proc.stdout.strip()).resolve()


def _active_lease_session_ids(repo_root: Path) -> set[str]:
    git_common_dir = _git_common_dir(repo_root)
    if git_common_dir is None:
        return set()
    db_path = git_common_dir / "aragora-agent-state" / "dev_coordination.db"
    if not db_path.exists():
        return set()

    now = datetime.now(timezone.utc)
    active_session_ids: set[str] = set()
    try:
        conn = sqlite3.connect(
            db_path,
            timeout=_COORDINATION_DB_BUSY_TIMEOUT_MS / 1000.0,
        )
        try:
            conn.execute(f"PRAGMA busy_timeout={_COORDINATION_DB_BUSY_TIMEOUT_MS}")
            rows = conn.execute(
                "SELECT owner_session_id, expires_at FROM leases WHERE status = ?",
                ("active",),
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return set()

    for owner_session_id, expires_at in rows:
        session_id = str(owner_session_id or "").strip()
        if not session_id:
            continue
        parsed_expiry = _parse_iso_dt(expires_at)
        if parsed_expiry is None or parsed_expiry > now:
            active_session_ids.add(session_id)
    return active_session_ids


def _managed_session_snapshots(repo_root: Path) -> dict[str, dict[str, Any]]:
    managed_root = repo_root / ".worktrees"
    if not managed_root.exists():
        return {}

    snapshots: dict[str, dict[str, Any]] = {}
    for state_path in managed_root.glob("*/state.json"):
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sessions = loaded.get("sessions")
        if not isinstance(sessions, list):
            continue
        for session in sessions:
            if not isinstance(session, dict):
                continue
            session_id = str(session.get("session_id", "")).strip()
            if session_id:
                snapshots[session_id] = session
    return snapshots


def _live_worktree_session_ids(repo_root: Path) -> set[str]:
    """Return live session ids without running git status across every worktree.

    Lease acquisition only needs to know whether a claiming session still has a
    live owning process. Reusing ``build_fleet_rows()`` for that is too
    expensive because it shells out into per-worktree git status/ahead-behind
    probes, which can stall hot claim paths.
    """

    live_session_ids: set[str] = set()
    for wt in _list_git_worktrees(repo_root):
        path_text = str(wt.get("path") or "").strip()
        if not path_text:
            continue
        worktree_path = Path(path_text)
        lock = _parse_lock_file(worktree_path / ".codex_session_active")
        meta: dict[str, Any] = {}
        meta_path = worktree_path / ".codex_session_meta.json"
        if meta_path.exists():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, dict):
                meta = loaded

        session_id = str(
            meta.get("session_id") or lock.get("session_id") or worktree_path.name
        ).strip()
        if not session_id:
            continue
        pid_raw = str(lock.get("pid") or meta.get("pid") or "").strip() or None
        if _pid_alive(pid_raw):
            live_session_ids.add(session_id)
    return live_session_ids


def _count_dirty(worktree_path: Path) -> int:
    if not worktree_path.exists():
        return 0
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],  # fixed command
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return 0
    if proc.returncode != 0:
        return 0
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def _ahead_behind(worktree_path: Path, base_branch: str) -> tuple[int | None, int | None]:
    if not worktree_path.exists():
        return None, None
    for target in (f"origin/{base_branch}", base_branch):
        try:
            proc = subprocess.run(
                ["git", "rev-list", "--left-right", "--count", f"{target}...HEAD"],  # fixed command
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return None, None
        if proc.returncode != 0:
            continue
        parts = proc.stdout.strip().split()
        if len(parts) != 2:
            continue
        try:
            behind = int(parts[0])
            ahead = int(parts[1])
            return ahead, behind
        except ValueError:
            continue
    return None, None


def _latest_activity_iso(paths: list[Path]) -> str | None:
    latest: float | None = None
    for path in paths:
        if not path.exists():
            continue
        try:
            ts = path.stat().st_mtime
        except OSError:
            continue
        latest = ts if latest is None or ts > latest else latest
    if latest is None:
        return None
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def infer_orchestration_pattern(meta: dict[str, Any]) -> str:
    """Infer orchestration flavor used by a session from command/meta fields."""
    if not meta:
        return "generic"

    direct = str(meta.get("orchestrator", "")).strip().lower()
    if direct in SUPPORTED_ORCHESTRATORS:
        return direct

    framework = str(meta.get("framework", "")).strip().lower()
    if framework in SUPPORTED_ORCHESTRATORS:
        return framework

    command = str(meta.get("command", "")).lower()
    args = meta.get("args") or []
    args_text = " ".join(str(x).lower() for x in args if x is not None)
    haystack = f"{command} {args_text}"

    markers: list[tuple[str, tuple[str, ...]]] = [
        ("gastown", ("gastown", "bead", "molecule", "handoff")),
        ("langgraph", ("langgraph",)),
        ("langchain", ("langchain", "lc-")),
        ("crewai", ("crewai", "crew-ai")),
        ("autogen", ("autogen",)),
        ("openclaw", ("openclaw",)),
        ("nomic", ("nomic", "fractal", "sprint_coordinator")),
    ]
    for label, needles in markers:
        if any(needle in haystack for needle in needles):
            return label

    return "generic"


def build_fleet_rows(
    repo_root: Path,
    *,
    base_branch: str,
    tail: int,
    include_git_metrics: bool = True,
) -> list[dict[str, Any]]:
    """Build fleet status rows for all git worktrees."""
    rows: list[dict[str, Any]] = []
    for wt in _list_git_worktrees(repo_root):
        path_text = str(wt.get("path") or "")
        if not path_text:
            continue
        worktree_path = Path(path_text)
        missing = not worktree_path.exists()
        lock_path = worktree_path / ".codex_session_active"
        meta_path = worktree_path / ".codex_session_meta.json"
        log_path = worktree_path / ".codex_session.log"
        lock = _parse_lock_file(lock_path)

        meta: dict[str, Any] = {}
        if meta_path.exists():
            try:
                loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    meta = loaded
            except (OSError, json.JSONDecodeError):
                meta = {}

        pid_raw = str(lock.get("pid") or meta.get("pid") or "").strip() or None
        if include_git_metrics:
            dirty_files = _count_dirty(worktree_path)
            ahead, behind = _ahead_behind(worktree_path, base_branch)
        else:
            dirty_files = None
            ahead, behind = None, None
        session_id = str(meta.get("session_id") or worktree_path.name)
        rows.append(
            {
                "session_id": session_id,
                "path": str(worktree_path),
                "branch": str(wt.get("branch") or "(detached)"),
                "detached": bool(wt.get("detached")),
                "missing": missing,
                "has_lock": lock_path.exists(),
                "pid": int(pid_raw) if pid_raw and pid_raw.isdigit() else None,
                "pid_alive": _pid_alive(pid_raw),
                "agent": str(meta.get("agent") or lock.get("agent") or ""),
                "mode": str(meta.get("mode") or lock.get("mode") or ""),
                "dirty_files": dirty_files,
                "ahead": ahead,
                "behind": behind,
                "meta_path": str(meta_path) if meta_path.exists() else None,
                "log_path": str(log_path) if log_path.exists() else None,
                "last_activity": _latest_activity_iso([log_path, lock_path, meta_path]),
                "log_tail": _tail_file(log_path, tail),
                "orchestration_pattern": infer_orchestration_pattern(meta),
                "meta": meta,
            }
        )
    rows.sort(key=lambda row: str(row.get("path", "")))
    return rows


class FleetCoordinationStore:
    """Persistent ownership + merge-queue state for fleet sessions."""

    def __init__(self, repo_root: Path):
        self.repo_root = resolve_repo_root(repo_root)
        self.path = self.repo_root / ".aragora" / "fleet_coordination.json"
        self.lock_path = self.repo_root / ".aragora" / "fleet_coordination.lock"

    @staticmethod
    def _default_state() -> dict[str, Any]:
        return {"claims": [], "merge_queue": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._default_state()
        if not isinstance(loaded, dict):
            return self._default_state()
        claims = loaded.get("claims")
        queue = loaded.get("merge_queue")
        if not isinstance(claims, list) or not isinstance(queue, list):
            return self._default_state()
        return {"claims": claims, "merge_queue": queue}

    def _save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(self.path)

    def _mutate_state(self, mutator: Any) -> Any:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                state = self._load()
                result = mutator(state)
                self._save(state)
                return result
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _normalize_claim_path(self, path_text: str) -> str:
        raw = path_text.strip()
        if not raw:
            return ""
        candidate = Path(raw)
        if candidate.is_absolute():
            try:
                return candidate.resolve().relative_to(self.repo_root).as_posix()
            except ValueError:
                return candidate.resolve().as_posix()
        return candidate.as_posix().lstrip("./")

    def list_claims(self) -> list[dict[str, Any]]:
        state = self._load()
        claims = [c for c in state["claims"] if isinstance(c, dict)]
        return sorted(
            claims,
            key=lambda row: (
                str(row.get("path", "")),
                str(row.get("session_id", "")),
            ),
        )

    def reap_stale_claims(
        self,
        *,
        stale_threshold_seconds: float = 1800.0,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        threshold_seconds = max(0.0, float(stale_threshold_seconds))
        live_session_ids = _live_worktree_session_ids(self.repo_root)
        active_lease_sessions = _active_lease_session_ids(self.repo_root)
        managed_session_snapshots = _managed_session_snapshots(self.repo_root)

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            claims = [c for c in state["claims"] if isinstance(c, dict)]
            claims_by_session: dict[str, list[dict[str, Any]]] = {}
            for claim in claims:
                session_id = str(claim.get("session_id", "")).strip()
                claims_by_session.setdefault(session_id, []).append(claim)

            stale_sessions: set[str] = set()
            kept_sessions: list[dict[str, Any]] = []
            reaped_sessions: list[dict[str, Any]] = []
            for session_id, session_claims in claims_by_session.items():
                last_updated: datetime | None = None
                for claim in session_claims:
                    claim_ts = _parse_iso_dt(claim.get("updated_at")) or _parse_iso_dt(
                        claim.get("claimed_at")
                    )
                    if claim_ts is None:
                        continue
                    if last_updated is None or claim_ts > last_updated:
                        last_updated = claim_ts

                if session_id in live_session_ids:
                    kept_sessions.append(
                        {
                            "session_id": session_id,
                            "claim_count": len(session_claims),
                            "reason": "live_session",
                        }
                    )
                    continue

                if session_id in active_lease_sessions:
                    kept_sessions.append(
                        {
                            "session_id": session_id,
                            "claim_count": len(session_claims),
                            "reason": "active_lease",
                        }
                    )
                    continue

                snapshot = managed_session_snapshots.get(session_id)
                if snapshot:
                    active_session = bool(snapshot.get("active_session"))
                    tracked_worktree = bool(snapshot.get("tracked_worktree"))
                    lease_status = str(snapshot.get("lease_status", "") or "").strip().lower()
                    if (
                        tracked_worktree
                        and not active_session
                        and lease_status
                        in {
                            "released",
                            "completed",
                            "expired",
                        }
                    ):
                        stale_sessions.add(session_id)
                        reaped_sessions.append(
                            {
                                "session_id": session_id,
                                "claim_count": len(session_claims),
                                "reason": "inactive_managed_session",
                                "lease_status": lease_status,
                                "last_updated_at": last_updated.isoformat()
                                if last_updated
                                else None,
                            }
                        )
                        continue

                if last_updated is not None:
                    age_seconds = max(0.0, (now - last_updated).total_seconds())
                    if age_seconds < threshold_seconds:
                        kept_sessions.append(
                            {
                                "session_id": session_id,
                                "claim_count": len(session_claims),
                                "reason": "within_grace_window",
                                "age_seconds": age_seconds,
                            }
                        )
                        continue
                else:
                    age_seconds = None

                stale_sessions.add(session_id)
                reaped_sessions.append(
                    {
                        "session_id": session_id,
                        "claim_count": len(session_claims),
                        "reason": "stale_claims",
                        "last_updated_at": last_updated.isoformat() if last_updated else None,
                        "age_seconds": age_seconds,
                    }
                )

            if not stale_sessions:
                return {
                    "released": 0,
                    "reaped_sessions": [],
                    "kept_sessions": kept_sessions,
                    "stale_threshold_seconds": threshold_seconds,
                }

            kept_claims = [
                claim
                for claim in claims
                if str(claim.get("session_id", "")).strip() not in stale_sessions
            ]
            released = len(claims) - len(kept_claims)
            state["claims"] = kept_claims
            return {
                "released": released,
                "reaped_sessions": reaped_sessions,
                "kept_sessions": kept_sessions,
                "stale_threshold_seconds": threshold_seconds,
            }

        return self._mutate_state(mutate)

    def claim_paths(
        self,
        *,
        session_id: str,
        paths: list[str],
        branch: str | None = None,
        mode: str = "exclusive",
    ) -> dict[str, Any]:
        if mode not in {"exclusive", "shared"}:
            raise ValueError("mode must be one of: exclusive, shared")
        self.reap_stale_claims()

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            claims = [c for c in state["claims"] if isinstance(c, dict)]
            now = datetime.now(timezone.utc).isoformat()
            normalized = [self._normalize_claim_path(path) for path in paths]
            normalized = sorted({item for item in normalized if item})

            conflicts: list[dict[str, str]] = []
            claimed: list[str] = []
            for path in normalized:
                conflict_rows = [
                    c
                    for c in claims
                    if _claims_overlap(str(c.get("path", "")), path)
                    and str(c.get("session_id", "")) != session_id
                    and ("exclusive" in {str(c.get("mode", "exclusive")), mode})
                ]
                if conflict_rows:
                    for row in conflict_rows:
                        conflicts.append(
                            {
                                "path": path,
                                "session_id": str(row.get("session_id", "")),
                                "branch": str(row.get("branch", "")),
                            }
                        )
                    continue

                existing = next(
                    (
                        c
                        for c in claims
                        if str(c.get("path", "")) == path
                        and str(c.get("session_id", "")) == session_id
                    ),
                    None,
                )
                if existing is not None:
                    existing["updated_at"] = now
                    existing["mode"] = mode
                    if branch:
                        existing["branch"] = branch
                else:
                    claims.append(
                        {
                            "session_id": session_id,
                            "path": path,
                            "branch": branch or "",
                            "mode": mode,
                            "claimed_at": now,
                            "updated_at": now,
                        }
                    )
                claimed.append(path)

            state["claims"] = claims
            return {
                "session_id": session_id,
                "mode": mode,
                "claimed": claimed,
                "conflicts": conflicts,
            }

        return self._mutate_state(mutate)

    def audit_session_paths(
        self,
        *,
        session_id: str,
        paths: list[str],
        branch: str | None = None,
    ) -> dict[str, Any]:
        """Validate that a session owns the provided paths."""
        state = self._load()
        claims = [c for c in state["claims"] if isinstance(c, dict)]
        normalized = [self._normalize_claim_path(path) for path in paths]
        normalized = sorted({item for item in normalized if item})
        owner_claims = [c for c in claims if str(c.get("session_id", "")) == session_id]

        owned: list[str] = []
        unowned: list[str] = []
        conflicts: list[dict[str, str]] = []
        for path in normalized:
            covering_owner_claims = [
                claim for claim in owner_claims if _claims_overlap(str(claim.get("path", "")), path)
            ]
            if covering_owner_claims:
                owned.append(path)
            else:
                unowned.append(path)

            owner_modes = {str(claim.get("mode", "exclusive")) for claim in covering_owner_claims}
            for claim in claims:
                foreign_session = str(claim.get("session_id", ""))
                if foreign_session == session_id:
                    continue
                foreign_path = str(claim.get("path", ""))
                if not _claims_overlap(foreign_path, path):
                    continue
                foreign_mode = str(claim.get("mode", "exclusive"))
                if owner_modes == {"shared"} and foreign_mode == "shared":
                    continue
                conflicts.append(
                    {
                        "path": path,
                        "conflicting_path": foreign_path,
                        "session_id": foreign_session,
                        "branch": str(claim.get("branch", "")),
                        "mode": foreign_mode,
                    }
                )

        return {
            "session_id": session_id,
            "branch": branch or "",
            "paths": normalized,
            "owned_paths": sorted(set(owned)),
            "unowned_paths": sorted(set(unowned)),
            "conflicts": conflicts,
            "ok": not unowned and not conflicts,
        }

    def release_paths(self, *, session_id: str, paths: list[str] | None = None) -> dict[str, Any]:
        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            claims = [c for c in state["claims"] if isinstance(c, dict)]
            path_filter: set[str] | None = None
            if paths:
                normalized = [self._normalize_claim_path(path) for path in paths]
                path_filter = {item for item in normalized if item}

            kept: list[dict[str, Any]] = []
            released = 0
            for claim in claims:
                owner = str(claim.get("session_id", ""))
                path = str(claim.get("path", ""))
                should_release = owner == session_id and (
                    path_filter is None or path in path_filter
                )
                if should_release:
                    released += 1
                    continue
                kept.append(claim)

            state["claims"] = kept
            return {"session_id": session_id, "released": released}

        return self._mutate_state(mutate)

    def enqueue_merge(
        self,
        *,
        session_id: str,
        branch: str,
        priority: int = 50,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not branch.strip():
            raise ValueError("branch is required")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            queue = [q for q in state["merge_queue"] if isinstance(q, dict)]
            normalized_branch = branch.strip()

            for item in queue:
                if (
                    str(item.get("branch", "")) == normalized_branch
                    and str(item.get("status", "queued")) in ACTIVE_QUEUE_STATUSES
                ):
                    return {"queued": False, "item": item, "duplicate": True}

            now = datetime.now(timezone.utc).isoformat()
            row = {
                "id": f"mq-{uuid.uuid4().hex[:12]}",
                "session_id": session_id,
                "branch": normalized_branch,
                "priority": max(0, min(int(priority), 100)),
                "title": title.strip(),
                "status": "queued",
                "created_at": now,
                "updated_at": now,
                "metadata": metadata or {},
            }
            queue.append(row)
            state["merge_queue"] = queue
            return {"queued": True, "item": row, "duplicate": False}

        return self._mutate_state(mutate)

    def claim_next_merge(
        self,
        *,
        worker_session_id: str,
        from_status: str = "queued",
        to_status: str = "validating",
    ) -> dict[str, Any] | None:
        if from_status not in MERGE_QUEUE_ALLOWED_STATUSES:
            raise ValueError(f"unknown merge queue status: {from_status}")
        if to_status not in MERGE_QUEUE_ALLOWED_STATUSES:
            raise ValueError(f"unknown merge queue status: {to_status}")

        def mutate(state: dict[str, Any]) -> dict[str, Any] | None:
            queue = [q for q in state["merge_queue"] if isinstance(q, dict)]
            candidates = [q for q in queue if str(q.get("status", "")) == from_status]
            if not candidates:
                return None
            candidates.sort(
                key=lambda row: (
                    -int(row.get("priority", 0)),
                    str(row.get("created_at", "")),
                )
            )
            chosen_id = str(candidates[0].get("id", ""))
            if not chosen_id:
                return None
            now = datetime.now(timezone.utc).isoformat()
            for item in queue:
                if str(item.get("id", "")) != chosen_id:
                    continue
                item["status"] = to_status
                metadata_obj = item.get("metadata")
                if not isinstance(metadata_obj, dict):
                    metadata_obj = {}
                metadata_obj["worker_session_id"] = worker_session_id
                item["metadata"] = metadata_obj
                item["updated_at"] = now
                state["merge_queue"] = queue
                return item
            return None

        return self._mutate_state(mutate)

    def update_merge_queue_item(
        self,
        *,
        item_id: str,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        title: str | None = None,
        expected_status: str | None = None,
    ) -> dict[str, Any]:
        if status is not None and status not in MERGE_QUEUE_ALLOWED_STATUSES:
            raise ValueError(f"unknown merge queue status: {status}")
        if expected_status is not None and expected_status not in MERGE_QUEUE_ALLOWED_STATUSES:
            raise ValueError(f"unknown merge queue status: {expected_status}")

        def mutate(state: dict[str, Any]) -> dict[str, Any]:
            queue = [q for q in state["merge_queue"] if isinstance(q, dict)]
            now = datetime.now(timezone.utc).isoformat()
            for item in queue:
                if str(item.get("id", "")) != item_id:
                    continue
                if expected_status is not None and str(item.get("status", "")) != expected_status:
                    raise KeyError(
                        f"Merge queue item {item_id} is no longer in status {expected_status}"
                    )
                if status is not None:
                    item["status"] = status
                if title is not None:
                    item["title"] = title.strip()
                if metadata:
                    existing_metadata = item.get("metadata")
                    if not isinstance(existing_metadata, dict):
                        existing_metadata = {}
                    existing_metadata.update(metadata)
                    item["metadata"] = existing_metadata
                item["updated_at"] = now
                state["merge_queue"] = queue
                return item
            raise KeyError(f"Unknown merge queue item: {item_id}")

        return self._mutate_state(mutate)

    def list_merge_queue(self, status: str | None = None) -> list[dict[str, Any]]:
        state = self._load()
        queue = [q for q in state["merge_queue"] if isinstance(q, dict)]
        if status:
            queue = [q for q in queue if str(q.get("status", "")) == status]
        queue.sort(
            key=lambda row: (
                MERGE_QUEUE_STATUS_ORDER.get(str(row.get("status", "queued")), 99),
                -int(row.get("priority", 0)),
                str(row.get("created_at", "")),
            )
        )
        return queue
