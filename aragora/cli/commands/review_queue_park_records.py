"""Exact-head park-record parsing for merge safety helpers."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

PARK_RECORD_MARKERS: tuple[str, ...] = (
    "Current-head repeat-blocker park",
    "Current-head evidence blocker",
    "Evidence safety correction",
)
PARK_LIFT_RECORD_MARKERS: tuple[str, ...] = (
    "Current-head park lift",
    "Current-head park override",
)
# A park only adds a merge block, so any maintainer may post one. A lift removes
# a block, so it uses the Tier 4 operator trust of scripts/settle_tier4_pr.py:
# OWNER; MEMBER on the trusted-operator allowlist; COLLABORATOR only with an
# allowlist entry and a live repo-admin permission check.
TRUSTED_PARK_AUTHOR_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
TRUSTED_LIFT_AUTHOR_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER"})
TRUSTED_LIFT_ALLOWLIST_ASSOCIATIONS: frozenset[str] = frozenset({"MEMBER"})
TRUSTED_LIFT_ALLOWLIST_ADMIN_ASSOCIATIONS: frozenset[str] = frozenset({"COLLABORATOR"})
TRUSTED_OPERATOR_LOGINS_ENV = "ARAGORA_TIER4_TRUSTED_OPERATORS"
DEFAULT_TRUSTED_OPERATOR_LOGINS: frozenset[str] = frozenset({"scarmani"})

AdminPermissionChecker = Callable[[str], bool]

_HEAD_LINE_RE = re.compile(
    r"(?i)^(?:exact\s+head|current\s+head|head)\s*[:=]\s*`?([0-9a-f]{40})(?![0-9a-f])"
)
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
_ALL_MARKERS: tuple[str, ...] = PARK_RECORD_MARKERS + PARK_LIFT_RECORD_MARKERS


def current_head_park_record(
    comments: list[Any],
    *,
    head_sha: str,
    trusted_operator_logins: Iterable[str] | None = None,
    admin_permission_checker: AdminPermissionChecker | None = None,
) -> dict[str, Any]:
    """Return the standing exact-head park record, if one is still authoritative.

    Park records are repo-visible PR comments from a trusted maintainer whose
    marker stands on its own line and whose block (the lines after the marker,
    up to the next heading or marker) carries a head line naming the current
    head. Text inside code fences, indented code and ``>`` quotes is ignored, so
    quoting a template or mentioning a marker in prose is not a park. Later
    supportive evidence on the same head is not a lift; only a later lift or
    override record for that same head, from a trusted operator, clears it.

    ``trusted_operator_logins`` defaults to ``ARAGORA_TIER4_TRUSTED_OPERATORS``
    (comma-separated), or ``scarmani`` when that is unset. A COLLABORATOR lift
    also needs ``admin_permission_checker`` to confirm live admin permission;
    without a checker, or when the check fails, the lift is ignored.
    """
    head = str(head_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return {"blocked": False, "head_sha": head, "lifted_by": None}

    operators = (
        _trusted_operator_logins_from_env()
        if trusted_operator_logins is None
        else _normalized_logins(trusted_operator_logins)
    )
    standing_park: dict[str, Any] | None = None
    lifted_by: dict[str, Any] | None = None
    for comment in _chronological_comments(comments):
        body = _comment_body(comment)
        if not body:
            continue
        park_record = _park_record(comment, head)
        if park_record is not None:
            standing_park = park_record
            lifted_by = None
            continue
        lift_record = _lift_record(
            comment,
            head,
            trusted_operator_logins=operators,
            admin_permission_checker=admin_permission_checker,
        )
        if lift_record is not None:
            standing_park = None
            lifted_by = lift_record

    if standing_park is None:
        return {"blocked": False, "head_sha": head, "lifted_by": lifted_by}

    marker = standing_park.get("park_marker") or "current-head park"
    where = standing_park.get("comment_url") or standing_park.get("created_at") or "repo comment"
    blocker = f"current-head park record present: {marker} at {where}"
    return {
        **standing_park,
        "blocked": True,
        "blocker": blocker,
        "reason": "Do not merge this PR on this head.",
        "lifted_by": None,
    }


def collaborator_admin_permission_checker(
    repo_slug: str,
    *,
    gh_json: Callable[[list[str]], Any],
) -> AdminPermissionChecker:
    """Build the live repo-admin lookup that a COLLABORATOR lift needs.

    Reads GitHub's collaborator permission endpoint, as scripts/settle_tier4_pr.py
    does. Errors from ``gh_json`` propagate; the park reader treats them as
    untrusted.
    """
    slug = str(repo_slug or "").strip()

    def _has_admin_permission(login: str) -> bool:
        if not slug or not login:
            return False
        payload = gh_json(["api", f"repos/{slug}/collaborators/{quote(login, safe='')}/permission"])
        if not isinstance(payload, dict):
            return False
        return (
            str(payload.get("permission") or "").lower() == "admin"
            or str(payload.get("role_name") or "").lower() == "admin"
        )

    return _has_admin_permission


def _normalized_logins(logins: Iterable[str]) -> frozenset[str]:
    return frozenset(str(login).strip().lower() for login in logins if str(login).strip())


def _trusted_operator_logins_from_env() -> frozenset[str]:
    configured = _normalized_logins(os.environ.get(TRUSTED_OPERATOR_LOGINS_ENV, "").split(","))
    return configured or DEFAULT_TRUSTED_OPERATOR_LOGINS


def _chronological_comments(comments: list[Any]) -> list[Any]:
    return sorted(
        comments or [],
        key=lambda comment: (
            _comment_timestamp(comment),
            _comment_url(comment),
            _comment_body(comment),
        ),
    )


def _comment_timestamp(comment: Any) -> datetime:
    if not isinstance(comment, dict):
        return datetime.min.replace(tzinfo=timezone.utc)
    raw = str(
        comment.get("createdAt")
        or comment.get("created_at")
        or comment.get("updatedAt")
        or comment.get("updated_at")
        or ""
    ).strip()
    if not raw:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _comment_body(comment: Any) -> str:
    return str(comment.get("body") or "") if isinstance(comment, dict) else ""


def _comment_url(comment: Any) -> str:
    if not isinstance(comment, dict):
        return ""
    return str(comment.get("url") or comment.get("html_url") or "").strip()


def _comment_created_at(comment: Any) -> str:
    if not isinstance(comment, dict):
        return ""
    return str(comment.get("createdAt") or comment.get("created_at") or "").strip()


def _structural_lines(body: str) -> list[str]:
    """Return stripped lines, with fenced, indented-code and quoted lines blanked.

    Blanking keeps line positions while guaranteeing that quoted text never
    matches a marker, a head line or a block-ending heading.
    """
    lines: list[str] = []
    fence = ""
    for raw_line in body.splitlines():
        if fence:
            if _closes_fence(raw_line, fence):
                fence = ""
            lines.append("")
            continue
        opened = _FENCE_OPEN_RE.match(raw_line)
        if opened:
            fence = opened.group(1)
            lines.append("")
            continue
        if raw_line.startswith(("    ", "\t")) or raw_line.lstrip().startswith(">"):
            lines.append("")
            continue
        lines.append(raw_line.strip())
    return lines


def _closes_fence(raw_line: str, fence: str) -> bool:
    # CommonMark: at most three spaces of indent, then only the opening fence
    # character, at least as many times as the opening fence used.
    indent = len(raw_line) - len(raw_line.lstrip(" "))
    stripped = raw_line.strip()
    return indent <= 3 and len(stripped) >= len(fence) and set(stripped) == {fence[0]}


def _marker_on_line(line: str, markers: tuple[str, ...]) -> str:
    marker_map = {marker.casefold(): marker for marker in markers}
    while line.startswith("#"):
        line = line[1:].strip()
    return marker_map.get(line.strip().strip(":").casefold(), "")


def _structured_marker(body: str, markers: tuple[str, ...], head_sha: str) -> str:
    """Return the first marker whose own block carries a head line naming ``head_sha``."""
    lines = _structural_lines(body)
    for index, line in enumerate(lines):
        marker = _marker_on_line(line, markers)
        if not marker:
            continue
        for following in lines[index + 1 :]:
            if _HEADING_RE.match(following) or _marker_on_line(following, _ALL_MARKERS):
                break
            head_line = _HEAD_LINE_RE.match(following)
            if head_line and head_line.group(1).lower() == head_sha:
                return marker
    return ""


def _park_record(comment: Any, head_sha: str) -> dict[str, Any] | None:
    body = _comment_body(comment)
    if not body or _author_association(comment) not in TRUSTED_PARK_AUTHOR_ASSOCIATIONS:
        return None
    marker = _structured_marker(body, PARK_RECORD_MARKERS, head_sha)
    if not marker:
        return None
    return {
        "head_sha": head_sha,
        "park_marker": marker,
        "created_at": _comment_created_at(comment),
        "comment_url": _comment_url(comment),
    }


def _lift_record(
    comment: Any,
    head_sha: str,
    *,
    trusted_operator_logins: frozenset[str],
    admin_permission_checker: AdminPermissionChecker | None,
) -> dict[str, Any] | None:
    body = _comment_body(comment)
    if not body:
        return None
    # Match the record first so the live permission lookup runs only for a real lift.
    marker = _structured_marker(body, PARK_LIFT_RECORD_MARKERS, head_sha)
    if not marker or not _lift_author_is_trusted(
        comment,
        trusted_operator_logins=trusted_operator_logins,
        admin_permission_checker=admin_permission_checker,
    ):
        return None
    return {
        "head_sha": head_sha,
        "lift_marker": marker,
        "created_at": _comment_created_at(comment),
        "comment_url": _comment_url(comment),
        "author_login": _author_login(comment),
        "author_association": _author_association(comment),
    }


def _lift_author_is_trusted(
    comment: Any,
    *,
    trusted_operator_logins: frozenset[str],
    admin_permission_checker: AdminPermissionChecker | None,
) -> bool:
    association = _author_association(comment)
    if association in TRUSTED_LIFT_AUTHOR_ASSOCIATIONS:
        return True
    if association not in (
        TRUSTED_LIFT_ALLOWLIST_ASSOCIATIONS | TRUSTED_LIFT_ALLOWLIST_ADMIN_ASSOCIATIONS
    ):
        return False
    login = _author_login(comment)
    if not login or login not in trusted_operator_logins:
        return False
    if association in TRUSTED_LIFT_ALLOWLIST_ASSOCIATIONS:
        return True
    if admin_permission_checker is None:
        return False
    try:
        return admin_permission_checker(login) is True
    except Exception:
        # An unknown permission must not lift a park.
        return False


def _author_association(comment: Any) -> str:
    if not isinstance(comment, dict):
        return ""
    return (
        str(comment.get("authorAssociation") or comment.get("author_association") or "")
        .strip()
        .upper()
    )


def _author_login(comment: Any) -> str:
    if not isinstance(comment, dict):
        return ""
    for key in ("author", "user"):
        author = comment.get(key)
        if isinstance(author, dict):
            login = str(author.get("login") or "").strip().lower()
            if login:
                return login
        elif isinstance(author, str) and author.strip():
            return author.strip().lower()
    return ""
