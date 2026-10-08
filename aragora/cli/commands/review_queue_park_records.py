"""Exact-head park-record parsing for merge safety helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

PARK_RECORD_MARKERS: tuple[str, ...] = (
    "Current-head repeat-blocker park",
    "Current-head evidence blocker",
    "Evidence safety correction",
)
PARK_LIFT_RECORD_MARKERS: tuple[str, ...] = (
    "Current-head park lift",
    "Current-head park override",
)
# A park only adds a merge block, so any maintainer may post one; a lift removes
# a block, so it keeps the narrower owner-only trust.
TRUSTED_PARK_AUTHOR_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
TRUSTED_LIFT_AUTHOR_ASSOCIATIONS: frozenset[str] = frozenset({"OWNER"})

_HEAD_RE = re.compile(r"(?im)\b(?:exact\s+head|current\s+head|head)\s*[:=]\s*`?([0-9a-f]{40})`?")


def current_head_park_record(comments: list[Any], *, head_sha: str) -> dict[str, Any]:
    """Return the standing exact-head park record, if one is still authoritative.

    Park records are repo-visible PR comments from a trusted maintainer whose
    marker stands on its own heading line and that explicitly cite the current
    head; prose that merely mentions a marker is not a park. Later supportive
    evidence on the same head is not a lift; only a later explicit operator lift
    or override comment for that same head clears it.
    """
    head = str(head_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return {"blocked": False, "head_sha": head, "lifted_by": None}

    standing_park: dict[str, Any] | None = None
    lifted_by: dict[str, Any] | None = None
    for comment in _chronological_comments(comments):
        body = _comment_body(comment)
        if not body or not _body_mentions_head(body, head):
            continue
        park_record = _park_record(comment, head)
        if park_record is not None:
            standing_park = park_record
            lifted_by = None
            continue
        lift_record = _lift_record(comment, head)
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


def _chronological_comments(comments: list[Any]) -> list[Any]:
    return sorted(
        list(comments or []),
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


def _body_mentions_head(body: str, head_sha: str) -> bool:
    return any(match.group(1).lower() == head_sha for match in _HEAD_RE.finditer(body))


def _structured_marker(body: str, markers: tuple[str, ...]) -> str:
    marker_map = {marker.casefold(): marker for marker in markers}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        while line.startswith("#"):
            line = line[1:].strip()
        normalized = line.strip().strip(":").casefold()
        if normalized in marker_map:
            return marker_map[normalized]
    return ""


def _park_record(comment: Any, head_sha: str) -> dict[str, Any] | None:
    body = _comment_body(comment)
    if not body or _author_association(comment) not in TRUSTED_PARK_AUTHOR_ASSOCIATIONS:
        return None
    marker = _structured_marker(body, PARK_RECORD_MARKERS)
    if not marker:
        return None
    return {
        "head_sha": head_sha,
        "park_marker": marker,
        "created_at": _comment_created_at(comment),
        "comment_url": _comment_url(comment),
    }


def _lift_record(comment: Any, head_sha: str) -> dict[str, Any] | None:
    body = _comment_body(comment)
    if not body or _author_association(comment) not in TRUSTED_LIFT_AUTHOR_ASSOCIATIONS:
        return None
    marker = _structured_marker(body, PARK_LIFT_RECORD_MARKERS)
    if not marker:
        return None
    return {
        "head_sha": head_sha,
        "lift_marker": marker,
        "created_at": _comment_created_at(comment),
        "comment_url": _comment_url(comment),
    }


def _author_association(comment: Any) -> str:
    if not isinstance(comment, dict):
        return ""
    return (
        str(comment.get("authorAssociation") or comment.get("author_association") or "")
        .strip()
        .upper()
    )
