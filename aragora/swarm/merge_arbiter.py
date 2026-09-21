"""Admin merge arbiter for automation PRs.

Polls open automation PRs matching configured branch prefixes and auto-merges
only ready PRs whose branch-protection checks and ready-only full-suite checks
have all passed. Draft PRs are never auto-merged here; the boss loop owns draft
promotion separately.

Usage:
    arbiter = MergeArbiter()
    await arbiter.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from aragora.config.trusted_authors import resolve_trusted_authors
from aragora.swarm.auto_merge_green import _reduce_rollup_states
from aragora.swarm.github_app_auth import gh_subprocess_run
from aragora.swarm.merge_quorum_io import (
    fetch_evidence_comments,
    fetch_pr_context,
    fetch_pr_tier,
)
from aragora.swarm.merge_quorum_reconcile import TIER_REQUIREMENTS, counted_reviewer_ids
from aragora.swarm.quorum_evidence import (
    DEFAULT_FAMILIES,
    collect_evidence,
    resolve_author,
)

logger = logging.getLogger(__name__)

REQUIRED_CHECKS: list[str] = [
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
]
AUTOMATION_BRANCH_PREFIXES: list[str] = [
    "codex/",
    "factory/",
    "aragora/boss-harvest/",
]
PASSING_CHECK_STATES = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED"})
READY_SUITE_GATE_CHECKS = frozenset({"Prioritize Required Checks"})
REDUCED_LANE_ONLY_CHECKS = frozenset(
    {
        "PR Admission Signal (Advisory)",
        "Prioritize Required Checks",
        "OpenAPI Scope",
        "SDK Change Detection",
        "publish-draft-pr",
        "review",
        "changes",
    }
)
# Generic automation identities only; operators add personal logins via
# ARAGORA_TRUSTED_AUTHORS (comma separated) so a public fork trusts no handle.
AUTOMATION_REVIEWER_LOGINS = resolve_trusted_authors(
    {
        "github-actions[bot]",
        "dependabot[bot]",
        "aragora-automation[bot]",
    }
)
_FULL_HEAD_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass
class MergeArbiterConfig:
    """Configuration for the merge arbiter polling loop."""

    repo: str = "synaptent/aragora"
    branch_prefixes: list[str] = field(default_factory=lambda: list(AUTOMATION_BRANCH_PREFIXES))
    poll_interval_seconds: float = 120.0
    max_runtime_hours: float = 12.0
    max_consecutive_failures: int = 3
    dry_run: bool = False
    # When True, the arbiter auto-collects model-quorum evidence for ready
    # candidates blocked solely on the quorum check (Tier 0-2 only). Posting is
    # tier-gated inside collect_evidence; high-tier PRs never auto-post.
    auto_collect_evidence: bool = True
    # Reviewer families for auto-collection; falls back to DEFAULT_FAMILIES.
    reviewer_families: list[str] | None = None


@dataclass
class MergeResult:
    """Outcome of a single merge attempt."""

    pr_number: int
    branch: str
    success: bool
    reason: str


@dataclass
class ArbiterSummary:
    """Final summary when the arbiter exits."""

    merged: list[int] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)
    failed: list[int] = field(default_factory=list)
    polls: int = 0
    stop_reason: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "merged": self.merged,
            "skipped": self.skipped,
            "failed": self.failed,
            "polls": self.polls,
            "stop_reason": self.stop_reason,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }


def _classify_required_checks(
    checks: dict[str, str],
    *,
    required_checks: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Split required checks into missing and failing buckets."""
    missing: list[str] = []
    failing: list[str] = []
    for name in required_checks or REQUIRED_CHECKS:
        status = checks.get(name)
        if status is None:
            missing.append(name)
        elif status != "SUCCESS":
            failing.append(f"{name}={status}")
    return missing, failing


def _normalize_branch_prefixes(branch_prefixes: list[str] | None) -> list[str]:
    """Normalize configured prefixes to the canonical automation branch forms."""
    raw_prefixes = list(branch_prefixes or AUTOMATION_BRANCH_PREFIXES)
    normalized: list[str] = []
    seen: set[str] = set()
    aliases = {
        "boss-harvest": "aragora/boss-harvest/",
        "boss-harvest/": "aragora/boss-harvest/",
        "aragora/boss-harvest": "aragora/boss-harvest/",
        "codex": "codex/",
        "factory": "factory/",
    }
    for prefix in raw_prefixes:
        value = aliases.get(str(prefix or "").strip(), str(prefix or "").strip())
        if not value:
            continue
        if value not in seen:
            seen.add(value)
            normalized.append(value)
    return normalized or list(AUTOMATION_BRANCH_PREFIXES)


