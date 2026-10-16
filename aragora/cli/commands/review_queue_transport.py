"""GitHub CLI transport helpers for review-queue commands."""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from aragora.review.github_transport import (
    GITHUB_TRANSPORT_BLOCKED_STATUS as GITHUB_TRANSPORT_BLOCKED_STATUS,
    GITHUB_TRANSPORT_ERROR_KIND as GITHUB_TRANSPORT_ERROR_KIND,
    gh_error_kind as _gh_error_kind,
    is_github_transport_error as _is_github_transport_error,
)

GH_COMMAND_TIMEOUT_SECONDS = 30


class _GhError(RuntimeError):
    """Raised when a 'gh' invocation fails or returns malformed JSON."""


def _command_timeout_message(cmd: list[str], timeout_seconds: int) -> str:
    return f"{' '.join(cmd)} timed out after {timeout_seconds}s"


def _gh_text(args: list[str]) -> str:
    """Run a 'gh' command and return plain stdout."""
    cmd = ["gh", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise _GhError(
            _command_timeout_message(cmd, int(exc.timeout or GH_COMMAND_TIMEOUT_SECONDS))
        ) from exc
    except OSError as exc:
        raise _GhError(f"{' '.join(cmd)} failed to start: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "no stderr"
        raise _GhError(f"gh {' '.join(args)} failed: {stderr}")
    return proc.stdout.strip()


def _gh_json(args: list[str]) -> Any:
    """Run a 'gh' command and parse JSON output. Returns None for empty stdout."""
    cmd = ["gh", *args]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=GH_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise _GhError(
            _command_timeout_message(cmd, int(exc.timeout or GH_COMMAND_TIMEOUT_SECONDS))
        ) from exc
    except OSError as exc:
        raise _GhError(f"{' '.join(cmd)} failed to start: {exc}") from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "no stderr"
        raise _GhError(f"gh {' '.join(args)} failed: {stderr}")
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise _GhError(f"gh {' '.join(args)} returned malformed JSON: {exc}") from exc


def _gh_json_with_transport_retries(
    args: list[str],
    *,
    gh_json: Callable[[list[str]], Any] = _gh_json,
    attempts: int = 2,
    delay_seconds: float = 0.0,
) -> Any:
    """Run a bounded gh JSON call, retrying only transient transport failures."""
    bounded_attempts = max(1, attempts)
    last_error: Exception | None = None
    for attempt in range(1, bounded_attempts + 1):
        try:
            return gh_json(args)
        except Exception as exc:
            last_error = exc
            if not _is_github_transport_error(exc) or attempt >= bounded_attempts:
                raise
            if delay_seconds > 0:
                time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error
    raise _GhError(f"gh {' '.join(args)} failed without an error")


def _github_repo_slug_from_override(repo_override: str | None) -> str:
    raw = str(repo_override or "").strip()
    if not raw:
        return ""
    raw = raw.removeprefix("repos/").strip("/")
    if raw.startswith("http"):
        match = re.search(r"github\.com[:/]+([^/]+)/([^/.?#]+)", raw)
        return f"{match.group(1)}/{match.group(2)}" if match else ""
    if "/" in raw and not raw.startswith("-"):
        return raw
    return ""


def _rest_pr_transport_fallback(
    *,
    pr_refs: list[str],
    repo_override: str | None,
    graphql_error: str,
    gh_json: Callable[[list[str]], Any] = _gh_json,
) -> dict[str, Any]:
    """Return compact REST PR/check-run metadata while preserving no-mutate state."""
    numbers = _numeric_pr_refs(pr_refs)
    repo_slug = _github_repo_slug_from_override(repo_override)
    fallback: dict[str, Any] = {
        "source": "rest",
        "available": False,
        "transport_blocked": True,
        "preserve_no_mutate": True,
        "mutation_forbidden": True,
        "graphql_error": graphql_error,
        "reason": "",
        "repo": repo_slug,
        "pr_refs": [str(ref) for ref in pr_refs],
    }
    if len(numbers) != 1:
        fallback["reason"] = "REST fallback requires exactly one numeric PR ref"
        return fallback
    if not repo_slug:
        fallback["reason"] = "REST fallback requires an explicit owner/repo"
        fallback["pr_number"] = numbers[0]
        return fallback

    pr_number = numbers[0]
    fallback["pr_number"] = pr_number
    pr_payload, pr_error = _try_rest_json(
        ["api", f"repos/{repo_slug}/pulls/{pr_number}"],
        gh_json=gh_json,
    )
    if not isinstance(pr_payload, dict):
        fallback["reason"] = "REST PR metadata unavailable"
        fallback["pr_error"] = pr_error or "REST PR endpoint returned a non-object payload"
        return fallback

    head_sha = _nested_str(pr_payload, "head", "sha")
    files_payload, files_error = _try_rest_json(
        ["api", f"repos/{repo_slug}/pulls/{pr_number}/files?per_page=100"],
        gh_json=gh_json,
    )
    check_runs_payload, check_runs_error = _try_rest_json(
        ["api", f"repos/{repo_slug}/commits/{head_sha}/check-runs?per_page=100"],
        gh_json=gh_json,
    )
    fallback.update(
        {
            "available": True,
            "reason": "GraphQL transport blocked; REST metadata is informational only",
            "pr": _compact_rest_pr(pr_payload),
            "files_available": files_payload is not None,
            "files": _compact_rest_files(files_payload),
            "files_error": files_error,
            "check_runs_available": check_runs_payload is not None,
            "check_runs_summary": _compact_rest_check_runs_summary(check_runs_payload),
            "check_runs_error": check_runs_error,
        }
    )
    return fallback


def _merge_packet_transport_blocked_envelope_with_rest_fallback(
    *,
    error: str,
    pr_refs: list[str],
    repo_override: str | None,
    limit: int,
    queue_cap: int = 6,
    gh_json: Callable[[list[str]], Any] = _gh_json,
) -> dict[str, Any]:
    envelope = _merge_packet_transport_blocked_envelope(
        error=error,
        pr_refs=pr_refs,
        repo_override=repo_override,
        limit=limit,
        queue_cap=queue_cap,
    )
    envelope["rest_fallback"] = _rest_pr_transport_fallback(
        pr_refs=pr_refs,
        repo_override=repo_override,
        graphql_error=error,
        gh_json=gh_json,
    )
    return envelope


def _try_rest_json(
    args: list[str],
    *,
    gh_json: Callable[[list[str]], Any],
) -> tuple[Any | None, str]:
    try:
        return _gh_json_with_transport_retries(args, gh_json=gh_json, attempts=2), ""
    except Exception as exc:  # noqa: BLE001 - REST fallback must remain best-effort.
        return None, str(exc)


def _compact_rest_pr(payload: dict[str, Any]) -> dict[str, Any]:
    state = str(payload.get("state") or "").upper()
    if payload.get("merged_at") or payload.get("mergedAt"):
        state = "MERGED"
    mergeable_state = str(payload.get("mergeable_state") or "").upper()
    return {
        "number": payload.get("number"),
        "title": str(payload.get("title") or ""),
        "url": str(payload.get("html_url") or payload.get("url") or ""),
        "state": state,
        "is_draft": bool(payload.get("draft")),
        "head_branch": _nested_str(payload, "head", "ref"),
        "head_sha": _nested_str(payload, "head", "sha"),
        "base_branch": _nested_str(payload, "base", "ref"),
        "base_sha": _nested_str(payload, "base", "sha"),
        "mergeable": _rest_mergeable(payload.get("mergeable"), mergeable_state),
        "merge_state_status": mergeable_state,
        "updated_at": str(payload.get("updated_at") or ""),
        "changed_files": payload.get("changed_files"),
    }


def _compact_rest_files(payload: Any) -> list[str]:
    if not isinstance(payload, list):
        return []
    paths: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        path = str(item.get("filename") or item.get("path") or "").strip()
        if path:
            paths.append(path)
    return paths


def _compact_rest_check_runs_summary(payload: Any) -> dict[str, Any]:
    runs = payload.get("check_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list):
        return {"available": False, "total": 0, "non_green_sample": []}

    by_status: dict[str, int] = {}
    by_conclusion: dict[str, int] = {}
    non_green: list[dict[str, str]] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        status = str(run.get("status") or "").strip().upper()
        conclusion = str(run.get("conclusion") or "").strip().upper()
        by_status[status or "UNKNOWN"] = by_status.get(status or "UNKNOWN", 0) + 1
        by_conclusion[conclusion or "UNKNOWN"] = by_conclusion.get(conclusion or "UNKNOWN", 0) + 1
        if _rest_check_run_non_green(status=status, conclusion=conclusion):
            non_green.append(_compact_rest_check_run(run, status=status, conclusion=conclusion))

    return {
        "available": True,
        "total": len([run for run in runs if isinstance(run, dict)]),
        "status_counts": by_status,
        "conclusion_counts": by_conclusion,
        "non_green_count": len(non_green),
        "non_green_sample": non_green[:12],
    }


def _compact_rest_check_run(run: dict[str, Any], *, status: str, conclusion: str) -> dict[str, str]:
    suite = run.get("check_suite")
    suite_dict: dict[str, Any] = suite if isinstance(suite, dict) else {}
    app = suite_dict.get("app")
    app_dict: dict[str, Any] = app if isinstance(app, dict) else {}
    return {
        "name": str(run.get("name") or run.get("context") or ""),
        "workflow": str(run.get("workflowName") or app_dict.get("name") or ""),
        "status": status,
        "conclusion": conclusion,
        "url": str(run.get("html_url") or run.get("details_url") or ""),
    }


def _rest_check_run_non_green(*, status: str, conclusion: str) -> bool:
    if conclusion in {"SUCCESS", "SKIPPED", "NEUTRAL"}:
        return False
    if conclusion:
        return True
    return status in {"QUEUED", "IN_PROGRESS", "PENDING", "EXPECTED"}


def _rest_mergeable(value: Any, mergeable_state: str) -> str:
    if value is True:
        return "MERGEABLE"
    if value is False:
        if mergeable_state in {"DIRTY", "CONFLICTING"}:
            return "CONFLICTING"
        return "UNKNOWN"
    return "UNKNOWN"


def _nested_str(payload: dict[str, Any], *path: str) -> str:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return str(value or "")


def _numeric_pr_refs(pr_refs: list[str]) -> list[int]:
    numbers: list[int] = []
    for ref in pr_refs:
        match = re.search(r"\d+", str(ref))
        if match:
            numbers.append(int(match.group(0)))
    return numbers


def _transport_blocked_next_prompt(command_name: str, pr_refs: list[str]) -> str:
    pr_text = ", ".join(f"#{number}" for number in _numeric_pr_refs(pr_refs)) or "the target PR"
    return (
        "Do not rely on transcript state. Re-check live GitHub/local state first. "
        f"Primary task: retry {command_name} for {pr_text} only after GitHub API transport "
        "recovers. Treat this packet as preserve/no-mutate; do not mark ready, collect "
        "evidence, record settlement, merge, close, label, rerun workflows, or touch branch "
        "protection while transport is blocked. If the prompt above accomplishes no "
        "incremental progress, make the next prompt one that does. If any work can be better "
        "automated by improving Aragora tooling at a meta level, include the concrete tooling "
        "improvement plan instead of repeating manual queue checks. Always include a final "
        "summary section with the best next recursive prompt."
    )


def _transport_blocked_fields(
    *,
    error: str,
    command_name: str,
    pr_refs: list[str],
    repo_override: str | None,
) -> dict[str, Any]:
    return {
        "status": GITHUB_TRANSPORT_BLOCKED_STATUS,
        "transport_blocked": True,
        "preserve_no_mutate": True,
        "retryable": _is_github_transport_error(error),
        "error_kind": _gh_error_kind(error),
        "error": error,
        "command": command_name,
        "repo": repo_override or "",
        "pr_refs": [str(ref) for ref in pr_refs],
        "not_ready": _numeric_pr_refs(pr_refs),
        "next_prompt": _transport_blocked_next_prompt(command_name, pr_refs),
    }


def _merge_packet_transport_blocked_envelope(
    *,
    error: str,
    pr_refs: list[str],
    repo_override: str | None,
    limit: int,
    queue_cap: int = 6,
) -> dict[str, Any]:
    return {
        "version": "merge_authorization_packet.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "queue_pressure": {
            "current_open_prs": len(pr_refs),
            "cap": queue_cap,
            "active": False,
            "scope": "explicit_pr_refs" if pr_refs else "open_pr_queue",
        },
        "limit": limit,
        "entries": [],
        "admin_squash_order": [],
        "human_risk_settlement_required": [],
        "admin_squash_allowed": False,
        **_transport_blocked_fields(
            error=error,
            command_name="review-queue merge-packet",
            pr_refs=pr_refs,
            repo_override=repo_override,
        ),
    }


def _queue_conductor_transport_blocked_envelope(
    *,
    error: str,
    pr_refs: list[str],
    repo_override: str | None,
    limit: int,
    mode: str,
) -> dict[str, Any]:
    return {
        "version": "queue_conductor.v1",
        "mode": mode,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "origin_main_sha": "",
        "limit": limit,
        "initial_heads": {},
        "candidates": [],
        "tooling_notes": [
            "read_only_packet",
            "transport_failure_is_preserve_no_mutate",
        ],
        **_transport_blocked_fields(
            error=error,
            command_name="review-queue conductor",
            pr_refs=pr_refs,
            repo_override=repo_override,
        ),
    }
