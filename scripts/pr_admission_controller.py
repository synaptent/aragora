#!/usr/bin/env python3
"""PR admission controller for multi-agent CI lane governance.

Policy:
- At most ``max_ready_per_stream`` open ready PRs per stream.
- Stream can be set via label prefixes: ``lane:``, ``lane/``, ``stream:``, ``stream/``.
- If no stream label exists, infer stream from changed files.

When ``--enforce`` is enabled and the current PR is over capacity for its stream:
- convert PR back to draft
- disable auto-merge (if enabled)
- post an explanatory PR comment
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib import error, parse, request


STREAM_LABEL_PREFIXES = ("lane:", "lane/", "stream:", "stream/")


def _normalize_stream_value(raw: str) -> str:
    value = raw.strip().lower()
    value = re.sub(r"[^a-z0-9._/-]+", "-", value)
    value = value.strip("-/")
    return value or "core"


def extract_stream_from_labels(labels: list[dict[str, Any]]) -> str | None:
    """Extract stream label from PR labels, if present."""
    for label in labels:
        name = str(label.get("name", "")).strip()
        lower_name = name.lower()
        for prefix in STREAM_LABEL_PREFIXES:
            if lower_name.startswith(prefix):
                return _normalize_stream_value(name[len(prefix) :])
    return None


def classify_stream_from_files(files: list[str]) -> str:
    """Infer stream from changed file paths."""
    if not files:
        return "core"

    normalized = [f.strip() for f in files if f.strip()]
    if not normalized:
        return "core"

    docs_only = all(
        f.startswith("docs/")
        or f.endswith(".md")
        or f.endswith(".mdx")
        or f.endswith(".rst")
        or f.endswith(".txt")
        for f in normalized
    )
    if docs_only:
        return "docs"

    ci_only = all(
        f.startswith(".github/workflows/")
        or f.startswith("scripts/pr_")
        or f.startswith("scripts/ci_")
        or f.startswith("scripts/check_")
        for f in normalized
    )
    if ci_only:
        return "ci"

    if any(f.startswith("aragora/live/") for f in normalized):
        return "frontend"
    if any(f.startswith("sdk/") for f in normalized):
        return "sdk"
    if any(f.startswith(".github/") for f in normalized):
        return "ci"
    return "core"


def select_admitted_pr_numbers(
    ready_prs: list[dict[str, Any]],
    stream_by_pr: dict[int, str],
    target_stream: str,
    max_ready_per_stream: int,
) -> set[int]:
    """Select admitted PR numbers for a stream by oldest-first fairness."""
    in_stream = [pr for pr in ready_prs if stream_by_pr.get(int(pr["number"])) == target_stream]
    in_stream.sort(key=lambda pr: (str(pr.get("created_at", "")), int(pr["number"])))
    return {int(pr["number"]) for pr in in_stream[:max_ready_per_stream]}


class GitHubApiError(RuntimeError):
    """Raised when GitHub API calls fail."""


class GitHubClient:
    """Small GitHub API client using urllib and GITHUB_TOKEN."""

    def __init__(self, repo: str, token: str) -> None:
        if "/" not in repo:
            raise ValueError(f"Invalid repo format '{repo}', expected OWNER/REPO")
        self.repo = repo
        self.token = token
        self.api_base = "https://api.github.com"

    def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[Any, request.addinfourl]:
        body: bytes | None = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "aragora-pr-admission-controller",
        }
        if extra_headers:
            headers.update(extra_headers)

        req = request.Request(url=url, data=body, headers=headers, method=method)
        try:
            resp = request.urlopen(req, timeout=30)
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return parsed, resp
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise GitHubApiError(
                f"GitHub API {method} {url} failed: {exc.code} {exc.reason}\n{details}"
            ) from exc

    def _api(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.api_base}{path}"
        if query:
            url += "?" + parse.urlencode(query, doseq=True)
        return url

    def get(self, path: str, query: dict[str, Any] | None = None) -> Any:
        data, _ = self._request_json("GET", self._api(path, query))
        return data

    def post(self, path: str, payload: dict[str, Any] | None = None) -> Any:
        data, _ = self._request_json("POST", self._api(path), payload=payload)
        return data

    def paginate(self, path: str, query: dict[str, Any] | None = None) -> list[Any]:
        items: list[Any] = []
        current_query = dict(query or {})
        current_query.setdefault("per_page", 100)
        current_query.setdefault("page", 1)

        while True:
            data, response = self._request_json("GET", self._api(path, current_query))
            if isinstance(data, list):
                page_items = data
            else:
                raise GitHubApiError(
                    f"Expected list response for paginated endpoint {path}, got {type(data)}"
                )
            items.extend(page_items)

            link_header = response.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            current_query["page"] = int(current_query["page"]) + 1

        return items

    def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        data, _ = self._request_json(
            "POST", self._api("/graphql"), payload={"query": query, "variables": variables}
        )
        return data

    def get_pull(self, number: int) -> dict[str, Any]:
        return self.get(f"/repos/{self.repo}/pulls/{number}")

    def list_open_pulls(self, base_branch: str) -> list[dict[str, Any]]:
        pulls = self.paginate(
            f"/repos/{self.repo}/pulls",
            query={"state": "open", "base": base_branch, "per_page": 100},
        )
        return [p for p in pulls if isinstance(p, dict)]

    def list_pull_files(self, number: int) -> list[str]:
        files = self.paginate(
            f"/repos/{self.repo}/pulls/{number}/files",
            query={"per_page": 100},
        )
        return [str(f.get("filename", "")).strip() for f in files if isinstance(f, dict)]

    def add_issue_comment(self, number: int, body: str) -> None:
        self.post(f"/repos/{self.repo}/issues/{number}/comments", payload={"body": body})

    def convert_pull_to_draft(self, pull_node_id: str) -> tuple[bool, str]:
        mutation = """
        mutation ConvertToDraft($pullRequestId: ID!) {
          convertPullRequestToDraft(input: {pullRequestId: $pullRequestId}) {
            pullRequest {
              number
              isDraft
            }
          }
        }
        """
        data = self.graphql(mutation, {"pullRequestId": pull_node_id})
        errors = data.get("errors") or []
        if errors:
            return False, str(errors)
        return True, "converted"

    def disable_auto_merge(self, pull_node_id: str) -> tuple[bool, str]:
        mutation = """
        mutation DisableAutoMerge($pullRequestId: ID!) {
          disablePullRequestAutoMerge(input: {pullRequestId: $pullRequestId}) {
            pullRequest {
              number
            }
          }
        }
        """
        data = self.graphql(mutation, {"pullRequestId": pull_node_id})
        errors = data.get("errors") or []
        if errors:
            # Common benign case: auto-merge wasn't enabled.
            return False, str(errors)
        return True, "disabled"


def _build_block_comment(
    *,
    stream: str,
    max_ready_per_stream: int,
    admitted_prs: set[int],
    current_pr_number: int,
) -> str:
    admitted_text = ", ".join(f"#{n}" for n in sorted(admitted_prs)) or "(none)"
    return (
        "⚠️ PR Admission Controller blocked this PR from staying ready-for-review.\n\n"
        f"- Stream: `{stream}`\n"
        f"- Allowed ready PRs in this stream: `{max_ready_per_stream}`\n"
        f"- Currently admitted PR(s): {admitted_text}\n"
        f"- This PR: `#{current_pr_number}` was converted back to draft.\n\n"
        "To proceed: merge/close the admitted PR, then mark this PR ready again."
    )


def evaluate_admission(
    *,
    client: GitHubClient,
    current_pr_number: int,
    max_ready_per_stream: int,
    enforce: bool,
) -> int:
    current_pr = client.get_pull(current_pr_number)
    if str(current_pr.get("state", "")).lower() != "open":
        print(f"PR #{current_pr_number} is not open; skipping.")
        return 0
    if bool(current_pr.get("draft")):
        print(f"PR #{current_pr_number} is draft; skipping.")
        return 0

    base_branch = str(current_pr.get("base", {}).get("ref", "main"))
    open_prs = client.list_open_pulls(base_branch)
    ready_prs = [pr for pr in open_prs if not bool(pr.get("draft"))]

    files_cache: dict[int, list[str]] = {}
    stream_by_pr: dict[int, str] = {}

    for pr in ready_prs:
        number = int(pr["number"])
        label_stream = extract_stream_from_labels(pr.get("labels", []))
        if label_stream:
            stream_by_pr[number] = label_stream
            continue
        files = files_cache.setdefault(number, client.list_pull_files(number))
        stream_by_pr[number] = classify_stream_from_files(files)

    current_stream = stream_by_pr.get(current_pr_number, "core")
    admitted = select_admitted_pr_numbers(
        ready_prs=ready_prs,
        stream_by_pr=stream_by_pr,
        target_stream=current_stream,
        max_ready_per_stream=max_ready_per_stream,
    )
    admitted_text = ", ".join(f"#{n}" for n in sorted(admitted)) or "(none)"
    print(
        json.dumps(
            {
                "current_pr": current_pr_number,
                "stream": current_stream,
                "max_ready_per_stream": max_ready_per_stream,
                "admitted_ready_prs": sorted(admitted),
            }
        )
    )

    if current_pr_number in admitted:
        print(
            f"Admission passed for PR #{current_pr_number} in stream '{current_stream}'. "
            f"Admitted: {admitted_text}"
        )
        return 0

    print(
        f"Admission blocked for PR #{current_pr_number} in stream '{current_stream}'. "
        f"Admitted: {admitted_text}"
    )
    if not enforce:
        return 2

    pr_node_id = str(current_pr.get("node_id", ""))
    if not pr_node_id:
        raise GitHubApiError(f"PR #{current_pr_number} is missing node_id")

    converted, converted_msg = client.convert_pull_to_draft(pr_node_id)
    disabled, disabled_msg = client.disable_auto_merge(pr_node_id)
    comment = _build_block_comment(
        stream=current_stream,
        max_ready_per_stream=max_ready_per_stream,
        admitted_prs=admitted,
        current_pr_number=current_pr_number,
    )
    client.add_issue_comment(current_pr_number, comment)

    print(
        f"Enforcement applied to PR #{current_pr_number}: "
        f"converted={converted} ({converted_msg}), "
        f"auto_merge_disabled={disabled} ({disabled_msg})"
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PR admission controller")
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", ""),
        help="GitHub repository in OWNER/REPO format",
    )
    parser.add_argument("--pr-number", type=int, required=True, help="PR number to evaluate")
    parser.add_argument(
        "--max-ready-per-stream",
        type=int,
        default=1,
        help="Maximum allowed open ready PRs per stream",
    )
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Apply enforcement (convert overflow PRs to draft)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.repo:
        print("--repo is required (or set GITHUB_REPOSITORY)", file=sys.stderr)
        return 1
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN is required", file=sys.stderr)
        return 1
    if args.max_ready_per_stream < 1:
        print("--max-ready-per-stream must be >= 1", file=sys.stderr)
        return 1

    try:
        client = GitHubClient(repo=args.repo, token=token)
        return evaluate_admission(
            client=client,
            current_pr_number=args.pr_number,
            max_ready_per_stream=args.max_ready_per_stream,
            enforce=bool(args.enforce),
        )
    except (GitHubApiError, ValueError) as exc:
        print(f"Admission controller error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
