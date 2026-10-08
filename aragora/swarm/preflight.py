from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from aragora.swarm.credential_envelope import CredentialEnvelope
from aragora.swarm.env_utils import git_safe_env
from aragora.swarm.mission import GateEvaluation, GateType, GateVerdict, MissionContextPolicy
from aragora.swarm.terminal_truth import TerminalClass, classify_preflight_failure
from aragora.swarm.worker_contract import WorkerContract, checksum_contract_payload
from aragora.swarm.worker_launcher import LaunchConfig, WorkerLauncher, WorkerProcess
from aragora.utils.async_utils import run_async
from aragora.utils.error_sanitizer import sanitize_error

_PREFLIGHT_RECEIPT_SCHEMA_VERSION = 1
_PREFLIGHT_TTL_SECONDS = {
    "scratch": 86400,
    "remote_publish": 3600,
}
_PR_URL_RE = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/(?P<number>\d+)")


@dataclass(slots=True)
class PreflightResult:
    repo_root: str
    base_ref: str
    branch: str
    worktree_path: str
    agent: str
    published: bool
    pull_request_created: bool
    pull_request_closed: bool
    cleanup_worktree_removed: bool
    cleanup_branch_removed: bool
    dispatch_gate: dict[str, Any] = field(default_factory=dict)
    worker: dict[str, Any] = field(default_factory=dict)
    passed: bool = False
    checks: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0
    envelope: CredentialEnvelope | None = None
    branch_lease_id: str = ""
    branch_lease_owner_session_id: str = ""
    branch_lease_work_id: str = ""
    branch_lease_released: bool = False
    publication_base_sha: str = ""
    remote_branch_seeded: bool = False
    cleanup_remote_branch_removed: bool = False

    @property
    def failure_terminal_class(self) -> TerminalClass | None:
        return classify_preflight_failure(
            passed=self.passed,
            checks=list(self.checks),
            dispatch_gate=dict(self.dispatch_gate),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "base_ref": self.base_ref,
            "branch": self.branch,
            "worktree_path": self.worktree_path,
            "agent": self.agent,
            "passed": self.passed,
            "checks": list(self.checks),
            "duration_seconds": self.duration_seconds,
            "envelope": self.envelope.to_dict() if self.envelope else None,
            "published": self.published,
            "pull_request_created": self.pull_request_created,
            "pull_request_closed": self.pull_request_closed,
            "cleanup_worktree_removed": self.cleanup_worktree_removed,
            "cleanup_branch_removed": self.cleanup_branch_removed,
            "dispatch_gate": dict(self.dispatch_gate),
            "worker": dict(self.worker),
            "branch_lease_id": self.branch_lease_id,
            "branch_lease_owner_session_id": self.branch_lease_owner_session_id,
            "branch_lease_work_id": self.branch_lease_work_id,
            "branch_lease_released": self.branch_lease_released,
            "publication_base_sha": self.publication_base_sha,
            "remote_branch_seeded": self.remote_branch_seeded,
            "cleanup_remote_branch_removed": self.cleanup_remote_branch_removed,
        }


@dataclass(slots=True)
class _BranchWriteLease:
    store: Any
    lease_id: str
    owner_session_id: str
    work_id: str


