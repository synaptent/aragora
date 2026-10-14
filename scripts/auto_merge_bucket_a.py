"""Stage 2 of the operator-delegation rollout — auto-merge Bucket A PRs.

Implements ``docs/roadmap/OPERATOR_DELEGATION_ROLLOUT.md`` Stage 2:

  - Reads the Stage 1 classifier output from ``scripts/triage_open_prs.py``.
  - For every PR classified as Bucket A, decides whether to ``gh pr merge
    --squash`` it.
  - Default ``--dry-run``: prints the intended merges, never mutates.
  - With ``--apply``: merges only PRs in Bucket A; never touches B/C/D.
  - Settling window: skip any PR whose most recent commit is younger
    than ``--settling-minutes`` (default 30) — gives sibling tooling
    and CI a chance to catch late breakage.
  - Defense-in-depth tripwires: a second, independent re-check of the
    PR's files, labels, draft status, mergeable status, and CI rollup.
    Any hit aborts that PR (with ``--apply``, exits the run non-zero
    overall to make the failure loud).
  - Writes durable intent/final receipts to
    ``docs/status/AUTO_MERGE_RECEIPT_<utc>_{INTENT,FINAL}.md`` on every
    ``--apply`` run, with the PR list, the policy version, and the
    sha256 of the classifier output.

Pure stdlib + ``gh`` subprocess. No ``aragora.*`` imports. No third-
party deps.

CLI::

    python3 scripts/auto_merge_bucket_a.py [--apply]
                                           [--settling-minutes N]
                                           [--only-pr N]
                                           [--delete-branch-on-merge]
                                           [--json]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
TRIAGE_SCRIPT = REPO_ROOT / "scripts" / "triage_open_prs.py"
RECEIPT_DIR = REPO_ROOT / "docs" / "status"
POLICY_DOC = REPO_ROOT / "docs" / "governance" / "OPERATOR_DELEGATION_POLICY.md"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from aragora.config.trusted_authors import (  # noqa: E402
    TRUSTED_AUTHORS_ENV as GLOBAL_TRUSTED_AUTHORS_ENV,
    resolve_trusted_authors,
)
from aragora.swarm.merge_halt import assert_merge_allowed  # noqa: E402
from scripts.post_merge_lane_audit import (  # noqa: E402
    post_merge_lane_audit_failed,
    post_merge_lane_audit_failure_reason,
    run_post_merge_lane_audit,
)

BUCKET_A = "A"

DEFAULT_SETTLING_MINUTES = 30

# Defense-in-depth tripwires. These intentionally duplicate the
# triage classifier's most dangerous checks so a future bug in the
# classifier can't accidentally bless an unsafe PR.
PROTECTED_PATHS: frozenset[str] = frozenset(
    {
        "CLAUDE.md",
        "AGENTS.md",
        "aragora/__init__.py",
        ".env",
        ".envrc",
        "scripts/auto_merge_bucket_a.py",
        "scripts/nomic_loop.py",
        "scripts/triage_open_prs.py",
        "docs/AGENT_OPERATING_CONTRACT.md",
        "docs/governance/OPERATOR_DELEGATION_POLICY.md",
        "automation.toml",
    }
)

PROTECTED_PREFIXES: tuple[str, ...] = (
    ".github/workflows/",
    "aragora/cli/",
    "aragora/policy/",
    "secrets/",
)

# No personal login is trusted by default; operators opt in via the global
# ARAGORA_TRUSTED_AUTHORS or the bucket-specific env var below.
DEFAULT_TRUSTED_AUTHORS: frozenset[str] = frozenset()
TRUSTED_AUTHORS_ENV = "ARAGORA_BUCKET_A_TRUSTED_AUTHORS"

# Labels that require a human/operator stop even if Stage 1 accidentally
# classifies the PR as Bucket A. Normalization maps spaces/underscores to "-".
BLOCKING_LABELS: frozenset[str] = frozenset(
    {
        "autonomous",
        "boss-ready",
        "do-not-merge",
        "hold",
        "manual-review",
        "manual-review-required",
        "needs-human-review",
        "needs-manual-review",
    }
)

PENDING_CHECK_STATUSES: frozenset[str] = frozenset(
    {
        "IN_PROGRESS",
        "PENDING",
        "QUEUED",
        "REQUESTED",
        "WAITING",
    }
)
RED_STATUS_CONTEXT_STATES: frozenset[str] = frozenset({"ERROR", "FAILURE"})
PENDING_STATUS_CONTEXT_STATES: frozenset[str] = frozenset({"EXPECTED", "PENDING"})
GREEN_STATUS_CONTEXT_STATES: frozenset[str] = frozenset({"SUCCESS"})
ALLOWED_COMPLETED_CONCLUSIONS: frozenset[str] = frozenset({"SUCCESS", "SKIPPED", "NEUTRAL"})


@dataclasses.dataclass(frozen=True)
class MergeDecision:
    pr_number: int
    title: str
    # Common values: "merge", "skip-settling", "skip-tripwire",
    # "skip-non-bucket-a", "skip-stale-snapshot", "merge-failed".
    decision: str
    reason: str
    head_sha: str | None = None
    applied: bool = False
    post_merge_lane_audit: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Subprocess helpers (testable: callers can inject a custom runner)
# ---------------------------------------------------------------------------


Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]
ReviewQueueSourceValidator = Callable[[], str | None]
PostMergeLaneAuditProvider = Callable[[int, bool], dict[str, Any]]


def _default_runner(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, text=True, capture_output=True, check=False)


def trusted_authors(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """Return the configured Bucket-A trusted authors.

    No personal login is trusted by default. Operators opt in without editing
    this script by setting the global ``ARAGORA_TRUSTED_AUTHORS`` or the
    bucket-specific ``ARAGORA_BUCKET_A_TRUSTED_AUTHORS`` to a comma-separated
    login list; the two sources are unioned.
    """
    return resolve_trusted_authors(
        DEFAULT_TRUSTED_AUTHORS,
        env_vars=(GLOBAL_TRUSTED_AUTHORS_ENV, TRUSTED_AUTHORS_ENV),
        env=env,
    )


def _git_stdout(args: list[str], *, cwd: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def _review_queue_source_tripwire() -> str | None:
    """Fail closed unless review-queue authorization comes from current main.

    ``--admin`` is only safe when the code computing the merge packet is not
    branch-local PR code. Dry-runs may still inspect packets, but apply-mode
    BLOCKED merges require the local review-queue source to be exactly
    ``origin/main`` with no local authorization-surface edits.
    """
    head = _git_stdout(["rev-parse", "HEAD"], cwd=REPO_ROOT)
    origin_main = _git_stdout(["rev-parse", "origin/main"], cwd=REPO_ROOT)
    if not head or not origin_main:
        return "review-queue authorization source is unavailable"
    if head != origin_main:
        return (
            "review-queue authorization source is not trusted "
            f"(HEAD {head[:12]} != origin/main {origin_main[:12]})"
        )

    auth_status = _git_stdout(
        ["status", "--short", "--", "aragora/cli", "aragora/policy"], cwd=REPO_ROOT
    )
    if auth_status:
        return "review-queue authorization source has local authorization-surface changes"
    return None


def run_triage(*, runner: Runner | None = None) -> dict[str, Any]:
    """Invoke the Stage 1 classifier and return its JSON output."""
    runner = runner or _default_runner
    proc = runner(["python3", str(TRIAGE_SCRIPT), "--json"])
    if proc.returncode != 0:
        raise RuntimeError(
            f"triage_open_prs.py --json failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return json.loads(proc.stdout or "{}")


def fetch_pr_commit_metadata(pr_number: int, *, runner: Runner | None = None) -> dict[str, Any]:
    """Fetch the gh metadata we need for the defense-in-depth re-check.

    Returns a dict with: ``commits`` (list, newest last), ``files``
    (list of {path, additions, deletions}), ``isDraft`` (bool),
    ``mergeable`` (str), ``mergeStateStatus`` (str), ``statusCheckRollup``
    (list), ``author.login`` (str), ``labels`` (list), ``headRefOid``
    (str), ``reviewDecision`` (str), ``title`` (str).
    """
    runner = runner or _default_runner
    proc = runner(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            (
                "number,title,author,isDraft,mergeable,mergeStateStatus,"
                "labels,files,commits,statusCheckRollup,headRefOid,reviewDecision"
            ),
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr view {pr_number} failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return json.loads(proc.stdout or "{}")


def fetch_merge_packet(pr_number: int, *, runner: Runner | None = None) -> dict[str, Any]:
    """Fetch the review-queue merge-packet for one PR."""
    runner = runner or _default_runner
    proc = runner(
        [
            "python3",
            "-m",
            "aragora.cli.main",
            "review-queue",
            "merge-packet",
            "--pr",
            str(pr_number),
            "--json",
        ]
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"review-queue merge-packet --pr {pr_number} failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return json.loads(proc.stdout or "{}")


def gh_pr_merge_squash(
    pr_number: int,
    head_sha: str,
    delete_branch_on_merge: bool = False,
    admin_squash: bool = False,
    *,
    runner: Runner | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute ``gh pr merge --squash`` for the given PR and exact head.

    Raises ``RuntimeError`` on non-zero exit. Returns the completed
    process so callers can inspect stdout/stderr.
    """
    runner = runner or _default_runner
    assert_merge_allowed(pr_number, head_sha)  # #9216: raises MergeHalted
    args = [
        "gh",
        "pr",
        "merge",
        str(pr_number),
        "--squash",
        "--match-head-commit",
        head_sha,
    ]
    if admin_squash:
        args.append("--admin")
    if delete_branch_on_merge:
        args.append("--delete-branch")
    proc = runner(args)
    if proc.returncode != 0:
        raise RuntimeError(
            f"gh pr merge --squash {pr_number} failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc


# ---------------------------------------------------------------------------
# Defense-in-depth tripwire (independent of Stage 1 classifier)
# ---------------------------------------------------------------------------


def _file_paths(metadata: dict[str, Any]) -> list[str]:
    files = metadata.get("files") or []
    out: list[str] = []
    for entry in files:
        if isinstance(entry, dict):
            path = str(entry.get("path") or "")
            if path:
                out.append(path)
    return out


def _is_protected_path(path: str) -> bool:
    if path in PROTECTED_PATHS:
        return True
    for prefix in PROTECTED_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _normalized_label_name(name: str) -> str:
    return re.sub(r"[\s_]+", "-", name.strip().lower())


def _label_names(metadata: dict[str, Any]) -> set[str]:
    raw = metadata.get("labels") or []
    out: set[str] = set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
        else:
            name = str(item)
        normalized = _normalized_label_name(name)
        if normalized:
            out.add(normalized)
    return out


def _ci_rollup_tripwire(checks: Any) -> str | None:
    if not isinstance(checks, list):
        return "CI rollup unavailable"
    if not checks:
        return "CI rollup empty"

    red_count = 0
    pending_count = 0
    non_green_conclusion: str | None = None

    for check in checks:
        if not isinstance(check, dict):
            return "CI rollup malformed"

        state = str(check.get("state") or "").upper()
        if state in RED_STATUS_CONTEXT_STATES:
            red_count += 1
            continue
        if state in PENDING_STATUS_CONTEXT_STATES:
            pending_count += 1
            continue
        if state:
            if state in GREEN_STATUS_CONTEXT_STATES:
                continue
            if non_green_conclusion is None:
                non_green_conclusion = f"STATUS_CONTEXT_{state}"
            continue

        status = str(check.get("status") or "").upper()
        if not status:
            return "CI rollup malformed"
        if status in PENDING_CHECK_STATUSES:
            pending_count += 1
            continue
        if status and status != "COMPLETED":
            pending_count += 1
            continue

        if status == "COMPLETED":
            conclusion = str(check.get("conclusion") or "(missing)").upper()
            if conclusion not in ALLOWED_COMPLETED_CONCLUSIONS:
                if conclusion == "FAILURE":
                    red_count += 1
                elif non_green_conclusion is None:
                    non_green_conclusion = conclusion

    if red_count:
        return f"CI red ({red_count} failures)"
    if pending_count:
        return f"CI pending ({pending_count} in-flight)"
    if non_green_conclusion is not None:
        return f"CI non-green ({non_green_conclusion})"
    return None


def _merge_packet_allows_blocked_state(
    metadata: dict[str, Any],
    *,
    merge_packet: dict[str, Any] | None,
) -> str | None:
    """Return ``None`` only for an explicit exact-head admin exception."""
    if merge_packet is None:
        return "merge state BLOCKED without merge-packet authorization"
    if merge_packet.get("version") != "merge_authorization_packet.v1":
        return "merge state BLOCKED without explicit review-queue merge authorization"

    pr_number = int(metadata.get("number") or 0)
    head_sha = str(metadata.get("headRefOid") or "")
    if not head_sha:
        return "merge state BLOCKED without head SHA"

    not_ready = merge_packet.get("not_ready")
    if not_ready != []:
        return "merge state BLOCKED but merge-packet not_ready is non-empty"

    entries = merge_packet.get("entries") or []
    review_decision = str(metadata.get("reviewDecision") or "")
    has_current_head_review_approval = review_decision == "APPROVED"
    has_review_queue_settlement = bool(
        str(merge_packet.get("authorization_sentence") or "").strip()
    )
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            entry_pr = int(entry.get("pr_number") or 0)
        except (TypeError, ValueError):
            entry_pr = 0
        if entry_pr != pr_number:
            continue
        if str(entry.get("head_sha") or "") != head_sha:
            return "merge state BLOCKED but merge-packet head does not match"
        if entry.get("admin_squash_allowed") is not True:
            return "merge state BLOCKED but admin squash is not authorized"
        if entry.get("status") != "satisfied":
            return "merge state BLOCKED but merge-packet status is not satisfied"
        if entry.get("verdict") != "admin_squash_allowed":
            return "merge state BLOCKED but merge-packet verdict is not admin_squash_allowed"
        if entry.get("requires_human_risk_settlement") is not False:
            return "merge state BLOCKED but human-risk settlement is required"
        if entry.get("unresolved_dissent") is not False:
            return "merge state BLOCKED but unresolved dissent is present"
        order = merge_packet.get("admin_squash_order") or []
        if pr_number not in order:
            return "merge state BLOCKED but PR is absent from admin_squash_order"
        if not has_current_head_review_approval and not has_review_queue_settlement:
            return (
                "merge state BLOCKED without current-head review approval "
                "or explicit review-queue settlement"
            )
        return None

    return "merge state BLOCKED but PR is absent from merge-packet"


def _fresh_pre_merge_authorization(
    pr_number: int,
    *,
    metadata_provider: Callable[[int], dict[str, Any]],
    merge_packet_provider: Callable[[int], dict[str, Any]],
    review_queue_source_validator: ReviewQueueSourceValidator,
    settling_minutes: int,
    now: datetime.datetime | None,
) -> tuple[dict[str, Any], bool, str | None]:
    """Fetch final metadata and authorization immediately before merge."""

    try:
        metadata = metadata_provider(pr_number)
    except Exception as exc:
        return {}, False, f"metadata fetch failed: {exc}"

    try:
        metadata_number = int(metadata.get("number") or 0)
    except (TypeError, ValueError):
        metadata_number = 0
    if metadata_number != pr_number:
        return metadata, False, f"PR number mismatch (classifier={pr_number}, gh={metadata_number})"

    settling = settling_window_skip_reason(
        metadata,
        settling_minutes=settling_minutes,
        now=now,
    )
    if settling is not None:
        return metadata, False, settling

    merge_packet: dict[str, Any] | None = None
    if str(metadata.get("mergeStateStatus") or "") == "BLOCKED":
        source_tripwire = review_queue_source_validator()
        if source_tripwire is not None:
            return metadata, False, source_tripwire
        try:
            merge_packet = merge_packet_provider(pr_number)
        except Exception as exc:
            return metadata, False, f"merge-packet fetch failed: {exc}"

    tripwire = defense_in_depth_tripwire(metadata, merge_packet=merge_packet)
    if tripwire is not None:
        return metadata, False, tripwire

    admin_squash = (
        str(metadata.get("mergeStateStatus") or "") == "BLOCKED"
        and _merge_packet_allows_blocked_state(metadata, merge_packet=merge_packet) is None
    )
    return metadata, admin_squash, None


def defense_in_depth_tripwire(
    metadata: dict[str, Any],
    *,
    merge_packet: dict[str, Any] | None = None,
) -> str | None:
    """Re-check the dangerous gates Stage 1 already checked.

    Returns a tripwire reason string on hit, or ``None`` if the PR
    clears every defense-in-depth check.
    """

    if bool(metadata.get("isDraft")):
        return "draft (defense-in-depth)"

    mergeable = str(metadata.get("mergeable") or "")
    if mergeable != "MERGEABLE":
        return f"not mergeable (mergeable={mergeable or '(unknown)'})"

    merge_state = str(metadata.get("mergeStateStatus") or "")
    if merge_state == "BLOCKED":
        blocked_reason = _merge_packet_allows_blocked_state(metadata, merge_packet=merge_packet)
        if blocked_reason is not None:
            return blocked_reason
    elif merge_state != "CLEAN":
        return f"merge state not clean (mergeStateStatus={merge_state or '(unknown)'})"

    author_raw = metadata.get("author") or {}
    author = author_raw.get("login", "") if isinstance(author_raw, dict) else str(author_raw)
    if author not in trusted_authors():
        return f"non-trusted author ({author or '(unknown)'})"

    for path in _file_paths(metadata):
        if _is_protected_path(path):
            return f"edits protected path ({path})"

    blocking_labels = sorted(_label_names(metadata) & BLOCKING_LABELS)
    if blocking_labels:
        return f"operator label tripwire ({blocking_labels[0]})"

    ci_tripwire = _ci_rollup_tripwire(metadata.get("statusCheckRollup"))
    if ci_tripwire is not None:
        return ci_tripwire

    return None


# ---------------------------------------------------------------------------
# Settling window
# ---------------------------------------------------------------------------


def _parse_commit_timestamp(raw: str) -> datetime.datetime | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None


def latest_commit_age_minutes(
    metadata: dict[str, Any],
    *,
    now: datetime.datetime | None = None,
) -> float | None:
    """Return age in minutes of the most recent commit on the PR.

    Returns ``None`` if no commit timestamp can be parsed.
    """
    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)
    commits = metadata.get("commits") or []
    latest: datetime.datetime | None = None
    for entry in commits:
        if not isinstance(entry, dict):
            continue
        ts = _parse_commit_timestamp(str(entry.get("committedDate") or ""))
        if ts is None:
            continue
        if latest is None or ts > latest:
            latest = ts
    if latest is None:
        return None
    return (now - latest).total_seconds() / 60.0