def classify_automation_branch_ownership(
    head_ref_name: object,
    *,
    branch_prefixes: list[str] | None = None,
) -> str | None:
    """Classify an automation branch as boss- or queue-owned."""
    if not isinstance(head_ref_name, str):
        return None
    for prefix in _normalize_branch_prefixes(branch_prefixes):
        if head_ref_name.startswith(prefix):
            if prefix == "aragora/boss-harvest/":
                return "boss-owned"
            return "queue-owned"
    return None


@lru_cache(maxsize=8)
def _get_required_checks(repo: str, base_branch: str = "main") -> list[str]:
    """Load required branch-protection contexts, with a local fallback."""
    result = _run_gh(
        [
            "api",
            f"repos/{repo}/branches/{base_branch}/protection",
            "--jq",
            ".required_status_checks.contexts",
        ]
    )
    if result.returncode != 0:
        return list(REQUIRED_CHECKS)
    try:
        contexts = json.loads(result.stdout or "[]")
    except (json.JSONDecodeError, TypeError):
        return list(REQUIRED_CHECKS)
    if not isinstance(contexts, list):
        return list(REQUIRED_CHECKS)
    normalized = [str(item).strip() for item in contexts if str(item).strip()]
    return normalized or list(REQUIRED_CHECKS)


def _classify_non_passing_checks(
    checks: dict[str, str],
    *,
    ignored_checks: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Split non-passing checks into waiting and failing buckets."""
    waiting: list[str] = []
    failing: list[str] = []
    ignored = ignored_checks or set()
    for name in sorted(checks):
        if name in ignored:
            continue
        status = checks.get(name, "")
        if status in PASSING_CHECK_STATES:
            continue
        detail = f"{name}={status}"
        if status in {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING", "REQUESTED"}:
            waiting.append(detail)
        else:
            failing.append(detail)
    return waiting, failing


def _ready_suite_check_names(
    checks: dict[str, str],
    *,
    required_checks: list[str],
) -> list[str]:
    ignored = set(required_checks) | set(REDUCED_LANE_ONLY_CHECKS)
    return sorted(name for name in checks if name not in ignored)


def _run_gh(
    args: list[str],
    *,
    timeout: float = 30.0,
    write_op: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a ``gh`` CLI command with App-token preference and rate-limit-aware retry.

    Read-only calls go through the GitHub App installation token to isolate
    quota from the user PAT. Write operations (PR ready, PR merge) force the
    user PAT because the App installation has narrow write scopes here.
    Retries on primary or secondary rate-limit errors with exponential backoff
    or until the relevant bucket resets.
    """
    return gh_subprocess_run(args, timeout=timeout, write_op=write_op)


def _is_full_head_sha(head_sha: object) -> bool:
    """Return whether ``head_sha`` is an exact lowercase Git commit SHA."""
    return isinstance(head_sha, str) and _FULL_HEAD_SHA_RE.fullmatch(head_sha) is not None


class ArbiterOperationalError(RuntimeError):
    """A genuine arbiter-operational fault (e.g. cannot list PRs), as opposed to a
    PR merely not being ready. Only these faults feed the circuit breaker."""


class CheckSnapshotHeadMismatch(RuntimeError):
    """The atomic check snapshot no longer belongs to the decision head."""


def _list_candidate_prs(config: MergeArbiterConfig) -> list[dict]:
    """Return open PRs whose head branch matches any configured prefix.

    Raises ``ArbiterOperationalError`` when the underlying ``gh pr list`` call or
    its JSON output cannot be obtained — a transient/operational fault that the
    poll loop counts toward the circuit breaker. An *empty* list means the fetch
    succeeded but no open PR matched a configured prefix (not a fault)."""
    prefixes = _normalize_branch_prefixes(config.branch_prefixes)
    result = _run_gh(
        [
            "pr",
            "list",
            "--repo",
            config.repo,
            "--state",
            "open",
            "--json",
            "number,headRefName,headRefOid,isDraft,reviewDecision",
            "--limit",
            "100",
        ]
    )
    if result.returncode != 0:
        raise ArbiterOperationalError(f"gh pr list failed: {result.stderr.strip()}")
    try:
        prs = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ArbiterOperationalError("failed to parse gh pr list output") from exc
    candidates = []
    for pr in prs:
        branch = pr.get("headRefName", "")
        if classify_automation_branch_ownership(branch, branch_prefixes=prefixes) is not None:
            candidates.append(pr)
    return candidates


def _get_check_status(pr_number: int, repo: str, expected_head_sha: str) -> dict[str, str]:
    """Return checks from one PR snapshot bound to ``expected_head_sha``.

    ``headRefOid`` and ``statusCheckRollup`` are fetched in the same GraphQL
    response. A head change between the caller's decision snapshot and this
    check snapshot fails closed instead of pairing checks from one commit with
    merge authority for another.

    Raises ``ArbiterOperationalError`` when the snapshot cannot be obtained or
    parsed. Raises ``CheckSnapshotHeadMismatch`` when the returned head differs
    from the decision head. An empty mapping means the matching snapshot
    reported no checks (a normal not-ready state)."""
    if not _is_full_head_sha(expected_head_sha):
        raise CheckSnapshotHeadMismatch("missing or malformed expected check-snapshot head SHA")
    result = _run_gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "headRefOid,statusCheckRollup",
        ]
    )
    if result.returncode != 0:
        raise ArbiterOperationalError(
            f"gh pr view failed for #{pr_number}: {result.stderr.strip()}"
        )
    try:
        snapshot = json.loads(result.stdout) if result.stdout else None
    except (json.JSONDecodeError, TypeError) as exc:
        raise ArbiterOperationalError(f"failed to parse check snapshot for #{pr_number}") from exc
    if not isinstance(snapshot, dict):
        raise ArbiterOperationalError(f"check snapshot for #{pr_number} is not an object")
    actual_head_sha = snapshot.get("headRefOid")
    if actual_head_sha != expected_head_sha:
        raise CheckSnapshotHeadMismatch(
            f"check snapshot head changed: expected {expected_head_sha}, got {actual_head_sha or '<missing>'}"
        )
    checks = snapshot.get("statusCheckRollup")
    if checks is None:
        return {}
    if not isinstance(checks, list):
        raise ArbiterOperationalError(f"check snapshot rollup for #{pr_number} is not a list")
    return _reduce_rollup_states(checks)