class PreflightOperationError(RuntimeError):
    """Structured failure for an expected preflight infrastructure operation."""

    def __init__(
        self,
        *,
        stage: str,
        detail: str,
        command: list[str] | None = None,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(detail)
        self.stage = stage
        self.detail = detail
        self.command = list(command or [])
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def to_check(self) -> dict[str, Any]:
        return {
            "name": self.stage,
            "passed": False,
            "detail": self.detail,
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass(slots=True)
class PreflightReceipt:
    receipt_id: str
    envelope_seal: str
    repo_root: str
    check_type: str
    started_at: str
    finished_at: str
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    schema_version: int = _PREFLIGHT_RECEIPT_SCHEMA_VERSION
    cache_key: str = ""
    ttl_seconds: int = 0
    expires_at: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def failure_terminal_class(self) -> TerminalClass | None:
        return classify_preflight_failure(
            passed=self.passed,
            checks=list(self.checks),
            dispatch_gate=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "envelope_seal": self.envelope_seal,
            "repo_root": self.repo_root,
            "check_type": self.check_type,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "passed": self.passed,
            "checks": [dict(item) for item in self.checks],
            "cache_key": self.cache_key,
            "ttl_seconds": self.ttl_seconds,
            "expires_at": self.expires_at,
            "artifacts": dict(self.artifacts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreflightReceipt":
        return cls(
            schema_version=int(data.get("schema_version", _PREFLIGHT_RECEIPT_SCHEMA_VERSION) or 0),
            receipt_id=str(data.get("receipt_id", "") or ""),
            envelope_seal=str(data.get("envelope_seal", "") or ""),
            repo_root=str(data.get("repo_root", "") or ""),
            check_type=str(data.get("check_type", "") or ""),
            started_at=str(data.get("started_at", "") or ""),
            finished_at=str(data.get("finished_at", "") or ""),
            passed=bool(data.get("passed", False)),
            checks=[dict(item) for item in list(data.get("checks", []) or [])],
            cache_key=str(data.get("cache_key", "") or ""),
            ttl_seconds=int(data.get("ttl_seconds", 0) or 0),
            expires_at=str(data.get("expires_at", "") or ""),
            artifacts=dict(data.get("artifacts", {}) or {}),
        )


def _write_stdout_line(text: str) -> None:
    sys.stdout.write(f"{text}\n")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_isoformat_utc(value: str) -> datetime:
    return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).astimezone(timezone.utc)


def _validate_check_type(check_type: str) -> str:
    normalized = str(check_type or "").strip()
    if normalized not in _PREFLIGHT_TTL_SECONDS:
        raise ValueError(f"Unsupported preflight check type: {normalized or '<empty>'}")
    return normalized


def _receipt_token() -> str:
    return uuid.uuid4().hex[:8]


def _preflight_receipt_id(check_type: str, *, now: datetime | None = None) -> str:
    stamp = _isoformat_utc(now or _utc_now()).replace(":", "").replace("-", "")
    return f"preflight-{check_type}-{stamp}-{_receipt_token()}"


def _validation_branch_name(check_type: str, *, now: datetime | None = None) -> str:
    normalized = _validate_check_type(check_type)
    stamp = (now or _utc_now()).astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")
    branch_scope = "remote" if normalized == "remote_publish" else "scratch"
    return f"preflight/{branch_scope}/{stamp}-{_receipt_token()}"


def _validation_worktree_path(repo_root: Path, branch: str) -> Path:
    return repo_root / ".worktrees" / f"preflight-{branch.replace('/', '-')}"


def _scratch_validation_file(worktree_path: Path) -> Path:
    return worktree_path / "scratch" / "preflight_receipt_check.txt"


def _check_detail(stdout: str, stderr: str, *, default: str) -> str:
    detail = (stderr or stdout or "").strip()
    return detail or default


def _append_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append(
        {
            "name": str(name).strip(),
            "passed": bool(passed),
            "detail": str(detail or "").strip() or ("ok" if passed else "failed"),
        }
    )


def _run_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str] | None:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _append_check(checks, name=name, passed=False, detail=str(exc))
        return None

    _append_check(
        checks,
        name=name,
        passed=result.returncode == 0,
        detail=_check_detail(
            result.stdout,
            result.stderr,
            default="ok" if result.returncode == 0 else f"Command failed: {' '.join(cmd)}",
        ),
    )
    return result


def _record_file_write_check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    path: Path,
    content: str,
) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        _append_check(checks, name=name, passed=False, detail=str(exc))
        return False
    _append_check(checks, name=name, passed=True, detail="ok")
    return True


def _preflight_receipt_dir(repo_root: Path) -> Path:
    return repo_root / ".aragora" / "receipts" / "preflight"


def _preflight_cache_key(
    repo_root: Path,
    envelope: CredentialEnvelope,
    check_type: str,
    *,
    base_ref: str = "",
) -> str:
    normalized = _validate_check_type(check_type)
    target_ref = ""
    if normalized == "remote_publish":
        target_ref = str(base_ref or "main").strip() or "main"
    payload = json.dumps(
        {
            "schema_version": _PREFLIGHT_RECEIPT_SCHEMA_VERSION,
            "repo_root": str(repo_root.resolve()),
            "envelope_seal": envelope.preflight_cache_seal(),
            "check_type": normalized,
            "target_ref": target_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _preflight_receipt_path(
    repo_root: Path,
    *,
    check_type: str,
    cache_key: str,
) -> Path:
    return _preflight_receipt_dir(repo_root) / f"{check_type}-{cache_key}.json"


def _receipt_is_cacheable(
    receipt: PreflightReceipt,
    *,
    repo_root: Path,
    envelope: CredentialEnvelope,
    check_type: str,
    base_ref: str = "",
    now: datetime | None = None,
) -> bool:
    normalized = _validate_check_type(check_type)
    if receipt.schema_version != _PREFLIGHT_RECEIPT_SCHEMA_VERSION:
        return False
    if not receipt.passed:
        return False
    if str(receipt.repo_root or "") != str(repo_root.resolve()):
        return False
    if receipt.check_type != normalized:
        return False
    if receipt.envelope_seal != envelope.preflight_cache_seal():
        return False
    expected_cache_key = _preflight_cache_key(
        repo_root,
        envelope,
        normalized,
        base_ref=base_ref,
    )
    if receipt.cache_key != expected_cache_key:
        return False
    if normalized == "remote_publish":
        expected_target_ref = str(base_ref or "main").strip() or "main"
        receipt_target_ref = str(receipt.artifacts.get("target_ref") or "").strip()
        if receipt_target_ref != expected_target_ref:
            return False
    if any(not bool(item.get("passed")) for item in receipt.checks):
        return False
    try:
        expires_at = _parse_isoformat_utc(receipt.expires_at)
    except ValueError:
        return False
    return (now or _utc_now()) < expires_at


def _load_cached_preflight_receipt(
    repo_root: Path,
    envelope: CredentialEnvelope,
    check_type: str,
    *,
    base_ref: str = "",
    now: datetime | None = None,
) -> PreflightReceipt | None:
    normalized = _validate_check_type(check_type)
    cache_key = _preflight_cache_key(
        repo_root,
        envelope,
        normalized,
        base_ref=base_ref,
    )
    path = _preflight_receipt_path(repo_root, check_type=normalized, cache_key=cache_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        receipt = PreflightReceipt.from_dict(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not _receipt_is_cacheable(
        receipt,
        repo_root=repo_root,
        envelope=envelope,
        check_type=normalized,
        base_ref=base_ref,
        now=now,
    ):
        return None
    return receipt


def _save_preflight_receipt(repo_root: Path, receipt: PreflightReceipt) -> Path:
    directory = _preflight_receipt_dir(repo_root)
    directory.mkdir(parents=True, exist_ok=True)
    path = _preflight_receipt_path(
        repo_root,
        check_type=receipt.check_type,
        cache_key=receipt.cache_key,
    )
    path.write_text(json.dumps(receipt.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def _finalize_preflight_receipt(
    *,
    repo_root: Path,
    envelope: CredentialEnvelope,
    check_type: str,
    base_ref: str = "",
    started_at: datetime,
    finished_at: datetime,
    checks: list[dict[str, Any]],
    artifacts: dict[str, Any],
) -> PreflightReceipt:
    normalized = _validate_check_type(check_type)
    ttl_seconds = _PREFLIGHT_TTL_SECONDS[normalized]
    passed = all(bool(item.get("passed")) for item in checks)
    cache_key = _preflight_cache_key(
        repo_root,
        envelope,
        normalized,
        base_ref=base_ref,
    )
    final_artifacts = dict(artifacts)
    if normalized == "remote_publish":
        final_artifacts["target_ref"] = str(base_ref or "main").strip() or "main"
    return PreflightReceipt(
        schema_version=_PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        receipt_id=_preflight_receipt_id(normalized, now=finished_at),
        envelope_seal=envelope.preflight_cache_seal(),
        repo_root=str(repo_root.resolve()),
        check_type=normalized,
        started_at=_isoformat_utc(started_at),
        finished_at=_isoformat_utc(finished_at),
        passed=passed,
        checks=[dict(item) for item in checks],
        cache_key=cache_key,
        ttl_seconds=ttl_seconds,
        expires_at=_isoformat_utc(finished_at + timedelta(seconds=ttl_seconds)),
        artifacts=final_artifacts,
    )


def _parse_pr_create_output(stdout: str, stderr: str) -> tuple[int | None, str]:
    text = "\n".join(part for part in [stdout, stderr] if part).strip()
    match = _PR_URL_RE.search(text)
    if match is None:
        return None, ""
    return int(match.group("number")), match.group(0)


def _find_open_pr_by_branch(
    *,
    cwd: Path,
    branch: str,
    base_ref: str,
    env: Mapping[str, str] | None = None,
) -> tuple[int | None, str]:
    result = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,url,isDraft,baseRefName",
        ],
        cwd=str(cwd),
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        return None, ""
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return None, ""
    if not isinstance(payload, list):
        return None, ""

    matches: list[tuple[int, str]] = []
    normalized_base_ref = str(base_ref or "main").strip() or "main"
    for item in payload:
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        url = str(item.get("url") or "").strip()
        item_base_ref = str(item.get("baseRefName") or "").strip()
        if not isinstance(number, int) or not url:
            continue
        if item_base_ref and item_base_ref != normalized_base_ref:
            continue
        matches.append((number, url))
    if len(matches) == 1:
        return matches[0]
    return None, ""


def _command_stage(cmd: list[str]) -> str:
    if cmd[:3] == ["git", "worktree", "add"]:
        return "git_worktree_add"
    if cmd[:3] == ["git", "push", "origin"]:
        return "git_push"
    if cmd[:3] == ["gh", "pr", "create"]:
        return "gh_pr_create"
    if cmd[:3] == ["gh", "pr", "close"]:
        return "gh_pr_close"
    if cmd[:4] == ["gh", "api", "--method", "POST"] and any(
        part.endswith("/git/refs") for part in cmd
    ):
        return "gh_remote_branch_seed"
    if cmd[:4] == ["gh", "api", "--method", "DELETE"] and any(
        "/git/refs/heads/" in part for part in cmd
    ):
        return "gh_remote_branch_delete"
    return "_".join(cmd[:2]) if cmd else "preflight_command"


def _operation_failure_detail(
    *,
    cmd: list[str],
    returncode: int | None,
    stdout: str,
    stderr: str,
) -> tuple[str, str, str]:
    sanitized_stdout = sanitize_error((stdout or "").strip(), max_length=2000)
    sanitized_stderr = sanitize_error((stderr or "").strip(), max_length=2000)
    parts = [f"command={' '.join(cmd)}"]
    if returncode is not None:
        parts.append(f"returncode={returncode}")
    if sanitized_stdout:
        parts.append(f"stdout:\n{sanitized_stdout}")
    if sanitized_stderr:
        parts.append(f"stderr:\n{sanitized_stderr}")
    detail = "\n".join(parts)
    return detail, sanitized_stdout, sanitized_stderr


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        detail, stdout, stderr = _operation_failure_detail(
            cmd=cmd,
            returncode=None,
            stdout="",
            stderr=str(exc),
        )
        raise PreflightOperationError(
            stage=_command_stage(cmd),
            detail=detail,
            command=cmd,
            stdout=stdout,
            stderr=stderr,
        ) from exc
    if result.returncode != 0:
        detail, stdout, stderr = _operation_failure_detail(
            cmd=cmd,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        raise PreflightOperationError(
            stage=_command_stage(cmd),
            detail=detail,
            command=cmd,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )


def _resolve_ref_sha(repo_root: Path, ref: str) -> str:
    cmd = ["git", "rev-parse", "--verify", f"{ref}^{{commit}}"]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env=git_safe_env(),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PreflightOperationError(
            stage="git_base_ref_resolve",
            detail=sanitize_error(str(exc), max_length=4000),
            command=cmd,
        ) from exc
    sha = (result.stdout or "").strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-fA-F]{40,64}", sha) is None:
        detail, stdout, stderr = _operation_failure_detail(
            cmd=cmd,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
        raise PreflightOperationError(
            stage="git_base_ref_resolve",
            detail=detail,
            command=cmd,
            returncode=result.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    return sha.lower()


def _seed_remote_branch_at_base(repo_root: Path, branch: str, base_sha: str) -> None:
    _run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            "repos/synaptent/aragora/git/refs",
            "-f",
            f"ref=refs/heads/{branch}",
            "-f",
            f"sha={base_sha}",
        ],
        cwd=repo_root,
    )


def _delete_seeded_remote_branch(repo_root: Path, branch: str) -> None:
    _run(
        [
            "gh",
            "api",
            "--method",
            "DELETE",
            f"repos/synaptent/aragora/git/refs/heads/{branch}",
        ],
        cwd=repo_root,
    )


def _claim_branch_write_lease(
    *,
    repo_root: Path,
    branch: str,
    worktree_path: Path,
    agent: str,
) -> _BranchWriteLease:
    from aragora.nomic.dev_coordination import DevCoordinationStore

    owner_session_id = str(os.environ.get("ARAGORA_SESSION_ID") or "").strip()
    if not owner_session_id:
        owner_session_id = f"swarm-preflight:{os.getpid()}:{branch}"
    work_id = f"branch:{branch}"
    try:
        store = DevCoordinationStore(repo_root=repo_root)
        lease = store.claim_lease(
            task_id=work_id,
            title=f"Remote publication preflight for {branch}",
            owner_agent=f"swarm-preflight:{agent}",
            owner_session_id=owner_session_id,
            branch=branch,
            worktree_path=str(worktree_path),
            allowed_globs=[f".aragora/branch-locks/{branch}"],
            claimed_paths=[],
            expected_tests=[],
            ttl_hours=1.0,
            metadata={
                "claimed_via": "swarm_preflight",
                "work_id": work_id,
            },
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        detail = sanitize_error(str(exc), max_length=4000)
        raise PreflightOperationError(
            stage="branch_write_lease_claim",
            detail=detail or f"Failed to claim branch write lease for {branch}",
        ) from exc
    return _BranchWriteLease(
        store=store,
        lease_id=lease.lease_id,
        owner_session_id=owner_session_id,
        work_id=work_id,
    )


def _release_branch_write_lease(claim: _BranchWriteLease) -> None:
    try:
        claim.store.release_lease(claim.lease_id)
    except (OSError, RuntimeError, sqlite3.Error, ValueError, KeyError) as exc:
        detail = sanitize_error(str(exc), max_length=4000)
        raise PreflightOperationError(
            stage="branch_write_lease_release",
            detail=detail or f"Failed to release branch write lease {claim.lease_id}",
        ) from exc


def _check_git_clean(repo_root: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        env=git_safe_env(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {
            "name": "git_status_clean",
            "passed": False,
            "detail": detail or "git status failed",
        }
    output = (result.stdout or "").strip()
    return {
        "name": "git_status_clean",
        "passed": output == "",
        "detail": "clean" if output == "" else "worktree has uncommitted changes",
    }


def _check_can_create_branch(repo_root: Path) -> dict[str, Any]:
    branch = f"preflight/check-{int(time.time())}"
    result = subprocess.run(
        ["git", "branch", branch],
        cwd=str(repo_root),
        env=git_safe_env(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {
            "name": "git_can_create_branch",
            "passed": False,
            "detail": detail or "branch create failed",
        }
    subprocess.run(
        ["git", "branch", "-D", branch],
        cwd=str(repo_root),
        env=git_safe_env(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return {"name": "git_can_create_branch", "passed": True, "detail": "ok"}


def _check_can_commit(repo_root: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "commit", "--allow-empty", "--dry-run", "-m", "preflight check"],
        cwd=str(repo_root),
        env=git_safe_env(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {
            "name": "git_can_commit",
            "passed": False,
            "detail": detail or "commit dry-run failed",
        }
    return {"name": "git_can_commit", "passed": True, "detail": "ok"}


def _check_tool_available(name: str, cmd: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return {"name": name, "passed": False, "detail": detail or "command failed"}
    return {"name": name, "passed": True, "detail": (result.stdout or "").strip() or "ok"}


def _runner_command(envelope: CredentialEnvelope) -> list[str] | None:
    command_path = str(envelope.runner.command_path or "").strip()
    if command_path:
        return [command_path, "--version"]
    profile = str(envelope.runner.profile or "").lower()
    if "codex" in profile:
        return ["codex", "--version"]
    if "claude" in profile:
        return ["claude", "--version"]
    return None


def run_preflight_checks(
    envelope: CredentialEnvelope,
    *,
    repo_root: Path,
) -> PreflightResult:
    start = time.monotonic()
    checks: list[dict[str, Any]] = [
        _check_git_clean(repo_root),
        _check_can_create_branch(repo_root),
        _check_can_commit(repo_root),
        _check_tool_available("ruff_available", ["python3", "-m", "ruff", "--version"]),
        _check_tool_available("pytest_available", ["python3", "-m", "pytest", "--version"]),
    ]
    runner_cmd = _runner_command(envelope)
    if runner_cmd:
        checks.append(_check_tool_available("runner_cli", runner_cmd))
    else:
        checks.append(
            {
                "name": "runner_cli",
                "passed": False,
                "detail": "runner command not configured",
            }
        )
    passed = all(check["passed"] for check in checks)
    duration = time.monotonic() - start
    return PreflightResult(
        passed=passed,
        checks=checks,
        duration_seconds=duration,
        envelope=envelope,
        repo_root=str(repo_root),
        base_ref="",
        branch="",
        worktree_path=str(repo_root),
        agent=envelope.runner.profile or "unknown",
        published=False,
        pull_request_created=False,
        pull_request_closed=False,
        cleanup_worktree_removed=False,
        cleanup_branch_removed=False,
        dispatch_gate={},
        worker={},
    )


def run_scratch_validation_receipt(
    *,
    repo_root: Path,
    envelope: CredentialEnvelope,
    force_refresh: bool = False,
    env: Mapping[str, str] | None = None,
) -> PreflightReceipt:
    resolved_repo_root = repo_root.resolve()
    normalized_base_ref = "main"
    git_env = git_safe_env(env)
    if not force_refresh:
        cached = _load_cached_preflight_receipt(resolved_repo_root, envelope, "scratch")
        if cached is not None:
            return cached

    started_at = _utc_now()
    branch = _validation_branch_name("scratch", now=started_at)
    worktree_path = _validation_worktree_path(resolved_repo_root, branch)
    artifacts: dict[str, Any] = {
        "branch": branch,
        "worktree_path": str(worktree_path),
        "target_ref": normalized_base_ref,
        "draft_pr_number": None,
        "draft_pr_url": "",
    }
    checks: list[dict[str, Any]] = []
    worktree_created = False
    scratch_file = _scratch_validation_file(worktree_path)

    try:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        worktree_result = _run_check(
            checks,
            name="git_worktree_add",
            cmd=[
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                normalized_base_ref,
            ],
            cwd=resolved_repo_root,
            env=git_env,
        )
        if worktree_result is not None and worktree_result.returncode == 0:
            worktree_created = True
            _append_check(checks, name="git_branch_create", passed=True, detail="ok")

        if worktree_created and _record_file_write_check(
            checks,
            name="scratch_file_write",
            path=scratch_file,
            content="preflight scratch validation\n",
        ):
            add_result = _run_check(
                checks,
                name="git_add",
                cmd=["git", "add", str(scratch_file.relative_to(worktree_path))],
                cwd=worktree_path,
                env=git_env,
            )
            if add_result is not None and add_result.returncode == 0:
                _run_check(
                    checks,
                    name="git_commit",
                    cmd=["git", "commit", "-m", "chore: preflight scratch validation"],
                    cwd=worktree_path,
                    env=git_env,
                )
    finally:
        if worktree_created:
            _run_check(
                checks,
                name="cleanup_worktree_remove",
                cmd=["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=resolved_repo_root,
                env=git_env,
            )
            _run_check(
                checks,
                name="cleanup_branch_delete",
                cmd=["git", "branch", "-D", branch],
                cwd=resolved_repo_root,
                env=git_env,
            )

    finished_at = _utc_now()
    receipt = _finalize_preflight_receipt(
        repo_root=resolved_repo_root,
        envelope=envelope,
        check_type="scratch",
        base_ref="",
        started_at=started_at,
        finished_at=finished_at,
        checks=checks,
        artifacts=artifacts,
    )
    _save_preflight_receipt(resolved_repo_root, receipt)
    return receipt


def run_remote_publish_validation_receipt(
    *,
    repo_root: Path,
    envelope: CredentialEnvelope,
    base_ref: str = "main",
    force_refresh: bool = False,
    env: Mapping[str, str] | None = None,
) -> PreflightReceipt:
    resolved_repo_root = repo_root.resolve()
    normalized_base_ref = str(base_ref or "main").strip() or "main"
    git_env = git_safe_env(env)
    command_env = dict(env) if env is not None else None
    if not force_refresh:
        cached = _load_cached_preflight_receipt(
            resolved_repo_root,
            envelope,
            "remote_publish",
            base_ref=normalized_base_ref,
        )
        if cached is not None:
            return cached

    started_at = _utc_now()
    branch = _validation_branch_name("remote_publish", now=started_at)
    worktree_path = _validation_worktree_path(resolved_repo_root, branch)
    artifacts: dict[str, Any] = {
        "branch": branch,
        "worktree_path": str(worktree_path),
        "target_ref": normalized_base_ref,
        "draft_pr_number": None,
        "draft_pr_url": "",
    }
    checks: list[dict[str, Any]] = []
    worktree_created = False
    pushed = False
    draft_created = False
    unresolved_remote_pr_state = False
    draft_close_succeeded = False
    scratch_file = _scratch_validation_file(worktree_path)

    try:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        worktree_result = _run_check(
            checks,
            name="git_worktree_add",
            cmd=["git", "worktree", "add", "-b", branch, str(worktree_path), "HEAD"],
            cwd=resolved_repo_root,
            env=git_env,
        )
        if worktree_result is not None and worktree_result.returncode == 0:
            worktree_created = True
            _append_check(checks, name="git_branch_create", passed=True, detail="ok")

        if worktree_created and _record_file_write_check(
            checks,
            name="scratch_file_write",
            path=scratch_file,
            content="preflight remote publish validation\n",
        ):
            add_result = _run_check(
                checks,
                name="git_add",
                cmd=["git", "add", str(scratch_file.relative_to(worktree_path))],
                cwd=worktree_path,
                env=git_env,
            )
            if add_result is not None and add_result.returncode == 0:
                commit_result = _run_check(
                    checks,
                    name="git_commit",
                    cmd=["git", "commit", "-m", "chore: preflight remote publish validation"],
                    cwd=worktree_path,
                    env=git_env,
                )
                if commit_result is not None and commit_result.returncode == 0:
                    push_result = _run_check(
                        checks,
                        name="git_push",
                        cmd=["git", "push", "origin", "HEAD"],
                        cwd=worktree_path,
                        env=git_env,
                    )
                    pushed = push_result is not None and push_result.returncode == 0
                    if pushed:
                        pr_result = _run_check(
                            checks,
                            name="gh_pr_create_draft",
                            cmd=[
                                "gh",
                                "pr",
                                "create",
                                "--base",
                                normalized_base_ref,
                                "--head",
                                branch,
                                "--title",
                                "[preflight] remote publish validation",
                                "--body",
                                "Internal remote publish preflight validation.",
                                "--draft",
                            ],
                            cwd=worktree_path,
                            env=command_env,
                        )
                        if pr_result is not None and pr_result.returncode == 0:
                            pr_number, pr_url = _parse_pr_create_output(
                                pr_result.stdout,
                                pr_result.stderr,
                            )
                            if pr_number is None or not pr_url:
                                pr_number, pr_url = _find_open_pr_by_branch(
                                    cwd=worktree_path if worktree_created else resolved_repo_root,
                                    branch=branch,
                                    base_ref=normalized_base_ref,
                                    env=command_env,
                                )
                            if pr_number is None or not pr_url:
                                _append_check(
                                    checks,
                                    name="gh_pr_capture",
                                    passed=False,
                                    detail=(
                                        "Draft PR create output did not include a parseable PR URL "
                                        "and fallback lookup by branch did not find an open PR."
                                    ),
                                )
                            else:
                                draft_created = True
                                artifacts["draft_pr_number"] = pr_number
                                artifacts["draft_pr_url"] = pr_url
                                _append_check(
                                    checks,
                                    name="gh_pr_capture",
                                    passed=True,
                                    detail=pr_url,
                                )
    finally:
        if pushed and not draft_created:
            pr_number, pr_url = _find_open_pr_by_branch(
                cwd=worktree_path if worktree_created else resolved_repo_root,
                branch=branch,
                base_ref=normalized_base_ref,
                env=command_env,
            )
            if pr_number is not None and pr_url:
                draft_created = True
                artifacts["draft_pr_number"] = pr_number
                artifacts["draft_pr_url"] = pr_url
                _append_check(
                    checks,
                    name="gh_pr_capture_recovery",
                    passed=True,
                    detail=pr_url,
                )
            else:
                unresolved_remote_pr_state = True

        if draft_created:
            close_target = str(artifacts.get("draft_pr_number") or branch)
            close_result = _run_check(
                checks,
                name="gh_pr_close",
                cmd=[
                    "gh",
                    "pr",
                    "close",
                    close_target,
                    "--comment",
                    "Preflight complete - closing.",
                ],
                cwd=worktree_path if worktree_created else resolved_repo_root,
                env=command_env,
            )
            draft_close_succeeded = close_result is not None and close_result.returncode == 0
        elif pushed and unresolved_remote_pr_state:
            _append_check(
                checks,
                name="gh_pr_close",
                passed=False,
                detail=(
                    "unable to confirm whether a draft PR exists after gh pr create; "
                    "remote branch retained for manual cleanup"
                ),
            )
        elif pushed:
            _append_check(
                checks,
                name="gh_pr_close",
                passed=True,
                detail="skipped (draft PR not created)",
            )

        if (
            pushed
            and not unresolved_remote_pr_state
            and (not draft_created or draft_close_succeeded)
        ):
            _run_check(
                checks,
                name="cleanup_remote_branch_delete",
                cmd=["git", "push", "origin", "--delete", branch],
                cwd=worktree_path if worktree_created else resolved_repo_root,
                env=git_env,
            )
        elif pushed and draft_created and not draft_close_succeeded:
            _append_check(
                checks,
                name="cleanup_remote_branch_delete",
                passed=False,
                detail="skipped because draft PR close failed; remote branch retained for manual cleanup",
            )
        elif pushed:
            _append_check(
                checks,
                name="cleanup_remote_branch_delete",
                passed=False,
                detail=("skipped because draft PR state could not be confirmed after gh pr create"),
            )
        else:
            _append_check(
                checks,
                name="cleanup_remote_branch_delete",
                passed=True,
                detail="skipped (branch was not pushed)",
            )

        if worktree_created:
            _run_check(
                checks,
                name="cleanup_worktree_remove",
                cmd=["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=resolved_repo_root,
                env=git_env,
            )
            _run_check(
                checks,
                name="cleanup_branch_delete",
                cmd=["git", "branch", "-D", branch],
                cwd=resolved_repo_root,
                env=git_env,
            )

    finished_at = _utc_now()
    receipt = _finalize_preflight_receipt(
        repo_root=resolved_repo_root,
        envelope=envelope,
        check_type="remote_publish",
        base_ref=normalized_base_ref,
        started_at=started_at,
        finished_at=finished_at,
        checks=checks,
        artifacts=artifacts,
    )
    _save_preflight_receipt(resolved_repo_root, receipt)
    return receipt


def _dispatch_gate_detail(dispatch_gate: dict[str, Any]) -> str:
    gate = dict(dispatch_gate or {})
    parts: list[str] = []
    verdict = str(gate.get("verdict", "") or "").strip()
    if verdict:
        parts.append(f"verdict={verdict}")
    failure_classes = [
        str(item).strip() for item in list(gate.get("failure_classes") or []) if str(item).strip()
    ]
    if failure_classes:
        parts.append(f"failure_classes={','.join(failure_classes)}")
    notes = str(gate.get("notes", "") or "").strip()
    if notes:
        parts.append(notes)
    return " | ".join(parts) or "dispatch gate unavailable"


def _checks_from_contract_preflight_result(
    result: PreflightResult,
    *,
    expected_contract_checksum: str,
    skip_publication: bool,
) -> list[dict[str, Any]]:
    checks = [dict(item) for item in list(result.checks or [])]
    worker = dict(result.worker or {})
    worker_checksum = str(worker.get("worker_contract_checksum", "") or "").strip()
    checks.append(
        {
            "name": "dispatch_gate",
            "passed": str(result.dispatch_gate.get("verdict", "")).strip()
            == GateVerdict.PASS.value,
            "detail": _dispatch_gate_detail(result.dispatch_gate),
        }
    )
    checks.append(
        {
            "name": "worker_contract_checksum",
            "passed": bool(worker_checksum) and worker_checksum == expected_contract_checksum,
            "detail": worker_checksum or "missing worker_contract_checksum",
        }
    )
    commit_shas = [
        str(item).strip() for item in list(worker.get("commit_shas") or []) if str(item).strip()
    ]
    checks.append(
        {
            "name": "worker_commit",
            "passed": bool(commit_shas),
            "detail": ",".join(commit_shas) if commit_shas else "worker produced no commit",
        }
    )
    if not skip_publication:
        checks.append(
            {
                "name": "publication_flow",
                "passed": bool(result.published)
                and bool(result.pull_request_created)
                and bool(result.pull_request_closed),
                "detail": (
                    f"published={result.published} "
                    f"pr_created={result.pull_request_created} "
                    f"pr_closed={result.pull_request_closed}"
                ),
            }
        )
    return checks


def _save_contract_preflight_receipt(
    *,
    result: PreflightResult,
    repo_root: Path,
    envelope: CredentialEnvelope,
    base_ref: str,
    skip_publication: bool,
    contract_path: Path,
    expected_contract_checksum: str,
) -> PreflightReceipt:
    resolved_repo_root = repo_root.resolve()
    normalized_base_ref = str(base_ref or "main").strip() or "main"
    normalized_contract_path = contract_path.expanduser().resolve()
    normalized_check_type = "scratch" if skip_publication else "remote_publish"
    finished_at = _utc_now()
    started_at = finished_at - timedelta(seconds=max(float(result.duration_seconds or 0.0), 0.0))
    checks = _checks_from_contract_preflight_result(
        result,
        expected_contract_checksum=expected_contract_checksum,
        skip_publication=skip_publication,
    )
    artifacts: dict[str, Any] = {
        "target_ref": normalized_base_ref,
        "contract_path": str(normalized_contract_path),
        "skip_publication": bool(skip_publication),
        "expected_contract_checksum": expected_contract_checksum,
        "branch": str(result.branch or "").strip(),
        "worktree_path": str(result.worktree_path or "").strip(),
        "agent": str(result.agent or "").strip(),
        "published": bool(result.published),
        "pull_request_created": bool(result.pull_request_created),
        "pull_request_closed": bool(result.pull_request_closed),
        "cleanup_worktree_removed": bool(result.cleanup_worktree_removed),
        "cleanup_branch_removed": bool(result.cleanup_branch_removed),
        "dispatch_gate": dict(result.dispatch_gate),
        "worker_contract_checksum": str(
            (result.worker or {}).get("worker_contract_checksum", "") or ""
        ).strip(),
        "commit_shas": [
            str(item).strip()
            for item in list((result.worker or {}).get("commit_shas") or [])
            if str(item).strip()
        ],
        "branch_lease_id": str(result.branch_lease_id or "").strip(),
        "branch_lease_owner_session_id": str(result.branch_lease_owner_session_id or "").strip(),
        "branch_lease_work_id": str(result.branch_lease_work_id or "").strip(),
        "branch_lease_released": bool(result.branch_lease_released),
        "publication_base_sha": str(result.publication_base_sha or "").strip(),
        "remote_branch_seeded": bool(result.remote_branch_seeded),
        "cleanup_remote_branch_removed": bool(result.cleanup_remote_branch_removed),
    }
    receipt = _finalize_preflight_receipt(
        repo_root=resolved_repo_root,
        envelope=envelope,
        check_type=normalized_check_type,
        base_ref=normalized_base_ref,
        started_at=started_at,
        finished_at=finished_at,
        checks=checks,
        artifacts=artifacts,
    )
    _save_preflight_receipt(resolved_repo_root, receipt)
    return receipt


def run_contract_preflight_receipt(
    *,
    repo_root: Path,
    agent: str | None = None,
    base_ref: str = "main",
    skip_publication: bool = False,
    contract_path: Path,
    envelope: CredentialEnvelope | None = None,
) -> PreflightReceipt:
    resolved_repo_root = repo_root.resolve()
    normalized_base_ref = str(base_ref or "main").strip() or "main"
    normalized_contract_path = contract_path.expanduser().resolve()
    normalized_check_type = "scratch" if skip_publication else "remote_publish"
    resolved_envelope = envelope or CredentialEnvelope.from_environment(os.environ)
    started_at = _utc_now()
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {
        "target_ref": normalized_base_ref,
        "contract_path": str(normalized_contract_path),
        "skip_publication": bool(skip_publication),
        "expected_contract_checksum": "",
    }
    try:
        _, expected_contract_checksum = _load_contract_payload(normalized_contract_path)
        artifacts["expected_contract_checksum"] = expected_contract_checksum
    except Exception as exc:
        checks.append({"name": "contract_payload", "passed": False, "detail": str(exc)})
        finished_at = _utc_now()
        receipt = _finalize_preflight_receipt(
            repo_root=resolved_repo_root,
            envelope=resolved_envelope,
            check_type=normalized_check_type,
            base_ref=normalized_base_ref,
            started_at=started_at,
            finished_at=finished_at,
            checks=checks,
            artifacts=artifacts,
        )
        _save_preflight_receipt(resolved_repo_root, receipt)
        return receipt

    try:
        result = run_preflight(
            repo_root=resolved_repo_root,
            agent=agent,
            base_ref=normalized_base_ref,
            skip_publication=skip_publication,
            contract_path=normalized_contract_path,
        )
    except Exception as exc:
        checks.append({"name": "contract_preflight", "passed": False, "detail": str(exc)})
    else:
        checks.extend(
            _checks_from_contract_preflight_result(
                result,
                expected_contract_checksum=expected_contract_checksum,
                skip_publication=skip_publication,
            )
        )
        artifacts.update(
            {
                "branch": str(result.branch or "").strip(),
                "worktree_path": str(result.worktree_path or "").strip(),
                "agent": str(result.agent or "").strip(),
                "published": bool(result.published),
                "pull_request_created": bool(result.pull_request_created),
                "pull_request_closed": bool(result.pull_request_closed),
                "cleanup_worktree_removed": bool(result.cleanup_worktree_removed),
                "cleanup_branch_removed": bool(result.cleanup_branch_removed),
                "dispatch_gate": dict(result.dispatch_gate),
                "worker_contract_checksum": str(
                    (result.worker or {}).get("worker_contract_checksum", "") or ""
                ).strip(),
                "commit_shas": [
                    str(item).strip()
                    for item in list((result.worker or {}).get("commit_shas") or [])
                    if str(item).strip()
                ],
                "branch_lease_id": str(result.branch_lease_id or "").strip(),
                "branch_lease_owner_session_id": str(
                    result.branch_lease_owner_session_id or ""
                ).strip(),
                "branch_lease_work_id": str(result.branch_lease_work_id or "").strip(),
                "branch_lease_released": bool(result.branch_lease_released),
            }
        )

    if "branch" in artifacts:
        receipt = _save_contract_preflight_receipt(
            result=result,
            repo_root=resolved_repo_root,
            envelope=resolved_envelope,
            base_ref=normalized_base_ref,
            skip_publication=skip_publication,
            contract_path=normalized_contract_path,
            expected_contract_checksum=expected_contract_checksum,
        )
        return receipt

    finished_at = _utc_now()
    receipt = _finalize_preflight_receipt(
        repo_root=resolved_repo_root,
        envelope=resolved_envelope,
        check_type=normalized_check_type,
        base_ref=normalized_base_ref,
        started_at=started_at,
        finished_at=finished_at,
        checks=checks,
        artifacts=artifacts,
    )
    _save_preflight_receipt(resolved_repo_root, receipt)
    return receipt


def evaluate_preflight_receipt_gate(
    receipt: PreflightReceipt | None,
    *,
    repo_root: Path,
    envelope: CredentialEnvelope,
    check_type: str,
    base_ref: str = "main",
    expected_contract_checksum: str = "",
    now: datetime | None = None,
) -> GateEvaluation:
    normalized = _validate_check_type(check_type)
    current_time = now or _utc_now()
    normalized_base_ref = str(base_ref or "main").strip() or "main"
    resolved_repo_root = repo_root.resolve()
    required_evidence = ["preflight_receipt"]
    if receipt is None:
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=["receipt_missing"],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: receipt missing.",
        )
    if str(receipt.check_type or "").strip() != normalized:
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=["receipt_check_type_mismatch"],
            required_evidence=required_evidence,
            notes=(
                "Preflight admission blocked: receipt check type "
                f"`{receipt.check_type}` does not match expected `{normalized}`."
            ),
        )
    if str(receipt.repo_root or "") != str(resolved_repo_root):
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=["receipt_repo_root_mismatch"],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: receipt repo root does not match the current repo.",
        )
    if str(receipt.envelope_seal or "").strip() != envelope.preflight_cache_seal():
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=["receipt_envelope_mismatch"],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: credential envelope no longer matches the receipt.",
        )
    if _parse_isoformat_utc(receipt.expires_at) <= current_time:
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=["receipt_expired"],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: receipt expired.",
        )
    if normalized == "remote_publish":
        target_ref = str(receipt.artifacts.get("target_ref", "") or "").strip() or "main"
        if target_ref != normalized_base_ref:
            return GateEvaluation(
                gate_type=GateType.DISPATCH_READY.value,
                verdict=GateVerdict.BLOCKED.value,
                failure_classes=["receipt_target_ref_mismatch"],
                required_evidence=required_evidence,
                notes=(
                    "Preflight admission blocked: receipt target ref "
                    f"`{target_ref}` does not match expected `{normalized_base_ref}`."
                ),
            )
    expected_cache_key = _preflight_cache_key(
        resolved_repo_root,
        envelope,
        normalized,
        base_ref=normalized_base_ref,
    )
    if str(receipt.cache_key or "").strip() != expected_cache_key:
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=["receipt_cache_key_mismatch"],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: receipt cache key does not match the current repo state.",
        )
    if expected_contract_checksum:
        actual_contract_checksum = str(
            receipt.artifacts.get("expected_contract_checksum", "") or ""
        ).strip()
        if actual_contract_checksum != expected_contract_checksum:
            return GateEvaluation(
                gate_type=GateType.DISPATCH_READY.value,
                verdict=GateVerdict.BLOCKED.value,
                failure_classes=["receipt_contract_mismatch"],
                required_evidence=required_evidence,
                notes="Preflight admission blocked: receipt contract checksum mismatch.",
            )
    if not receipt.passed:
        failure_class = receipt.failure_terminal_class
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=[
                failure_class.value if failure_class is not None else "preflight_failed"
            ],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: receipt recorded a failed preflight.",
        )
    failed_checks = [
        dict(item)
        for item in list(receipt.checks)
        if isinstance(item, dict) and not bool(item.get("passed", False))
    ]
    if failed_checks:
        failure_class = classify_preflight_failure(
            passed=False,
            checks=failed_checks,
            dispatch_gate=None,
        )
        return GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=[
                failure_class.value if failure_class is not None else "preflight_failed"
            ],
            required_evidence=required_evidence,
            notes="Preflight admission blocked: receipt checks recorded a failed preflight.",
        )
    return GateEvaluation(
        gate_type=GateType.DISPATCH_READY.value,
        verdict=GateVerdict.PASS.value,
        required_evidence=required_evidence,
        notes=f"Preflight receipt verified: {receipt.receipt_id}",
    )


def _branch_name() -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"preflight/{stamp}"


def _worktree_path(repo_root: Path, branch: str) -> Path:
    return repo_root / ".worktrees" / f"preflight-{branch.replace('/', '-')}"


def _preflight_filename(contract: WorkerContract | None = None) -> str:
    return "scratch/preflight_worker_check.txt"


def _work_order(agent: str, *, contract: WorkerContract | None = None) -> dict[str, object]:
    filename = _preflight_filename(contract)
    mission_id = "mission-rs-worker-contract-preflight"
    stage_id = "stage-dispatch-ready-preflight"
    assertion_ids = ["RS-PREFLIGHT-ASSERT-1"]
    evidence_expectations = [
        "worker_contract",
        "worker_contract_checksum",
        "receipt",
    ]
    if contract is not None:
        policy = dict(contract.mission_context_policy or {})
        required_sources = [
            str(item).strip()
            for item in list(policy.get("required_sources", []) or [])
            if str(item).strip()
        ]
        mission_id = str(contract.mission_id or "").strip()
        stage_id = str(contract.stage_id or "").strip()
        assertion_ids = [
            str(item).strip() for item in list(contract.assertion_ids or []) if str(item).strip()
        ]
        evidence_expectations = [
            str(item).strip()
            for item in list(contract.evidence_expectations or [])
            if str(item).strip()
        ] or evidence_expectations
    description = (
        f"Create a file named `{filename}` with a single line "
        "timestamp. Commit it with message `chore: preflight worker check`. "
        "Do not modify any other files."
    )
    if contract is not None and required_sources:
        quoted_sources = ", ".join(f"`{item}`" for item in required_sources)
        description = (
            f"Read the required source files {quoted_sources} to confirm access, then "
            + description
        )

    return {
        "work_order_id": f"preflight-{int(time.time())}",
        "target_agent": agent,
        "mission_id": mission_id,
        "stage_id": stage_id,
        "assertion_ids": assertion_ids,
        "evidence_expectations": evidence_expectations,
        "mission_context_policies": (
            {"worker": dict(contract.mission_context_policy or {})}
            if contract is not None
            else None
        ),
        "title": "Contract-aware preflight worker check"
        if contract is not None
        else "Preflight worker check",
        "description": description,
        "file_scope": [filename],
        "expected_tests": [],
        "metadata": {"admin_approved": True},
    }


def _preflight_launch_config(
    *,
    agent: str,
    contract: WorkerContract | None,
    claude_profile: str | None = None,
) -> LaunchConfig:
    """Build the preflight-owned ``LaunchConfig``.

    Threads ``expected_contract.profile`` (when non-default, for claude
    workers) into ``LaunchConfig.claude_profile`` so that the launcher's
    rebuilt worker-contract matches the preview-persisted contract.

    Pre-v1.2 this inheritance was missing, which caused two drift sources
    that together tripped ``_enforce_expected_contract()``:

    * ``profile`` field: preview "max-07" vs launcher "default"
    * ``env_checksum`` field: preview env has ``ARAGORA_CLAUDE_PROFILE``,
      launcher env did not.

    See ``docs/plans/2026-04-17-worker-drift-diagnosis.md``.
    ``claude_profile`` lets preview call-sites model the same preflight-owned
    launch config before a preview contract exists.  It uses the same
    ``"default"`` sentinel handling as the contract-derived path.
    """
    launcher_profile: str | None = None
    if str(agent or "").strip().lower() == "claude":
        raw_profile = str(claude_profile or "").strip()
        if not raw_profile and contract is not None:
            raw_profile = str(contract.profile or "").strip()
        if raw_profile and raw_profile.lower() != "default":
            launcher_profile = raw_profile
    return LaunchConfig(
        allow_claude_dangerously_skip_permissions=True,
        allow_codex_full_auto=True,
        # Preflight already provisions and owns the disposable worktree.
        # Wrapping the worker in codex_session.sh tries to create another
        # managed worktree on top of it and fails before any commit happens.
        use_managed_session_script=False,
        require_explicit_approval=False,
        claude_profile=launcher_profile,
    )


async def _run_worker(
    *,
    repo_root: Path,
    worktree_path: Path,
    branch: str,
    agent: str,
    contract: WorkerContract | None = None,
) -> WorkerProcess:
    config = _preflight_launch_config(agent=agent, contract=contract)
    launcher = WorkerLauncher(config=config)
    work_order = _work_order(agent, contract=contract)
    return await launcher.launch_and_wait(
        work_order,
        worktree_path=str(worktree_path),
        branch=branch,
        timeout=900.0,
    )


def evaluate_preflight_dispatch_gate(worker: WorkerProcess) -> dict[str, Any]:
    contract = dict(worker.worker_contract or {})
    mission_id = str(contract.get("mission_id", "") or "").strip()
    stage_id = str(contract.get("stage_id", "") or "").strip()
    assertion_ids = [
        str(item).strip() for item in contract.get("assertion_ids", []) if str(item).strip()
    ]
    failure_classes: list[str] = []
    notes: list[str] = []

    if not contract:
        failure_classes.append("contract_missing")
        notes.append("Preflight worker did not emit a worker contract.")
    if not worker.worker_contract_checksum:
        failure_classes.append("contract_missing")
        notes.append("Preflight worker did not emit a worker contract checksum.")
    if contract and worker.worker_contract_checksum:
        checksum = checksum_contract_payload(contract)
        if checksum != worker.worker_contract_checksum:
            failure_classes.append("contract_missing")
            notes.append("Worker contract checksum does not match the contract payload.")

    policy = MissionContextPolicy.from_dict(contract.get("mission_context_policy"))
    if not policy.is_resolvable():
        failure_classes.append("context_policy_unresolved")
        notes.append("Worker mission context policy is missing or not enforceable.")

    verdict = GateVerdict.PASS.value if not failure_classes else GateVerdict.BLOCKED.value
    gate = GateEvaluation(
        gate_type=GateType.DISPATCH_READY.value,
        verdict=verdict,
        mission_id=mission_id,
        stage_id=stage_id,
        assertion_ids=assertion_ids,
        failure_classes=failure_classes,
        repair_eligible=any(
            failure in {"contract_missing", "context_policy_unresolved"}
            for failure in failure_classes
        ),
        required_evidence=[
            "worker_contract",
            "worker_contract_checksum",
            "mission_context_policy",
        ],
        notes=" ".join(notes).strip(),
    )
    return gate.to_dict()


def _validate_worker_contract(worker: WorkerProcess) -> dict[str, Any]:
    if not worker.worker_contract:
        raise RuntimeError("Preflight worker did not emit a worker contract.")
    if not worker.worker_contract_checksum:
        raise RuntimeError("Preflight worker did not emit a worker contract checksum.")
    checksum = checksum_contract_payload(worker.worker_contract)
    if checksum != worker.worker_contract_checksum:
        raise RuntimeError(
            "Preflight worker emitted a worker contract checksum that does not match the contract payload."
        )
    gate = evaluate_preflight_dispatch_gate(worker)
    if str(gate.get("verdict", "")).strip() != GateVerdict.PASS.value:
        raise RuntimeError(str(gate.get("notes") or "Preflight dispatch gate failed."))
    return gate


def _load_contract_payload(contract_path: Path) -> tuple[WorkerContract, str]:
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    worker_contract_payload: Any = payload
    expected_checksum = ""
    if isinstance(payload, dict) and isinstance(payload.get("worker_contract"), dict):
        worker_contract_payload = payload.get("worker_contract")
        expected_checksum = str(payload.get("worker_contract_checksum", "") or "").strip()
    if not isinstance(worker_contract_payload, dict):
        raise RuntimeError("Worker contract file must contain a JSON object payload.")
    contract = WorkerContract.from_dict(worker_contract_payload)
    contract_checksum = contract.checksum()
    if expected_checksum and expected_checksum != contract_checksum:
        raise RuntimeError("Worker contract file checksum does not match the contract payload.")
    if not contract.admission_check():
        raise RuntimeError("Worker contract file failed dispatch admission check.")
    return contract, expected_checksum or contract_checksum


def _enforce_expected_contract(
    worker: WorkerProcess,
    *,
    expected_contract: WorkerContract,
    expected_checksum: str,
) -> None:
    actual_contract = WorkerContract.from_dict(worker.worker_contract or {})
    actual_checksum = str(worker.worker_contract_checksum or "").strip()
    expected_dict = expected_contract.to_dict()
    actual_dict = actual_contract.to_dict()
    if actual_dict != expected_dict:
        # v1.2.1: surface field-level diff to structured log and error message.
        # v1.2 closed profile + admin_approved divergences for claude workers;
        # this diagnostic exposes any remaining drift sources.
        drifted = {
            k: {"expected": expected_dict.get(k), "actual": actual_dict.get(k)}
            for k in set(expected_dict) | set(actual_dict)
            if expected_dict.get(k) != actual_dict.get(k)
        }
        try:
            import json as _json
            from datetime import datetime as _dt

            log_path = Path.cwd() / ".aragora/overnight/contract_drift_diagnostics.jsonl"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a") as _f:
                _f.write(
                    _json.dumps(
                        {
                            "recorded_at": _dt.utcnow().isoformat() + "Z",
                            "agent": expected_contract.agent,
                            "drifted_fields": sorted(drifted.keys()),
                            "diff": drifted,
                        }
                    )
                    + "\n"
                )
        except Exception:  # noqa: BLE001 — diagnostic-only, never mask the drift error
            pass
        raise RuntimeError(
            "Preflight worker emitted a contract that drifted from the expected contract. "
            f"Drifted fields: {sorted(drifted.keys())}."
        )
    if actual_checksum != expected_checksum:
        raise RuntimeError(
            "Preflight worker emitted a contract checksum that drifted from the expected contract."
        )


def _create_pr(repo_root: Path, branch: str, base_ref: str) -> None:
    _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            "synaptent/aragora",
            "--head",
            branch,
            "--base",
            base_ref,
            "--title",
            "[preflight] worker check",
            "--body",
            "Preflight validation of worker read/write/commit/push.",
            "--draft",
        ],
        cwd=repo_root,
    )


def _close_pr(repo_root: Path, branch: str) -> None:
    _run(
        [
            "gh",
            "pr",
            "close",
            "--repo",
            "synaptent/aragora",
            branch,
            "--delete-branch",
            "--comment",
            "Preflight complete - closing.",
        ],
        cwd=repo_root,
    )


def run_preflight(
    *,
    repo_root: Path,
    agent: str | None = None,
    base_ref: str = "main",
    skip_publication: bool = False,
    envelope: CredentialEnvelope | None = None,
    contract_path: Path | None = None,
) -> PreflightResult:
    if envelope is not None:
        return run_preflight_checks(envelope, repo_root=repo_root)

    start = time.monotonic()
    resolved_repo_root = repo_root.resolve()
    expected_contract: WorkerContract | None = None
    expected_contract_checksum = ""
    normalized_contract_path: Path | None = None
    if contract_path is not None:
        normalized_contract_path = contract_path.expanduser().resolve()
        expected_contract, expected_contract_checksum = _load_contract_payload(
            normalized_contract_path
        )
    if expected_contract is not None and str(expected_contract.agent or "").strip():
        normalized_agent = str(expected_contract.agent).strip()
    else:
        normalized_agent = str(agent or "").strip() or "claude"
    normalized_base_ref = str(base_ref or "main").strip() or "main"
    branch = _branch_name()
    worktree_path = _worktree_path(resolved_repo_root, branch)
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    worktree_created = False
    worker: WorkerProcess | None = None
    published = False
    pull_request_created = False
    pull_request_closed = False
    cleanup_worktree_removed = False
    cleanup_branch_removed = False
    dispatch_gate: dict[str, Any] = {}
    branch_lease: _BranchWriteLease | None = None
    branch_lease_released = False
    operation_failure: PreflightOperationError | None = None
    cleanup_failure: PreflightOperationError | None = None
    publication_base_sha = ""
    remote_branch_seeded = False
    cleanup_remote_branch_removed = False

    try:
        if not skip_publication:
            publication_base_sha = _resolve_ref_sha(resolved_repo_root, normalized_base_ref)
        _run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path), normalized_base_ref],
            cwd=resolved_repo_root,
        )
        worktree_created = True

        worker = run_async(
            _run_worker(
                repo_root=resolved_repo_root,
                worktree_path=worktree_path,
                branch=branch,
                agent=normalized_agent,
                contract=expected_contract,
            ),
            timeout=900.0,
        )
        dispatch_gate = _validate_worker_contract(worker)
        if expected_contract is not None:
            _enforce_expected_contract(
                worker,
                expected_contract=expected_contract,
                expected_checksum=expected_contract_checksum,
            )
        if not worker.commit_shas:
            raise RuntimeError("Preflight worker did not produce a commit.")

        if not skip_publication:
            branch_lease = _claim_branch_write_lease(
                repo_root=resolved_repo_root,
                branch=branch,
                worktree_path=worktree_path,
                agent=normalized_agent,
            )
            _seed_remote_branch_at_base(
                resolved_repo_root,
                branch,
                publication_base_sha,
            )
            remote_branch_seeded = True
            _run(["git", "push", "origin", "HEAD"], cwd=worktree_path, env=git_safe_env())
            published = True
            _create_pr(resolved_repo_root, branch, normalized_base_ref)
            pull_request_created = True
            _close_pr(resolved_repo_root, branch)
            pull_request_closed = True
            cleanup_remote_branch_removed = True
    except PreflightOperationError as exc:
        operation_failure = exc
    finally:
        if remote_branch_seeded and not published:
            try:
                _delete_seeded_remote_branch(resolved_repo_root, branch)
            except PreflightOperationError as exc:
                cleanup_failure = exc
            else:
                cleanup_remote_branch_removed = True
        if branch_lease is not None:
            try:
                _release_branch_write_lease(branch_lease)
            except PreflightOperationError as exc:
                if operation_failure is None:
                    operation_failure = exc
            else:
                branch_lease_released = True
        if worktree_created:
            worktree_remove = subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree_path)],
                cwd=str(resolved_repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            cleanup_worktree_removed = worktree_remove.returncode == 0
            branch_remove = subprocess.run(
                ["git", "branch", "-D", branch],
                cwd=str(resolved_repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            cleanup_branch_removed = branch_remove.returncode == 0

    checks: list[dict[str, Any]] = []
    failures = [failure for failure in (operation_failure, cleanup_failure) if failure is not None]
    if failures:
        checks.extend(failure.to_check() for failure in failures)
        failure_class = classify_preflight_failure(passed=False, checks=checks)
        dispatch_gate = GateEvaluation(
            gate_type=GateType.DISPATCH_READY.value,
            verdict=GateVerdict.BLOCKED.value,
            failure_classes=[(failure_class or TerminalClass.BLOCKED_NOT_DISPATCH_BOUNDED).value],
            required_evidence=["preflight_receipt"],
            notes=f"Preflight operation failed at {failures[0].stage}.",
        ).to_dict()

    passed = False
    if dispatch_gate and not failures:
        passed = str(dispatch_gate.get("verdict", "")).strip() == GateVerdict.PASS.value
    duration = time.monotonic() - start
    result = PreflightResult(
        passed=passed,
        checks=checks,
        duration_seconds=duration,
        envelope=None,
        repo_root=str(resolved_repo_root),
        base_ref=normalized_base_ref,
        branch=branch,
        worktree_path=str(worktree_path),
        agent=normalized_agent,
        published=published,
        pull_request_created=pull_request_created,
        pull_request_closed=pull_request_closed,
        cleanup_worktree_removed=cleanup_worktree_removed,
        cleanup_branch_removed=cleanup_branch_removed,
        dispatch_gate=dispatch_gate,
        worker=worker.to_dict() if worker is not None else {},
        branch_lease_id=branch_lease.lease_id if branch_lease is not None else "",
        branch_lease_owner_session_id=(
            branch_lease.owner_session_id if branch_lease is not None else ""
        ),
        branch_lease_work_id=branch_lease.work_id if branch_lease is not None else "",
        branch_lease_released=branch_lease_released,
        publication_base_sha=publication_base_sha,
        remote_branch_seeded=remote_branch_seeded,
        cleanup_remote_branch_removed=cleanup_remote_branch_removed,
    )
    if normalized_contract_path is not None:
        envelope_for_receipt = CredentialEnvelope.from_environment(os.environ)
        receipt = _save_contract_preflight_receipt(
            result=result,
            repo_root=resolved_repo_root,
            envelope=envelope_for_receipt,
            base_ref=normalized_base_ref,
            skip_publication=skip_publication,
            contract_path=normalized_contract_path,
            expected_contract_checksum=expected_contract_checksum,
        )
        admission_gate = evaluate_preflight_receipt_gate(
            receipt,
            repo_root=resolved_repo_root,
            envelope=envelope_for_receipt,
            check_type="scratch" if skip_publication else "remote_publish",
            base_ref=normalized_base_ref,
            expected_contract_checksum=expected_contract_checksum,
        )
        result.dispatch_gate = admission_gate.to_dict()
        result.passed = admission_gate.verdict == GateVerdict.PASS.value
        result.checks = [dict(item) for item in receipt.checks]
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run swarm worker preflight.")
    parser.add_argument(
        "--repo-root",
        default=str(Path.cwd()),
        help="Repository root",
    )
    parser.add_argument(
        "--agent",
        default=os.environ.get("WORKER_MODEL", "claude"),
        help="Target agent (claude or codex)",
    )
    parser.add_argument(
        "--base-ref",
        default="main",
        help="Base ref to branch from and target for the temporary PR (default: main).",
    )
    parser.add_argument(
        "--skip-publication",
        action="store_true",
        help="Skip push/PR steps (debug only).",
    )
    parser.add_argument(
        "--contract",
        default=None,
        help="Path to a JSON worker contract file for contract-aware preflight.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit a structured result payload.",
    )
    args = parser.parse_args()

    result = run_preflight(
        repo_root=Path(args.repo_root),
        agent=str(args.agent),
        base_ref=str(args.base_ref),
        skip_publication=bool(args.skip_publication),
        contract_path=Path(args.contract) if args.contract else None,
    )
    if args.json:
        _write_stdout_line(json.dumps(result.to_dict(), indent=2))
    else:
        _write_stdout_line(f"preflight={'ok' if result.passed else 'blocked'}")
        _write_stdout_line(f"agent={result.agent}")
        _write_stdout_line(f"base_ref={result.base_ref}")
        _write_stdout_line(f"branch={result.branch}")
        if not result.passed:
            failed_check = next(
                (item for item in result.checks if not bool(item.get("passed", False))),
                None,
            )
            if failed_check is not None:
                _write_stdout_line(f"failed_check={failed_check.get('name', 'preflight')}")
        checksum = str(result.worker.get("worker_contract_checksum", "")).strip()
        if checksum:
            _write_stdout_line(f"worker_contract_checksum={checksum}")
        commit_shas = [
            str(item) for item in result.worker.get("commit_shas", []) if str(item).strip()
        ]
        if commit_shas:
            _write_stdout_line(f"commit_shas={','.join(commit_shas)}")
    return 0 if result.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