def settling_window_skip_reason(
    metadata: dict[str, Any],
    *,
    settling_minutes: int,
    now: datetime.datetime | None = None,
) -> str | None:
    age = latest_commit_age_minutes(metadata, now=now)
    if age is None:
        return "could not parse latest commit timestamp"
    if age < settling_minutes:
        return (
            f"settling window not met (last commit {age:.1f}min ago, need ≥ {settling_minutes}min)"
        )
    return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def decide(
    triage_payload: dict[str, Any],
    *,
    apply: bool,
    settling_minutes: int,
    only_pr: int | None = None,
    metadata_provider: Callable[[int], dict[str, Any]] | None = None,
    merge_packet_provider: Callable[[int], dict[str, Any]] | None = None,
    review_queue_source_validator: ReviewQueueSourceValidator | None = None,
    merger: Callable[[int, str, bool, bool], subprocess.CompletedProcess[str]] | None = None,
    post_merge_lane_audit_provider: PostMergeLaneAuditProvider | None = None,
    apply_post_merge_lane_audit: bool = False,
    delete_branch_on_merge: bool = False,
    now: datetime.datetime | None = None,
) -> tuple[list[MergeDecision], int]:
    """Decide what to do with each PR; return decisions + tripwire exit code.

    Tripwire exit code is 0 if every Bucket A PR was either merged
    (with --apply) or cleanly deferred (settling window). Any
    defense-in-depth tripwire hit forces a non-zero exit code; that
    is the policy's "abort and exit non-zero on any single tripwire"
    requirement.
    """
    metadata_provider = metadata_provider or fetch_pr_commit_metadata
    using_default_merge_packet_provider = merge_packet_provider is None
    merge_packet_provider = merge_packet_provider or fetch_merge_packet
    if review_queue_source_validator is None:
        review_queue_source_validator = (
            _review_queue_source_tripwire if using_default_merge_packet_provider else (lambda: None)
        )
    merger = merger or gh_pr_merge_squash
    if post_merge_lane_audit_provider is None:

        def _default_post_merge_lane_audit(pr: int, audit_apply: bool = False) -> dict[str, Any]:
            return run_post_merge_lane_audit(pr, repo_root=REPO_ROOT, apply=audit_apply)

        post_merge_lane_audit_provider = _default_post_merge_lane_audit

    decisions: list[MergeDecision] = []
    tripwire_exit = 0
    apply_merge_attempted = False

    for entry in triage_payload.get("results") or []:
        if not isinstance(entry, dict):
            continue
        bucket = str(entry.get("bucket") or "")
        pr_number = int(entry.get("pr_number") or 0)
        title = str(entry.get("title") or "")
        if only_pr is not None and pr_number != only_pr:
            continue
        if bucket != BUCKET_A:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="skip-non-bucket-a",
                    reason=f"bucket={bucket} (Stage 2 only acts on A)",
                    applied=False,
                )
            )
            continue

        if apply and apply_merge_attempted:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="skip-stale-snapshot",
                    reason=(
                        "apply mode already attempted one merge from this triage/base snapshot; "
                        "rerun full triage and merge-packet validation before another merge"
                    ),
                    applied=False,
                )
            )
            continue

        try:
            metadata = metadata_provider(pr_number)
        except Exception as exc:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="metadata-fetch-failed",
                    reason=f"metadata fetch failed: {exc}",
                    applied=False,
                )
            )
            tripwire_exit = 1
            continue
        head_sha = str(metadata.get("headRefOid") or "")

        try:
            metadata_number = int(metadata.get("number") or 0)
        except (TypeError, ValueError):
            metadata_number = 0
        if metadata_number != pr_number:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="skip-tripwire",
                    reason=f"PR number mismatch (classifier={pr_number}, gh={metadata_number})",
                    head_sha=head_sha or None,
                    applied=False,
                )
            )
            tripwire_exit = 1
            continue

        settling = settling_window_skip_reason(
            metadata,
            settling_minutes=settling_minutes,
            now=now,
        )
        if settling is not None:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="skip-settling",
                    reason=settling,
                    head_sha=head_sha or None,
                    applied=False,
                )
            )
            continue

        merge_packet: dict[str, Any] | None = None
        if str(metadata.get("mergeStateStatus") or "") == "BLOCKED":
            if apply:
                source_tripwire = review_queue_source_validator()
                if source_tripwire is not None:
                    decisions.append(
                        MergeDecision(
                            pr_number=pr_number,
                            title=title,
                            decision="skip-tripwire",
                            reason=source_tripwire,
                            head_sha=head_sha or None,
                            applied=False,
                        )
                    )
                    tripwire_exit = 1
                    continue
            try:
                merge_packet = merge_packet_provider(pr_number)
            except Exception as exc:
                decisions.append(
                    MergeDecision(
                        pr_number=pr_number,
                        title=title,
                        decision="skip-tripwire",
                        reason=f"merge-packet fetch failed: {exc}",
                        head_sha=head_sha or None,
                        applied=False,
                    )
                )
                tripwire_exit = 1
                continue

        tripwire = defense_in_depth_tripwire(metadata, merge_packet=merge_packet)
        if tripwire is not None:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="skip-tripwire",
                    reason=tripwire,
                    head_sha=head_sha or None,
                    applied=False,
                )
            )
            tripwire_exit = 1
            continue

        if apply:
            fresh_metadata, admin_squash, fresh_tripwire = _fresh_pre_merge_authorization(
                pr_number,
                metadata_provider=metadata_provider,
                merge_packet_provider=merge_packet_provider,
                review_queue_source_validator=review_queue_source_validator,
                settling_minutes=settling_minutes,
                now=now,
            )
            fresh_head_sha = str(fresh_metadata.get("headRefOid") or "")
            if fresh_tripwire is not None:
                decisions.append(
                    MergeDecision(
                        pr_number=pr_number,
                        title=title,
                        decision="skip-tripwire",
                        reason=f"fresh pre-merge validation failed: {fresh_tripwire}",
                        head_sha=fresh_head_sha or head_sha or None,
                        applied=False,
                    )
                )
                tripwire_exit = 1
                continue

            head_sha = fresh_head_sha
            apply_merge_attempted = True
            try:
                merger(pr_number, head_sha, delete_branch_on_merge, admin_squash)
            except RuntimeError as exc:
                decisions.append(
                    MergeDecision(
                        pr_number=pr_number,
                        title=title,
                        decision="merge-failed",
                        reason=str(exc),
                        head_sha=head_sha or None,
                        applied=False,
                    )
                )
                tripwire_exit = 1
                continue
            try:
                post_merge_lane_audit = post_merge_lane_audit_provider(
                    pr_number,
                    apply_post_merge_lane_audit,
                )
            except Exception as exc:
                post_merge_lane_audit = {
                    "audit_ok": False,
                    "audit_applied": False,
                    "audit_apply_requested": apply_post_merge_lane_audit,
                    "audit_error": str(exc),
                }
            reason = "bucket A + tripwire clear + settling window met"
            if post_merge_lane_audit_failed(
                post_merge_lane_audit,
                apply_requested=apply_post_merge_lane_audit,
            ):
                tripwire_exit = 1
                reason = (
                    f"{reason}; post-merge lane audit failed: "
                    f"{post_merge_lane_audit_failure_reason(post_merge_lane_audit)}"
                )
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="merge",
                    reason=reason,
                    head_sha=head_sha or None,
                    applied=True,
                    post_merge_lane_audit=post_merge_lane_audit,
                )
            )
        else:
            decisions.append(
                MergeDecision(
                    pr_number=pr_number,
                    title=title,
                    decision="merge",
                    reason="bucket A + tripwire clear + settling window met (dry-run)",
                    head_sha=head_sha or None,
                    applied=False,
                )
            )

    return decisions, tripwire_exit