def _list_pr_reviews(pr_number: int, repo: str) -> list[dict]:
    """Return PR review events as raw GitHub API payloads."""
    result = _run_gh(
        [
            "api",
            f"repos/{repo}/pulls/{pr_number}/reviews",
            "--paginate",
        ]
    )
    if result.returncode != 0:
        logger.debug("gh api pulls/%d/reviews failed: %s", pr_number, result.stderr.strip())
        return []
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _review_counts_as_human_approval(review: dict, head_sha: str | None) -> bool:
    """Return True when a review is an approval tied to the current head and not automation."""
    if not _is_full_head_sha(head_sha):
        return False
    if str(review.get("state", "")).upper() != "APPROVED":
        return False
    if review.get("commit_id") != head_sha:
        return False
    user = review.get("user") or {}
    if not isinstance(user, dict):
        return False
    login = str(user.get("login", "")).strip()
    user_type = str(user.get("type", "")).strip().lower()
    if not login:
        return False
    if login in AUTOMATION_REVIEWER_LOGINS or login.endswith("[bot]") or user_type == "bot":
        return False
    return True


def _has_matching_human_approval(pr_number: int, repo: str, head_sha: str | None) -> bool:
    """Require an explicit human approval on the current PR head SHA."""
    if not _is_full_head_sha(head_sha):
        return False
    for review in reversed(_list_pr_reviews(pr_number, repo)):
        if _review_counts_as_human_approval(review, head_sha):
            return True
    return False


def _has_local_settlement_receipt(
    pr_number: int, head_sha: str | None, repo_root: Path | None = None
) -> bool:
    """Accept a local review-queue approval receipt as an explicit settlement signal."""
    if not isinstance(head_sha, str) or not _is_full_head_sha(head_sha):
        return False
    root = (repo_root or Path.cwd()) / ".aragora" / "review-queue" / "settlements"
    receipt = root / f"pr-{pr_number}-{head_sha[:12]}-approve.json"
    if not receipt.exists():
        return False
    try:
        payload = json.loads(receipt.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        str(payload.get("action", "")).strip() == "approve" and payload.get("head_sha") == head_sha
    )


