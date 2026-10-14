"""Salvage candidate discovery and queue helpers for development coordination."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .dev_coordination import (
    SalvageCandidate,
    SalvageStatus,
    _estimate_salvage_value,
    _json_dump,
    _normalize_claim,
    _parse_worktree_entries,
    _status_paths,
    _utcnow,
)


def list_salvage_candidates(self, statuses: list[str] | None = None) -> list[SalvageCandidate]:
    conn = self._connect()
    try:
        rows = conn.execute("SELECT * FROM salvage_candidates ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()
    items = [SalvageCandidate.from_row(row) for row in rows]
    if statuses is None:
        return items
    allowed = set(statuses)
    return [item for item in items if item.status in allowed]


def upsert_salvage_candidate(
    self,
    *,
    source_kind: str,
    source_ref: str,
    branch: str = "",
    worktree_path: str = "",
    stash_ref: str = "",
    head_sha: str = "",
    changed_paths: list[str] | None = None,
    summary: str = "",
    likely_value: float = 0.0,
    status: SalvageStatus = SalvageStatus.DETECTED,
    metadata: dict[str, Any] | None = None,
) -> SalvageCandidate:
    now = _utcnow().isoformat()
    candidate_id = hashlib.sha1(
        f"{source_kind}:{source_ref}".encode(),
        usedforsecurity=False,
    ).hexdigest()[:12]
    candidate = SalvageCandidate(
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_ref=source_ref,
        branch=branch,
        worktree_path=str(Path(worktree_path).resolve()) if worktree_path else "",
        stash_ref=stash_ref,
        head_sha=head_sha,
        changed_paths=[_normalize_claim(item) for item in changed_paths or [] if str(item).strip()],
        summary=summary,
        likely_value=float(likely_value),
        status=status.value,
        created_at=now,
        updated_at=now,
        metadata=dict(metadata or {}),
    )
    conn = self._connect()
    try:
        conn.execute(
            """
            INSERT INTO salvage_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_kind, source_ref) DO UPDATE SET
                branch = excluded.branch,
                worktree_path = excluded.worktree_path,
                stash_ref = excluded.stash_ref,
                head_sha = excluded.head_sha,
                changed_paths_json = excluded.changed_paths_json,
                summary = excluded.summary,
                likely_value = excluded.likely_value,
                status = excluded.status,
                updated_at = excluded.updated_at,
                metadata_json = excluded.metadata_json
            """,
            (
                candidate.candidate_id,
                candidate.source_kind,
                candidate.source_ref,
                candidate.branch,
                candidate.worktree_path,
                candidate.stash_ref,
                candidate.head_sha,
                _json_dump(candidate.changed_paths),
                candidate.summary,
                candidate.likely_value,
                candidate.status,
                candidate.created_at,
                candidate.updated_at,
                _json_dump(candidate.metadata),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM salvage_candidates WHERE source_kind = ? AND source_ref = ?",
            (source_kind, source_ref),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise RuntimeError("Failed to persist salvage candidate")
    return SalvageCandidate.from_row(row)


def scan_salvage_sources(
    self,
    *,
    include_worktrees: bool = True,
    include_stashes: bool = True,
    max_stashes: int = 25,
) -> list[SalvageCandidate]:
    candidates: list[SalvageCandidate] = []
    if include_worktrees:
        candidates.extend(self._scan_worktrees())
    if include_stashes:
        candidates.extend(self._scan_stashes(max_stashes=max_stashes))
    return candidates


def _scan_worktrees(self) -> list[SalvageCandidate]:
    proc = subprocess.run(
        ["git", "-C", str(self.repo_root), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    candidates: list[SalvageCandidate] = []
    for path, branch in _parse_worktree_entries(proc.stdout):
        if not branch or branch in {"main", "master"}:
            continue
        dirty_proc = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
        ahead_proc = subprocess.run(
            ["git", "-C", str(self.repo_root), "rev-list", "--count", f"origin/main..{branch}"],
            capture_output=True,
            text=True,
            check=False,
        )
        head_proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        ahead = int(ahead_proc.stdout.strip() or "0") if ahead_proc.returncode == 0 else 0
        status_lines = [line for line in dirty_proc.stdout.splitlines() if line.strip()]
        if not status_lines and ahead == 0:
            continue
        changed_paths = _status_paths(status_lines)
        if ahead > 0:
            diff_proc = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo_root),
                    "diff",
                    "--name-only",
                    f"origin/main...{branch}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            changed_paths.extend(
                _normalize_claim(item) for item in diff_proc.stdout.splitlines() if item.strip()
            )
        summary = f"worktree {branch} dirty={bool(status_lines)} ahead={ahead}"
        candidate = self.upsert_salvage_candidate(
            source_kind="worktree",
            source_ref=branch,
            branch=branch,
            worktree_path=str(path),
            head_sha=head_proc.stdout.strip() if head_proc.returncode == 0 else "",
            changed_paths=sorted(set(changed_paths)),
            summary=summary,
            likely_value=_estimate_salvage_value(
                ahead=ahead, changed_paths=changed_paths, dirty=bool(status_lines)
            ),
            metadata={"ahead": ahead, "dirty": bool(status_lines)},
        )
        candidates.append(candidate)
    return candidates


def _scan_stashes(self, *, max_stashes: int = 25) -> list[SalvageCandidate]:
    proc = subprocess.run(
        ["git", "-C", str(self.repo_root), "stash", "list"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    candidates: list[SalvageCandidate] = []
    for line in proc.stdout.splitlines()[:max_stashes]:
        if not line.strip() or ":" not in line:
            continue
        source_ref, summary = line.split(":", 1)
        source_ref = source_ref.strip()
        summary = summary.strip()
        names_proc = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_root),
                "stash",
                "show",
                "--name-only",
                "--include-untracked",
                source_ref,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        changed_paths = [
            _normalize_claim(item) for item in names_proc.stdout.splitlines() if item.strip()
        ]
        if not changed_paths:
            continue
        candidate = self.upsert_salvage_candidate(
            source_kind="stash",
            source_ref=source_ref,
            stash_ref=source_ref,
            changed_paths=changed_paths,
            summary=summary,
            likely_value=_estimate_salvage_value(ahead=0, changed_paths=changed_paths, dirty=True),
            metadata={"summary": summary},
        )
        candidates.append(candidate)
    return candidates