# ---------------------------------------------------------------------------
# Receipt
# ---------------------------------------------------------------------------


def _classifier_sha256(triage_payload: dict[str, Any]) -> str:
    serialized = json.dumps(triage_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _policy_version() -> str:
    if not POLICY_DOC.is_file():
        return "unknown"
    text = POLICY_DOC.read_text(encoding="utf-8")
    match = re.search(r"(?im)^\s*version\s*:\s*(?P<version>.+?)\s*$", text)
    if match is not None:
        return match.group("version").strip()
    return "tracked-doc"


def render_receipt(
    decisions: list[MergeDecision],
    *,
    triage_payload: dict[str, Any],
    apply: bool,
    settling_minutes: int,
    now: datetime.datetime | None = None,
) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    lines: list[str] = []
    lines.append("# Auto-merge Bucket A receipt")
    lines.append("")
    lines.append(f"- Generated: `{now.strftime('%Y-%m-%dT%H:%M:%SZ')}`")
    lines.append(f"- Mode: `{'apply' if apply else 'dry-run'}`")
    lines.append(f"- Settling window: `{settling_minutes} min`")
    lines.append(f"- Policy version: `{_policy_version()}`")
    lines.append(f"- Classifier output sha256: `{_classifier_sha256(triage_payload)}`")
    lines.append("")
    lines.append("## Decisions")
    lines.append("")
    if not decisions:
        lines.append("No Bucket A PRs available; nothing to do.")
        lines.append("")
        return "\n".join(lines)
    lines.append("| PR | Decision | Applied | Head SHA | Reason |")
    lines.append("|---|---|---|---|---|")
    for d in decisions:
        head = (d.head_sha or "—")[:12]
        lines.append(
            f"| #{d.pr_number} | `{d.decision}` | {'yes' if d.applied else 'no'} | "
            f"`{head}` | {d.reason} |"
        )
    audit_decisions = [d for d in decisions if d.post_merge_lane_audit is not None]
    if audit_decisions:
        lines.append("")
        lines.append("## Post-merge lane audit")
        lines.append("")
        lines.append("| PR | Findings | Resolved | Blocked reason | Operator apply command |")
        lines.append("|---|---:|---:|---|---|")
        for d in audit_decisions:
            audit = d.post_merge_lane_audit or {}
            command = str(audit.get("operator_apply_command") or "—").replace("|", "\\|")
            lines.append(
                f"| #{d.pr_number} | {audit.get('finding_count', '—')} | "
                f"{audit.get('resolved_count', '—')} | "
                f"{audit.get('blocked_reason') or '—'} | `{command}` |"
            )
    lines.append("")
    return "\n".join(lines)


def render_intent_receipt(
    triage_payload: dict[str, Any],
    *,
    apply: bool,
    settling_minutes: int,
    only_pr: int | None = None,
    now: datetime.datetime | None = None,
) -> str:
    """Render the durable pre-mutation audit record for an apply run."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    lines: list[str] = []
    lines.append("# Auto-merge Bucket A intent receipt")
    lines.append("")
    lines.append(f"- Generated: `{now.strftime('%Y-%m-%dT%H:%M:%SZ')}`")
    lines.append(f"- Mode: `{'apply' if apply else 'dry-run'}`")
    lines.append(f"- Settling window: `{settling_minutes} min`")
    lines.append(f"- Policy version: `{_policy_version()}`")
    lines.append(f"- Classifier output sha256: `{_classifier_sha256(triage_payload)}`")
    if only_pr is not None:
        lines.append(f"- Only PR: `#{only_pr}`")
    lines.append("")
    lines.append(
        "This intent receipt is written before any merge attempt so an interrupted "
        "apply run still leaves durable audit evidence."
    )
    lines.append("")
    lines.append("## Planned Bucket A candidates")
    lines.append("")

    candidates: list[dict[str, Any]] = []
    for entry in triage_payload.get("results") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("bucket") or "") != BUCKET_A:
            continue
        try:
            pr_number = int(entry.get("pr_number") or 0)
        except (TypeError, ValueError):
            pr_number = 0
        if only_pr is not None and pr_number != only_pr:
            continue
        candidates.append(entry)

    if not candidates:
        lines.append("No matching Bucket A PRs were present in the classifier output.")
        lines.append("")
        return "\n".join(lines)

    lines.append("| PR | Title | Classifier reason |")
    lines.append("|---|---|---|")
    for entry in candidates:
        pr_number = int(entry.get("pr_number") or 0)
        title = str(entry.get("title") or "")
        reason = str(entry.get("reason") or "")
        lines.append(f"| #{pr_number} | {title} | {reason} |")
    lines.append("")
    return "\n".join(lines)


def write_receipt(
    receipt_md: str,
    *,
    now: datetime.datetime | None = None,
    receipt_dir: Path | None = None,
    receipt_kind: str | None = None,
) -> Path:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    receipt_dir = receipt_dir or RECEIPT_DIR
    receipt_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    suffix = ""
    if receipt_kind:
        safe_kind = re.sub(r"[^A-Za-z0-9_-]+", "-", receipt_kind.strip()).strip("-").upper()
        if safe_kind:
            suffix = f"_{safe_kind}"
    path = receipt_dir / f"AUTO_MERGE_RECEIPT_{stamp}{suffix}.md"
    path.write_text(receipt_md, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def emit_json(
    decisions: list[MergeDecision],
    *,
    triage_payload: dict[str, Any],
    apply: bool,
    settling_minutes: int,
    receipt_path: Path | None,
) -> str:
    payload = {
        "mode": "apply" if apply else "dry-run",
        "settling_minutes": settling_minutes,
        "policy_version": _policy_version(),
        "classifier_sha256": _classifier_sha256(triage_payload),
        "receipt_path": str(receipt_path) if receipt_path else None,
        "decisions": [dataclasses.asdict(d) for d in decisions],
    }
    return json.dumps(payload, indent=2)


def emit_table(decisions: list[MergeDecision], *, apply: bool) -> str:
    lines: list[str] = []
    lines.append(f"auto_merge_bucket_a — mode={'apply' if apply else 'dry-run'}")
    if not decisions:
        lines.append("  (no Bucket A PRs)")
        return "\n".join(lines)
    for d in decisions:
        applied = "[applied]" if d.applied else "[skipped]"
        head = (d.head_sha or "—")[:10]
        lines.append(f"  #{d.pr_number:<5d} {applied:9s} {d.decision:24s} head={head} — {d.reason}")
        lines.append(f"      title: {d.title}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Stage 2 of operator-delegation rollout — auto-merge Bucket A PRs.")
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually merge. Without this, runs dry-run by default.",
    )
    parser.add_argument(
        "--settling-minutes",
        type=int,
        default=DEFAULT_SETTLING_MINUTES,
        help=(
            "Skip PRs whose latest commit is younger than this "
            f"(default {DEFAULT_SETTLING_MINUTES})."
        ),
    )
    parser.add_argument(
        "--only-pr",
        type=int,
        default=None,
        help="Process only this PR number (still bucket-A gated).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable table.",
    )
    parser.add_argument(
        "--delete-branch-on-merge",
        action="store_true",
        help="Delete merged PR branches. Default keeps branches for auditability.",
    )
    parser.add_argument(
        "--apply-post-merge-lane-audit",
        action="store_true",
        help=(
            "After a successful protected merge, apply the merged-PR lane audit "
            "with operator authorization and the live merge commit guard. "
            "Default is dry-run/report only."
        ),
    )

    args = parser.parse_args(argv)

    if args.settling_minutes < 0:
        print("error: --settling-minutes must be non-negative", file=sys.stderr)
        return 2
    if args.apply_post_merge_lane_audit and not args.apply:
        print("error: --apply-post-merge-lane-audit requires --apply", file=sys.stderr)
        return 2

    try:
        triage_payload = run_triage()
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    run_started_at = datetime.datetime.now(datetime.timezone.utc)
    receipt_path: Path | None = None
    if args.apply:
        receipt_md = render_intent_receipt(
            triage_payload,
            apply=True,
            settling_minutes=args.settling_minutes,
            only_pr=args.only_pr,
            now=run_started_at,
        )
        try:
            receipt_path = write_receipt(receipt_md, now=run_started_at, receipt_kind="INTENT")
        except OSError as exc:
            print(f"error: could not write pre-merge receipt: {exc}", file=sys.stderr)
            return 2

    decisions, tripwire_exit = decide(
        triage_payload,
        apply=args.apply,
        settling_minutes=args.settling_minutes,
        only_pr=args.only_pr,
        delete_branch_on_merge=args.delete_branch_on_merge,
        apply_post_merge_lane_audit=args.apply_post_merge_lane_audit,
    )

    if args.apply:
        receipt_md = render_receipt(
            decisions,
            triage_payload=triage_payload,
            apply=True,
            settling_minutes=args.settling_minutes,
            now=run_started_at,
        )
        try:
            receipt_path = write_receipt(receipt_md, now=run_started_at, receipt_kind="FINAL")
        except OSError as exc:
            print(f"error: could not write final receipt: {exc}", file=sys.stderr)
            return 2

    if args.json:
        print(
            emit_json(
                decisions,
                triage_payload=triage_payload,
                apply=args.apply,
                settling_minutes=args.settling_minutes,
                receipt_path=receipt_path,
            )
        )
    else:
        print(emit_table(decisions, apply=args.apply))
        if receipt_path is not None:
            print(f"receipt: {receipt_path}")

    return tripwire_exit


if __name__ == "__main__":
    sys.exit(main())