def _promote_draft(pr_number: int, repo: str) -> bool:
    """Mark a draft PR as ready for review."""
    result = _run_gh(
        ["pr", "ready", str(pr_number), "--repo", repo],
        timeout=30.0,
        write_op=True,
    )
    return result.returncode == 0


def _merge_pr(
    pr_number: int,
    repo: str,
    head_sha: str | None = None,
) -> tuple[bool, str]:
    """Squash-merge a PR pinned to its authorized full head SHA."""
    if not isinstance(head_sha, str) or not _is_full_head_sha(head_sha):
        return False, "missing or malformed full head SHA"
    args = [
        "pr",
        "merge",
        str(pr_number),
        "--repo",
        repo,
        "--admin",
        "--squash",
        "--delete-branch",
        "--match-head-commit",
        head_sha,
    ]
    result = _run_gh(args, write_op=True)
    if result.returncode != 0:
        reason = result.stderr.strip() or "unknown error"
        return False, reason
    return True, "merged"


def _evaluate_pr(pr: dict, config: MergeArbiterConfig) -> MergeResult:
    """Evaluate a single PR and merge it if all required checks pass."""
    pr_number: int = pr["number"]
    branch: str = pr.get("headRefName", "")
    head_sha = pr.get("headRefOid")
    is_draft: bool = pr.get("isDraft", False)
    review_decision = str(pr.get("reviewDecision", "")).strip().upper()

    if not isinstance(head_sha, str) or not _is_full_head_sha(head_sha):
        return MergeResult(
            pr_number,
            branch,
            False,
            "missing or malformed full head SHA in PR snapshot",
        )
    required_checks = _get_required_checks(config.repo)

    try:
        checks = _get_check_status(pr_number, config.repo, head_sha)
    except CheckSnapshotHeadMismatch as exc:
        return MergeResult(pr_number, branch, False, str(exc))

    if is_draft:
        if not checks:
            return MergeResult(
                pr_number,
                branch,
                False,
                "draft PR: never auto-merged; no fast required checks reported yet",
            )
        missing, failing = _classify_required_checks(checks, required_checks=required_checks)
        if missing or failing:
            reason_parts = ["draft PR: never auto-merged"]
            if missing:
                reason_parts.append(f"fast required checks missing: {', '.join(missing)}")
            if failing:
                reason_parts.append(f"fast required checks failing: {', '.join(failing)}")
            return MergeResult(pr_number, branch, False, "; ".join(reason_parts))
        return MergeResult(
            pr_number,
            branch,
            False,
            "draft PR: fast required checks passed; waiting for boss-loop promotion to ready",
        )

    if not checks:
        return MergeResult(pr_number, branch, False, "no checks found")

    missing, failing = _classify_required_checks(checks, required_checks=required_checks)

    if missing:
        return MergeResult(
            pr_number,
            branch,
            False,
            f"missing required checks: {', '.join(missing)}",
        )
    if failing:
        return MergeResult(
            pr_number,
            branch,
            False,
            f"failing required checks: {', '.join(failing)}",
        )

    missing_ready_gates = sorted(name for name in READY_SUITE_GATE_CHECKS if name not in checks)
    if missing_ready_gates:
        return MergeResult(
            pr_number,
            branch,
            False,
            f"ready PR missing full-suite gate checks: {', '.join(missing_ready_gates)}",
        )

    ready_suite_checks = _ready_suite_check_names(checks, required_checks=required_checks)
    if not ready_suite_checks:
        return MergeResult(
            pr_number,
            branch,
            False,
            "ready PR still only has reduced fast-lane checks; no full-suite checks reported yet",
        )

    ready_suite_statuses = {name: checks[name] for name in ready_suite_checks}
    waiting_ready, failing_ready = _classify_non_passing_checks(ready_suite_statuses)
    if waiting_ready:
        return MergeResult(
            pr_number,
            branch,
            False,
            f"waiting on full-suite checks: {', '.join(waiting_ready)}",
        )
    if failing_ready:
        return MergeResult(
            pr_number,
            branch,
            False,
            f"failing full-suite checks: {', '.join(failing_ready)}",
        )

    has_settlement = _has_local_settlement_receipt(pr_number, head_sha) or (
        review_decision == "APPROVED"
        and _has_matching_human_approval(pr_number, config.repo, head_sha)
    )
    if not has_settlement:
        return MergeResult(
            pr_number,
            branch,
            False,
            "waiting for explicit human settlement on the current head SHA",
        )

    if config.dry_run:
        logger.info("[dry-run] Would merge PR #%d (%s)", pr_number, branch)
        return MergeResult(pr_number, branch, True, "dry-run: would merge")

    ok, reason = _merge_pr(pr_number, config.repo, head_sha)
    if ok:
        logger.info("Merged PR #%d (%s)", pr_number, branch)
    else:
        logger.warning("Failed to merge PR #%d: %s", pr_number, reason)
    return MergeResult(pr_number, branch, ok, reason)


