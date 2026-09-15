#!/usr/bin/env python3
"""Build a read-only ledger of unanswered PR authorization requests.

The ledger compresses operator transport only. It never grants authority and
never posts, edits, reruns, settles, or merges anything on GitHub.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from founder_decision_queue import _escape_table_cell, _github_cli_env, _parse_datetime
except ImportError:  # pragma: no cover - import path used by repository tests
    from scripts.founder_decision_queue import (
        _escape_table_cell,
        _github_cli_env,
        _parse_datetime,
    )

UTC = timezone.utc
DEFAULT_REPO = "synaptent/aragora"
DEFAULT_OPERATOR_LOGINS = ("an0mium",)
TRUSTED_AUTHOR_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
GH_TIMEOUT_SECONDS = 60
NON_QUORUM_REQUIRED_CONTEXTS = {
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
}
ASK_MARKERS = (
    "authorization request",
    "preapproval request",
    "operator decision needed",
    "operator authorization needed",
    "human owner must decide",
)
DECISIVE_REPLY_MARKERS = (
    "i authorize",
    "i accept",
    "i approve",
    "i reject",
    "i decline",
    "do not advance",
    "keep this pr parked",
    "close this pr",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequiredCheckSummary:
    green: bool
    summary: str


@dataclass(frozen=True)
class AuthorizationItem:
    pr: int
    title: str
    tier: int
    ask_head: str
    current_head: str
    head_matches: bool
    mergeable: str
    merge_state_status: str
    required_checks_green: bool
    required_checks: str
    ask_created_at: str
    age_days: int
    source_url: str
    expected_reply: str

    @property
    def settlement_shape_green(self) -> bool:
        return (
            self.head_matches
            and self.required_checks_green
            and self.mergeable == "MERGEABLE"
            and self.merge_state_status in {"CLEAN", "BLOCKED"}
        )


def _run_json(command: Sequence[str]) -> Any:
    result = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_SECONDS,
        env=_github_cli_env(),
    )
    if not result.stdout.strip():
        detail = result.stderr.strip() or f"exit {result.returncode}"
        raise RuntimeError(f"command returned no JSON: {' '.join(command)}: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned malformed JSON: {' '.join(command)}") from exc


def load_open_prs(*, repo: str) -> list[dict[str, Any]]:
    try:
        payload = _run_json(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                "500",
                "--json",
                "number,title,headRefOid,headRefName,isDraft,mergeable,mergeStateStatus,author,comments",
            ]
        )
        if not isinstance(payload, list):
            raise RuntimeError("gh pr list returned a non-list payload")
        return [item for item in payload if isinstance(item, dict)]
    except RuntimeError as exc:
        print(f"warning: GraphQL PR scan failed, using REST fallback: {exc}", file=sys.stderr)
        return _load_open_prs_rest(repo=repo)


def _flatten_pages(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    values: list[Any] = []
    for item in payload:
        values.extend(item if isinstance(item, list) else [item])
    return [item for item in values if isinstance(item, dict)]


def _rest_comment(comment: Mapping[str, Any]) -> dict[str, Any]:
    user = comment.get("user")
    login = user.get("login") if isinstance(user, Mapping) else ""
    return {
        "author": {"login": login},
        "authorAssociation": comment.get("author_association"),
        "body": comment.get("body"),
        "createdAt": comment.get("created_at"),
        "url": comment.get("html_url"),
    }


def _load_open_prs_rest(*, repo: str) -> list[dict[str, Any]]:
    pulls = _flatten_pages(
        _run_json(
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/pulls?state=open&per_page=100",
            ]
        )
    )
    result: list[dict[str, Any]] = []
    for pull in pulls:
        number = pull.get("number")
        if not isinstance(number, int):
            continue
        comments = _flatten_pages(
            _run_json(
                [
                    "gh",
                    "api",
                    "--paginate",
                    "--slurp",
                    f"repos/{repo}/issues/{number}/comments?per_page=100",
                ]
            )
        )
        normalized_comments = [_rest_comment(comment) for comment in comments]
        has_ask = any(
            isinstance(comment.get("body"), str) and _looks_like_ask(comment["body"])
            for comment in normalized_comments
        )
        detail = _run_json(["gh", "api", f"repos/{repo}/pulls/{number}"]) if has_ask else pull
        if not isinstance(detail, Mapping):
            detail = pull
        head = pull.get("head")
        author = pull.get("user")
        mergeable = detail.get("mergeable")
        merge_state = detail.get("mergeable_state")
        result.append(
            {
                "number": number,
                "title": pull.get("title"),
                "headRefOid": head.get("sha") if isinstance(head, Mapping) else None,
                "headRefName": head.get("ref") if isinstance(head, Mapping) else None,
                "isDraft": bool(pull.get("draft")),
                "mergeable": (
                    "MERGEABLE"
                    if mergeable is True
                    else "CONFLICTING"
                    if mergeable is False
                    else "UNKNOWN"
                ),
                "mergeStateStatus": (
                    str(merge_state).upper() if isinstance(merge_state, str) else "UNKNOWN"
                ),
                "author": {"login": author.get("login") if isinstance(author, Mapping) else ""},
                "comments": normalized_comments,
            }
        )
    return result


def load_required_checks(*, repo: str, pr: int) -> RequiredCheckSummary:
    payload = _run_json(
        [
            "gh",
            "pr",
            "checks",
            str(pr),
            "--repo",
            repo,
            "--required",
            "--json",
            "name,state,bucket,link",
        ]
    )
    if not isinstance(payload, list):
        return RequiredCheckSummary(False, "unknown")
    relevant = [
        check
        for check in payload
        if isinstance(check, dict) and check.get("name") in NON_QUORUM_REQUIRED_CONTEXTS
    ]
    if len(relevant) != len(NON_QUORUM_REQUIRED_CONTEXTS):
        return RequiredCheckSummary(False, f"{len(relevant)}/5 observed")
    passed = sum(check.get("bucket") == "pass" for check in relevant)
    return RequiredCheckSummary(passed == len(relevant), f"{passed}/5 green")


def _author_login(comment: Mapping[str, Any]) -> str:
    author = comment.get("author")
    if not isinstance(author, Mapping):
        return ""
    login = author.get("login")
    return login if isinstance(login, str) else ""


def _trusted_ask_author(comment: Mapping[str, Any], *, trusted_logins: set[str]) -> bool:
    association = comment.get("authorAssociation") or comment.get("author_association")
    if isinstance(association, str) and association.upper() in TRUSTED_AUTHOR_ASSOCIATIONS:
        return True
    return _author_login(comment).lower() in trusted_logins


def _looks_like_ask(body: str) -> bool:
    lowered = _unquoted_markdown_prose(body).lower()
    return any(marker in lowered for marker in ASK_MARKERS) and bool(_extract_reply_block(body))


def _extract_reply_block(body: str) -> str | None:
    fenced = re.findall(r"```(?:text)?\s*\n(.*?)```", body, flags=re.IGNORECASE | re.DOTALL)
    for block in reversed(fenced):
        stripped = block.strip()
        if re.search(r"\bI\s+(?:authorize|accept|approve)\b", stripped, flags=re.IGNORECASE):
            return stripped

    groups: list[list[str]] = []
    current: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^>\s?(.*)$", line)
        if match:
            current.append(match.group(1))
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    for group in reversed(groups):
        block = "\n".join(group).strip()
        if re.search(r"\bI\s+(?:authorize|accept|approve)\b", block, flags=re.IGNORECASE):
            return block
    return None


def _extract_tier(body: str) -> int | None:
    match = re.search(r"\bTier[- ]?([0-4])\b", body, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_head(body: str) -> str | None:
    labeled = re.search(
        r"Exact\s+head(?:\s+SHA)?[^0-9a-f]+`?([0-9a-f]{40})`?",
        body,
        flags=re.IGNORECASE,
    )
    if labeled:
        return labeled.group(1)
    match = re.search(r"\b([0-9a-f]{40})\b", body, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _comment_time(comment: Mapping[str, Any]) -> datetime | None:
    raw = comment.get("createdAt") or comment.get("created_at")
    return _parse_datetime(raw) if isinstance(raw, str) else None


def _unquoted_markdown_prose(body: str) -> str:
    """Return prose that can carry an operator decision, excluding quoted/code text."""
    prose: list[str] = []
    fence: tuple[str, int] | None = None
    for line in body.splitlines():
        stripped = line.lstrip()
        fence_match = re.match(r"(`{3,}|~{3,})(?:\s|$)", stripped)
        if fence is not None:
            if (
                fence_match
                and fence_match.group(1)[0] == fence[0]
                and len(fence_match.group(1)) >= fence[1]
            ):
                fence = None
            continue
        if fence_match:
            marker = fence_match.group(1)
            fence = (marker[0], len(marker))
            continue
        if re.match(r"^\s*>", line) or line.startswith(("    ", "\t")):
            continue
        prose.append(re.sub(r"`+[^`]*`+", "", line))
    return "\n".join(prose)


def _decisive_operator_reply(body: str, *, pr: int, head: str) -> bool:
    prose = _unquoted_markdown_prose(body)
    lowered = prose.lower()
    references_target = bool(re.search(rf"#{pr}(?!\d)", prose)) or head in lowered
    return references_target and any(marker in lowered for marker in DECISIVE_REPLY_MARKERS)


def _is_dependabot_pr(pr: Mapping[str, Any]) -> bool:
    head_ref = pr.get("headRefName")
    author = pr.get("author")
    author_login = author.get("login") if isinstance(author, Mapping) else ""
    return (
        isinstance(head_ref, str)
        and head_ref.startswith("dependabot/")
        or author_login == "dependabot[bot]"
    )


def collect_authorizations(
    prs: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    operator_logins: set[str],
    check_loader: Callable[[int], RequiredCheckSummary],
    trusted_ask_logins: set[str] | None = None,
) -> list[AuthorizationItem]:
    trusted_logins = {login.lower() for login in (trusted_ask_logins or operator_logins)}
    items: list[AuthorizationItem] = []
    for pr in prs:
        if _is_dependabot_pr(pr):
            continue
        comments = [comment for comment in pr.get("comments", []) if isinstance(comment, dict)]
        comments.sort(
            key=lambda comment: _comment_time(comment) or datetime.min.replace(tzinfo=UTC)
        )
        for index in range(len(comments) - 1, -1, -1):
            comment = comments[index]
            body = comment.get("body")
            if not isinstance(body, str) or not _looks_like_ask(body):
                continue
            if not _trusted_ask_author(comment, trusted_logins=trusted_logins):
                logger.warning(
                    "ignoring authorization ask from untrusted author %r on PR #%s",
                    _author_login(comment),
                    pr.get("number"),
                )
                continue
            reply = _extract_reply_block(body)
            tier = _extract_tier(reply or body)
            ask_head = _extract_head(reply or body)
            created_at = _comment_time(comment)
            if reply is None or tier is None or ask_head is None or created_at is None:
                continue
            pr_number = pr.get("number")
            current_head = pr.get("headRefOid")
            title = pr.get("title")
            if not isinstance(pr_number, int) or not isinstance(current_head, str):
                continue
            if not isinstance(title, str):
                title = ""
            answered = any(
                _author_login(later) in operator_logins
                and isinstance(later.get("body"), str)
                and _decisive_operator_reply(later["body"], pr=pr_number, head=ask_head)
                for later in comments[index + 1 :]
            )
            if answered:
                break
            checks = check_loader(pr_number)
            age_days = max(0, int((now - created_at).total_seconds() // 86400))
            items.append(
                AuthorizationItem(
                    pr=pr_number,
                    title=title,
                    tier=tier,
                    ask_head=ask_head,
                    current_head=current_head,
                    head_matches=ask_head == current_head,
                    mergeable=str(pr.get("mergeable") or "UNKNOWN"),
                    merge_state_status=str(pr.get("mergeStateStatus") or "UNKNOWN"),
                    required_checks_green=checks.green,
                    required_checks=checks.summary,
                    ask_created_at=created_at.isoformat().replace("+00:00", "Z"),
                    age_days=age_days,
                    source_url=str(comment.get("url") or ""),
                    expected_reply=reply,
                )
            )
            break
    return sorted(
        items,
        key=lambda item: (
            not item.head_matches,
            not item.settlement_shape_green,
            item.tier,
            -item.age_days,
            item.pr,
        ),
    )


def render_packet(items: Iterable[AuthorizationItem], *, repo: str, now: datetime) -> str:
    rows = list(items)
    lines = [
        "# Parked Authorization Ledger",
        "",
        f"Generated: {now.astimezone(UTC).isoformat().replace('+00:00', 'Z')}",
        f"Repository: `{repo}`",
        "",
        "> This read-only ledger compresses transport. It grants no implementation, review,",
        "> settlement, merge, workflow, or branch-protection authority. The exact reply blocks",
        "> below remain subject to live head, ownership, and gate revalidation.",
        "",
        "## Pending Rulings",
        "",
        "| Priority | Link | Tier | Ask head | Current head | Head status | Required checks | Merge state | Age | Current blocker | Requested action | One-word reply |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for priority, item in enumerate(rows, start=1):
        head_status = "MATCH" if item.head_matches else "HEAD MOVED - re-ask"
        requested_action = f"Paste the exact PR #{item.pr} block below after live revalidation."
        pointer = f"See exact block for PR #{item.pr} below"
        blocker = "Human authorization pending" if item.head_matches else "Recorded ask is stale"
        link = f"PR #{item.pr}: https://github.com/{repo}/pull/{item.pr}"
        values = [
            str(priority),
            link,
            str(item.tier),
            f"`{item.ask_head}`",
            f"`{item.current_head}`",
            head_status,
            item.required_checks,
            f"{item.mergeable}/{item.merge_state_status}",
            f"{item.age_days}d",
            blocker,
            requested_action,
            pointer,
        ]
        lines.append("| " + " | ".join(_escape_table_cell(value) for value in values) + " |")
    if not rows:
        lines.append("| - | - | - | - | - | - | - | - | - | No unanswered asks found | - | - |")

    lines.extend(["", "## Exact Reply Blocks", ""])
    for item in rows:
        lines.extend(
            [
                f"### PR #{item.pr}",
                "",
                f"Source: {item.source_url or 'PR comment URL unavailable'}",
                "",
                "```text",
                item.expected_reply,
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--operator-login", action="append", default=[])
    parser.add_argument("--trusted-ask-login", action="append", default=[])
    parser.add_argument("--now", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _parse_datetime(args.now) if args.now else datetime.now(tz=UTC)
    if now is None:
        raise SystemExit(f"invalid --now timestamp: {args.now}")
    operator_logins = set(args.operator_login or DEFAULT_OPERATOR_LOGINS)
    trusted_ask_logins = operator_logins | set(args.trusted_ask_login)
    prs = load_open_prs(repo=args.repo)
    items = collect_authorizations(
        prs,
        now=now,
        operator_logins=operator_logins,
        check_loader=lambda pr: load_required_checks(repo=args.repo, pr=pr),
        trusted_ask_logins=trusted_ask_logins,
    )
    if args.json:
        print(
            json.dumps({"count": len(items), "items": [asdict(item) for item in items]}, indent=2)
        )
        return 0
    packet = render_packet(items, repo=args.repo, now=now)
    if not args.output:
        print(packet, end="")
        return 0
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(packet, encoding="utf-8")
    print(f"wrote {output} ({len(items)} pending authorizations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
