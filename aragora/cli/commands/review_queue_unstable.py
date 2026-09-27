"""Verified handling for allowlisted non-required cancellation noise.

This module contains the narrowly scoped exception documented in
``MERGE_STATE_UNSTABLE_SETTLEMENT.md``. It deliberately fails closed unless
the cancelled run is allowlisted, belongs to the exact PR head, stopped before
its substantive verifier steps, and every required check is green.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from aragora.cli.commands import review_queue_rest_fallback as rest_fallback
from aragora.cli.commands.review_queue_transport import _GhError

UNSTABLE_CANCELLATION_POLICY_PATH = "docs/runbooks/MERGE_STATE_UNSTABLE_SETTLEMENT.md"
UNSTABLE_ALLOWLISTED_WORKFLOW_PATHS: dict[str, str] = {
    "Build Documentation (PR Check)": ".github/workflows/docs-build.yml",
    "Docs Consistency": ".github/workflows/docs-consistency.yml",
    "Portability Lint": ".github/workflows/portability-lint.yml",
    "Self-Hosted Shadow CI": ".github/workflows/self-hosted-shadow.yml",
}
# A PR that edits any of these files could smuggle substantive work into an
# allowlisted job (or weaken this gate) and then present its own cancellation
# as harmless noise, so such PRs never qualify for the UNSTABLE exception.
UNSTABLE_RECEIPT_GUARD_PATHS: frozenset[str] = frozenset(
    {
        *UNSTABLE_ALLOWLISTED_WORKFLOW_PATHS.values(),
        ".github/workflows/required-check-priority.yml",
        "aragora/cli/commands/review_queue_unstable.py",
        "scripts/check_required_check_priority_policy.py",
    }
)
UNSTABLE_CANCELLED_CONTEXT_VERIFIERS: dict[tuple[str, str], tuple[str, ...]] = {
    ("Build Documentation (PR Check)", "build"): (
        "Update doc stats",
        "Sync documentation",
        "Check capability matrix is synced",
        "Check command guidance drift",
        "Check CLI reference is synced",
        "Ensure docs are synced",
        "Generate capability matrix summary artifact",
        "Build documentation",
        "Check for broken links",
    ),
    ("Docs Consistency", "Docs Consistency"): (
        "Run docs consistency lint",
        "Inspect cold-review proof surface",
    ),
    ("Portability Lint", "portability"): ("Portability guard (no new private/legacy references)",),
    ("Self-Hosted Shadow CI", "Mac TypeScript SDK Shadow"): ("Run TypeScript SDK typecheck",),
}


def _is_injected_wrapup_step(name: str) -> bool:
    """GitHub-injected wrap-up steps that may legitimately succeed after a
    mid-job cancellation (action post-hooks and job teardown). Authored steps
    may not use these names; the policy check enforces that in CI."""
    return name == "Complete job" or name.startswith("Post ") or name.startswith("Stop containers")


def _pr_modifies_guarded_paths(
    *,
    pr_number: int,
    repo_slug: str,
    gh_json: Callable[[list[str]], Any],
) -> bool:
    """Fail closed unless the PR provably avoids every receipt-guarded path.

    Uses the REST files listing because it reports `previous_filename` for
    renames — a rename away from a guarded file must disqualify the PR just
    like an in-place edit, and the GraphQL `files` surface only shows the
    new path."""
    args = [
        "api",
        f"repos/{repo_slug}/pulls/{pr_number}/files",
        "--paginate",
        "--slurp",
    ]
    try:
        payload = gh_json(args)
    except _GhError:
        return True
    if not isinstance(payload, list):
        return True
    entries: list[Any] = []
    for page in payload:
        if not isinstance(page, list):
            return True
        entries.extend(page)
    # A pull request always changes at least one file; an empty listing means
    # the lookup cannot be trusted.
    if not entries:
        return True
    for entry in entries:
        if not isinstance(entry, dict):
            return True
        for key in ("filename", "previous_filename"):
            value = entry.get(key)
            if value and str(value).strip() in UNSTABLE_RECEIPT_GUARD_PATHS:
                return True
    return False


def _review_queue_backend() -> Any:
    """Resolve the parent module lazily so its monkeypatch seams remain stable."""
    from aragora.cli.commands import review_queue

    return review_queue


def _normalized_rollup_conclusion(check: dict[str, Any]) -> str:
    conclusion = str(check.get("conclusion") or "").strip().upper()
    if conclusion:
        return conclusion
    state = str(check.get("status") or check.get("state") or "").strip().upper()
    if state in {
        "SUCCESS",
        "FAILURE",
        "TIMED_OUT",
        "ACTION_REQUIRED",
        "CANCELLED",
        "SKIPPED",
        "NEUTRAL",
        "STALE",
    }:
        return state
    if state in {"ERROR", "FAILED"}:
        return "FAILURE"
    return ""


def _actions_run_job_ids(details_url: str, repo_slug: str) -> tuple[str, str] | None:
    parsed = urlparse(details_url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "github.com":
        return None
    expected_prefix = f"/{repo_slug.strip('/')}/actions/runs/"
    if not repo_slug or not parsed.path.startswith(expected_prefix):
        return None
    suffix = parsed.path.removeprefix(expected_prefix)
    match = re.fullmatch(r"(?P<run>\d+)/job/(?P<job>\d+)/?", suffix)
    if not match:
        return None
    return match.group("run"), match.group("job")


def _verify_cancelled_context_run(
    *,
    check: dict[str, Any],
    head_sha: str,
    repo_slug: str,
    gh_json: Callable[[list[str]], Any],
) -> dict[str, Any] | None:
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    verifier_names = UNSTABLE_CANCELLED_CONTEXT_VERIFIERS.get((workflow, name))
    if not verifier_names:
        return None

    details_url = str(check.get("detailsUrl") or check.get("link") or "").strip()
    run_job_ids = _actions_run_job_ids(details_url, repo_slug)
    if not run_job_ids:
        return None
    run_id, job_id = run_job_ids
    args = [
        "run",
        "view",
        run_id,
        "--json",
        "headSha,status,conclusion,workflowName,jobs",
    ]
    if repo_slug:
        args.extend(["--repo", repo_slug])
    try:
        run = gh_json(args)
    except _GhError:
        return None
    if not isinstance(run, dict):
        return None
    if str(run.get("headSha") or "").strip() != head_sha:
        return None
    if str(run.get("workflowName") or "").strip() != workflow:
        return None
    if str(run.get("status") or "").strip().upper() != "COMPLETED":
        return None
    if str(run.get("conclusion") or "").strip().upper() != "CANCELLED":
        return None

    job: dict[str, Any] | None = None
    for candidate in run.get("jobs") or []:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("databaseId") or candidate.get("id") or "").strip() == job_id:
            job = candidate
            break
    if not job:
        return None
    if str(job.get("name") or "").strip() != name:
        return None
    if str(job.get("status") or "").strip().upper() != "COMPLETED":
        return None
    if str(job.get("conclusion") or "").strip().upper() != "CANCELLED":
        return None

    raw_steps = job.get("steps")
    if (
        not isinstance(raw_steps, list)
        or not raw_steps
        or any(not isinstance(step, dict) for step in raw_steps)
    ):
        return None
    steps = raw_steps
    verifier_steps = [
        step for step in steps if str(step.get("name") or "").strip() in verifier_names
    ]
    if {str(step.get("name") or "").strip() for step in verifier_steps} != set(verifier_names):
        return None
    if any(
        str(step.get("conclusion") or "").strip().upper() != "SKIPPED" for step in verifier_steps
    ):
        return None
    # Enumerated names alone are fail-open under additive drift: a substantive
    # step added to the job after this allowlist was written would be invisible.
    # Require every step from the first verifier onward to have been skipped or
    # cancelled, whatever its name (GitHub-injected wrap-up steps exempt).
    first_verifier_index = min(
        index
        for index, step in enumerate(steps)
        if str(step.get("name") or "").strip() in verifier_names
    )
    for step in steps[first_verifier_index:]:
        step_name = str(step.get("name") or "").strip()
        conclusion = str(step.get("conclusion") or "").strip().upper()
        if conclusion in {"SKIPPED", "CANCELLED"}:
            continue
        if _is_injected_wrapup_step(step_name):
            continue
        return None

    return {
        "workflow": workflow,
        "name": name,
        "url": details_url,
        "run_id": int(run_id),
        "job_id": int(job_id),
        "head_sha": head_sha,
        "conclusion": "CANCELLED",
        "reason": (
            "allowlisted non-required current-head run cancelled before "
            "substantive verifier command"
        ),
        "verifier_steps": [
            {
                "name": str(step.get("name") or "").strip(),
                "conclusion": str(step.get("conclusion") or "").strip().upper(),
            }
            for step in verifier_steps
        ],
    }


def verified_unstable_non_required_cancellation_receipt(
    *,
    pr: dict[str, Any],
    pr_number: int,
    repo_override: str | None,
) -> dict[str, Any]:
    """Return an exact-head receipt for fully verified advisory cancellations."""
    if str(pr.get("mergeStateStatus") or "").strip().upper() != "UNSTABLE":
        return {}
    head_sha = str(pr.get("headRefOid") or "").strip()
    rollup = pr.get("statusCheckRollup")
    if not head_sha or not isinstance(rollup, list):
        return {}

    backend = _review_queue_backend()
    latest_checks = backend._latest_status_check_rollup(rollup)
    cancelled_checks: list[dict[str, Any]] = []
    for check in latest_checks:
        if not isinstance(check, dict) or backend._is_current_merge_quorum_self_check(check):
            continue
        conclusion = _normalized_rollup_conclusion(check)
        if conclusion in {"SUCCESS", "SKIPPED", "NEUTRAL"}:
            continue
        if conclusion == "CANCELLED":
            cancelled_checks.append(check)
            continue
        # Anything else — in-flight, unknown, or failing — fails closed.
        return {}
    if not cancelled_checks:
        return {}
    for check in cancelled_checks:
        workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
        name = str(check.get("name") or check.get("context") or "").strip()
        if (workflow, name) not in UNSTABLE_CANCELLED_CONTEXT_VERIFIERS:
            return {}

    required_surface = backend._fetch_required_pr_check_surface(pr_number, repo_override)
    required_checks = [
        check for check in required_surface.get("checks") or [] if isinstance(check, dict)
    ]
    if not required_surface.get("available") or not required_checks:
        return {}
    if not any(backend._is_merge_quorum_check(check) for check in required_checks):
        return {}
    effective_required = backend._effective_required_pr_checks(required_checks)
    if not effective_required:
        return {}
    if any(backend._required_pr_check_bucket(check) != "pass" for check in effective_required):
        return {}
    if any(
        backend._rollup_check_matches_required(check, required_checks) for check in cancelled_checks
    ):
        return {}

    repo_slug = rest_fallback._repo_slug_from_pr_payload(pr, repo_override)
    if not repo_slug:
        return {}
    if _pr_modifies_guarded_paths(
        pr_number=pr_number,
        repo_slug=repo_slug,
        gh_json=backend._gh_json,
    ):
        return {}
    verified_contexts: list[dict[str, Any]] = []
    for check in cancelled_checks:
        verified = _verify_cancelled_context_run(
            check=check,
            head_sha=head_sha,
            repo_slug=repo_slug,
            gh_json=backend._gh_json,
        )
        if not verified:
            return {}
        verified_contexts.append(verified)

    required_summary, required_failures, required_pending = backend._summarize_required_pr_checks(
        required_checks
    )
    if required_failures or required_pending:
        return {}
    return {
        "schema_version": "unstable_non_required_cancellation.v1",
        "head_sha": head_sha,
        "merge_state_status": "UNSTABLE",
        "policy_path": UNSTABLE_CANCELLATION_POLICY_PATH,
        "required_checks_summary": required_summary,
        "current_merge_quorum_self_check_ignored": (
            len(effective_required) != len(required_checks)
        ),
        "required_checks": [
            {
                "workflow": str(check.get("workflow") or "").strip(),
                "name": str(check.get("name") or "").strip(),
                "state": str(check.get("state") or "").strip(),
                "link": str(check.get("link") or "").strip(),
            }
            for check in effective_required
        ],
        "ignored_contexts": verified_contexts,
    }


def attach_verified_cancellation_receipt(
    *,
    pr: dict[str, Any],
    pr_number: int,
    repo_override: str | None,
    check_surfaces: dict[str, Any],
) -> dict[str, Any]:
    receipt = verified_unstable_non_required_cancellation_receipt(
        pr=pr,
        pr_number=pr_number,
        repo_override=repo_override,
    )
    if receipt:
        check_surfaces["unstable_non_required_cancellation_receipt"] = receipt
    return receipt


def attach_verified_cancellation_contexts(
    *,
    pr: dict[str, Any],
    pr_number: int,
    repo_override: str | None,
    check_surfaces: dict[str, Any],
) -> list[dict[str, Any]]:
    """Attach the receipt and return its ignored contexts for the packet."""
    receipt = attach_verified_cancellation_receipt(
        pr=pr,
        pr_number=pr_number,
        repo_override=repo_override,
        check_surfaces=check_surfaces,
    )
    return list(receipt.get("ignored_contexts") or [])


def _verified_unstable_cancellation_override(packet: Any) -> bool:
    receipt = packet.check_surfaces.get("unstable_non_required_cancellation_receipt")
    if not isinstance(receipt, dict):
        return False
    ignored = receipt.get("ignored_contexts")
    if not isinstance(ignored, list) or not ignored:
        return False
    if ignored != packet.unstable_non_required_contexts_ignored:
        return False
    if str(receipt.get("head_sha") or "").strip() != packet.head_sha:
        return False
    if str(receipt.get("merge_state_status") or "").strip().upper() != "UNSTABLE":
        return False
    if str(receipt.get("policy_path") or "").strip() != UNSTABLE_CANCELLATION_POLICY_PATH:
        return False
    if not receipt.get("required_checks"):
        return False

    backend = _review_queue_backend()
    if bool(receipt.get("current_merge_quorum_self_check_ignored")) and not (
        os.environ.get("GITHUB_WORKFLOW") == backend.MERGE_QUORUM_WORKFLOW_NAME
        and os.environ.get("GITHUB_JOB") == backend.MERGE_QUORUM_JOB_ID
    ):
        return False
    quorum = packet.model_review_quorum
    if not bool(quorum.get("admin_squash_allowed")):
        return False
    if bool(quorum.get("unresolved_dissent")):
        return False
    return all(
        isinstance(context, dict)
        and str(context.get("head_sha") or "").strip() == packet.head_sha
        and str(context.get("conclusion") or "").strip().upper() == "CANCELLED"
        for context in ignored
    )


def admin_squash_live_gate_blockers(packet: Any) -> list[str]:
    backend = _review_queue_backend()
    blockers: list[str] = []
    labels = {str(label).strip().lower() for label in packet.labels if str(label).strip()}
    if backend.OPERATOR_REVIEW_REQUIRED_LABEL in labels:
        blockers.append("operator-review-required label present")

    merge_state_status = str(packet.merge_state_status or "").strip().upper()
    if not merge_state_status:
        blockers.append("mergeStateStatus unavailable; admin squash requires CLEAN or BLOCKED")
    elif merge_state_status == "UNSTABLE" and _verified_unstable_cancellation_override(packet):
        pass
    elif merge_state_status not in {"CLEAN", "BLOCKED"}:
        blockers.append(
            f"mergeStateStatus={merge_state_status}; admin squash requires CLEAN or BLOCKED"
        )
    return blockers


def render_verified_cancellations(
    entry: dict[str, Any], emit: Callable[[str], None] = print
) -> None:
    ignored_contexts = entry.get("unstable_non_required_contexts_ignored") or []
    if not ignored_contexts:
        return
    emit("  verified UNSTABLE advisory cancellations ignored:")
    for context in ignored_contexts:
        emit(
            "    - "
            f"{context.get('workflow', '')} / {context.get('name', '')}: "
            f"{context.get('url', '')}"
        )