QUORUM_REQUIRED_CHECK = "aragora-merge-quorum"


def _required_model_signals(tier: int | None) -> int:
    """Number of distinct countable model families a PR's tier requires."""
    return TIER_REQUIREMENTS.get(tier if tier is not None else -1, (2, True, True))[0]


def _result_blocked_only_on_quorum(result: MergeResult) -> bool:
    """True when a not-ready PR is blocked solely on the merge-quorum check.

    The quorum check is a branch-protection required context, so the arbiter
    reports a quorum-only block as a 'failing'/'missing required checks' reason
    naming exactly ``aragora-merge-quorum``. Any other failing/missing required
    check (a real functional failure) returns False — we never spend reviewers
    on a PR that is broken for other reasons.
    """
    if result.success:
        return False
    for prefix in ("failing required checks: ", "missing required checks: "):
        if result.reason.startswith(prefix):
            entries = [e.strip() for e in result.reason[len(prefix) :].split(",") if e.strip()]
            return bool(entries) and all(
                e.split("=", 1)[0].strip() == QUORUM_REQUIRED_CHECK for e in entries
            )
    return False


def _should_collect_evidence(
    pr: dict,
    result: MergeResult,
    *,
    config: MergeArbiterConfig,
    tier_fetcher,
    context_fetcher,
    evidence_reader,
) -> bool:
    """Decide whether to auto-collect quorum evidence for a not-ready candidate.

    True iff the flag is on; the PR is blocked only on the quorum check; its tier
    is auto-postable (0-2); and it has fewer countable model families than its
    tier requires. All I/O is injected so this is fully testable with fakes.
    """
    if not config.auto_collect_evidence:
        return False
    if not _result_blocked_only_on_quorum(result):
        return False
    pr_number = pr.get("number")
    if pr_number is None:
        return False
    tier = tier_fetcher(config.repo, pr_number)
    if tier is None or tier < 0 or tier > 2:
        return False
    ctx = context_fetcher(config.repo, pr_number) or {}
    head_sha = str(ctx.get("head_sha") or "")
    if not head_sha:
        return False
    head_committed_at = str(ctx.get("head_committed_at") or "")
    comments = evidence_reader(config.repo, pr_number, head_sha, head_committed_at)
    return len(counted_reviewer_ids(comments)) < _required_model_signals(tier)


