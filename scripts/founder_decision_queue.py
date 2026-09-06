#!/usr/bin/env python3
"""Render pending founder/operator decision packets.

This is a read-only transport-compression helper. It scans local founder
decision packet markdown files, plus optional exported issue comments, and
prints one table of pending rulings with their expected one-word replies.
It never posts, mutates PRs, reruns checks, settles, or merges.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

UTC = timezone.utc
DEFAULT_DECISIONS_ROOT = Path(".aragora/founder-decisions")
GH_ISSUE_VIEW_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class DecisionItem:
    item: str
    target: str
    requested_action: str
    expected_reply: str
    source: str
    packet_generated_at: datetime | None = None
    title: str | None = None
    exact_head_sha: str | None = None

    def dedupe_key(self) -> tuple[str, str, str]:
        return (
            _compact_text(self.target).lower(),
            _compact_text(self.requested_action).lower(),
            _compact_text(self.expected_reply).lower(),
        )


@dataclass(frozen=True)
class DecisionSource:
    source: str
    body: str
    thread_key: str
    source_created_at: datetime | None = None
    thread_open: bool = True
    later_thread_comments: tuple[tuple[datetime | None, str], ...] = ()

    @property
    def packet_time(self) -> datetime | None:
        return self.source_created_at or _packet_generated_at(self.body)


@dataclass(frozen=True)
class SourceLoadFailure:
    source: str
    message: str


@dataclass(frozen=True)
class SourceCollection:
    sources: tuple[DecisionSource, ...]
    failures: tuple[SourceLoadFailure, ...] = ()


@dataclass(frozen=True)
class DecisionCollection:
    items: list[DecisionItem]
    source_failures: tuple[SourceLoadFailure, ...] = ()


class SourceCollectionError(RuntimeError):
    def __init__(self, failures: Iterable[SourceLoadFailure]) -> None:
        self.failures = tuple(failures)
        detail = "; ".join(f"{failure.source}: {failure.message}" for failure in self.failures)
        super().__init__(f"no decision sources could be collected ({detail})")


def _warn_source_failure(failure: SourceLoadFailure) -> None:
    print(f"warning: skipped {failure.source}: {failure.message}", file=sys.stderr)


def _github_cli_env() -> dict[str, str]:
    try:
        from aragora.swarm.github_app_auth import github_cli_env
    except ImportError:  # pragma: no cover - fallback for partially bootstrapped script contexts
        return dict(os.environ)
    return github_cli_env(os.environ)


def _compact_text(value: str) -> str:
    return " ".join(value.strip().split())


def _strip_markdown_code(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and stripped.startswith("`") and stripped.endswith("`"):
        return stripped[1:-1].strip()
    return stripped


def _parse_datetime(value: str) -> datetime | None:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _packet_generated_at(markdown: str) -> datetime | None:
    match = re.search(r"^Generated(?:\s+at)?:\s*(.+?)\s*$", markdown, flags=re.MULTILINE)
    if not match:
        return None
    return _parse_datetime(match.group(1))


def _normalize_header(value: str) -> str:
    normalized = _compact_text(_strip_markdown_code(value)).lower()
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _header_index(header: list[str], aliases: set[str]) -> int | None:
    for index, value in enumerate(header):
        if _normalize_header(value) in aliases:
            return index
    return None


def _markdown_heading_slug(line: str) -> str | None:
    if not line.startswith("#"):
        return None
    heading = line.lstrip("#").strip()
    if not heading:
        return None
    return _normalize_header(heading)


def _section_body(markdown: str, aliases: set[str]) -> str:
    lines = markdown.splitlines()
    in_section = False
    body: list[str] = []
    for line in lines:
        heading = _markdown_heading_slug(line)
        if heading is not None:
            if in_section:
                break
            if heading in aliases:
                in_section = True
                continue
        if in_section:
            body.append(line)
    return "\n".join(body).strip()


def _extract_first_code_or_line(markdown: str) -> str | None:
    code_match = re.search(r"`([^`\n]+)`", markdown)
    if code_match:
        return _compact_text(code_match.group(1))
    for line in markdown.splitlines():
        compact = _compact_text(line.strip("- "))
        if compact:
            return _strip_markdown_code(compact)
    return None


def _extract_markdown_field(markdown: str, label: str) -> str | None:
    pattern = rf"^\s*[-*]?\s*{re.escape(label)}\s*:\s*(.+?)\s*$"
    match = re.search(pattern, markdown, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return None
    return _strip_markdown_code(_compact_text(match.group(1)))


def _extract_exact_head(value: str) -> str | None:
    match = re.search(r"\b[0-9a-f]{40}\b", value, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(0).lower()


def _extract_target_from_section(markdown: str) -> str | None:
    pr_url = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+", markdown)
    if pr_url:
        number = pr_url.group(0).rstrip("/").rsplit("/", 1)[-1]
        return f"PR #{number}: {pr_url.group(0)}"
    issue_url = re.search(r"https://github\.com/[^/\s]+/[^/\s]+/issues/\d+", markdown)
    if issue_url:
        number = issue_url.group(0).rstrip("/").rsplit("/", 1)[-1]
        return f"Issue #{number}: {issue_url.group(0)}"
    target = _extract_markdown_field(markdown, "Target") or _extract_markdown_field(markdown, "PR")
    if target:
        return target
    return None


def _split_table_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return None
    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if not cells:
        return None
    return cells


def _is_separator_row(cells: list[str]) -> bool:
    return all(cell and set(cell) <= {"-", ":", " "} for cell in cells)


def _pending_ruling_rows(markdown: str) -> list[list[str]]:
    lines = markdown.splitlines()
    in_section = False
    rows: list[list[str]] = []
    for line in lines:
        if line.startswith("#"):
            heading = line.lstrip("#").strip().lower()
            if not in_section and heading == "pending rulings":
                in_section = True
                continue
            if in_section:
                break
        if not in_section:
            continue
        cells = _split_table_row(line)
        if cells is None:
            if rows and line.strip():
                break
            continue
        rows.append(cells)
    return rows


def _all_table_rows(markdown: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in markdown.splitlines():
        cells = _split_table_row(line)
        if cells is None:
            if current:
                tables.append(current)
                current = []
            continue
        current.append(cells)
    if current:
        tables.append(current)
    return tables


def _parse_decision_table(
    rows: list[list[str]], *, source: str, generated_at: datetime | None
) -> list[DecisionItem]:
    header: list[str] | None = None
    data_rows: list[list[str]] = []
    for row in rows:
        if _is_separator_row(row):
            continue
        if header is None:
            header = row
            continue
        data_rows.append(row)
    if header is None:
        return []

    priority_i = _header_index(header, {"priority", "item"})
    target_i = _header_index(header, {"link", "target", "pr issue", "pr", "issue"})
    action_i = _header_index(
        header,
        {
            "requested action",
            "requested operator action",
            "request",
            "recommended default",
            "action",
        },
    )
    reply_i = _header_index(
        header,
        {"one word reply", "reply token", "expected reply", "exact reply", "token", "reply"},
    )
    title_i = _header_index(header, {"title", "pr title", "issue title"})
    head_i = _header_index(
        header,
        {"exact head", "head", "head sha", "exact head sha", "live head", "sha"},
    )
    if target_i is None or action_i is None or reply_i is None:
        return []

    items: list[DecisionItem] = []
    for row in data_rows:
        if max(target_i, action_i, reply_i) >= len(row):
            continue
        priority = row[priority_i] if priority_i is not None and priority_i < len(row) else ""
        target = _compact_text(row[target_i])
        requested_action = _compact_text(row[action_i])
        expected_reply = _strip_markdown_code(_compact_text(row[reply_i]))
        if not target or not expected_reply:
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", expected_reply):
            continue
        title = (
            _strip_markdown_code(_compact_text(row[title_i]))
            if title_i is not None and title_i < len(row) and row[title_i].strip()
            else None
        )
        head_text = (
            row[head_i]
            if head_i is not None and head_i < len(row)
            else f"{target} {requested_action}"
        )
        exact_head_sha = _extract_exact_head(head_text)
        item = f"Priority {priority}" if priority else target
        items.append(
            DecisionItem(
                item=item,
                target=target,
                requested_action=requested_action,
                expected_reply=expected_reply,
                source=source,
                packet_generated_at=generated_at,
                title=title,
                exact_head_sha=exact_head_sha,
            )
        )
    return items


def _standalone_expected_reply(markdown: str) -> str | None:
    patterns = [
        r"^Expected one-word reply[^\n]*:\s*\n+(?P<reply>[^\n]+)",
        r"^## Requested operator reply\s*\n+(?P<reply>[^\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, markdown, flags=re.IGNORECASE | re.MULTILINE)
        if not match:
            continue
        reply = _strip_markdown_code(_compact_text(match.group("reply")))
        if reply:
            return reply
    return None


def _standalone_target(markdown: str) -> str | None:
    url_match = re.search(
        r"https://github\.com/[^\s)]+/(?P<kind>pull|issues)/(?P<number>\d+)",
        markdown,
    )
    if url_match:
        kind = "PR" if url_match.group("kind") == "pull" else "Issue"
        return f"{kind} #{url_match.group('number')}: {url_match.group(0)}"
    number_match = re.search(r"\b(?P<kind>PR|Issue)\s+#(?P<number>\d+)\b", markdown)
    if number_match:
        return f"{number_match.group('kind')} #{number_match.group('number')}"
    return None


def _standalone_item_name(target: str) -> str:
    number = _target_number(target)
    if number is None:
        return target
    if "issues/" in target or target.lower().startswith("issue"):
        return f"Issue #{number}"
    return f"PR #{number}"


def _standalone_requested_action(markdown: str) -> str:
    match = re.search(
        r"^## Requested action\s*\n+(?P<body>.+?)(?:\n\n|\Z)",
        markdown,
        flags=re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    if not match:
        return "Founder/operator decision requested."
    return _compact_text(match.group("body"))


def _parse_standalone_request(markdown: str, *, source: str) -> list[DecisionItem]:
    reply_section = _section_body(markdown, {"requested operator reply", "operator reply"})
    reply = (
        _extract_first_code_or_line(reply_section)
        if reply_section
        else _standalone_expected_reply(markdown)
    )
    if not reply:
        return []
    expected_reply = _strip_markdown_code(_compact_text(reply))
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", expected_reply):
        return []
    target_section = _section_body(markdown, {"target"})
    requested_action_section = _section_body(markdown, {"requested action", "action requested"})
    requested_action = (
        _compact_text(requested_action_section)
        if requested_action_section
        else _standalone_requested_action(markdown)
    )
    target = _extract_target_from_section(target_section or markdown) or _standalone_target(
        markdown
    )
    if not target:
        return []
    generated_at = _packet_generated_at(markdown)
    title = _extract_markdown_field(target_section, "Title")
    exact_head_sha = _extract_exact_head(target_section) or _extract_exact_head(requested_action)
    item = title or _standalone_item_name(target)
    return [
        DecisionItem(
            item=item,
            target=target,
            requested_action=requested_action,
            expected_reply=expected_reply,
            source=source,
            packet_generated_at=generated_at,
            title=title,
            exact_head_sha=exact_head_sha,
        )
    ]


def parse_decision_packet(markdown: str, *, source: str) -> list[DecisionItem]:
    """Parse a founder decision packet markdown body."""

    standalone = _parse_standalone_request(markdown, source=source)

    generated_at = _packet_generated_at(markdown)
    rows = _pending_ruling_rows(markdown)
    table_items: list[DecisionItem] = []
    if not rows:
        for table in _all_table_rows(markdown):
            table_items.extend(
                _parse_decision_table(table, source=source, generated_at=generated_at)
            )
    else:
        table_items = _parse_decision_table(rows, source=source, generated_at=generated_at)
    return [*standalone, *table_items]


def _has_pending_rulings_table(source: DecisionSource) -> bool:
    return bool(_pending_ruling_rows(source.body))


def _has_decision_table(source: DecisionSource) -> bool:
    return _has_pending_rulings_table(source) or _body_has_decision_table(source.body)


def _body_has_decision_request(body: str) -> bool:
    if _is_local_only_draft(body):
        return False
    lowered = body.lower()
    return (
        "## pending rulings" in lowered
        or "## pending ruling" in lowered
        or "## requested operator reply" in lowered
        or (_standalone_expected_reply(body) is not None and _standalone_target(body) is not None)
        or _body_has_decision_table(body)
    )


def _is_decision_packet_body(body: str) -> bool:
    return _body_has_decision_request(body)


def _body_has_decision_table(body: str) -> bool:
    for table in _all_table_rows(body):
        header: list[str] | None = None
        for row in table:
            if _is_separator_row(row):
                continue
            header = row
            break
        if header is None:
            continue
        has_target = (
            _header_index(header, {"link", "target", "pr issue", "pr", "issue"}) is not None
        )
        has_action = (
            _header_index(
                header,
                {
                    "requested action",
                    "requested operator action",
                    "request",
                    "recommended default",
                    "action",
                },
            )
            is not None
        )
        has_reply = (
            _header_index(
                header,
                {
                    "one word reply",
                    "reply token",
                    "expected reply",
                    "exact reply",
                    "token",
                    "reply",
                },
            )
            is not None
        )
        if has_target and has_action and has_reply:
            return True
    return False


def _is_local_only_draft(body: str) -> bool:
    lowered = body.lower()
    return "draft is local only" in lowered or "this draft is local only" in lowered


def _is_consolidated_decision_source(source: str, body: str) -> bool:
    lowered_source = source.lower()
    lowered_body = body.lower()
    return (
        "consolidated" in lowered_source
        or "consolidated" in lowered_body
        or "compact queue blocker" in lowered_body
    )


def _is_standalone_request_source(body: str) -> bool:
    lowered = body.lower()
    return "## requested operator reply" in lowered or "expected one-word reply" in lowered


def _packet_time_sort_key(value: datetime | None) -> datetime:
    return value or datetime.min.replace(tzinfo=UTC)


def _local_source_thread_key(
    path: Path,
    *,
    body: str,
    decisions_root: Path,
    newest_consolidated_time: datetime | None,
) -> str | None:
    if _is_consolidated_decision_source(str(path), body):
        return _local_thread_key(path, decisions_root=decisions_root)
    if not _body_has_decision_request(body):
        return None
    packet_time = _packet_generated_at(body)
    if newest_consolidated_time is None or _packet_time_sort_key(
        packet_time
    ) >= _packet_time_sort_key(newest_consolidated_time):
        prefix = "local-standalone" if _is_standalone_request_source(body) else "local-specific"
        return f"{prefix}:{path.resolve()}"
    return None


def _comment_source_thread_key(
    *,
    body: str,
    source: str,
    thread_key: str,
) -> str:
    if _is_consolidated_decision_source(source, body):
        return thread_key
    return f"{thread_key}:{source}"


def _item_freshness_key(item: DecisionItem) -> tuple[datetime, str]:
    return (
        item.packet_generated_at or datetime.min.replace(tzinfo=UTC),
        item.source,
    )


def _item_target_key(item: DecisionItem) -> str:
    number = _target_number(item.target)
    if number is not None:
        return f"target:{number}"
    return f"reply:{_compact_text(item.expected_reply).lower()}"


def _item_identity_key(item: DecisionItem) -> tuple[str, str]:
    return (
        _item_target_key(item),
        _compact_text(item.requested_action).lower(),
    )


def _dedupe_decision_items(items: Iterable[DecisionItem]) -> list[DecisionItem]:
    deduped: dict[tuple[str, str], DecisionItem] = {}
    for item in items:
        key = _item_identity_key(item)
        current = deduped.get(key)
        if current is None or _item_freshness_key(item) > _item_freshness_key(current):
            deduped[key] = item
    return list(deduped.values())


def _dedupe_table_decision_items(items: Iterable[DecisionItem]) -> list[DecisionItem]:
    by_identity: dict[tuple[str, str], DecisionItem] = {}
    for item in items:
        key = _item_identity_key(item)
        current = by_identity.get(key)
        if current is None or _item_freshness_key(item) > _item_freshness_key(current):
            by_identity[key] = item
    return list(by_identity.values())


def _newest_consolidated_sources_by_thread(
    sources: Iterable[DecisionSource],
) -> dict[str, DecisionSource]:
    newest: dict[str, DecisionSource] = {}
    for source in sources:
        if not _is_consolidated_decision_source(source.source, source.body):
            continue
        current = newest.get(source.thread_key)
        if current is None or _packet_sort_key(source) > _packet_sort_key(current):
            newest[source.thread_key] = source
    return newest


def _consolidated_source_item_filter(
    table_sources: Iterable[DecisionSource],
) -> dict[str, set[str]]:
    newest_sources = _newest_consolidated_sources_by_thread(table_sources)
    newest_target_keys: dict[str, set[str]] = {}
    for thread_key, source in newest_sources.items():
        newest_target_keys[thread_key] = {
            _item_target_key(item)
            for item in parse_decision_packet(source.body, source=source.source)
        }
    return newest_target_keys


def _sort_decision_items_newest_first(items: Iterable[DecisionItem]) -> list[DecisionItem]:
    return sorted(
        items,
        key=lambda item: _packet_time_sort_key(item.packet_generated_at),
        reverse=True,
    )


def _packet_sort_key(source: DecisionSource) -> tuple[datetime, str]:
    return (
        source.packet_time or datetime.min.replace(tzinfo=UTC),
        source.source,
    )


def _newest_sources_by_thread(sources: Iterable[DecisionSource]) -> list[DecisionSource]:
    newest: dict[str, DecisionSource] = {}
    for source in sources:
        current = newest.get(source.thread_key)
        if current is None or _packet_sort_key(source) > _packet_sort_key(current):
            newest[source.thread_key] = source
    return list(newest.values())


def _local_thread_key(path: Path, *, decisions_root: Path | None = None) -> str:
    if decisions_root is not None:
        return f"local:{decisions_root.resolve()}"
    parent = path.parent if path.parent != Path("") else Path(".")
    return f"local:{parent.resolve()}"


def _thread_key_from_comment(comment: dict[str, Any], *, fallback: str) -> str:
    for key in ("issue_url", "pull_request_url", "thread_url"):
        value = comment.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("html_url", "url"):
        value = comment.get(key)
        if not isinstance(value, str) or not value:
            continue
        match = re.search(r"/(?:issues|pulls|pull)/(\d+)(?:[/#?]|$)", value)
        if match:
            return f"github-thread:{match.group(1)}"
    return fallback


def _thread_open_from_comment(comment: dict[str, Any], *, default: bool) -> bool:
    for key in ("thread_state", "issue_state", "pr_state", "state"):
        value = comment.get(key)
        if isinstance(value, str):
            return value.lower() == "open"
    return default


def _comment_created_at(comment: dict[str, Any]) -> datetime | None:
    value = (
        comment.get("created_at")
        or comment.get("createdAt")
        or comment.get("updated_at")
        or comment.get("updatedAt")
    )
    if not isinstance(value, str):
        return None
    return _parse_datetime(value)


def _first_nonempty_line(body: str) -> str:
    for line in body.splitlines():
        compact = _compact_text(line)
        if compact:
            return compact
    return ""


def _target_number(target: str) -> str | None:
    match = re.search(r"(?:pull|issues)/(\d+)|#(\d+)", target)
    if not match:
        return None
    return match.group(1) or match.group(2)


def _comment_resolves_item(body: str, item: DecisionItem) -> bool:
    first_line = _strip_markdown_code(_first_nonempty_line(body))
    expected = item.expected_reply
    if first_line and first_line == expected:
        return True
    if _body_has_decision_request(body) or _is_local_only_draft(body):
        return False
    if _is_decision_packet_body(body):
        return False
    number = _target_number(item.target)
    if number is None:
        return False
    lowered = body.lower()
    if "settlement" not in lowered:
        return False
    number_pattern = re.escape(number)
    target_patterns = [
        rf"#\s*{number_pattern}\b",
        rf"/(?:issues|pull|pulls)/{number_pattern}\b",
        rf"\b(?:issue|pr|pull request)\s+#?\s*{number_pattern}\b",
        rf"\b{number_pattern}\b",
    ]
    return any(re.search(pattern, lowered) for pattern in target_patterns)


def _item_resolved_after_packet(source: DecisionSource, item: DecisionItem) -> bool:
    packet_time = source.packet_time
    for created_at, body in source.later_thread_comments:
        if packet_time is not None and created_at is not None and created_at <= packet_time:
            continue
        if _comment_resolves_item(body, item):
            return True
    return False


def _load_issue_comment_sources(path: Path) -> list[DecisionSource]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    default_thread_open = True
    if isinstance(payload, dict):
        state = payload.get("state") or payload.get("thread_state")
        if isinstance(state, str):
            default_thread_open = state.lower() == "open"
        comments_payload = payload.get("comments")
    else:
        comments_payload = payload

    if not isinstance(comments_payload, list):
        return []
    comments = [comment for comment in comments_payload if isinstance(comment, dict)]
    sources: list[DecisionSource] = []
    for index, comment in enumerate(comments):
        body = comment.get("body")
        if not isinstance(body, str) or not _body_has_decision_request(body):
            continue
        source = str(comment.get("html_url") or comment.get("url") or f"{path}#{index}")
        base_thread_key = _thread_key_from_comment(comment, fallback=f"{path}")
        thread_key = _comment_source_thread_key(
            body=body,
            source=source,
            thread_key=base_thread_key,
        )
        created_at = _comment_created_at(comment)
        later_comments: list[tuple[datetime | None, str]] = []
        for other in comments:
            other_body = other.get("body")
            if not isinstance(other_body, str):
                continue
            if _thread_key_from_comment(other, fallback=f"{path}") != base_thread_key:
                continue
            later_comments.append((_comment_created_at(other), other_body))
        sources.append(
            DecisionSource(
                source=source,
                body=body,
                thread_key=thread_key,
                source_created_at=created_at,
                thread_open=_thread_open_from_comment(comment, default=default_thread_open),
                later_thread_comments=tuple(later_comments),
            )
        )
    return sources


def _github_issue_comment_sources(
    *,
    repo: str,
    issue: str,
    payload: dict[str, Any],
) -> list[DecisionSource]:
    comments_payload = payload.get("comments")
    if not isinstance(comments_payload, list):
        return []
    comments = [comment for comment in comments_payload if isinstance(comment, dict)]
    thread_open = str(payload.get("state") or "open").lower() == "open"
    thread_url = str(payload.get("url") or f"https://github.com/{repo}/issues/{issue}")
    base_thread_key = f"github-thread:{issue}"
    sources: list[DecisionSource] = []
    for index, comment in enumerate(comments):
        body = comment.get("body")
        if not isinstance(body, str) or not _body_has_decision_request(body):
            continue
        source = str(
            comment.get("html_url") or comment.get("url") or f"{thread_url}#comment-{index}"
        )
        thread_key = _comment_source_thread_key(
            body=body,
            source=source,
            thread_key=base_thread_key,
        )
        created_at = _comment_created_at(comment)
        later_comments: list[tuple[datetime | None, str]] = []
        for other in comments:
            other_body = other.get("body")
            if not isinstance(other_body, str):
                continue
            later_comments.append((_comment_created_at(other), other_body))
        sources.append(
            DecisionSource(
                source=source,
                body=body,
                thread_key=thread_key,
                source_created_at=created_at,
                thread_open=thread_open,
                later_thread_comments=tuple(later_comments),
            )
        )
    return sources


def _flatten_paginated_items(value: Any) -> list[Mapping[str, Any]]:
    items: list[Mapping[str, Any]] = []
    if isinstance(value, list):
        for page in value:
            if isinstance(page, list):
                items.extend(item for item in page if isinstance(item, Mapping))
            elif isinstance(page, Mapping):
                items.append(page)
    elif isinstance(value, Mapping):
        items.append(value)
    return items


def _load_github_issue_sources(
    *,
    repo: str,
    issue: str,
    timeout_seconds: int = GH_ISSUE_VIEW_TIMEOUT_SECONDS,
) -> list[DecisionSource]:
    env = _github_cli_env()
    issue_command = [
        "gh",
        "issue",
        "view",
        issue,
        "--repo",
        repo,
        "--json",
        "state,url",
    ]
    comments_command = [
        "gh",
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repo}/issues/{issue}/comments",
    ]
    try:
        issue_proc = subprocess.run(
            issue_command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("gh executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"gh issue view timed out after {timeout_seconds}s for {repo}#{issue}"
        ) from exc
    try:
        comments_proc = subprocess.run(
            comments_command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("gh executable not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"gh issue comments timed out after {timeout_seconds}s for {repo}#{issue}"
        ) from exc
    if issue_proc.returncode != 0:
        message = issue_proc.stderr.strip() or issue_proc.stdout.strip() or "unknown gh error"
        raise RuntimeError(f"gh issue view failed for {repo}#{issue}: {message}")
    if comments_proc.returncode != 0:
        message = comments_proc.stderr.strip() or comments_proc.stdout.strip() or "unknown gh error"
        raise RuntimeError(f"gh issue comments failed for {repo}#{issue}: {message}")
    try:
        payload = json.loads(issue_proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh issue view returned malformed JSON for {repo}#{issue}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"gh issue view returned non-object JSON for {repo}#{issue}")
    try:
        comments_payload = json.loads(comments_proc.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh issue comments returned malformed JSON for {repo}#{issue}") from exc
    payload = dict(payload)
    payload["comments"] = _flatten_paginated_items(comments_payload)
    return _github_issue_comment_sources(repo=repo, issue=issue, payload=payload)


def _legacy_load_issue_comment_bodies(path: Path) -> list[tuple[str, str]]:
    """Compatibility shim for tests or callers that imported the private helper."""

    bodies: list[tuple[str, str]] = []
    for source in _load_issue_comment_sources(path):
        bodies.append((source.source, source.body))
    return bodies


_load_issue_comment_bodies = _legacy_load_issue_comment_bodies


def _collect_sources(
    *,
    decisions_root: Path,
    packet_files: Iterable[Path],
    issue_comments_json: Path | None,
    github_issues: Iterable[str],
    repo: str,
) -> SourceCollection:
    sources: list[DecisionSource] = []
    failures: list[SourceLoadFailure] = []
    if decisions_root.exists():
        local_bodies: list[tuple[Path, str]] = []
        for path in sorted(decisions_root.glob("*.md")):
            try:
                body = path.read_text(encoding="utf-8")
            except OSError:
                continue
            local_bodies.append((path, body))
        consolidated_times = [
            _packet_generated_at(body)
            for path, body in local_bodies
            if _is_consolidated_decision_source(str(path), body)
        ]
        newest_consolidated_time = max(
            (time for time in consolidated_times if time is not None),
            default=None,
        )
        for path, body in local_bodies:
            thread_key = _local_source_thread_key(
                path,
                body=body,
                decisions_root=decisions_root,
                newest_consolidated_time=newest_consolidated_time,
            )
            if thread_key is None:
                continue
            sources.append(
                DecisionSource(
                    source=str(path),
                    body=body,
                    thread_key=thread_key,
                )
            )
    for path in packet_files:
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        sources.append(
            DecisionSource(
                source=str(path),
                body=body,
                thread_key=_local_thread_key(path),
            )
        )
    if issue_comments_json is not None:
        sources.extend(_load_issue_comment_sources(issue_comments_json))
    for issue in github_issues:
        try:
            sources.extend(_load_github_issue_sources(repo=repo, issue=issue))
        except RuntimeError as exc:
            failure = SourceLoadFailure(source=f"github issue {repo}#{issue}", message=str(exc))
            failures.append(failure)
            _warn_source_failure(failure)
    if failures and not sources:
        raise SourceCollectionError(failures)
    return SourceCollection(sources=tuple(sources), failures=tuple(failures))


def collect_decision_collection(
    *,
    decisions_root: Path = DEFAULT_DECISIONS_ROOT,
    packet_files: Iterable[Path] = (),
    issue_comments_json: Path | None = None,
    github_issues: Iterable[str] = (),
    repo: str = "synaptent/aragora",
) -> DecisionCollection:
    table_items: list[DecisionItem] = []
    standalone_items: list[DecisionItem] = []
    source_collection = _collect_sources(
        decisions_root=decisions_root,
        packet_files=packet_files,
        issue_comments_json=issue_comments_json,
        github_issues=github_issues,
        repo=repo,
    )
    table_sources = [source for source in source_collection.sources if _has_decision_table(source)]
    newest_consolidated_sources = _newest_consolidated_sources_by_thread(table_sources)
    newest_consolidated_target_keys = _consolidated_source_item_filter(table_sources)
    standalone_sources = [
        source for source in source_collection.sources if not _has_decision_table(source)
    ]
    for source in sorted(table_sources, key=_packet_sort_key):
        if not source.thread_open:
            continue
        for item in parse_decision_packet(source.body, source=source.source):
            newest_source = newest_consolidated_sources.get(source.thread_key)
            if (
                newest_source is not None
                and source != newest_source
                and _is_consolidated_decision_source(source.source, source.body)
                and _item_target_key(item)
                not in newest_consolidated_target_keys.get(source.thread_key, set())
            ):
                continue
            if _item_resolved_after_packet(source, item):
                continue
            table_items.append(item)
    for source in sorted(standalone_sources, key=_packet_sort_key):
        if not source.thread_open:
            continue
        for item in parse_decision_packet(source.body, source=source.source):
            if _item_resolved_after_packet(source, item):
                continue
            standalone_items.append(item)
    deduped_items = [
        *_dedupe_table_decision_items(table_items),
        *_dedupe_decision_items(standalone_items),
    ]
    return DecisionCollection(
        items=_sort_decision_items_newest_first(deduped_items),
        source_failures=source_collection.failures,
    )


def collect_decision_items(
    *,
    decisions_root: Path = DEFAULT_DECISIONS_ROOT,
    packet_files: Iterable[Path] = (),
    issue_comments_json: Path | None = None,
    github_issues: Iterable[str] = (),
    repo: str = "synaptent/aragora",
) -> list[DecisionItem]:
    return collect_decision_collection(
        decisions_root=decisions_root,
        packet_files=packet_files,
        issue_comments_json=issue_comments_json,
        github_issues=github_issues,
        repo=repo,
    ).items


def _format_age(item: DecisionItem, *, now: datetime) -> str:
    if item.packet_generated_at is None:
        return "unknown"
    seconds = max(0.0, (now - item.packet_generated_at).total_seconds())
    hours = seconds / 3600.0
    if hours < 1:
        return f"{int(seconds // 60)}m"
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24.0:.1f}d"


def render_markdown(
    items: Iterable[DecisionItem],
    *,
    now: datetime | None = None,
    source_failures: Iterable[SourceLoadFailure] = (),
) -> str:
    now_dt = (now or datetime.now(tz=UTC)).astimezone(UTC)
    rows = list(items)
    failures = list(source_failures)
    lines = [
        "# Founder Decision Queue",
        "",
        f"Generated: {now_dt.isoformat().replace('+00:00', 'Z')}",
        "",
    ]
    if failures:
        lines.extend(["## Source Warnings", ""])
        for failure in failures:
            lines.append(f"- Skipped {failure.source}: {failure.message}")
        lines.append("")
    if not rows:
        lines.append("No pending operator rulings found.")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| Item | PR/Issue | Expected reply | Age | Source |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_table_cell(item.item),
                    _escape_table_cell(item.target),
                    f"`{_escape_table_cell(item.expected_reply)}`",
                    _format_age(item, now=now_dt),
                    _escape_table_cell(item.source),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def render_brief(
    items: Iterable[DecisionItem],
    *,
    now: datetime | None = None,
    source_failures: Iterable[SourceLoadFailure] = (),
) -> str:
    now_dt = (now or datetime.now(tz=UTC)).astimezone(UTC)
    rows = list(items)
    failures = list(source_failures)
    lines = [
        "# Founder Decision Queue Brief",
        "",
        f"Generated: {now_dt.isoformat().replace('+00:00', 'Z')}",
        f"Pending decisions: {len(rows)}",
        "",
    ]
    for item in rows:
        head = f" head={item.exact_head_sha}" if item.exact_head_sha else ""
        title = f" {item.title}" if item.title else ""
        lines.append(
            "- "
            f"{item.expected_reply}: {item.target}{title}{head} "
            f"age={_format_age(item, now=now_dt)}"
        )
    if failures:
        lines.append("")
        lines.append("Source warnings:")
        for failure in failures:
            lines.append(f"- {failure.source}: {failure.message}")
    return "\n".join(lines) + "\n"


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render pending founder/operator one-word decision packets."
    )
    parser.add_argument(
        "--decisions-root",
        default=str(DEFAULT_DECISIONS_ROOT),
        help="Directory of local founder decision packet markdown files.",
    )
    parser.add_argument(
        "--packet-file",
        action="append",
        default=[],
        help="Additional founder decision packet markdown file to parse.",
    )
    parser.add_argument(
        "--issue-comments-json",
        default=None,
        help="Optional JSON export of issue comments containing founder decision packets.",
    )
    parser.add_argument(
        "--github-issue",
        action="append",
        default=[],
        help="Read-only GitHub issue number to scan for founder decision packet comments.",
    )
    parser.add_argument(
        "--repo",
        default="synaptent/aragora",
        help="GitHub repository for --github-issue lookups.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="Override current UTC timestamp for deterministic rendering.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of Markdown.")
    parser.add_argument("--brief", action="store_true", help="Emit a compact Markdown brief.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.now:
        now = _parse_datetime(args.now)
        if now is None:
            raise SystemExit(f"invalid --now timestamp: {args.now}")
    else:
        now = datetime.now(tz=UTC)
    try:
        collection = collect_decision_collection(
            decisions_root=Path(args.decisions_root),
            packet_files=[Path(path) for path in args.packet_file],
            issue_comments_json=Path(args.issue_comments_json)
            if args.issue_comments_json
            else None,
            github_issues=args.github_issue,
            repo=args.repo,
        )
    except SourceCollectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    items = collection.items
    if args.json:
        payload = {
            "generated_at": now.isoformat().replace("+00:00", "Z"),
            "count": len(items),
            "source_failures": [
                {"source": failure.source, "message": failure.message}
                for failure in collection.source_failures
            ],
            "items": [
                {
                    "item": item.item,
                    "target": item.target,
                    "requested_action": item.requested_action,
                    "expected_reply": item.expected_reply,
                    "token": item.expected_reply,
                    "source": item.source,
                    "title": item.title,
                    "exact_head_sha": item.exact_head_sha,
                    "packet_generated_at": (
                        item.packet_generated_at.isoformat().replace("+00:00", "Z")
                        if item.packet_generated_at
                        else None
                    ),
                    "age": _format_age(item, now=now),
                }
                for item in items
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if args.brief:
        print(render_brief(items, now=now, source_failures=collection.source_failures), end="")
        return 0
    print(render_markdown(items, now=now, source_failures=collection.source_failures), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
