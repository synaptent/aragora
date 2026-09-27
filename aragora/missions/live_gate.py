"""Live FleetGate adapter for Aragora mission dispatch.

The adapter keeps the existing policy helpers as the source of read truth, then
uses one exact-head, non-admin GitHub CLI merge call when dispatch is explicitly
running in an auto-drain path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .dispatch import GateVerdict
from .state import Feature

Runner = Callable[[list[str], Path], str]


class LiveBossLoopGate:
    """Thin live binding for :class:`aragora.missions.dispatch.FleetGate`."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        repo_slug: str = "synaptent/aragora",
        base: str = "origin/main",
        runner: Runner | None = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.repo_slug = repo_slug
        self.base = base
        self.runner = runner or _run
        self._metadata_by_branch: dict[str, dict[str, Any]] = {}

    def branch_for(self, feature: Feature) -> str:
        metadata = dict(feature.metadata)
        branch = str(metadata.get("branch") or f"mission/{feature.id}")
        self._metadata_by_branch[branch] = metadata
        return branch

    def already_merged(self, branch: str) -> bool:
        metadata = self._metadata_by_branch.get(branch, {})
        pr = metadata.get("pr")
        if pr is not None:
            payload = self._run_json(
                [
                    "gh",
                    "pr",
                    "view",
                    str(pr),
                    "--repo",
                    self.repo_slug,
                    "--json",
                    "state,mergedAt,headRefOid,headRefName",
                ]
            )
            if str(payload.get("state") or "").upper() == "MERGED" or payload.get("mergedAt"):
                pr_branch = str(payload.get("headRefName") or "").strip()
                if pr_branch == branch:
                    return True
                try:
                    branch_head = self.head_of(branch)
                except RuntimeError:
                    return bool(pr_branch) and pr_branch == branch
                pr_head = str(payload.get("headRefOid") or "").strip()
                return bool(pr_head) and pr_head == branch_head
        # `git branch --merged base` lists any branch whose tip is REACHABLE
        # from base — including a tip EQUAL to base, which is exactly what a
        # freshly materialized branch looks like (#8766 claude P1: every
        # decomposed child instantly "already merged" with zero work done).
        # A branch with no commits beyond base has no work that could have
        # merged: fail closed toward doing the work (the merge gate still
        # prevents any double-merge).
        try:
            if self.head_of(branch) == self.head_of(self.base):
                return False
        except RuntimeError:
            pass  # unresolvable ref: fall through to the reachability check
        output = self.runner(
            ["git", "branch", "--merged", self.base, "--list", branch], self.repo_root
        )
        return bool(output.strip())

    def head_of(self, branch: str) -> str:
        return self.runner(
            ["git", "rev-parse", "--verify", "--end-of-options", branch],
            self.repo_root,
        ).strip()

    def foreign_commits(
        self, branch: str, base: str, allowed_prefixes: tuple[str, ...]
    ) -> list[str]:
        output = self.runner(
            ["git", "log", "--format=%H%x09%s", f"{base}..{branch}"],
            self.repo_root,
        )
        if not output.strip():
            return []
        subject_prefixes = _subject_prefixes(allowed_prefixes)
        allowed_paths = _metadata_paths(self._metadata_by_branch.get(branch, {}).get("paths"))
        foreign: list[str] = []
        for line in output.splitlines():
            commit, _, subject = line.partition("\t")
            if not subject.startswith(subject_prefixes):
                foreign.append(f"{commit} {subject}".strip())
                continue
            changed_paths = _changed_paths_for_commit(self.runner, self.repo_root, commit)
            if not allowed_paths:
                foreign.append(f"{commit} {subject} (missing mission path allowlist)".strip())
                continue
            unexpected = [
                path for path in changed_paths if not _path_is_allowed(path, allowed_paths)
            ]
            if unexpected:
                sample = ", ".join(unexpected[:3])
                foreign.append(f"{commit} {subject} (unexpected paths: {sample})".strip())
        return foreign

    def tier_of(self, feature: Feature) -> int:
        pr = feature.metadata.get("pr")
        if pr is not None:
            pr_number = _int_or_default(pr, -1)
            if pr_number < 0:
                return 3
            branch = self.branch_for(feature)
            try:
                head = self.head_of(branch)
            except RuntimeError:
                return 3
            payload = self._run_json(
                [
                    sys.executable,
                    "-m",
                    "aragora.cli.main",
                    "review-queue",
                    "merge-packet",
                    "--pr",
                    str(pr_number),
                    "--repo",
                    self.repo_slug,
                    "--json",
                ]
            )
            entry = _find_packet_entry(payload, pr_number, head)
            if entry is not None:
                return _int_or_default(entry.get("tier"), 3)
            return 3
        raw_tier = feature.metadata.get("tier")
        if raw_tier is not None:
            return _int_or_default(raw_tier, 3)
        return 3

    def collect_evidence(self, branch: str, head: str) -> GateVerdict:
        metadata = self._metadata_by_branch.get(branch, {})
        pr = metadata.get("pr")
        if pr is None:
            return GateVerdict(satisfied=False, tier=3, dissent=["feature metadata has no PR"])

        payload = self._run_json(
            [
                sys.executable,
                "-m",
                "aragora.cli.main",
                "review-queue",
                "merge-packet",
                "--pr",
                str(pr),
                "--repo",
                self.repo_slug,
                "--json",
            ]
        )
        entry = _find_packet_entry(payload, int(pr), head)
        if entry is None:
            return GateVerdict(
                satisfied=False,
                tier=3,
                dissent=[f"merge-packet had no exact-head entry for PR {pr} at {head}"],
            )

        quorum = entry.get("model_review_quorum")
        if not isinstance(quorum, dict):
            quorum = entry
        tier = _int_or_default(quorum.get("tier"), _int_or_default(entry.get("tier"), 3))
        verdict = str(quorum.get("verdict") or entry.get("verdict") or "").lower()
        reasons = quorum.get("reasons") or entry.get("reasons") or []
        if isinstance(reasons, str):
            reasons = [reasons]
        satisfied = _packet_allows_admin_squash(entry, quorum, verdict)
        return GateVerdict(satisfied=satisfied, tier=tier, dissent=list(reasons))

    def merge_head_bound(self, branch: str, head: str) -> bool:
        metadata = self._metadata_by_branch.get(branch, {})
        pr = metadata.get("pr")
        if pr is None:
            return False
        verdict = self.collect_evidence(branch, head)
        if not verdict.satisfied:
            return False
        if verdict.tier >= 3:
            return False
        self.runner(
            [
                "gh",
                "pr",
                "merge",
                str(pr),
                "--repo",
                self.repo_slug,
                "--squash",
                "--match-head-commit",
                head,
            ],
            self.repo_root,
        )
        payload = self._run_json(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--repo",
                self.repo_slug,
                "--json",
                "state,mergedAt",
            ]
        )
        return str(payload.get("state") or "").upper() == "MERGED" or bool(payload.get("mergedAt"))

    def _run_json(self, cmd: list[str]) -> dict[str, Any]:
        output = self.runner(cmd, self.repo_root)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return {"error": "unparseable JSON", "raw": output}
        return payload if isinstance(payload, dict) else {"items": payload}


