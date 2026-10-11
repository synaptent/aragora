"""Issue selection and deduplication helpers for the boss loop.

Extracted from boss_loop.py to keep the main module under the LOC ratchet.
These are pure-logic functions that operate on issue lists without boss loop
instance state.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
from typing import TYPE_CHECKING, Any, cast

from aragora.config.secrets import get_secret_presence, is_secret_presence_available

if TYPE_CHECKING:
    from aragora.swarm.boss_loop import GitHubIssue

logger = logging.getLogger(__name__)


def _has_api_key(*names: str) -> bool:
    return any(is_secret_presence_available(get_secret_presence(name)) for name in names)


def semantic_dedup_issues(issues: list[GitHubIssue]) -> list[GitHubIssue]:
    """Use LLM to cluster semantically duplicate issues, keep one per cluster."""
    if len(issues) < 6:
        return issues

    try:
        from aragora.agents.base import create_agent

        agent = None
        if _has_api_key("OPENROUTER_API_KEY"):
            agent = create_agent(
                "openrouter", name="dedup", role="proposer", model="deepseek/deepseek-v4-pro"
            )
        elif _has_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            agent = create_agent("gemini", name="dedup", role="proposer", model="gemini-2.0-flash")
        if agent is None:
            return issues

        issue_map = {
            str(i.number): re.sub(r"\[from #\d+\]\s*", "", i.title).strip() for i in issues
        }
        prompt = (
            "You are deduplicating GitHub issues. Group semantically equivalent tasks. "
            "Return ONLY a JSON array of arrays: [[num1,num2],[num3],...]\n\n"
            + "\n".join(f"#{num}: {title}" for num, title in issue_map.items())
        )

        try:
            asyncio.get_running_loop()
            return issues  # Can't call asyncio.run inside running loop
        except RuntimeError:
            pass

        raw = asyncio.run(agent.generate(prompt))
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return issues

        clusters = _json.loads(match.group())
        if not isinstance(clusters, list):
            return issues

        kept = {int(c[0]) for c in clusters if isinstance(c, list) and c}
        all_clustered = {int(n) for c in clusters if isinstance(c, list) for n in c}
        deduped = [i for i in issues if i.number in kept or i.number not in all_clustered]

        logger.info("Semantic dedup: %d → %d issues", len(issues), len(deduped))
        return deduped
    except Exception as exc:
        logger.debug("Semantic dedup skipped: %s", exc)
        return issues


def scope_hint_is_specific(scope_entry: str) -> bool:
    """Check if a scope entry is file-specific (has extension or glob)."""
    basename = str(scope_entry or "").rstrip("/").rsplit("/", 1)[-1]
    return "*" in scope_entry or "." in basename


def scope_hint_is_validation_command_scope(issue: GitHubIssue, scope_entry: str) -> bool:
    """Check if scope_entry only appears as part of a validation command."""
    if scope_hint_is_specific(scope_entry):
        return False
    scope = str(scope_entry or "").strip().rstrip("/")
    if not scope:
        return False
    validation_command_re = re.compile(
        r"\b(pytest|ruff|mypy|npm|pnpm|yarn|python\s+-m\s+pytest)\b",
        re.IGNORECASE,
    )
    for line in str(issue.body or "").splitlines():
        normalized = line.strip().strip("-* ").replace("`", "").rstrip("/")
        if scope in normalized and validation_command_re.search(normalized):
            return True
    return False


def parallel_claim_scope_entries(issue: GitHubIssue) -> list[str]:
    """Get scope entries that represent exclusive edit claims."""
    from aragora.swarm.boss_loop import infer_issue_scope_entries

    return [
        scope_entry
        for scope_entry in infer_issue_scope_entries(issue)
        if not scope_hint_is_validation_command_scope(issue, scope_entry)
    ]


def has_explicit_parallel_lane_hint(issue: GitHubIssue) -> bool:
    """Check if an issue has explicit lane/area metadata."""
    if any(
        re.match(r"^(?:lane|area)[:/]", str(label or "").strip(), re.IGNORECASE)
        for label in issue.labels
    ):
        return True
    combined = "\n".join(
        part for part in (str(issue.title or "").strip(), str(issue.body or "").strip()) if part
    )
    return bool(re.search(r"(?im)^(?:lane|owner lane|lane id)\s*:", combined))


def select_issues_for_batch(
    issues: list[GitHubIssue],
    *,
    limit: int | None,
    blocked_scopes: set[str] | None = None,
    skip_labels: set[str] | frozenset[str] | None = None,
    require_labels: set[str] | frozenset[str] | None = None,
    issue_number: int | None = None,
    dedup_fn: Any | None = None,
) -> list[GitHubIssue]:
    """Select non-overlapping issues for one iteration batch.

    This is the extracted core of BossLoop._select_issues_for_iteration.
    """
    from aragora.swarm.boss_loop import (
        infer_issue_lane_hints,
        select_eligible_issue,
    )

    blocked_scope_entries = set(blocked_scopes or set())
    eligible_skip_labels = cast(set[str] | None, skip_labels)
    eligible_require_labels = cast(set[str] | None, require_labels)

    if limit is not None and limit <= 1:
        if issue_number is not None:
            target = next((i for i in issues if i.number == issue_number), None)
            selected = (
                select_eligible_issue(
                    [target],
                    skip_labels=eligible_skip_labels,
                    require_labels=eligible_require_labels,
                    blocked_scopes=blocked_scope_entries,
                )
                if target is not None
                else None
            )
            return [selected] if selected is not None else []
        selected = select_eligible_issue(
            issues,
            skip_labels=eligible_skip_labels,
            require_labels=eligible_require_labels,
            blocked_scopes=blocked_scope_entries,
        )
        return [selected] if selected is not None else []

    if issue_number is not None:
        target = next((i for i in issues if i.number == issue_number), None)
        selected = (
            select_eligible_issue(
                [target],
                skip_labels=eligible_skip_labels,
                require_labels=eligible_require_labels,
                blocked_scopes=blocked_scope_entries,
            )
            if target is not None
            else None
        )
        return [selected] if selected is not None else []

    # Semantic dedup
    pre_dedup = [issue for issue in issues if not (set(issue.labels) & set(skip_labels or set()))]
    _dedup = dedup_fn if dedup_fn is not None else semantic_dedup_issues
    issues = _dedup(pre_dedup)

    selected_issues: list[GitHubIssue] = []
    claimed_scopes: set[str] = set(blocked_scope_entries)
    claimed_lanes: set[str] = set()
    claimed_stems: set[str] = set()

    for issue in issues:
        candidate = select_eligible_issue(
            [issue],
            skip_labels=eligible_skip_labels,
            require_labels=eligible_require_labels,
            blocked_scopes=claimed_scopes,
        )
        if candidate is None:
            continue

        claim_scope_hints = set(parallel_claim_scope_entries(candidate))
        if claim_scope_hints and claim_scope_hints & claimed_scopes:
            continue
        lane_hints = (
            set(infer_issue_lane_hints(candidate))
            if claim_scope_hints or has_explicit_parallel_lane_hint(candidate)
            else set()
        )
        if lane_hints and lane_hints & claimed_lanes:
            continue

        stem = re.sub(r"\[from #\d+\]\s*", "", candidate.title).strip().lower()[:60]
        if stem in claimed_stems:
            continue

        selected_issues.append(candidate)
        claimed_scopes.update(claim_scope_hints)
        claimed_lanes.update(lane_hints)
        claimed_stems.add(stem)
        if limit is not None and len(selected_issues) >= limit:
            break
    return selected_issues


def target_issue_miss_guidance(
    *,
    issue_number: int,
    fetch_issue: Any,
    skip_labels: set[str] | None,
    require_labels: set[str] | None,
    blocked_scopes: set[str] | None,
) -> tuple[list[str], list[str]]:
    """Return truthful guidance for an explicitly targeted issue miss."""
    from aragora.swarm.boss_loop import GitHubIssue, infer_issue_scope_entries

    reasons = [
        f"Target issue #{issue_number} was not found in the issue feed or is not eligible under current filters/retry state."
    ]
    next_actions = [
        f"Verify issue #{issue_number} is still open, eligible, and has not exceeded retry limits.",
        "Remove --boss-issue-number to return to feed-driven selection.",
    ]
    if not callable(fetch_issue):
        return reasons, next_actions
    try:
        issue = fetch_issue(issue_number, allow_closed=True)
    except TypeError:
        try:
            issue = fetch_issue(issue_number)
        except Exception:
            return reasons, next_actions
    except Exception:
        return reasons, next_actions
    if not isinstance(issue, GitHubIssue):
        return reasons, next_actions

    state = str(issue.state or "").strip().lower()
    if state and state != "open":
        return (
            [
                f"Target issue #{issue_number} is {state} and cannot be selected by the open-issue boss feed."
            ],
            [
                f"Reopen issue #{issue_number} if it should be eligible for Boss dispatch.",
                "Remove --boss-issue-number to return to feed-driven selection.",
            ],
        )

    labels = {str(label).strip() for label in issue.labels if str(label).strip()}
    skipped = sorted(labels & set(skip_labels or set()))
    if skipped:
        return (
            [f"Target issue #{issue_number} is excluded by skip labels: {', '.join(skipped)}."],
            [
                f"Remove skip labels from issue #{issue_number} or adjust --label-filter/skip-label settings.",
                "Remove --boss-issue-number to return to feed-driven selection.",
            ],
        )

    # Scope-overlap is checked before required-labels because the proof-first
    # filter (filter_noncanonical_boss_ready_issues) mutates issue.labels to
    # strip `boss-ready` for non-canonical issues. Reporting "missing labels"
    # in that path masks the more actionable root cause when both apply.
    overlapping_scopes = sorted(
        {
            entry
            for entry in infer_issue_scope_entries(issue)
            if entry in set(blocked_scopes or set())
        }
    )
    if overlapping_scopes:
        overlap_summary = ", ".join(overlapping_scopes[:3])
        if len(overlapping_scopes) > 3:
            overlap_summary = f"{overlap_summary}, +{len(overlapping_scopes) - 3} more"
        return (
            [
                (
                    f"Target issue #{issue_number} overlaps files already owned by open PR or "
                    f"in-flight work: {overlap_summary}."
                )
            ],
            [
                f"Merge, close, or retarget the overlapping work before redispatching issue #{issue_number}.",
                "Remove --boss-issue-number to return to feed-driven selection.",
            ],
        )

    required = set(require_labels or set())
    missing_labels = sorted(required - labels)
    if missing_labels:
        return (
            [
                f"Target issue #{issue_number} is missing required labels: {', '.join(missing_labels)}."
            ],
            [
                f"Add the required labels to issue #{issue_number} or adjust --require-label settings.",
                "Remove --boss-issue-number to return to feed-driven selection.",
            ],
        )

    if not issue.title:
        return (
            [f"Target issue #{issue_number} is missing a title and cannot be selected."],
            [
                f"Add a non-empty title to issue #{issue_number}.",
                "Remove --boss-issue-number to return to feed-driven selection.",
            ],
        )
    return reasons, next_actions
