#!/usr/bin/env python3
"""Reconcile B0 cohort PR truth against live GitHub state.

This script is intentionally narrow. It does not replace the existing B0
measurement script. Instead it adds GitHub-truth reconciliation for the B0
cohort by:
- reading boss metrics JSONL
- identifying B0 cohort issues from `cohort_tag` or `[B0-cohort]` titles
- computing issue-level proxy success from metrics
- resolving linked PRs for each issue via GitHub issue comments and PR metadata
- reporting truth states per issue: no linked PR, open PR, mergeable PR,
  closed-unmerged PR, merged PR

Proxy metric:
- an issue has a PR signal in metrics

Truth metrics:
- open PR: at least one linked PR exists on GitHub and is open
- mergeable PR: at least one linked PR is open and GitHub reports MERGEABLE
- merged PR: at least one linked PR is merged
- no-rescue truth success: the issue reached mergeable or merged truth without any
  rescue_worker_crash rows in the metrics file
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.swarm.terminal_truth import TerminalClass, classify_from_metrics  # noqa: E402
from aragora.utils.git_paths import git_common_repo_root, resolve_repo_fallback_path  # noqa: E402

DEFAULT_METRICS_PATH = REPO_ROOT / ".aragora" / "overnight" / "boss_metrics.jsonl"
B0_TAG = "b0-cohort"
PR_URL_RE = re.compile(r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)")
PR_SIGNAL_ACTIONS = frozenset({"pr_created", "existing_pr", "discovered_after_push"})
PR_SIGNAL_OUTCOMES = frozenset({"pr_adopted"})
MERGEABLE_STATES = frozenset({"MERGEABLE"})
MERGED_STATES = frozenset({"MERGED"})
OPEN_STATES = frozenset({"OPEN"})
ISSUE_COMMENTS_PER_PAGE = 100
ISSUE_COMMENTS_MAX_PAGES = 5
CROSS_REFS_PER_PAGE = 100
CROSS_REFS_MAX_PAGES = 5
COMMENTS_LOOKUP_ERROR_KEY = "_comments_lookup_error"
GITHUB_CONNECTION_ERROR_SNIPPET = "error connecting to api.github.com"
GH_NETWORK_RETRY_ATTEMPTS = 3


def _git_common_repo_root() -> Path | None:
    return git_common_repo_root(REPO_ROOT)


def resolve_metrics_path(candidate: Path) -> Path:
    return resolve_repo_fallback_path(
        candidate,
        repo_root=REPO_ROOT,
        common_root=_git_common_repo_root(),
    )


@dataclass(frozen=True)
class LinkedPullRequest:
    number: int
    title: str
    url: str
    state: str
    mergeable: str
    merge_state_status: str
    merged_at: str | None
    is_draft: bool

    @property
    def truth_state(self) -> str:
        if self.state in MERGED_STATES or self.merged_at:
            return "merged_pr"
        if self.state in OPEN_STATES and self.mergeable in MERGEABLE_STATES:
            return "mergeable_pr"
        if self.state in OPEN_STATES:
            return "open_pr"
        return "closed_unmerged_pr"


@dataclass
class IssueMetricsAggregate:
    issue_number: int
    title: str = ""
    row_count: int = 0
    proxy_pr_signal: bool = False
    had_rescue: bool = False


@dataclass(frozen=True)
class IssueTruthRecord:
    issue_number: int
    issue_title: str
    proxy_pr_signal: bool
    had_rescue: bool
    truth_state: str
    truth_success: bool
    no_rescue_truth_success: bool
    issue_url: str = ""
    issue_state: str = ""
    issue_state_reason: str = ""
    issue_closed_at: str | None = None
    linkage_status: str = "verified"
    linkage_error: str = ""
    linked_prs: list[LinkedPullRequest] = field(default_factory=list)

    @property
    def linkage_verification_incomplete(self) -> bool:
        return self.linkage_status != "verified"

    @property
    def stale_corpus_issue(self) -> bool:
        return (
            self.issue_state == "CLOSED"
            and self.truth_state == "no_linked_pr"
            and not self.linkage_verification_incomplete
        )

    @property
    def stale_corpus_reason(self) -> str | None:
        if not self.stale_corpus_issue:
            return None
        return "closed_without_linked_pr"

    def to_dict(self) -> dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "issue_title": self.issue_title,
            "proxy_pr_signal": self.proxy_pr_signal,
            "had_rescue": self.had_rescue,
            "truth_state": self.truth_state,
            "truth_success": self.truth_success,
            "no_rescue_truth_success": self.no_rescue_truth_success,
            "issue_url": self.issue_url,
            "issue_state": self.issue_state,
            "issue_state_reason": self.issue_state_reason,
            "issue_closed_at": self.issue_closed_at,
            "linkage_status": self.linkage_status,
            "linkage_error": self.linkage_error,
            "linkage_verification_incomplete": self.linkage_verification_incomplete,
            "stale_corpus_issue": self.stale_corpus_issue,
            "stale_corpus_reason": self.stale_corpus_reason,
            "linked_prs": [asdict(pr) | {"truth_state": pr.truth_state} for pr in self.linked_prs],
        }


@dataclass(frozen=True)
class TruthSummary:
    attempted_issue_count: int
    proxy_success_issue_count: int
    proxy_success_rate: float
    linked_pr_issue_count: int
    linked_pr_issue_rate: float
    truth_success_issue_count: int
    truth_success_rate: float
    merged_issue_count: int
    merged_issue_rate: float
    no_rescue_truth_success_issue_count: int
    no_rescue_truth_success_rate: float
    truth_state_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempted_issue_count": self.attempted_issue_count,
            "proxy_success_issue_count": self.proxy_success_issue_count,
            "proxy_success_rate": round(self.proxy_success_rate, 4),
            "linked_pr_issue_count": self.linked_pr_issue_count,
            "linked_pr_issue_rate": round(self.linked_pr_issue_rate, 4),
            "truth_success_issue_count": self.truth_success_issue_count,
            "truth_success_rate": round(self.truth_success_rate, 4),
            "merged_issue_count": self.merged_issue_count,
            "merged_issue_rate": round(self.merged_issue_rate, 4),
            "no_rescue_truth_success_issue_count": self.no_rescue_truth_success_issue_count,
            "no_rescue_truth_success_rate": round(self.no_rescue_truth_success_rate, 4),
            "truth_state_counts": self.truth_state_counts,
        }


class GitHubTruthClient:
    """Minimal GitHub reader backed by the gh CLI."""

    def _run_json_object(self, args: list[str]) -> dict[str, Any]:
        last_error = "gh command failed"
        for attempt in range(1, GH_NETWORK_RETRY_ATTEMPTS + 1):
            proc = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                payload = json.loads(proc.stdout or "{}")
                if not isinstance(payload, dict):
                    raise RuntimeError("gh command did not return a JSON object")
                return payload
            last_error = proc.stderr.strip() or proc.stdout.strip() or "gh command failed"
            if (
                GITHUB_CONNECTION_ERROR_SNIPPET not in last_error.lower()
                or attempt >= GH_NETWORK_RETRY_ATTEMPTS
            ):
                raise RuntimeError(last_error)
        raise RuntimeError(last_error)

    def _run_json_list(self, args: list[str]) -> list[dict[str, Any]]:
        last_error = "gh command failed"
        for attempt in range(1, GH_NETWORK_RETRY_ATTEMPTS + 1):
            proc = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                payload = json.loads(proc.stdout or "[]")
                if not isinstance(payload, list):
                    raise RuntimeError("gh command did not return a JSON array")
                return [item for item in payload if isinstance(item, dict)]
            last_error = proc.stderr.strip() or proc.stdout.strip() or "gh command failed"
            if (
                GITHUB_CONNECTION_ERROR_SNIPPET not in last_error.lower()
                or attempt >= GH_NETWORK_RETRY_ATTEMPTS
            ):
                raise RuntimeError(last_error)
        raise RuntimeError(last_error)

    def get_issue(self, repo: str, number: int) -> dict[str, Any]:
        payload = self._run_json_object(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,title,url,state,stateReason,closedAt,updatedAt,closedByPullRequestsReferences",
            ]
        )
        try:
            payload["comments"] = self.get_issue_comments(repo, number)
        except RuntimeError as error:
            payload["comments"] = []
            payload[COMMENTS_LOOKUP_ERROR_KEY] = str(error)
        return payload

    def get_pr(self, repo: str, number: int) -> dict[str, Any]:
        return self._run_json_object(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                repo,
                "--json",
                "number,title,url,state,mergeable,mergeStateStatus,mergedAt,isDraft",
            ]
        )

    def get_issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        comments: list[dict[str, Any]] = []
        for page in range(1, ISSUE_COMMENTS_MAX_PAGES + 1):
            payload = self._run_json_list(
                [
                    "api",
                    f"repos/{repo}/issues/{number}/comments?per_page={ISSUE_COMMENTS_PER_PAGE}&page={page}",
                ]
            )
            comments.extend(payload)
            if len(payload) < ISSUE_COMMENTS_PER_PAGE:
                return comments
        raise RuntimeError(
            f"issue comment pagination exceeded bound for {repo}#{number} "
            f"after {ISSUE_COMMENTS_MAX_PAGES} pages"
        )

    def get_cross_referenced_pr_numbers(self, repo: str, number: int) -> list[int]:
        owner, name = repo.split("/", 1)
        pr_numbers: list[int] = []
        cursor: str | None = None

        for _page in range(CROSS_REFS_MAX_PAGES):
            args = [
                "api",
                "graphql",
                "-f",
                (
                    "query=query($owner:String!, $name:String!, $number:Int!, $after:String) "
                    "{ repository(owner:$owner, name:$name) { issue(number:$number) { "
                    f"timelineItems(itemTypes:[CROSS_REFERENCED_EVENT], first:{CROSS_REFS_PER_PAGE}, after:$after) "
                    "{ nodes { ... on CrossReferencedEvent { source { __typename ... on PullRequest { number } } } } "
                    "pageInfo { hasNextPage endCursor } } } } }"
                ),
                "-F",
                f"owner={owner}",
                "-F",
                f"name={name}",
                "-F",
                f"number={number}",
            ]
            if cursor is not None:
                args.extend(["-F", f"after={cursor}"])
            payload = self._run_json_object(args)
            timeline = (
                payload.get("data", {})
                .get("repository", {})
                .get("issue", {})
                .get("timelineItems", {})
            )
            nodes = timeline.get("nodes", [])
            for node in nodes:
                source = node.get("source") if isinstance(node, dict) else None
                if not isinstance(source, dict):
                    continue
                if source.get("__typename") != "PullRequest":
                    continue
                pr_number = source.get("number")
                if isinstance(pr_number, int):
                    pr_numbers.append(pr_number)

            page_info = timeline.get("pageInfo", {})
            has_next = bool(page_info.get("hasNextPage"))
            if not has_next:
                return pr_numbers
            cursor = str(page_info.get("endCursor") or "").strip() or None
            if cursor is None:
                raise RuntimeError(
                    f"cross-reference pagination missing endCursor for {repo}#{number}"
                )

        raise RuntimeError(
            f"cross-reference pagination exceeded bound for {repo}#{number} "
            f"after {CROSS_REFS_MAX_PAGES} pages"
        )


def load_metrics_rows(metrics_file: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with metrics_file.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _normalize_issue_number(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _contains_b0_tag(value: Any) -> bool:
    if isinstance(value, str):
        return B0_TAG in value.lower()
    if isinstance(value, dict):
        return any(_contains_b0_tag(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_b0_tag(item) for item in value)
    return False


def is_b0_issue_row(row: dict[str, Any]) -> bool:
    cohort_tag = _normalize_text(row.get("cohort_tag"))
    if cohort_tag == B0_TAG:
        return True
    for key in ("issue_title", "title", "metadata", "issue_metadata"):
        if _contains_b0_tag(row.get(key)):
            return True
    return False


def resolve_terminal_class(row: dict[str, Any]) -> TerminalClass:
    existing = row.get("terminal_class")
    if isinstance(existing, str) and existing.strip():
        try:
            return TerminalClass(existing.strip())
        except ValueError:
            pass
    return classify_from_metrics(row)


def has_proxy_pr_signal(row: dict[str, Any], terminal_class: TerminalClass) -> bool:
    if terminal_class is TerminalClass.DELIVERABLE_PR_CREATED:
        return True
    publish_action = _normalize_text(row.get("publish_action"))
    worker_outcome = _normalize_text(row.get("worker_outcome"))
    return publish_action in PR_SIGNAL_ACTIONS or worker_outcome in PR_SIGNAL_OUTCOMES


def aggregate_b0_issues(rows: list[dict[str, Any]]) -> list[IssueMetricsAggregate]:
    issues: dict[int, IssueMetricsAggregate] = {}
    for row in rows:
        if not is_b0_issue_row(row):
            continue
        issue_number = _normalize_issue_number(row.get("issue_number"))
        if issue_number is None:
            continue
        aggregate = issues.setdefault(
            issue_number, IssueMetricsAggregate(issue_number=issue_number)
        )
        aggregate.row_count += 1
        if not aggregate.title:
            aggregate.title = str(row.get("issue_title") or row.get("title") or "").strip()
        terminal_class = resolve_terminal_class(row)
        if has_proxy_pr_signal(row, terminal_class):
            aggregate.proxy_pr_signal = True
        if terminal_class is TerminalClass.RESCUE_WORKER_CRASH:
            aggregate.had_rescue = True
    return [issues[number] for number in sorted(issues)]


def _payload_dict_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, tuple):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nodes = value.get("nodes")
        if isinstance(nodes, list):
            return [item for item in nodes if isinstance(item, dict)]
    return []


def extract_pr_numbers_from_issue(
    repo: str, issue_payload: dict[str, Any], *, strict: bool = False
) -> list[int]:
    """Return PR numbers linked to ``issue_payload``.

    In strict mode (``strict=True``), only PRs on GitHub's
    ``closedByPullRequestsReferences`` GraphQL edge count as closure evidence.
    This is the honesty-audit-mandated linkage source for the benchmark truth
    surface: it ensures forensic-reference PRs (unrelated merged PRs that
    merely cite the issue in their bodies or comments) are not credited as
    success signals. See ``docs/archive/benchmarks/corpus_honesty_audit_2026-04-17.md``.

    In non-strict mode (default; used by the B0 cohort reconciliation flow),
    we also fall back to parsing PR URLs out of issue comments.
    """

    expected_repo = repo.lower()
    found: set[int] = set()
    for pr_payload in _payload_dict_items(issue_payload.get("closedByPullRequestsReferences")):
        pr_repo = pr_payload.get("repository")
        if isinstance(pr_repo, dict):
            owner = pr_repo.get("owner")
            owner_login = owner.get("login") if isinstance(owner, dict) else ""
            repo_name = pr_repo.get("name")
            if f"{owner_login}/{repo_name}".lower() != expected_repo:
                continue
        pr_number = pr_payload.get("number")
        if isinstance(pr_number, int):
            found.add(pr_number)
    if strict:
        return sorted(found)
    for comment in _payload_dict_items(issue_payload.get("comments")):
        body = str(comment.get("body") or "")
        for match in PR_URL_RE.finditer(body):
            if match.group(1).lower() != expected_repo:
                continue
            found.add(int(match.group(2)))
    return sorted(found)


def classify_issue_truth_state(linked_prs: list[LinkedPullRequest]) -> str:
    states = {pr.truth_state for pr in linked_prs}
    if "merged_pr" in states:
        return "merged_pr"
    if "mergeable_pr" in states:
        return "mergeable_pr"
    if "open_pr" in states:
        return "open_pr"
    if "closed_unmerged_pr" in states:
        return "closed_unmerged_pr"
    return "no_linked_pr"


def reconcile_issue_truth(
    repo: str,
    aggregate: IssueMetricsAggregate,
    client: GitHubTruthClient,
    *,
    strict_linkage: bool = False,
) -> IssueTruthRecord:
    """Reconcile autonomy truth for ``aggregate`` against live GitHub state.

    When ``strict_linkage`` is True, the only linkage source is GitHub's
    ``closedByPullRequestsReferences`` GraphQL edge — i.e. PRs that
    actually closed the issue. Comment-body PR URLs and cross-referenced
    timeline events are ignored. This mode is used by the benchmark truth
    artifact (see ``scripts/build_benchmark_truth_artifact.py``) per the
    2026-04-17 honesty audit: forensic-reference PRs must not count as
    closure evidence.
    """

    try:
        issue_payload = client.get_issue(repo, aggregate.issue_number)
    except RuntimeError as error:
        return IssueTruthRecord(
            issue_number=aggregate.issue_number,
            issue_title=aggregate.title,
            proxy_pr_signal=aggregate.proxy_pr_signal,
            had_rescue=aggregate.had_rescue,
            truth_state="no_linked_pr",
            truth_success=False,
            no_rescue_truth_success=False,
            linkage_status="issue_lookup_failed",
            linkage_error=str(error),
        )
    comments_lookup_error = str(issue_payload.get(COMMENTS_LOOKUP_ERROR_KEY) or "").strip()
    issue_title = aggregate.title or str(issue_payload.get("title") or "").strip()
    issue_url = str(issue_payload.get("url") or "").strip()
    issue_state = str(issue_payload.get("state") or "").strip().upper()
    issue_state_reason = str(issue_payload.get("stateReason") or "").strip().upper()
    issue_closed_at = issue_payload.get("closedAt")
    linkage_status = "verified"
    linkage_error = ""

    pr_numbers = extract_pr_numbers_from_issue(repo, issue_payload, strict=strict_linkage)
    if not pr_numbers and not strict_linkage:
        # Lenient (non-benchmark) path: if the GraphQL edge and the comment
        # body both had no PR references, fall back to the cross-referenced
        # timeline. Strict mode deliberately skips this — it would re-admit
        # forensic references that happen to be "mentioned in timeline".
        try:
            pr_numbers = sorted(
                set(client.get_cross_referenced_pr_numbers(repo, aggregate.issue_number))
            )
        except RuntimeError as error:
            if issue_state != "CLOSED":
                raise
            linkage_status = "cross_reference_lookup_failed"
            linkage_error = str(error)
            pr_numbers = []
    if not pr_numbers and comments_lookup_error and not strict_linkage:
        if linkage_status == "verified":
            linkage_status = "issue_comments_lookup_failed"
            linkage_error = comments_lookup_error
        else:
            prior_status = linkage_status
            prior_error = linkage_error
            linkage_status = "linkage_lookup_failed"
            linkage_error = "; ".join(
                part
                for part in (
                    f"issue_comments_lookup_failed: {comments_lookup_error}",
                    f"{prior_status}: {prior_error}" if prior_error else prior_status,
                )
                if part
            )

    linked_prs: list[LinkedPullRequest] = []
    for pr_number in pr_numbers:
        pr_payload = client.get_pr(repo, pr_number)
        linked_prs.append(
            LinkedPullRequest(
                number=int(pr_payload.get("number", pr_number)),
                title=str(pr_payload.get("title") or "").strip(),
                url=str(pr_payload.get("url") or "").strip(),
                state=str(pr_payload.get("state") or "").strip().upper(),
                mergeable=str(pr_payload.get("mergeable") or "").strip().upper(),
                merge_state_status=str(pr_payload.get("mergeStateStatus") or "").strip().upper(),
                merged_at=pr_payload.get("mergedAt"),
                is_draft=bool(pr_payload.get("isDraft", False)),
            )
        )

    truth_state = classify_issue_truth_state(linked_prs)
    truth_success = truth_state in {"mergeable_pr", "merged_pr"}
    no_rescue_truth_success = truth_success and not aggregate.had_rescue
    return IssueTruthRecord(
        issue_number=aggregate.issue_number,
        issue_title=issue_title,
        proxy_pr_signal=aggregate.proxy_pr_signal,
        had_rescue=aggregate.had_rescue,
        truth_state=truth_state,
        truth_success=truth_success,
        no_rescue_truth_success=no_rescue_truth_success,
        issue_url=issue_url,
        issue_state=issue_state,
        issue_state_reason=issue_state_reason,
        issue_closed_at=issue_closed_at if isinstance(issue_closed_at, str) else None,
        linkage_status=linkage_status,
        linkage_error=linkage_error,
        linked_prs=linked_prs,
    )


def summarize_truth(records: list[IssueTruthRecord]) -> TruthSummary:
    attempted = len(records)
    proxy_success = sum(1 for record in records if record.proxy_pr_signal)
    linked_pr = sum(1 for record in records if record.truth_state != "no_linked_pr")
    truth_success = sum(1 for record in records if record.truth_success)
    merged = sum(1 for record in records if record.truth_state == "merged_pr")
    no_rescue_truth_success = sum(1 for record in records if record.no_rescue_truth_success)
    state_counts = Counter(record.truth_state for record in records)
    return TruthSummary(
        attempted_issue_count=attempted,
        proxy_success_issue_count=proxy_success,
        proxy_success_rate=(proxy_success / attempted if attempted else 0.0),
        linked_pr_issue_count=linked_pr,
        linked_pr_issue_rate=(linked_pr / attempted if attempted else 0.0),
        truth_success_issue_count=truth_success,
        truth_success_rate=(truth_success / attempted if attempted else 0.0),
        merged_issue_count=merged,
        merged_issue_rate=(merged / attempted if attempted else 0.0),
        no_rescue_truth_success_issue_count=no_rescue_truth_success,
        no_rescue_truth_success_rate=(no_rescue_truth_success / attempted if attempted else 0.0),
        truth_state_counts=dict(sorted(state_counts.items())),
    )


def render_table(
    repo: str, metrics_file: Path, records: list[IssueTruthRecord], summary: TruthSummary
) -> str:
    headers = ["Issue", "Proxy", "Truth", "No rescue", "Linked PRs", "Title"]
    body_rows: list[list[str]] = []
    for record in records:
        pr_cell = (
            ", ".join(
                f"#{pr.number}:{pr.truth_state}:{pr.mergeable or '-'}" for pr in record.linked_prs
            )
            or "-"
        )
        body_rows.append(
            [
                str(record.issue_number),
                "yes" if record.proxy_pr_signal else "no",
                record.truth_state,
                "yes" if record.no_rescue_truth_success else "no",
                pr_cell,
                record.issue_title,
            ]
        )

    widths = [len(header) for header in headers]
    for row in body_rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def fmt(row: list[str]) -> str:
        return " | ".join(value.ljust(widths[idx]) for idx, value in enumerate(row))

    lines = [
        f"Repo: {repo}",
        f"Metrics file: {metrics_file}",
        "",
        "Rates are issue-level. Proxy success is metrics-derived. Truth success is GitHub-derived (mergeable or merged PR).",
        f"Attempted issues: {summary.attempted_issue_count}",
        (
            "Proxy success (proxy): "
            f"{summary.proxy_success_issue_count}/{summary.attempted_issue_count} "
            f"({summary.proxy_success_rate:.1%})"
        ),
        (
            "Linked PR issues (truth): "
            f"{summary.linked_pr_issue_count}/{summary.attempted_issue_count} "
            f"({summary.linked_pr_issue_rate:.1%})"
        ),
        (
            "Mergeable or merged issues (truth success): "
            f"{summary.truth_success_issue_count}/{summary.attempted_issue_count} "
            f"({summary.truth_success_rate:.1%})"
        ),
        (
            "Merged issues (truth): "
            f"{summary.merged_issue_count}/{summary.attempted_issue_count} "
            f"({summary.merged_issue_rate:.1%})"
        ),
        (
            "No-rescue truth success (truth + metrics): "
            f"{summary.no_rescue_truth_success_issue_count}/{summary.attempted_issue_count} "
            f"({summary.no_rescue_truth_success_rate:.1%})"
        ),
        f"Truth state counts: {summary.truth_state_counts}",
        "",
        fmt(headers),
        "-+-".join("-" * width for width in widths),
    ]
    lines.extend(fmt(row) for row in body_rows)
    return "\n".join(lines)


def report_to_json(
    repo: str,
    metrics_file: Path,
    records: list[IssueTruthRecord],
    summary: TruthSummary,
) -> str:
    payload = {
        "repo": repo,
        "metrics_file": str(metrics_file),
        "issue_level_only": True,
        "proxy_metric_note": "PR signal is metrics-derived proxy, not GitHub truth.",
        "truth_metric_note": "Truth success requires at least one linked PR with state mergeable_pr or merged_pr.",
        "summary": summary.to_dict(),
        "issues": [record.to_dict() for record in records],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--metrics-file",
        type=Path,
        default=DEFAULT_METRICS_PATH,
        help=f"Metrics JSONL file (default: {DEFAULT_METRICS_PATH})",
    )
    parser.add_argument("--repo", default="synaptent/aragora", help="GitHub repo owner/name")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    metrics_file = resolve_metrics_path(args.metrics_file)
    if not metrics_file.exists():
        parser.error(f"metrics file not found: {metrics_file}")

    rows = load_metrics_rows(metrics_file)
    aggregates = aggregate_b0_issues(rows)
    client = GitHubTruthClient()
    records = [reconcile_issue_truth(args.repo, aggregate, client) for aggregate in aggregates]
    summary = summarize_truth(records)

    if args.json:
        print(report_to_json(args.repo, metrics_file, records, summary))
    else:
        print(render_table(args.repo, metrics_file, records, summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
