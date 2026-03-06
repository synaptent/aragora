"""Shared fleet status and coordination primitives for worktree sessions."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
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


def resolve_repo_root(path_hint: Path) -> Path:
    """Resolve git repo root from any path inside a repository."""
    proc = subprocess.run(
        ["git", "-C", str(path_hint), "rev-parse", "--show-toplevel"],  # noqa: S607 -- fixed command
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return path_hint.resolve()


def _list_git_worktrees(repo_root: Path) -> list[dict[str, str | bool | None]]:
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],  # noqa: S607 -- fixed command
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
        for raw in lock_path.read_text(encoding="utf-8").splitlines():
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


def _count_dirty(worktree_path: Path) -> int:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],  # noqa: S607 -- fixed command
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return 0
    return len([line for line in proc.stdout.splitlines() if line.strip()])


def _ahead_behind(worktree_path: Path, base_branch: str) -> tuple[int | None, int | None]:
    for target in (f"origin/{base_branch}", base_branch):
        proc = subprocess.run(
            ["git", "rev-list", "--left-right", "--count", f"{target}...HEAD"],  # noqa: S607 -- fixed command
            cwd=worktree_path,
            capture_output=True,
            text=True,
            check=False,
        )
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


def build_fleet_rows(repo_root: Path, *, base_branch: str, tail: int) -> list[dict[str, Any]]:
    """Build fleet status rows for all git worktrees."""
    rows: list[dict[str, Any]] = []
    for wt in _list_git_worktrees(repo_root):
        path_text = str(wt.get("path") or "")
        if not path_text:
            continue
        worktree_path = Path(path_text)
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

        pid_raw = lock.get("pid")
        ahead, behind = _ahead_behind(worktree_path, base_branch)
        session_id = str(meta.get("session_id") or worktree_path.name)
        rows.append(
            {
                "session_id": session_id,
                "path": str(worktree_path),
                "branch": str(wt.get("branch") or "(detached)"),
                "detached": bool(wt.get("detached")),
                "has_lock": lock_path.exists(),
                "pid": int(pid_raw) if pid_raw and pid_raw.isdigit() else None,
                "pid_alive": _pid_alive(pid_raw),
                "agent": str(meta.get("agent") or lock.get("agent") or ""),
                "mode": str(meta.get("mode") or lock.get("mode") or ""),
                "dirty_files": _count_dirty(worktree_path),
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
                    if str(c.get("path", "")) == path
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
