#!/usr/bin/env python3
"""Diagnose PR check state and generate a bounded follow-up prompt.

The helper is intentionally read-only by default: it shells out to ``gh`` for
current PR state and run/job diagnostics, but never reruns jobs, pushes, or
edits files. When ``--wait-run`` is provided, it polls one Actions run until it
completes or times out, then switches the generated prompt to failed-job
diagnosis or narrow current-head cancelled-job rerun commands.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> str:
    env = os.environ.get("ARAGORA_REPO_ROOT")
    if env:
        return env
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return str(Path(__file__).resolve().parents[1])


INCREMENTAL_PROGRESS_SENTENCE = (
    "If the prompt above accomplishes no incremental progress make the next prompt one that "
    "does, include this sentence in all subsequent prompts to ensure they converge towards "
    "prompts that make incremental progress."
)
META_AUTOMATION_SENTENCE = (
    "If any of the work involved can be better automated and made more autonomous by "
    "improving aragora tooling at a meta level create a plan to do that instead, include "
    "this sentence in all subsequent prompts to ensure they converge towards automating "
    "and making more autonomous all steps at a meta level where this makes sense for the "
    "repo and project."
)

FAILURE_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "ACTION_REQUIRED"}
GREEN_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
PENDING_STATUSES = {"IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED", "REQUESTED", "WAITING"}
NAMED_NON_REQUIRED_ROLLUP_WORKFLOWS = {
    "aragora code review",
    "core suites",
    "release readiness",
    "security gate",
    "smoke tests",
}
CHECKOUT_MARKERS = ("checkout", "sparse-checkout", "repository checkout")
SUBSTANTIVE_MARKERS = (
    "verify",
    "build",
    "test",
    "smoke",
    "drift",
    "consistency",
    "quorum",
    "readiness",
)
MODEL_QUORUM_MARKERS = (
    "needs_model_review_quorum",
    "collect_model_quorum_before_merge",
    "model quorum incomplete",
    "focused adversarial dogfood evidence is required",
)
DEPENDENCY_SECURITY_MARKERS = (
    "pip-audit",
    "known vulnerabilit",
    "fix versions",
    "cve-",
    "pysec-",
    "ghsa-",
)
DEPENDENCY_REPAIR_FILES = {
    "pyproject.toml",
    "uv.lock",
    "aragora/live/package-lock.json",
    "aragora/live/package.json",
    "sdk/typescript/package-lock.json",
    "sdk/typescript/package.json",
}
DEPENDENCY_REPAIR_PREFIXES = ("requirements",)


@dataclass
class CheckDiagnosis:
    """Normalized status for a PR check row or Actions job."""

    workflow: str
    name: str
    status: str
    conclusion: str
    classification: str
    details_url: str = ""
    run_id: str | None = None
    job_id: str | None = None
    run_head_sha: str | None = None
    summary: str = ""
    rerun_command: str | None = None
    log_command: str | None = None
    log_summary: list[str] = field(default_factory=list)
    superseding_dependency_prs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WaitRunDiagnosis:
    """Summary for an optionally waited GitHub Actions run."""

    run_id: str
    status: str
    conclusion: str
    workflow: str
    head_sha: str
    timed_out: bool
    jobs: list[CheckDiagnosis]


@dataclass
class FollowupResult:
    """Machine-readable PR follow-up decision."""

    pr: int
    head: str
    mergeable: str
    merge_state_status: str
    expected_head: str | None
    action: str
    checks: list[CheckDiagnosis]
    rerun_commands: list[str]
    prompt: str
    wait_run: WaitRunDiagnosis | None = None


def parse_run_job_ids(details_url: str) -> tuple[str | None, str | None]:
    """Extract GitHub Actions run/job ids from a details URL."""
    match = re.search(r"/actions/runs/(\d+)/job/(\d+)", details_url or "")
    if not match:
        return None, None
    return match.group(1), match.group(2)


def check_identity(check: dict[str, Any]) -> str:
    """Return a stable check identity for latest-row collapse."""
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if not name:
        return ""
    return f"{workflow}:{name}" if workflow else name


def latest_status_check_rollup(checks: list[Any]) -> list[dict[str, Any]]:
    """Collapse superseded check rows to the latest row per workflow/job identity."""
    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            continue
        identity = check_identity(check)
        if not identity:
            passthrough.append(check)
            continue
        timestamp = str(
            check.get("completedAt")
            or check.get("startedAt")
            or check.get("createdAt")
            or check.get("updatedAt")
            or ""
        )
        previous = latest.get(identity)
        if previous is None or (timestamp, index) >= (previous[0], previous[1]):
            latest[identity] = (timestamp, index, check)
    return passthrough + [item[2] for item in sorted(latest.values(), key=lambda item: item[1])]


def _parse_datetime(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _duration_seconds(check: dict[str, Any]) -> float | None:
    started = _parse_datetime(str(check.get("startedAt") or ""))
    completed = _parse_datetime(str(check.get("completedAt") or ""))
    if not started or not completed:
        return None
    return max(0.0, (completed - started).total_seconds())


def classify_check(
    check: dict[str, Any], pr_head: str, run_data: dict[str, Any] | None = None
) -> CheckDiagnosis:
    """Classify a statusCheckRollup row into operator-relevant buckets."""
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    status = str(check.get("status") or check.get("state") or "").upper()
    conclusion = str(check.get("conclusion") or "").upper()
    if not conclusion and status in FAILURE_CONCLUSIONS | GREEN_CONCLUSIONS | {
        "CANCELLED",
        "STALE",
    }:
        conclusion = status

    details_url = str(check.get("detailsUrl") or check.get("link") or "").strip()
    run_id, job_id = parse_run_job_ids(details_url)
    run_head = str((run_data or {}).get("headSha") or "").strip() or None
    classification = "unknown"
    summary = ""

    if conclusion == "CANCELLED":
        if run_head and run_head != pr_head:
            classification = "stale_cancelled"
            summary = f"cancelled on stale head {run_head}"
        else:
            duration = _duration_seconds(check)
            if _is_early_cancelled_job(run_data, job_id) or (
                duration is not None and duration <= 120
            ):
                classification = "early_cancelled"
                summary = "cancelled before substantive verification"
            else:
                classification = "unknown"
                summary = "cancelled after job startup; inspect log before rerun"
    elif conclusion in FAILURE_CONCLUSIONS:
        classification = "real_failure"
        summary = (
            _failure_after_checkout_summary(_job_steps(run_data, job_id))
            or "current-head failure requiring repair"
        )
    elif status in PENDING_STATUSES or not conclusion:
        classification = "in_progress"
        summary = "check still running or pending"
    elif conclusion in GREEN_CONCLUSIONS:
        classification = "green"
        summary = "green or green-equivalent"
    elif conclusion == "STALE":
        classification = "stale_cancelled"
        summary = "stale status context"

    rerun_command = f"gh run rerun {run_id} --job {job_id}" if run_id and job_id else None
    log_command = f"gh run view {run_id} --job {job_id} --log" if run_id and job_id else None
    return CheckDiagnosis(
        workflow=workflow,
        name=name,
        status=status,
        conclusion=conclusion,
        classification=classification,
        details_url=details_url,
        run_id=run_id,
        job_id=job_id,
        run_head_sha=run_head,
        summary=summary,
        rerun_command=rerun_command,
        log_command=log_command,
    )


def _job_id(job: dict[str, Any]) -> str:
    return str(job.get("databaseId") or job.get("id") or "").strip()


def _step_names_before_first_cancel(steps: list[dict[str, Any]]) -> tuple[list[str], bool]:
    names = [str(step.get("name") or "").lower() for step in steps]
    first_cancelled_index = next(
        (
            index
            for index, step in enumerate(steps)
            if str(step.get("conclusion") or "").upper() == "CANCELLED"
        ),
        None,
    )
    if first_cancelled_index is None:
        return names, False
    return names[: first_cancelled_index + 1], True


def _is_early_cancelled_steps(steps: list[dict[str, Any]]) -> bool:
    if not steps:
        return False
    before_cancel, had_cancel = _step_names_before_first_cancel(steps)
    if not had_cancel:
        return False
    return any(
        any(marker in name for marker in CHECKOUT_MARKERS) for name in before_cancel
    ) and not any(
        any(marker in name for marker in SUBSTANTIVE_MARKERS) for name in before_cancel[:-1]
    )


def _is_early_cancelled_job(run_data: dict[str, Any] | None, job_id: str | None) -> bool:
    if not run_data or not job_id:
        return False
    for job in run_data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        database_id = _job_id(job)
        if database_id and database_id != job_id:
            continue
        steps = [step for step in job.get("steps") or [] if isinstance(step, dict)]
        return _is_early_cancelled_steps(steps)
    return False


def _job_steps(run_data: dict[str, Any] | None, job_id: str | None) -> list[dict[str, Any]]:
    if not run_data or not job_id:
        return []
    for job in run_data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        database_id = _job_id(job)
        if database_id and database_id != job_id:
            continue
        return [step for step in job.get("steps") or [] if isinstance(step, dict)]
    return []


def _failure_after_checkout_summary(steps: list[dict[str, Any]]) -> str | None:
    """Return the first failing substantive step after checkout, if available."""
    checkout_index: int | None = None
    for index, step in enumerate(steps):
        name = str(step.get("name") or "").lower()
        conclusion = str(step.get("conclusion") or "").upper()
        if checkout_index is None and any(marker in name for marker in CHECKOUT_MARKERS):
            if conclusion == "SUCCESS":
                checkout_index = index
            continue
        if checkout_index is None or index <= checkout_index:
            continue
        if conclusion in FAILURE_CONCLUSIONS or conclusion == "FAILURE":
            step_name = str(step.get("name") or "substantive step").strip()
            return f"failed after checkout during {step_name}"
    return None


def _is_merge_quorum_check(check: CheckDiagnosis) -> bool:
    workflow = check.workflow.lower()
    name = check.name.lower()
    return "merge quorum" in workflow or "merge-quorum" in workflow or "merge-quorum" in name


def _has_model_quorum_blocker(check: CheckDiagnosis) -> bool:
    if check.classification != "real_failure" or not _is_merge_quorum_check(check):
        return False
    text = "\n".join([check.summary, *check.log_summary]).lower()
    return any(marker in text for marker in MODEL_QUORUM_MARKERS)


def _is_security_gate_check(check: CheckDiagnosis) -> bool:
    workflow = check.workflow.lower()
    name = check.name.lower()
    return "security gate" in workflow or "security" in workflow or "security" in name


def _has_dependency_security_failure(check: CheckDiagnosis) -> bool:
    if check.classification != "real_failure" or not _is_security_gate_check(check):
        return False
    text = "\n".join([check.summary, *check.log_summary]).lower()
    return any(marker in text for marker in DEPENDENCY_SECURITY_MARKERS)


def _has_superseding_dependency_pr(check: CheckDiagnosis) -> bool:
    return bool(check.superseding_dependency_prs) and _has_dependency_security_failure(check)


def _is_named_non_required_rollup_gate(check: CheckDiagnosis) -> bool:
    workflow = check.workflow.lower()
    if workflow == "tests":
        return True
    return any(marker in workflow for marker in NAMED_NON_REQUIRED_ROLLUP_WORKFLOWS)


def _pending_named_non_required_rollup_gates(
    checks: list[CheckDiagnosis],
) -> list[CheckDiagnosis]:
    return [
        check
        for check in checks
        if check.classification == "in_progress" and _is_named_non_required_rollup_gate(check)
    ]


def _dependency_repair_file(path: str) -> bool:
    normalized = path.strip()
    if normalized in DEPENDENCY_REPAIR_FILES:
        return True
    name = normalized.rsplit("/", maxsplit=1)[-1]
    return any(name.startswith(prefix) for prefix in DEPENDENCY_REPAIR_PREFIXES)


def dependency_search_terms_from_logs(lines: list[str]) -> list[str]:
    """Extract package/advisory terms from dependency-audit log summaries."""
    terms: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        normalized = value.strip()
        if not normalized:
            return
        key = normalized.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(normalized)

    for line in lines:
        for match in re.findall(
            r"\b(?:CVE-\d{4}-\d{4,}|PYSEC-\d{4}-\d+|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})\b",
            line,
            flags=re.IGNORECASE,
        ):
            add(match.upper() if match.lower().startswith(("cve-", "pysec-")) else match)
        table_match = re.match(
            r"\s*([A-Za-z0-9][A-Za-z0-9_.-]+)\s+[0-9][^\s]*\s+"
            r"(?:CVE-\d{4}-\d{4,}|PYSEC-\d{4}-\d+|GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})\b",
            line,
            flags=re.IGNORECASE,
        )
        if table_match:
            add(table_match.group(1))
    return terms


def _view_pr_files(pr_number: int) -> list[str]:
    try:
        payload = _run_gh_json(["gh", "pr", "view", str(pr_number), "--json", "files"])
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return []
    files: list[str] = []
    for item in payload.get("files") or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if path:
            files.append(path)
    return files


def _search_superseding_dependency_prs(
    *,
    current_pr: int,
    terms: list[str],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Find open or recently merged PRs that repair the dependency audit failure."""
    candidates: dict[int, dict[str, Any]] = {}
    for term in terms:
        try:
            payload = _run_gh_json(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "all",
                    "--limit",
                    str(limit),
                    "--search",
                    term,
                    "--json",
                    "number,title,state,url,headRefOid,headRefName,baseRefName,mergedAt",
                ]
            )
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        rows: list[Any] = payload if isinstance(payload, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            number = int(row.get("number") or 0)
            if not number or number == current_pr:
                continue
            state = str(row.get("state") or "").upper()
            if state not in {"OPEN", "MERGED"}:
                continue
            candidate = candidates.setdefault(number, dict(row))
            match_terms = candidate.setdefault("match_terms", [])
            if term not in match_terms:
                match_terms.append(term)

    repairs: list[dict[str, Any]] = []
    for number, row in sorted(candidates.items()):
        files = _view_pr_files(number)
        dependency_files = [path for path in files if _dependency_repair_file(path)]
        if not dependency_files:
            continue
        repairs.append(
            {
                "number": number,
                "state": str(row.get("state") or ""),
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "headRefOid": str(row.get("headRefOid") or ""),
                "headRefName": str(row.get("headRefName") or ""),
                "baseRefName": str(row.get("baseRefName") or ""),
                "mergedAt": str(row.get("mergedAt") or ""),
                "files": dependency_files,
                "match_terms": list(row.get("match_terms") or []),
            }
        )
    return repairs


def _find_superseding_dependency_prs_by_job(
    *,
    pr_number: int,
    checks: list[CheckDiagnosis],
) -> dict[str, list[dict[str, Any]]]:
    by_job: dict[str, list[dict[str, Any]]] = {}
    for check in checks:
        if not check.job_id or not _has_dependency_security_failure(check):
            continue
        terms = dependency_search_terms_from_logs(check.log_summary)
        if not terms:
            continue
        repairs = _search_superseding_dependency_prs(current_pr=pr_number, terms=terms)
        if repairs:
            by_job[check.job_id] = repairs
    return by_job


def _wait_check_selector_parts(selector: str) -> tuple[str, str] | None:
    """Parse a workflow/name selector into normalized parts."""
    parts = [part.strip().lower() for part in selector.split("/", maxsplit=1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def wait_check_run_id(pr_data: dict[str, Any], selector: str) -> str | None:
    """Return the run id for a matching in-progress status check, if any."""
    parsed = _wait_check_selector_parts(selector)
    if parsed is None:
        return None
    expected_workflow, expected_name = parsed
    pr_head = str(pr_data.get("headRefOid") or "").strip()
    for check in latest_status_check_rollup(list(pr_data.get("statusCheckRollup") or [])):
        workflow = str(check.get("workflowName") or check.get("workflow") or "").strip().lower()
        name = str(check.get("name") or check.get("context") or "").strip().lower()
        if workflow != expected_workflow or name != expected_name:
            continue
        diagnosis = classify_check(check, pr_head)
        if diagnosis.classification == "in_progress":
            return diagnosis.run_id
        return None
    return None


def _has_branch_conflict(pr_data: dict[str, Any]) -> bool:
    mergeable = str(pr_data.get("mergeable") or "").upper()
    merge_state = str(pr_data.get("mergeStateStatus") or "").upper()
    return mergeable == "CONFLICTING" or merge_state == "DIRTY"


def classify_run_job(
    job: dict[str, Any],
    run_id: str,
    run_data: dict[str, Any],
    *,
    pr_head: str | None = None,
) -> CheckDiagnosis:
    """Classify an Actions job from gh run view JSON."""
    job_id = _job_id(job)
    status = str(job.get("status") or "").upper()
    conclusion = str(job.get("conclusion") or "").upper()
    workflow = str(run_data.get("workflowName") or "").strip()
    name = str(job.get("name") or job_id or "").strip()
    head_sha = str(run_data.get("headSha") or "").strip() or None
    classification = "unknown"
    summary = ""

    if pr_head and head_sha and head_sha != pr_head:
        classification = "stale_cancelled"
        summary = f"run belongs to stale head {head_sha}; current PR head is {pr_head}"
    elif conclusion == "CANCELLED":
        if _is_early_cancelled_steps(
            [step for step in job.get("steps") or [] if isinstance(step, dict)]
        ):
            classification = "early_cancelled"
            summary = "cancelled before substantive verification"
        else:
            classification = "unknown"
            summary = "cancelled after job startup; inspect log before rerun"
    elif conclusion in FAILURE_CONCLUSIONS:
        classification = "real_failure"
        summary = (
            _failure_after_checkout_summary(
                [step for step in job.get("steps") or [] if isinstance(step, dict)]
            )
            or "current-head failure requiring repair"
        )
    elif status in PENDING_STATUSES or not conclusion:
        classification = "in_progress"
        summary = "job still running or pending"
    elif conclusion in GREEN_CONCLUSIONS:
        classification = "green"
        summary = "green or green-equivalent"

    rerun_command = f"gh run rerun {run_id} --job {job_id}" if job_id else None
    log_command = f"gh run view {run_id} --job {job_id} --log" if job_id else None
    return CheckDiagnosis(
        workflow=workflow,
        name=name,
        status=status,
        conclusion=conclusion,
        classification=classification,
        run_id=run_id,
        job_id=job_id or None,
        run_head_sha=head_sha,
        summary=summary,
        rerun_command=rerun_command,
        log_command=log_command,
    )


def summarize_log(log_text: str, max_lines: int = 12) -> list[str]:
    """Extract high-signal failure lines without dumping complete logs."""
    markers = (
        "##[error]",
        "FAIL:",
        "FAILED",
        "Out of date:",
        " E ",
        "Error:",
        "error:",
        "verdict=",
        "status=needs_model_review_quorum",
        "model quorum incomplete",
        "focused adversarial dogfood evidence is required",
        "CVE-",
        "PYSEC-",
        "GHSA-",
        "Fix Versions",
        "known vulnerabilit",
    )
    lines: list[str] = []
    for raw in log_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if any(marker in line for marker in markers):
            lines.append(line)
    return lines[-max_lines:]


def diagnose_wait_run(
    run_id: str,
    run_data: dict[str, Any],
    *,
    pr_head: str | None = None,
    timed_out: bool = False,
    log_summary_by_job: dict[str, list[str]] | None = None,
) -> WaitRunDiagnosis:
    """Build a diagnosis for a waited Actions run."""
    jobs = [
        classify_run_job(job, run_id, run_data, pr_head=pr_head)
        for job in run_data.get("jobs") or []
        if isinstance(job, dict)
    ]
    for diagnosis in jobs:
        if diagnosis.job_id and log_summary_by_job:
            diagnosis.log_summary = log_summary_by_job.get(diagnosis.job_id, [])
    return WaitRunDiagnosis(
        run_id=run_id,
        status=str(run_data.get("status") or "").lower(),
        conclusion=str(run_data.get("conclusion") or "").lower(),
        workflow=str(run_data.get("workflowName") or ""),
        head_sha=str(run_data.get("headSha") or ""),
        timed_out=timed_out,
        jobs=jobs,
    )


def _derive_action(
    checks: list[CheckDiagnosis],
    wait_run: WaitRunDiagnosis | None,
    *,
    expected_head: str | None,
    head: str,
    branch_conflict: bool = False,
) -> str:
    if expected_head and head != expected_head:
        return "head_drift"
    if wait_run and wait_run.head_sha and head and wait_run.head_sha != head:
        return "stale_wait_run"

    wait_jobs = wait_run.jobs if wait_run else []
    real_wait_jobs = [job for job in wait_jobs if job.classification == "real_failure"]
    if real_wait_jobs and any(_has_superseding_dependency_pr(job) for job in real_wait_jobs):
        unsuperseded = [job for job in real_wait_jobs if not _has_superseding_dependency_pr(job)]
        if all(_has_model_quorum_blocker(job) for job in unsuperseded):
            return "verify_superseding_dependency_pr"
    if wait_run and (
        wait_run.timed_out or any(job.classification == "in_progress" for job in wait_jobs)
    ):
        return "monitor"
    if any(job.classification == "real_failure" for job in wait_jobs):
        if all(
            job.classification != "real_failure" or _has_model_quorum_blocker(job)
            for job in wait_jobs
        ):
            return "collect_model_evidence"
        return "repair_failures"
    if any(job.classification == "unknown" for job in wait_jobs):
        return "diagnose_unknown"
    if (
        wait_jobs
        and any(job.classification == "early_cancelled" for job in wait_jobs)
        and not any(job.classification == "real_failure" for job in wait_jobs)
    ):
        return "rerun_cancelled"

    real_checks = [check for check in checks if check.classification == "real_failure"]
    if _pending_named_non_required_rollup_gates(checks):
        return "monitor_named_rollup_gates"
    if real_checks and any(_has_superseding_dependency_pr(check) for check in real_checks):
        unsuperseded = [check for check in real_checks if not _has_superseding_dependency_pr(check)]
        if all(_has_model_quorum_blocker(check) for check in unsuperseded):
            return "verify_superseding_dependency_pr"
    if any(check.classification == "real_failure" for check in checks):
        if all(
            check.classification != "real_failure" or _has_model_quorum_blocker(check)
            for check in checks
        ):
            return "collect_model_evidence"
        return "repair_failures"
    if any(check.classification == "in_progress" for check in checks):
        return "monitor"
    if any(check.classification == "unknown" for check in checks):
        return "diagnose_unknown"
    if any(check.classification == "early_cancelled" for check in checks):
        return "rerun_cancelled"
    if branch_conflict:
        return "diagnose_branch_conflict"
    return "green"


def build_followup_result(
    pr_data: dict[str, Any],
    *,
    expected_head: str | None = None,
    run_data_by_id: dict[str, dict[str, Any]] | None = None,
    log_summary_by_job: dict[str, list[str]] | None = None,
    superseding_dependency_prs_by_job: dict[str, list[dict[str, Any]]] | None = None,
    wait_run: WaitRunDiagnosis | None = None,
    allow_rerun_commands: bool = False,
) -> FollowupResult:
    """Build the follow-up decision from already-fetched PR/run data."""
    pr_number = int(pr_data.get("number") or pr_data.get("pr") or 0)
    head = str(pr_data.get("headRefOid") or "").strip()
    mergeable = str(pr_data.get("mergeable") or "").strip()
    merge_state_status = str(pr_data.get("mergeStateStatus") or "").strip()
    checks: list[CheckDiagnosis] = []
    for check in latest_status_check_rollup(list(pr_data.get("statusCheckRollup") or [])):
        run_id, _job_id_value = parse_run_job_ids(str(check.get("detailsUrl") or ""))
        diagnosis = classify_check(check, head, (run_data_by_id or {}).get(run_id or ""))
        if diagnosis.job_id and log_summary_by_job:
            diagnosis.log_summary = log_summary_by_job.get(diagnosis.job_id, [])
        if diagnosis.job_id and superseding_dependency_prs_by_job:
            diagnosis.superseding_dependency_prs = superseding_dependency_prs_by_job.get(
                diagnosis.job_id, []
            )
        checks.append(diagnosis)

    if wait_run and not (wait_run.head_sha and head and wait_run.head_sha != head):
        if superseding_dependency_prs_by_job:
            for job in wait_run.jobs:
                if job.job_id:
                    job.superseding_dependency_prs = superseding_dependency_prs_by_job.get(
                        job.job_id, []
                    )
        waited_job_ids = {job.job_id for job in wait_run.jobs if job.job_id}
        checks = [check for check in checks if check.job_id not in waited_job_ids]
        checks.extend(wait_run.jobs)

    action = _derive_action(
        checks,
        wait_run,
        expected_head=expected_head,
        head=head,
        branch_conflict=_has_branch_conflict(pr_data),
    )
    rerun_commands = [
        check.rerun_command
        for check in checks
        if check.classification == "early_cancelled" and check.rerun_command
    ]
    if not allow_rerun_commands or action != "rerun_cancelled":
        rerun_commands = []

    prompt = build_prompt(
        pr_number=pr_number,
        head=head,
        expected_head=expected_head,
        action=action,
        checks=checks,
        rerun_commands=rerun_commands,
        wait_run=wait_run,
    )
    return FollowupResult(
        pr=pr_number,
        head=head,
        mergeable=mergeable,
        merge_state_status=merge_state_status,
        expected_head=expected_head,
        action=action,
        checks=checks,
        rerun_commands=rerun_commands,
        prompt=prompt,
        wait_run=wait_run,
    )


def build_prompt(
    *,
    pr_number: int,
    head: str,
    expected_head: str | None,
    action: str,
    checks: list[CheckDiagnosis],
    rerun_commands: list[str],
    wait_run: WaitRunDiagnosis | None = None,
) -> str:
    """Render the recursive best-next prompt."""
    lines = [
        f"Start from live repo truth in {_repo_root()}. Do not trust prior transcript state. Check your Aragora operator-steering mailbox before lane work.",
        "",
    ]
    pin = expected_head or head
    if action == "head_drift":
        lines.extend(
            [
                f"Goal: refresh #{pr_number} follow-up because the live head drifted from {expected_head} to {head}. Do not merge, rerun, push, edit files, start cleanup, or start broader queue settlement.",
                "",
            ]
        )
    elif action == "stale_wait_run":
        run_head = wait_run.head_sha if wait_run else "unknown"
        lines.extend(
            [
                f"Goal: refresh #{pr_number} follow-up because the waited Actions run belongs to stale head {run_head}, while the live PR head is {head}. Do not merge, rerun, push, edit files, start cleanup, or start broader queue settlement.",
                "",
            ]
        )
    elif action == "repair_failures":
        lines.extend(
            [
                f"Goal: make one bounded progress increment on #{pr_number} by repairing only current-head real CI failures at head {pin}. Do not merge, start broader queue settlement, rerun cancelled jobs, start cleanup, or touch unrelated PRs/files.",
                "",
            ]
        )
    elif action == "collect_model_evidence":
        lines.extend(
            [
                f"Goal: make one bounded progress increment on #{pr_number} by collecting exactly one current-head non-Codex model/dogfood evidence signal at head {pin}. Do not merge, start broader queue settlement, rerun cancelled jobs, start cleanup, push unrelated work, or touch unrelated PRs/files.",
                "",
            ]
        )
    elif action == "verify_superseding_dependency_pr":
        lines.extend(
            [
                f"Goal: avoid duplicate branch-local dependency repair on #{pr_number} at head {pin}; verify the dependency-security superseding PR instead. Do not merge, push, edit #{pr_number}, rerun CI, start cleanup, or touch unrelated PRs/files.",
                "",
            ]
        )
    elif action == "rerun_cancelled":
        lines.extend(
            [
                f"Goal: make one bounded progress increment on #{pr_number} by rerunning only current-head early-cancelled jobs at head {pin}. Do not merge, push, edit files, start cleanup, or touch unrelated PRs/files.",
                "",
            ]
        )
    elif action == "monitor":
        lines.extend(
            [
                f"Goal: monitor #{pr_number} at head {pin} until checks settle. Do not merge, rerun, push, edit files, start cleanup, or start broader queue settlement.",
                "",
            ]
        )
    elif action == "monitor_named_rollup_gates":
        lines.extend(
            [
                f"Goal: monitor #{pr_number} at head {pin} until named non-required rollup gates settle. Do not collect model evidence, merge, rerun, push, edit files, start cleanup, or start broader queue settlement while these gates are pending.",
                "",
            ]
        )
    elif action == "diagnose_branch_conflict":
        lines.extend(
            [
                f"Goal: diagnose only #{pr_number}'s live branch conflict or mergeability blocker at head {pin}. Do not merge, rerun CI, push, edit files outside a later explicitly authorized conflict repair, start cleanup, or start broader queue settlement.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"Goal: continue exact-head follow-up for #{pr_number} at head {pin}. Do not merge, push, edit files, start cleanup, or touch unrelated PRs/files.",
                "",
            ]
        )

    lines.extend(
        [
            "Run read-only first:",
            "- git status --short --branch --untracked-files=all",
            "- python3 scripts/agent_bridge.py health --json || true",
            f"- python3 scripts/identify_lane_owner.py --pr {pr_number} --json || true",
            f"- gh pr view {pr_number} --json number,state,isDraft,headRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup,url",
            "",
            f"If any active lane owns #{pr_number} repair/settlement, stop and report owner. If #{pr_number} head drifted from {pin}, stop and produce a refreshed prompt pinned to live head.",
            "",
        ]
    )

    if wait_run:
        lines.extend(
            [
                f"Wait-run diagnosis: run {wait_run.run_id} / {wait_run.workflow} is {wait_run.status} with conclusion {wait_run.conclusion or 'none'} at head {wait_run.head_sha or 'unknown'}.",
                "",
            ]
        )

    interesting = [check for check in checks if check.classification != "green"]
    if interesting:
        lines.append("Current non-green diagnosis:")
        for check in interesting:
            run_job = (
                f" run {check.run_id}, job {check.job_id}" if check.run_id and check.job_id else ""
            )
            lines.append(
                f"- {check.workflow} / {check.name}: {check.classification}{run_job}; {check.summary}"
            )
            if (
                action in {"repair_failures", "collect_model_evidence"}
                and check.classification == "real_failure"
                and check.log_command
            ):
                lines.append(f"  inspect: {check.log_command}")
            for item in check.log_summary[-3:]:
                lines.append(f"  log: {item}")
            for repair in check.superseding_dependency_prs:
                number = repair.get("number")
                state = repair.get("state") or "UNKNOWN"
                title = repair.get("title") or ""
                url = repair.get("url") or ""
                files = ", ".join(repair.get("files") or [])
                terms = ", ".join(repair.get("match_terms") or [])
                lines.append(f"  superseded-by: PR #{number} [{state}] {title} {url}".rstrip())
                if terms:
                    lines.append(f"  match: {terms}")
                if files:
                    lines.append(f"  files: {files}")
        lines.append("")

    if action == "repair_failures":
        lines.append(
            "Repair only the real failed checks. Do not rerun cancelled rows until the substantive failures are green."
        )
    elif action == "collect_model_evidence":
        lines.append(
            "If merge-packet still blocks on model quorum or focused adversarial dogfood, collect exactly one current-head non-Codex model/dogfood evidence signal."
        )
        lines.append(
            "Before posting, lint the exact comment with `python3 -m aragora.cli.main review-queue evidence-lint --pr <PR> --head-sha <HEAD> --body-file <FILE> --author <GITHUB_LOGIN> --json` and require `would_count=true` with no problems."
        )
        lines.append(
            "Use a countable non-Codex header and metadata block, for example `## Claude focused adversarial dogfood`, `Exact head: <HEAD>`, `Reviewer harness: claude-code`, `Model family: claude`, `Model id: <MODEL>`, and `Receipt artifact: <PATH>`."
        )
        lines.append(
            "Post exactly one valid PR comment only if the evidence is current-head, not Codex, not any OpenAI-family model, lists files reviewed, puts findings first, includes validation run/not-run reasons, includes focused adversarial dogfood verdict, and states that it is not merge authorization."
        )
        lines.append(
            "Then rerun review-queue merge-packet for the PR and report the next blocker. Do not merge."
        )
    elif action == "verify_superseding_dependency_pr":
        lines.append(
            "Do not open or continue a branch-local dependency repair for this PR while the superseding dependency-security PR is open or newly merged."
        )
        lines.append(
            "Verify the superseding PR's exact head, dependency files, Security Gate, required checks, and merge-packet state; if it is merged into current main, re-evaluate this PR from current main before collecting fresh evidence or settlement."
        )
    elif action == "rerun_cancelled" and rerun_commands:
        lines.append("If the same rows remain current-head early cancellations, run only:")
        for command in rerun_commands:
            lines.append(f"- {command}")
        lines.append("Then monitor until those rerun jobs settle.")
    elif action == "rerun_cancelled":
        lines.append(
            "Only early-cancelled rows remain; rerun commands were intentionally withheld by the helper. Re-run the helper with --allow-rerun-commands to generate exact commands."
        )
    elif action == "stale_wait_run":
        lines.append(
            "Ignore the stale waited run for current-head decisions. Re-run the helper against a current-head run/check or omit --wait-run and use live statusCheckRollup."
        )
    elif action == "monitor" and wait_run and wait_run.timed_out:
        lines.append(
            f"Run {wait_run.run_id} did not settle before the wait timeout. Monitor again before diagnosing or rerunning."
        )
    elif action == "monitor":
        lines.append("If checks are still in progress, report exact names and stop.")
    elif action == "monitor_named_rollup_gates":
        lines.append(
            "Named non-required rollup gates are still pending. Report the exact pending names and stop; do not collect model evidence or start repair until they settle."
        )
    elif action == "green":
        lines.append(
            f"If #{pr_number} remains green/green-equivalent, run review-queue merge-packet for the PR. Do not merge."
        )
    elif action == "diagnose_branch_conflict":
        lines.append(
            f"Checks are green/green-equivalent, but #{pr_number} is still CONFLICTING/DIRTY. Diagnose only the live branch conflict or merge-packet blocker and produce a bounded repair prompt. Do not merge."
        )

    lines.extend(
        [
            "",
            "Final report must include root state, active/conflict lanes, head/check state, action withheld/taken, and a recursive best next prompt.",
            INCREMENTAL_PROGRESS_SENTENCE,
            META_AUTOMATION_SENTENCE,
        ]
    )
    return "\n".join(lines)


def _run_gh_json(args: list[str]) -> dict[str, Any]:
    completed = subprocess.run(args, check=True, text=True, capture_output=True)
    return json.loads(completed.stdout)


def _run_gh_log(args: list[str]) -> str:
    completed = subprocess.run(args, check=True, text=True, capture_output=True)
    return completed.stdout


def wait_for_run(
    run_id: str,
    *,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> tuple[dict[str, Any], bool]:
    """Poll a GitHub Actions run until it completes or the timeout expires."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    latest: dict[str, Any] | None = None
    while True:
        latest = _run_gh_json(
            [
                "gh",
                "run",
                "view",
                run_id,
                "--json",
                "status,conclusion,event,headSha,workflowName,jobs",
            ]
        )
        if str(latest.get("status") or "").lower() == "completed":
            return latest, False
        if time.monotonic() >= deadline:
            return latest, True
        time.sleep(max(0.0, poll_interval_seconds))


def _fetch_logs_for_failed_jobs(run_id: str, run_data: dict[str, Any]) -> dict[str, list[str]]:
    summaries: dict[str, list[str]] = {}
    for job in run_data.get("jobs") or []:
        if not isinstance(job, dict):
            continue
        job_id = _job_id(job)
        conclusion = str(job.get("conclusion") or "").upper()
        if not job_id or conclusion not in FAILURE_CONCLUSIONS:
            continue
        try:
            log_text = _run_gh_log(["gh", "run", "view", run_id, "--job", job_id, "--log"])
            summaries[job_id] = summarize_log(log_text)
        except subprocess.CalledProcessError:
            summaries[job_id] = ["failed to fetch job log"]
    return summaries


def fetch_live_result(
    pr_number: int,
    *,
    expected_head: str | None,
    include_logs: bool,
    allow_rerun_commands: bool,
    wait_run_id: str | None = None,
    wait_check: str | None = None,
    wait_interval_seconds: float = 180.0,
    wait_timeout_seconds: float = 1800.0,
) -> FollowupResult:
    """Fetch live PR/run data through gh and build a follow-up result."""
    pr_data = _run_gh_json(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,state,isDraft,headRefName,headRefOid,mergeable,mergeStateStatus,statusCheckRollup,url",
        ]
    )
    head = str(pr_data.get("headRefOid") or "")
    run_data_by_id: dict[str, dict[str, Any]] = {}
    log_summary_by_job: dict[str, list[str]] = {}
    wait_run: WaitRunDiagnosis | None = None

    if wait_run_id is None and wait_check:
        wait_run_id = wait_check_run_id(pr_data, wait_check)

    if wait_run_id:
        run_data, timed_out = wait_for_run(
            wait_run_id,
            poll_interval_seconds=wait_interval_seconds,
            timeout_seconds=wait_timeout_seconds,
        )
        run_data_by_id[wait_run_id] = run_data
        log_summary_by_job.update(_fetch_logs_for_failed_jobs(wait_run_id, run_data))
        wait_run = diagnose_wait_run(
            wait_run_id,
            run_data,
            pr_head=head,
            timed_out=timed_out,
            log_summary_by_job=log_summary_by_job,
        )

    for check in latest_status_check_rollup(list(pr_data.get("statusCheckRollup") or [])):
        diagnosis = classify_check(check, head)
        if diagnosis.classification not in {"real_failure", "early_cancelled", "unknown"}:
            continue
        if not diagnosis.run_id or not diagnosis.job_id or diagnosis.run_id in run_data_by_id:
            continue
        try:
            run_data_by_id[diagnosis.run_id] = _run_gh_json(
                [
                    "gh",
                    "run",
                    "view",
                    diagnosis.run_id,
                    "--json",
                    "status,conclusion,event,headSha,workflowName,jobs",
                ]
            )
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
        should_fetch_log = include_logs or (
            diagnosis.classification == "real_failure"
            and (_is_merge_quorum_check(diagnosis) or _is_security_gate_check(diagnosis))
        )
        if should_fetch_log and diagnosis.classification == "real_failure":
            try:
                log_text = _run_gh_log(
                    ["gh", "run", "view", diagnosis.run_id, "--job", diagnosis.job_id, "--log"]
                )
                log_summary_by_job[diagnosis.job_id] = summarize_log(log_text)
            except subprocess.CalledProcessError:
                log_summary_by_job[diagnosis.job_id] = ["failed to fetch job log"]

    preliminary = build_followup_result(
        pr_data,
        expected_head=expected_head,
        run_data_by_id=run_data_by_id,
        log_summary_by_job=log_summary_by_job,
        wait_run=wait_run,
        allow_rerun_commands=allow_rerun_commands,
    )
    superseding_dependency_prs_by_job = _find_superseding_dependency_prs_by_job(
        pr_number=int(pr_data.get("number") or pr_number),
        checks=preliminary.checks,
    )
    if not superseding_dependency_prs_by_job:
        return preliminary
    return build_followup_result(
        pr_data,
        expected_head=expected_head,
        run_data_by_id=run_data_by_id,
        log_summary_by_job=log_summary_by_job,
        superseding_dependency_prs_by_job=superseding_dependency_prs_by_job,
        wait_run=wait_run,
        allow_rerun_commands=allow_rerun_commands,
    )


def _result_to_json(result: FollowupResult) -> str:
    payload = asdict(result)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return json.dumps(payload, indent=2, sort_keys=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True, help="Pull request number to inspect")
    parser.add_argument("--head", help="Expected PR head SHA; head drift stops the prompt")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--prompt", action="store_true", help="Print the recursive prompt")
    parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Fetch failed job logs and include concise failure snippets",
    )
    parser.add_argument(
        "--allow-rerun-commands",
        action="store_true",
        help="Include exact rerun commands when only current-head early cancellations remain",
    )
    parser.add_argument(
        "--wait-run",
        help="Poll one GitHub Actions run until completion before generating the prompt",
    )
    parser.add_argument(
        "--wait-check",
        help="Poll the run for an in-progress status check selected as 'Workflow/Check name'",
    )
    parser.add_argument(
        "--wait-interval-seconds",
        type=float,
        default=180.0,
        help="Polling interval for --wait-run (default: 180)",
    )
    parser.add_argument(
        "--wait-timeout-seconds",
        type=float,
        default=1800.0,
        help="Maximum wait duration for --wait-run (default: 1800)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    result = fetch_live_result(
        args.pr,
        expected_head=args.head,
        include_logs=args.include_logs,
        allow_rerun_commands=args.allow_rerun_commands,
        wait_run_id=args.wait_run,
        wait_check=args.wait_check,
        wait_interval_seconds=args.wait_interval_seconds,
        wait_timeout_seconds=args.wait_timeout_seconds,
    )
    if args.json:
        print(_result_to_json(result))
    if args.prompt or not args.json:
        print(result.prompt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
