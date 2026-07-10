"""Tier 4 repo-visible settlement trust helpers for review-queue."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from aragora.cli.commands import review_queue_rest_fallback as rest_fallback
from aragora.cli.commands.review_queue_transport import _GhError, _gh_json

UTC = timezone.utc
HUMAN_SETTLEMENT_CONTEXT = "aragora/human-settlement"
TIER_FOUR_SETTLEMENT_MARKER = "Tier-4 Human Settlement Authorization"
DEFAULT_TRUSTED_SETTLEMENT_CREATOR = "scarmani"
SETTLEMENT_CREATOR_ENV_VAR = "ARAGORA_SETTLEMENT_CREATOR"
TIER_FOUR_AUTHORIZED_MERGE_TOKENS = ("admin_squash_merge", "admin squash")
STATUS_TIMESTAMP_FIELDS = (
    "updated_at",
    "updatedAt",
    "created_at",
    "createdAt",
    "completed_at",
    "completedAt",
    "started_at",
    "startedAt",
)

GhJson = Callable[[list[str]], Any]


def _trusted_settlement_creator() -> str:
    return (
        str(os.environ.get(SETTLEMENT_CREATOR_ENV_VAR, "") or "").strip()
        or DEFAULT_TRUSTED_SETTLEMENT_CREATOR
    )


def _human_settlement_status_creator_verified(
    *,
    repo_slug: str,
    head_sha: str,
    context: str = HUMAN_SETTLEMENT_CONTEXT,
    target_url: str = "",
    gh_json: GhJson = _gh_json,
) -> tuple[bool, str]:
    trusted = _trusted_settlement_creator()
    expected_target_url = str(target_url or "").strip()

    def fail(reason: str) -> tuple[bool, str]:
        return (False, f"settlement-creator pin: {reason}")

    if not repo_slug or not head_sha:
        return fail("missing repo slug or head sha; failing closed")
    if not expected_target_url:
        return fail("missing trusted settlement comment target_url; failing closed")
    try:
        payload = gh_json(["api", f"repos/{repo_slug}/commits/{head_sha}/statuses?per_page=100"])
    except _GhError as exc:
        return fail(f"could not fetch commit statuses ({exc}); failing closed")
    if not isinstance(payload, list):
        return fail("unexpected statuses payload shape; failing closed")
    ok, status, reason = _newest_human_settlement_status(payload, context=context)
    if not ok:
        return fail(reason)
    if status is None:
        return fail(f"no '{context}' status found on head commit; failing closed")
    state = str(status.get("state") or "").strip().lower()
    creator = status.get("creator")
    login = str(creator.get("login") or "").strip() if isinstance(creator, dict) else ""
    if state != "success":
        return fail(f"newest '{context}' status state is '{state}', not success")
    if not login:
        return fail(f"newest '{context}' status has no creator login; failing closed")
    if login.casefold() != trusted.casefold():
        return fail(
            f"newest '{context}' status was created by '{login}', "
            f"not trusted settlement creator '{trusted}'"
        )
    status_target_url = str(status.get("target_url") or status.get("targetUrl") or "").strip()
    if status_target_url != expected_target_url:
        return fail(
            f"newest '{context}' status target_url does not match the trusted settlement comment"
        )
    return (
        True,
        f"settlement-creator pin: '{context}' status created by trusted settlement creator '{trusted}'",
    )


def _status_timestamp(status: dict[str, Any]) -> datetime | None:
    for key in STATUS_TIMESTAMP_FIELDS:
        parsed = _parse_github_datetime(status.get(key))
        if parsed is not None:
            return parsed
    return None


def _newest_human_settlement_status(
    payload: list[Any], *, context: str
) -> tuple[bool, dict[str, Any] | None, str]:
    statuses = [
        status
        for status in payload
        if isinstance(status, dict) and str(status.get("context") or "").strip() == context
    ]
    if not statuses:
        return True, None, ""
    if len(statuses) == 1:
        return True, statuses[0], ""

    timestamped: list[tuple[datetime, int, dict[str, Any]]] = []
    for index, status in enumerate(statuses):
        timestamp = _status_timestamp(status)
        if timestamp is None:
            return (
                False,
                None,
                f"multiple '{context}' statuses include missing timestamp; failing closed",
            )
        timestamped.append((timestamp, index, status))
    timestamped.sort(key=lambda item: (item[0], item[1]), reverse=True)
    newest = timestamped[0]
    if len(timestamped) > 1 and timestamped[1][0] == newest[0]:
        return (
            False,
            None,
            f"multiple '{context}' statuses share newest timestamp; failing closed",
        )
    return True, newest[2], ""


def _comment_author_login(comment: dict[str, Any]) -> str:
    for key in ("author", "user"):
        author = comment.get(key)
        if isinstance(author, dict):
            login = str(author.get("login") or "").strip()
            if login:
                return login
        elif isinstance(author, str) and author.strip():
            return author.strip()
    return ""


def _comment_author_association(comment: dict[str, Any]) -> str:
    return (
        str(comment.get("authorAssociation") or comment.get("author_association") or "")
        .strip()
        .upper()
    )


def _comment_created_at(comment: dict[str, Any]) -> str:
    return str(comment.get("createdAt") or comment.get("created_at") or "").strip()


def _comment_url(comment: dict[str, Any]) -> str:
    return str(comment.get("url") or comment.get("html_url") or "").strip()


def _trusted_comment_author_verified(
    comment: dict[str, Any],
    *,
    repo_slug: str,
    gh_json: GhJson = _gh_json,
) -> bool:
    association = _comment_author_association(comment)
    if association not in {"OWNER", "MEMBER", "COLLABORATOR"}:
        return False
    login = _comment_author_login(comment)
    trusted = _trusted_settlement_creator()
    if not login or login.casefold() != trusted.casefold() or not repo_slug:
        return False
    # GitHub authorAssociation is PR metadata, not enough authority for Tier 4.
    # Bind every accepted settlement comment to the configured trusted operator
    # and a live repo-admin permission check, including OWNER-labeled comments.
    try:
        payload = gh_json(
            ["api", f"repos/{repo_slug}/collaborators/{quote(login, safe='')}/permission"]
        )
    except _GhError:
        return False
    if not isinstance(payload, dict):
        return False
    return (
        str(payload.get("permission") or "").strip().lower() == "admin"
        or str(payload.get("role_name") or "").strip().lower() == "admin"
    )


def _comment_is_fresh_for_head(
    comment: dict[str, Any],
    *,
    head_committed_at: str,
) -> bool:
    created_at = _comment_created_at(comment)
    created = _parse_github_datetime(created_at)
    committed = _parse_github_datetime(head_committed_at)
    return bool(created and committed and created >= committed)


def _parse_github_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _trusted_tier_four_human_preapproval_comment_url(
    pr: dict[str, Any],
    *,
    head_sha: str,
    head_committed_at: str,
    repo_slug: str,
    gh_json: GhJson = _gh_json,
) -> str:
    head = str(head_sha or "").strip()
    if not head:
        return ""
    candidates: list[tuple[datetime, int, str]] = []
    for index, comment in enumerate(pr.get("comments") or []):
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body") or "")
        lowered = body.lower()
        if TIER_FOUR_SETTLEMENT_MARKER not in body:
            continue
        if head not in body:
            continue
        if not any(token in lowered for token in TIER_FOUR_AUTHORIZED_MERGE_TOKENS):
            continue
        if "human-risk settlement" not in lowered:
            continue
        comment_url = _comment_url(comment)
        if not comment_url:
            continue
        if not _comment_is_fresh_for_head(comment, head_committed_at=head_committed_at):
            continue
        if not _trusted_comment_author_verified(comment, repo_slug=repo_slug, gh_json=gh_json):
            continue
        created_at = _parse_github_datetime(_comment_created_at(comment))
        if created_at is None:
            continue
        candidates.append((created_at, index, comment_url))
    if not candidates:
        return ""
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def _trusted_recorded_settlement_comment_url(
    *,
    pr_number: int,
    repo_slug: str,
    repo_override: str | None,
    head_sha: str,
    gh_json: GhJson = _gh_json,
) -> str:
    fields = "number,url,headRefOid,comments,commits"
    args = ["pr", "view", str(pr_number), "--json", fields]
    if repo_override:
        args.extend(["--repo", repo_override])
    pr = gh_json(args)
    if not isinstance(pr, dict):
        raise _GhError(f"PR #{pr_number} not found while binding settlement status")
    live_head = str(pr.get("headRefOid", "") or "").strip()
    if live_head != head_sha:
        raise _GhError(
            f"PR #{pr_number} head changed from {head_sha} to {live_head}; "
            "refusing to post exact-head settlement status"
        )
    comment_url = _trusted_tier_four_human_preapproval_comment_url(
        pr,
        head_sha=head_sha,
        head_committed_at=_head_committed_at_from_pr(pr),
        repo_slug=repo_slug,
        gh_json=gh_json,
    )
    if not comment_url:
        raise _GhError(
            "no trusted exact-head Tier 4 settlement comment URL found; "
            "refusing to post aragora/human-settlement status"
        )
    return comment_url


def _has_tier_four_human_preapproval_comment(
    pr: dict[str, Any],
    *,
    head_sha: str,
    gh_json: GhJson = _gh_json,
) -> bool:
    return bool(
        _trusted_tier_four_human_preapproval_comment_url(
            pr,
            head_sha=head_sha,
            head_committed_at=_head_committed_at_from_pr(pr),
            repo_slug=rest_fallback._repo_slug_from_pr_payload(pr, None),
            gh_json=gh_json,
        )
    )


def _head_committed_at_from_pr(pr: dict[str, Any]) -> str:
    head_sha = str(pr.get("headRefOid", "") or "").strip()
    if not head_sha:
        return ""
    for commit in pr.get("commits") or []:
        if not isinstance(commit, dict):
            continue
        oid = str(commit.get("oid") or commit.get("sha") or "").strip()
        if not oid or oid != head_sha:
            continue
        committed = str(
            commit.get("committedDate")
            or commit.get("committed_at")
            or commit.get("commit", {}).get("committer", {}).get("date")
            or ""
        ).strip()
        if committed:
            return committed
    return ""