class MergeArbiter:
    """Polling loop that auto-merges boss-loop PRs when CI passes."""

    def __init__(
        self,
        config: MergeArbiterConfig | None = None,
        *,
        tier_fetcher=fetch_pr_tier,
        context_fetcher=fetch_pr_context,
        evidence_reader=fetch_evidence_comments,
        collector=collect_evidence,
        author_resolver=resolve_author,
    ) -> None:
        self.config = config or MergeArbiterConfig()
        self._consecutive_failures = 0
        self._collected_heads: set[str] = set()
        self._tier_fetcher = tier_fetcher
        self._context_fetcher = context_fetcher
        self._evidence_reader = evidence_reader
        self._collector = collector
        self._author_resolver = author_resolver

    def _maybe_collect_evidence(self, pr: dict, result: MergeResult) -> bool:
        """Collect quorum evidence at most once per head for a quorum-blocked PR.

        Returns True iff a collection was attempted. Posting is tier-gated inside
        ``collect_evidence`` (Tier 3+ never posts). The head is recorded before
        collecting so a transient fault never re-triggers the costly multi-model
        collection on the same head every poll.
        """
        head_sha = str(pr.get("headRefOid") or "")
        if head_sha and head_sha in self._collected_heads:
            return False
        if not _should_collect_evidence(
            pr,
            result,
            config=self.config,
            tier_fetcher=self._tier_fetcher,
            context_fetcher=self._context_fetcher,
            evidence_reader=self._evidence_reader,
        ):
            return False
        self._collected_heads.add(head_sha)
        try:
            self._collector(
                repo=self.config.repo,
                pr=pr["number"],
                families=self.config.reviewer_families or list(DEFAULT_FAMILIES),
                author=self._author_resolver(),
                apply=True,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort resilience boundary: one bad collection must not abort the poll loop
            logger.warning("evidence collection fault for #%s: %s", pr.get("number"), exc)
            return False
        logger.info("Auto-collected quorum evidence for #%s", pr.get("number"))
        return True

    async def run(self) -> ArbiterSummary:
        """Run the polling loop until max runtime or circuit breaker trips."""
        summary = ArbiterSummary()
        start = time.monotonic()
        deadline = start + self.config.max_runtime_hours * 3600

        logger.info(
            "Merge arbiter started: repo=%s prefixes=%s interval=%ds max_hours=%.1f dry_run=%s",
            self.config.repo,
            self.config.branch_prefixes,
            int(self.config.poll_interval_seconds),
            self.config.max_runtime_hours,
            self.config.dry_run,
        )

        while time.monotonic() < deadline:
            summary.polls += 1
            collected_this_poll = False
            list_fault_this_poll = False
            eval_faults_this_poll = 0
            clean_evaluations_this_poll = 0

            try:
                candidates = _list_candidate_prs(self.config)
            except ArbiterOperationalError as exc:
                list_fault_this_poll = True
                candidates = []
                logger.warning("Poll %d: candidate fetch fault: %s", summary.polls, exc)
            logger.debug("Poll %d: %d candidate PRs", summary.polls, len(candidates))

            for pr in candidates:
                try:
                    result = _evaluate_pr(pr, self.config)
                except ArbiterOperationalError as exc:
                    # Genuine evaluation fault (not "PR not ready"): count it, skip
                    # this PR, keep polling the rest.
                    eval_faults_this_poll += 1
                    logger.warning(
                        "Poll %d: evaluation fault for #%s: %s",
                        summary.polls,
                        pr.get("number"),
                        exc,
                    )
                    continue
                clean_evaluations_this_poll += 1
                if result.success:
                    summary.merged.append(result.pr_number)
                    logger.info("PR #%d: %s (%s)", result.pr_number, result.reason, result.branch)
                elif "failing" in result.reason or "failed" in result.reason:
                    # A PR with failing/missing required checks is NOT ready — a
                    # normal waiting state, NOT an arbiter fault. Record it for
                    # reporting, but it must never trip the circuit breaker: a
                    # normal all-red queue would otherwise stop the engine before
                    # it can post the very evidence that turns those checks green.
                    summary.failed.append(result.pr_number)
                    logger.info(
                        "PR #%d not ready: %s (%s)",
                        result.pr_number,
                        result.reason,
                        result.branch,
                    )
                else:
                    summary.skipped.append(result.pr_number)
                    logger.debug(
                        "PR #%d waiting: %s (%s)",
                        result.pr_number,
                        result.reason,
                        result.branch,
                    )

                # Auto-collect quorum evidence for a candidate blocked only on the
                # quorum check (at most one collection per poll, once per head).
                if (
                    not result.success
                    and not collected_this_poll
                    and self._maybe_collect_evidence(pr, result)
                ):
                    collected_this_poll = True

            # Circuit breaker: trip only on consecutive polls with a *systemic*
            # operational fault, never on not-ready PRs. A list-fetch fault is
            # always systemic. Evaluation faults are systemic only when every
            # evaluation in the poll faulted: a single PR that consistently
            # faults (a poison pill) must not halt the arbiter for the healthy
            # rest of the queue.
            operational_fault_this_poll = list_fault_this_poll or (
                eval_faults_this_poll > 0 and clean_evaluations_this_poll == 0
            )
            if operational_fault_this_poll:
                self._consecutive_failures += 1
            else:
                self._consecutive_failures = 0

            if self._consecutive_failures >= self.config.max_consecutive_failures:
                summary.stop_reason = (
                    f"circuit breaker: {self._consecutive_failures} consecutive operational faults"
                )
                logger.warning("Merge arbiter stopping: %s", summary.stop_reason)
                break

            await asyncio.sleep(self.config.poll_interval_seconds)
        else:
            summary.stop_reason = "max runtime reached"

        summary.elapsed_seconds = time.monotonic() - start
        logger.info(
            "Merge arbiter finished: %s (merged=%d skipped=%d failed=%d polls=%d)",
            summary.stop_reason,
            len(summary.merged),
            len(summary.skipped),
            len(summary.failed),
            summary.polls,
        )
        return summary