def _run(cmd: list[str], cwd: Path) -> str:
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{cmd[0]} timed out after {exc.timeout}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or f"{cmd[0]} exited {proc.returncode}").strip()
        )
    return proc.stdout


def _find_packet_entry(payload: dict[str, Any], pr: int, head: str) -> dict[str, Any] | None:
    candidates: list[Any] = []
    for key in ("ready", "not_ready", "items", "entries"):
        raw = payload.get(key)
        if isinstance(raw, list):
            candidates.extend(raw)
    if not candidates and any(k in payload for k in ("pr_number", "number", "head_sha")):
        candidates.append(payload)

    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        entry_pr = _int_or_default(entry.get("pr_number", entry.get("number")), -1)
        entry_head = entry.get("head_sha") or entry.get("headRefOid") or entry.get("head")
        if entry_pr == pr and entry_head == head:
            return entry
    return None


def _subject_prefixes(allowed_prefixes: tuple[str, ...]) -> tuple[str, ...]:
    prefixes: set[str] = set(allowed_prefixes)
    for prefix in allowed_prefixes:
        if prefix.endswith("/"):
            stem = prefix[:-1]
            prefixes.add(f"{stem}:")
            prefixes.update(
                {
                    f"feat({stem}):",
                    f"fix({stem}):",
                    f"docs({stem}):",
                    f"test({stem}):",
                    f"refactor({stem}):",
                    f"style({stem}):",
                    f"chore({stem}):",
                }
            )
    return tuple(sorted(prefixes))


def _metadata_paths(raw: Any) -> tuple[str, ...]:
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        values = [str(item) for item in raw]
    else:
        return ()
    paths = []
    for value in values:
        normalized = value.strip().lstrip("./")
        if normalized:
            paths.append(normalized.rstrip("/") + ("/" if value.rstrip().endswith("/") else ""))
    return tuple(paths)


def _changed_paths_for_commit(runner: Runner, repo_root: Path, commit: str) -> list[str]:
    output = runner(["git", "show", "--format=", "--name-only", commit], repo_root)
    return [line.strip().lstrip("./") for line in output.splitlines() if line.strip()]


def _path_is_allowed(path: str, allowed_paths: tuple[str, ...]) -> bool:
    normalized = path.strip().lstrip("./")
    for allowed in allowed_paths:
        clean_allowed = allowed.strip().lstrip("./")
        if not clean_allowed:
            continue
        if clean_allowed.endswith("/"):
            if normalized.startswith(clean_allowed):
                return True
        elif normalized == clean_allowed or normalized.startswith(f"{clean_allowed}/"):
            return True
    return False


def _packet_allows_admin_squash(
    entry: dict[str, Any], quorum: dict[str, Any], verdict: str
) -> bool:
    status = str(_packet_value(entry, quorum, "status") or "").lower()
    if status != "satisfied" or verdict != "admin_squash_allowed":
        return False
    if _packet_value(entry, quorum, "admin_squash_allowed") is not True:
        return False
    for blocker in (
        "requires_human_risk_settlement",
        "requires_human_preapproval",
        "unresolved_dissent",
    ):
        if _packet_value(entry, quorum, blocker) is not False:
            return False
    return True


def _packet_value(entry: dict[str, Any], quorum: dict[str, Any], key: str) -> Any:
    if key in entry:
        return entry.get(key)
    return quorum.get(key)


def _find_packet_entry_for_pr(payload: dict[str, Any], pr: int) -> dict[str, Any] | None:
    candidates: list[Any] = []
    for key in ("ready", "not_ready", "items", "entries"):
        raw = payload.get(key)
        if isinstance(raw, list):
            candidates.extend(raw)
    if not candidates and any(k in payload for k in ("pr_number", "number", "head_sha")):
        candidates.append(payload)

    for entry in candidates:
        if not isinstance(entry, dict):
            continue
        if _int_or_default(entry.get("pr_number", entry.get("number")), -1) == pr:
            return entry
    return None


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
