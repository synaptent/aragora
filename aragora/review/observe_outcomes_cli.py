"""``aragora review-queue observe-outcomes`` — bounded receipt observation.

Round 30g phase A (operator tool that follows on from #6921; this CLI does NOT close #6375).

Iterates settled receipts in a bounded window, fetches GitHub timeline
events for each PR with bounded fanout, calls
:func:`aragora.review.settlement_outcome.observe_outcome`, and either
*previews* the proposed v2 outcome fields (the default; ``--dry-run``
implied) or *writes* them back into the receipt JSON in place
(``--write``).

Safety contract
---------------

  - **Default mode is read-only.** No filesystem mutation, no GitHub
    write, nothing committed. ``--write`` is the only flag that
    permits in-place mutation.
  - **Bounded fan-out.** ``--max-receipts`` (default 20) caps the
    number of receipts examined; ``--per-receipt-event-cap`` (default
    100) caps the number of timeline events fetched per PR. Both are
    enforced before the GitHub fetch.
  - **No network on dry-run when fixtures are provided.** Tests pass
    ``timeline_provider`` to inject synthetic events so the CLI is
    fully testable offline.
  - **No commits.** This module never invokes ``git`` or ``gh pr``
    write operations. Receipt files are JSON on disk and may be
    rewritten by the operator's local tooling, but the *only* mutation
    this CLI performs under ``--write`` is rewriting the receipt JSON
    payload with the new ``outcome_*`` fields.
  - **Sharper insufficiency receipt.** When the post-observation
    baseline still lacks data, a structured insufficiency receipt is
    proposed in dry-run mode and written under
    ``.aragora/evolve-round/<round-id>/`` only when ``--write`` is
    passed. It describes *what* would unblock the next measurement
    (sample-size shortfall, no v2-eligible receipts, GitHub-fetch
    errors, etc.).

Out of scope
------------

  - This CLI does **not** edit ``docs/THESIS.md``. Replacing the
    placeholder 5% in Commitment 3 is gated on a measured baseline
    *and* CI safety margin, neither of which this CLI produces on its
    own.
  - This CLI does **not** close #6375. It is an operator tool that
    observes outcome signals into receipts; the empirical question
    behind #6375 (human-side invalidation rate) is a separate
    downstream interpretation step.
  - This CLI does **not** replace the placeholder 5% threshold.
    Threshold replacement requires a measured baseline plus an
    explicit thesis-level decision, neither of which this tool
    produces.
  - This CLI does **not** unblock H2. H2's no-go status is determined
    by separate evidence questions and is not advanced by running
    this tool.
  - This CLI does **not** invent synthetic outcome data. If
    ``observe_outcome`` returns "no signals fired" for every receipt
    in the window, that is recorded honestly as
    ``schema_v2_observed_no_signals``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aragora.review.invalidation_event_source import (
    RECEIPTS_SUBDIR,
    _V2_OUTCOME_FIELD_NAMES,
    _any_receipt_has_v2_outcome_fields,
    resolve_review_queue_root,
)
from aragora.review.settlement_outcome import observe_outcome
from aragora.review.settlement_receipt import SettlementReceipt

logger = logging.getLogger(__name__)

UTC = timezone.utc

DEFAULT_WINDOW_DAYS = 14
DEFAULT_MAX_RECEIPTS = 20
DEFAULT_PER_RECEIPT_EVENT_CAP = 100
DEFAULT_GH_API_MAX_ATTEMPTS = 3
DEFAULT_GH_API_THROTTLE_SECONDS = 0.15
DEFAULT_GH_SEARCH_API_THROTTLE_SECONDS = 2.1
DEFAULT_GH_API_BACKOFF_MAX_SECONDS = 30.0

_GH_RATE_LIMIT_NEEDLES = (
    "api rate limit exceeded",
    "secondary rate limit",
    "rate limit exceeded",
    "rate limited",
    "abuse detection",
)
_GH_LAST_CALL_AT_BY_BUCKET: dict[str, float] = {}


@dataclass(frozen=True, slots=True)
class _ReceiptOnDisk:
    path: Path
    payload: dict[str, Any]


@dataclass(slots=True)
class _ObserveResult:
    receipt_path: Path
    pr_number: int
    head_sha: str
    fetched_event_count: int
    fetch_error: str | None
    signals_before: dict[str, Any]
    signals_after: dict[str, Any]
    written: bool
    skipped_reason: str | None = None
    fetch_error_class: str | None = None  # "rate_limit" | "other" | None when fetch_error is None


# ---------------------------------------------------------------------------
# Receipt iteration (bounded, read-only)
# ---------------------------------------------------------------------------


def _parse_iso(raw: str) -> datetime:
    cleaned = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iter_eligible_receipts(
    *,
    store_root: str | Path | None,
    window_end: datetime,
    window_days: int,
    max_receipts: int,
) -> list[_ReceiptOnDisk]:
    receipts_dir = resolve_review_queue_root(store_root) / RECEIPTS_SUBDIR
    if not receipts_dir.exists():
        return []
    window_start = window_end - timedelta(days=window_days)
    out: list[_ReceiptOnDisk] = []
    try:
        candidates = sorted(
            (p for p in receipts_dir.iterdir() if p.is_file() and p.suffix == ".json"),
            key=lambda p: p.name,
        )
    except OSError as exc:
        logger.warning("review.observe_outcomes_cli: cannot list %s: %s", receipts_dir, exc)
        return []
    for path in candidates:
        if len(out) >= max_receipts:
            break
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("could not read %s: %s", path, exc)
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("malformed JSON in %s: %s", path, exc)
            continue
        if not isinstance(payload, dict):
            continue
        reviewed_raw = payload.get("reviewed_at")
        if not reviewed_raw:
            continue
        try:
            reviewed_at = _parse_iso(str(reviewed_raw))
        except (TypeError, ValueError):
            continue
        if not (window_start <= reviewed_at <= window_end):
            continue
        out.append(_ReceiptOnDisk(path=path, payload=payload))
    return out


# ---------------------------------------------------------------------------
# GitHub timeline fetch (bounded; pluggable for tests)
# ---------------------------------------------------------------------------


TimelineProvider = Callable[[int, str, int], tuple[list[Mapping[str, Any]], str | None]]
"""Signature: (pr_number, head_sha, event_cap) -> (events, fetch_error_or_None)."""


def _looks_like_github_rate_limit_error(message: str) -> bool:
    lowered = message.lower()
    return any(needle in lowered for needle in _GH_RATE_LIMIT_NEEDLES)


def _gh_throttle_seconds_for(args: list[str]) -> float:
    if _gh_throttle_bucket(args) == "search":
        # GitHub search endpoints are more aggressively limited than
        # ordinary API reads; 2.1s keeps sustained runs below 30/minute.
        return DEFAULT_GH_SEARCH_API_THROTTLE_SECONDS
    return DEFAULT_GH_API_THROTTLE_SECONDS


def _gh_throttle_bucket(args: list[str]) -> str:
    if "search/issues" in args or "search/commits" in args:
        return "search"
    return "default"


def _pace_gh_call(
    args: list[str],
    *,
    throttle_seconds: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> None:
    if throttle_seconds <= 0:
        return
    bucket = _gh_throttle_bucket(args)
    now = clock()
    last = _GH_LAST_CALL_AT_BY_BUCKET.get(bucket)
    if last is not None:
        delay = throttle_seconds - (now - last)
        if delay > 0:
            sleep(delay)
            now += delay
    _GH_LAST_CALL_AT_BY_BUCKET[bucket] = now


def _run_gh_json(
    args: list[str],
    *,
    timeout: int = 20,
    attempts: int = DEFAULT_GH_API_MAX_ATTEMPTS,
    throttle_seconds: float | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
) -> tuple[Any, str | None]:
    """Run a bounded ``gh`` command and parse JSON, returning (payload, error).

    ``observe-outcomes`` can issue several read-only GitHub API requests per
    receipt. Keep calls below GitHub's secondary-rate-limit burst envelope and
    retry the transient rate-limit failures instead of marking clean receipts
    as fetch errors.
    """
    max_attempts = max(1, attempts)
    throttle = _gh_throttle_seconds_for(args) if throttle_seconds is None else throttle_seconds
    sleeper = sleep or time.sleep
    monotonic = clock or time.monotonic
    for attempt in range(1, max_attempts + 1):
        _pace_gh_call(
            args,
            throttle_seconds=throttle,
            sleep=sleeper,
            clock=monotonic,
        )
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return None, f"{args[:3]} raised {type(exc).__name__}: {exc}"
        if proc.returncode == 0:
            try:
                return json.loads(proc.stdout or "null"), None
            except json.JSONDecodeError as exc:
                return None, f"{args[:3]} JSON parse error: {exc}"

        error_text = " ".join(
            part.strip() for part in (proc.stderr, proc.stdout) if part and part.strip()
        )
        error = f"{args[:3]} returned {proc.returncode}: {error_text[:300]}"
        if attempt >= max_attempts or not _looks_like_github_rate_limit_error(error):
            return None, error
        backoff = min(throttle * (2 ** (attempt - 1)), DEFAULT_GH_API_BACKOFF_MAX_SECONDS)
        if backoff > 0:
            sleeper(backoff)
    return None, f"{args[:3]} failed after {max_attempts} attempts"


def _gh_repo_slug() -> tuple[str | None, str | None]:
    payload, error = _run_gh_json(["gh", "repo", "view", "--json", "nameWithOwner"])
    if error is not None:
        return None, error
    if not isinstance(payload, dict) or not isinstance(payload.get("nameWithOwner"), str):
        return None, "gh repo view did not return nameWithOwner"
    return payload["nameWithOwner"], None


def _gh_timeline_provider(
    pr_number: int, head_sha: str, event_cap: int
) -> tuple[list[Mapping[str, Any]], str | None]:
    """Default timeline provider using ``gh api``.

    This intentionally fails closed. If any bounded GitHub fetch fails,
    we return an error and the caller must not write explicit ``False``
    outcome fields from an incomplete evidence source.

    Returns (events, error). On any error returns ([], error_message).
    """
    if shutil.which("gh") is None:
        return [], "gh CLI not found on PATH"
    events: list[Mapping[str, Any]] = []
    # Issue/PR timeline (covers reopen events and labeled issues that
    # mention the merge sha). Bounded to one page of `event_cap` items.
    data, error = _run_gh_json(
        [
            "gh",
            "api",
            "-H",
            "Accept: application/vnd.github+json",
            f"/repos/:owner/:repo/issues/{pr_number}/timeline?per_page={min(event_cap, 100)}",
        ]
    )
    if error is not None:
        return [], error
    if not isinstance(data, list):
        return [], "timeline JSON was not a list"
    for entry in data[:event_cap]:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_timeline_entry(entry, pr_number=pr_number)
        if normalized is not None:
            events.append(normalized)

    repo_slug, error = _gh_repo_slug()
    if error is not None:
        return [], error
    if repo_slug is None:
        return [], "gh repo view did not return a repository slug"

    # Search issues/PRs that reference the original PR or head sha so the
    # operator CLI can observe the non-timeline signals that observe_outcome
    # understands: post-merge incidents, human redo PRs, and rollback PRs.
    # Each query is bounded to a single page and the combined result is capped
    # again before returning.
    queries = [
        f"repo:{repo_slug} {head_sha}",
        f"repo:{repo_slug} {head_sha[:7]}",
        f"repo:{repo_slug} #{pr_number}",
    ]
    seen: set[str] = set()
    per_page = min(event_cap, 100)
    for query in queries:
        payload, error = _run_gh_json(
            [
                "gh",
                "api",
                "-X",
                "GET",
                "-H",
                "Accept: application/vnd.github+json",
                "search/issues",
                "-f",
                f"q={query}",
                "-f",
                f"per_page={per_page}",
            ]
        )
        if error is not None:
            return [], error
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return [], "search/issues JSON did not contain an items list"
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("node_id") or item.get("html_url") or item.get("url") or id(item))
            if key in seen:
                continue
            seen.add(key)
            normalized = _normalize_issue_search_item(item)
            if normalized is not None:
                events.append(normalized)

    for query in (f"repo:{repo_slug} {head_sha}", f"repo:{repo_slug} {head_sha[:7]}"):
        payload, error = _run_gh_json(
            [
                "gh",
                "api",
                "-X",
                "GET",
                "-H",
                "Accept: application/vnd.github+json",
                "search/commits",
                "-f",
                f"q={query}",
                "-f",
                f"per_page={per_page}",
            ]
        )
        if error is not None:
            return [], error
        items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            return [], "search/commits JSON did not contain an items list"
        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("node_id") or item.get("sha") or item.get("url") or id(item))
            if key in seen:
                continue
            seen.add(key)
            normalized = _normalize_commit_search_item(item)
            if normalized is not None:
                events.append(normalized)

    return events[:event_cap], None


def _str_or_empty(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _labels_from_issue(item: Mapping[str, Any]) -> list[str]:
    labels = item.get("labels")
    if not isinstance(labels, list):
        return []
    out: list[str] = []
    for label in labels:
        if isinstance(label, Mapping) and isinstance(label.get("name"), str):
            out.append(label["name"])
    return out


def _normalize_issue_search_item(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    created_at = item.get("created_at")
    if not isinstance(created_at, str):
        return None
    common = {
        "at": created_at,
        "labels": _labels_from_issue(item),
        "title": _str_or_empty(item.get("title")),
        "body": _str_or_empty(item.get("body")),
        "number": item.get("number"),
    }
    if isinstance(item.get("pull_request"), Mapping):
        return {"type": "pr_opened", **common}
    return {"type": "issue_opened", **common}


def _normalize_commit_search_item(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    commit_raw = item.get("commit")
    commit: Mapping[str, Any] = commit_raw if isinstance(commit_raw, Mapping) else {}
    author_raw = commit.get("author")
    author: Mapping[str, Any] = author_raw if isinstance(author_raw, Mapping) else {}
    created_at = author.get("date") or item.get("committer_date") or item.get("author_date")
    if not isinstance(created_at, str):
        return None
    return {
        "type": "commit",
        "at": created_at,
        "message": _str_or_empty(commit.get("message")),
        "sha": _str_or_empty(item.get("sha")),
    }


def _normalize_timeline_entry(
    entry: Mapping[str, Any], *, pr_number: int
) -> Mapping[str, Any] | None:
    """Map a GitHub timeline entry into the shape ``observe_outcome`` expects."""
    event_kind = entry.get("event")
    created_at = entry.get("created_at") or entry.get("submitted_at")
    if not isinstance(created_at, str):
        return None
    if event_kind == "reopened":
        return {"type": "pr_reopened", "at": created_at, "pr_number": pr_number}
    if event_kind == "committed":
        message = ""
        commit = entry.get("commit") if isinstance(entry.get("commit"), dict) else None
        if commit:
            message = str(commit.get("message", ""))
        else:
            message = str(entry.get("message", ""))
        return {"type": "commit", "at": created_at, "message": message}
    if event_kind == "labeled":
        label_obj = entry.get("label") if isinstance(entry.get("label"), dict) else {}
        labels = [str(label_obj.get("name", ""))] if label_obj else []
        source_raw = entry.get("source")
        source: Mapping[str, Any] = source_raw if isinstance(source_raw, Mapping) else {}
        issue_raw = source.get("issue")
        issue: Mapping[str, Any] = issue_raw if isinstance(issue_raw, Mapping) else {}
        return {
            "type": "issue_opened",
            "at": created_at,
            "labels": labels,
            "title": _str_or_empty(issue.get("title")),
            "body": _str_or_empty(issue.get("body")),
        }
    return None


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically via tempfile + rename, preserving permissions."""
    target_dir = path.parent
    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        existing_mode = path.stat().st_mode & 0o777
    except FileNotFoundError:
        existing_mode = None
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(target_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        if existing_mode is not None:
            os.chmod(tmp_name, existing_mode)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Insufficiency receipt
# ---------------------------------------------------------------------------


def _resolve_insufficiency_receipt_path(
    *,
    repo_root: Path,
    round_id: str,
    dry_run: bool = False,
    observed_at: datetime | None = None,
) -> Path:
    """Resolve the insufficiency-receipt destination.

    Non-dry-run (write=True) routes to the round's canonical evolve
    directory. Dry-run isolates the proposed artifact under an
    observe-outcomes/<utc-iso> subtree so dry-run runs cannot pollute
    a round's receipts and cannot ever land under docs/ or tests/.
    """
    if dry_run:
        ts = (observed_at or datetime.now(UTC)).strftime("%Y%m%dT%H%M%SZ")
        return (
            repo_root
            / ".aragora"
            / "evolve-round"
            / "observe-outcomes"
            / ts
            / "insufficiency-receipt.json"
        )
    return (
        repo_root
        / ".aragora"
        / "evolve-round"
        / round_id
        / "phase-a-observe-outcomes-insufficiency-receipt.json"
    )


def _build_insufficiency_receipt(
    *,
    window_end: datetime,
    window_days: int,
    max_receipts: int,
    receipts_examined: int,
    receipts_with_signals: int,
    receipts_written: int,
    fetch_errors: int,
    rate_limit_fetch_errors: int = 0,
    other_fetch_errors: int = 0,
    v2_now_present: bool,
) -> dict[str, Any]:
    reasons: list[str] = []
    if receipts_examined == 0:
        reasons.append(
            "no_receipts_in_window: 0 settlement receipts found inside the "
            f"{window_days}d window ending {window_end.isoformat()}"
        )
    if receipts_examined > 0 and receipts_with_signals == 0:
        reasons.append(
            "no_signals_fired: every receipt observed produced 0 invalidation "
            "signals; either the window is genuinely clean or the timeline "
            "fetch did not surface revert/incident/redo events"
        )
    if rate_limit_fetch_errors > 0:
        reasons.append(
            f"github_rate_limit_fetch_errors: {rate_limit_fetch_errors} of "
            f"{receipts_examined} receipts hit GitHub API rate limits during "
            "timeline fetch; wait for the rate limit window to reset "
            "(check 'gh api rate_limit') and rerun"
        )
    if other_fetch_errors > 0:
        reasons.append(
            f"github_fetch_errors: {other_fetch_errors} of {receipts_examined} "
            "receipts had non-rate-limit timeline fetch errors; rerun with "
            "network connectivity verified"
        )
    if max_receipts <= receipts_examined:
        reasons.append(
            f"max_receipts_cap_hit: --max-receipts={max_receipts} reached, "
            "increase the cap or narrow the window to inspect more"
        )
    return {
        "kind": "phase-a-observe-outcomes-insufficiency-receipt",
        "round": "2026-04-30g",
        "window_end_utc": window_end.isoformat(),
        "window_days": window_days,
        "max_receipts": max_receipts,
        "receipts_examined": receipts_examined,
        "receipts_with_signals_fired": receipts_with_signals,
        "receipts_written": receipts_written,
        "github_fetch_errors": fetch_errors,
        "github_rate_limit_fetch_errors": rate_limit_fetch_errors,
        "github_other_fetch_errors": other_fetch_errors,
        "v2_outcome_fields_now_present_in_window": v2_now_present,
        "remaining_blockers": reasons,
        "next_action_advice": (
            "If v2_outcome_fields_now_present_in_window is True but no signals "
            "fired, the empirical baseline can be measured but the human-side "
            "numerator is genuinely zero in this window — do not invent a "
            "threshold; rerun on a wider window or a later cohort."
            if receipts_examined > 0 and receipts_with_signals == 0
            else "Run with --window-days adjusted, ensure gh CLI is "
            "authenticated, and re-attempt. Do NOT manually populate v2 "
            "outcome fields without observing real timeline evidence."
        ),
    }


# ---------------------------------------------------------------------------
# Core observation loop
# ---------------------------------------------------------------------------


def _materialize_receipt(payload: Mapping[str, Any]) -> Any:
    """Reconstruct a ``SettlementReceipt`` from a JSON payload."""
    field_names = {f.name for f in SettlementReceipt.__dataclass_fields__.values()}
    kwargs = {k: v for k, v in payload.items() if k in field_names}
    return SettlementReceipt(**kwargs)


def _signal_extract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Project the v2 outcome-field subset for before/after comparison."""
    return {name: payload.get(name) for name in sorted(_V2_OUTCOME_FIELD_NAMES)}


def _observe_one(
    receipt: _ReceiptOnDisk,
    *,
    window_days: int,
    timeline_provider: TimelineProvider,
    per_receipt_event_cap: int,
    write: bool,
    observed_at: datetime,
) -> _ObserveResult:
    payload = receipt.payload
    pr_number = int(payload.get("pr_number", 0))
    head_sha = str(payload.get("head_sha", ""))
    if pr_number <= 0 or not head_sha:
        return _ObserveResult(
            receipt_path=receipt.path,
            pr_number=pr_number,
            head_sha=head_sha,
            fetched_event_count=0,
            fetch_error="malformed receipt: missing pr_number or head_sha",
            signals_before=_signal_extract(payload),
            signals_after=_signal_extract(payload),
            written=False,
            skipped_reason="malformed receipt",
        )
    try:
        receipt_obj = _materialize_receipt(payload)
    except (TypeError, ValueError) as exc:
        return _ObserveResult(
            receipt_path=receipt.path,
            pr_number=pr_number,
            head_sha=head_sha,
            fetched_event_count=0,
            fetch_error=f"malformed receipt: {exc}",
            signals_before=_signal_extract(payload),
            signals_after=_signal_extract(payload),
            written=False,
            skipped_reason="malformed receipt",
        )
    events, fetch_error = timeline_provider(pr_number, head_sha, per_receipt_event_cap)
    if fetch_error is not None:
        fetch_error_class = (
            "rate_limit" if _looks_like_github_rate_limit_error(fetch_error) else "other"
        )
        return _ObserveResult(
            receipt_path=receipt.path,
            pr_number=pr_number,
            head_sha=head_sha,
            fetched_event_count=len(events),
            fetch_error=fetch_error,
            signals_before=_signal_extract(payload),
            signals_after=_signal_extract(payload),
            written=False,
            skipped_reason="github fetch error",
            fetch_error_class=fetch_error_class,
        )
    observed = observe_outcome(
        receipt_obj,
        github_timeline=events,
        window_days=window_days,
        observed_at=observed_at,
    )
    new_payload = dict(payload)
    for name in _V2_OUTCOME_FIELD_NAMES:
        new_payload[name] = getattr(observed, name)
    written = False
    if write:
        try:
            _atomic_write_json(receipt.path, new_payload)
            written = True
        except OSError as exc:
            return _ObserveResult(
                receipt_path=receipt.path,
                pr_number=pr_number,
                head_sha=head_sha,
                fetched_event_count=len(events),
                fetch_error=None,
                signals_before=_signal_extract(payload),
                signals_after=_signal_extract(new_payload),
                written=False,
                skipped_reason=f"atomic write failed: {exc}",
            )
    return _ObserveResult(
        receipt_path=receipt.path,
        pr_number=pr_number,
        head_sha=head_sha,
        fetched_event_count=len(events),
        fetch_error=None,
        signals_before=_signal_extract(payload),
        signals_after=_signal_extract(new_payload),
        written=written,
    )


def run_observe_outcomes(
    *,
    store_root: str | Path | None,
    repo_root: Path,
    window_end: datetime,
    window_days: int,
    max_receipts: int,
    per_receipt_event_cap: int,
    write: bool,
    timeline_provider: TimelineProvider | None = None,
    insufficiency_receipt_path: Path | None = None,
    round_id: str = "2026-04-30g",
) -> dict[str, Any]:
    """Run the observation pipeline. Pure-function-shaped; testable.

    Returns a structured summary dict that the CLI prints. The
    summary includes a ``"results"`` list (one per receipt examined),
    aggregate counters, the ``v2_outcome_fields_now_present`` boolean,
    and (when applicable) the proposed or written insufficiency
    receipt payload and path.
    """
    if window_days <= 0:
        raise ValueError("window_days must be positive")
    if max_receipts <= 0:
        raise ValueError("max_receipts must be positive")
    if per_receipt_event_cap <= 0:
        raise ValueError("per_receipt_event_cap must be positive")
    provider = timeline_provider or _gh_timeline_provider
    observed_at = datetime.now(UTC)

    receipts = _iter_eligible_receipts(
        store_root=store_root,
        window_end=window_end,
        window_days=window_days,
        max_receipts=max_receipts,
    )
    results: list[_ObserveResult] = []
    for receipt in receipts:
        results.append(
            _observe_one(
                receipt,
                window_days=window_days,
                timeline_provider=provider,
                per_receipt_event_cap=per_receipt_event_cap,
                write=write,
                observed_at=observed_at,
            )
        )

    receipts_with_signals = sum(
        1
        for r in results
        if any(v is True for v in r.signals_after.values() if isinstance(v, bool))
    )
    receipts_written = sum(1 for r in results if r.written)
    fetch_errors = sum(1 for r in results if r.fetch_error is not None)
    rate_limit_fetch_errors = sum(1 for r in results if r.fetch_error_class == "rate_limit")
    other_fetch_errors = sum(
        1 for r in results if r.fetch_error is not None and r.fetch_error_class != "rate_limit"
    )

    # If we wrote any v2 fields, the next baseline measurement should
    # see them. Probe defensively.
    try:
        v2_now_present = _any_receipt_has_v2_outcome_fields(
            store_root=store_root,
            window_end=window_end,
            window_days=window_days,
        )
    except (OSError, ValueError) as exc:
        logger.warning("post-observation probe failed: %s", exc)
        v2_now_present = False

    insufficiency_path: Path | None = None
    insufficiency_payload: dict[str, Any] | None = None
    if len(results) == 0 or receipts_with_signals == 0 or fetch_errors > 0:
        insufficiency_payload = _build_insufficiency_receipt(
            window_end=window_end,
            window_days=window_days,
            max_receipts=max_receipts,
            receipts_examined=len(results),
            receipts_with_signals=receipts_with_signals,
            receipts_written=receipts_written,
            fetch_errors=fetch_errors,
            rate_limit_fetch_errors=rate_limit_fetch_errors,
            other_fetch_errors=other_fetch_errors,
            v2_now_present=v2_now_present,
        )
        insufficiency_path = insufficiency_receipt_path or _resolve_insufficiency_receipt_path(
            repo_root=repo_root,
            round_id=round_id,
            dry_run=not write,
            observed_at=observed_at,
        )
        if write:
            try:
                _atomic_write_json(insufficiency_path, insufficiency_payload)
            except OSError as exc:
                logger.warning(
                    "could not write insufficiency receipt %s: %s",
                    insufficiency_path,
                    exc,
                )

    return {
        "mode": "write" if write else "dry-run",
        "window_end_utc": window_end.isoformat(),
        "window_days": window_days,
        "max_receipts": max_receipts,
        "per_receipt_event_cap": per_receipt_event_cap,
        "receipts_examined": len(results),
        "receipts_with_signals_fired": receipts_with_signals,
        "receipts_written": receipts_written,
        "github_fetch_errors": fetch_errors,
        "github_rate_limit_fetch_errors": rate_limit_fetch_errors,
        "github_other_fetch_errors": other_fetch_errors,
        "v2_outcome_fields_now_present_in_window": v2_now_present,
        "insufficiency_receipt_path": (str(insufficiency_path) if insufficiency_path else None),
        "insufficiency_receipt": insufficiency_payload,
        "results": [
            {
                "receipt_path": str(r.receipt_path),
                "pr_number": r.pr_number,
                "head_sha": r.head_sha,
                "fetched_event_count": r.fetched_event_count,
                "fetch_error": r.fetch_error,
                "fetch_error_class": r.fetch_error_class,
                "signals_before": r.signals_before,
                "signals_after": r.signals_after,
                "written": r.written,
                "skipped_reason": r.skipped_reason,
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# argparse subparser registration
# ---------------------------------------------------------------------------


def add_observe_outcomes_subparser(sub: argparse._SubParsersAction) -> None:
    """Register ``observe-outcomes`` under the ``review-queue`` subparser."""
    p = sub.add_parser(
        "observe-outcomes",
        help=(
            "Observe post-settlement invalidation signals from GitHub "
            "timeline events and (optionally) write them back into v2 "
            "outcome fields on settlement receipts. Dry-run by default."
        ),
        description=(
            "Round 30g phase A. Iterates settled receipts in a bounded\n"
            "window, fetches GitHub timeline events for each PR with\n"
            "bounded fanout, and computes the five canonical v2 outcome\n"
            "signals via aragora.review.settlement_outcome.observe_outcome.\n\n"
            "Default mode is read-only: nothing is written. Pass --write\n"
            "to mutate receipt JSON files in place. The CLI never invokes\n"
            "git or gh write operations and never edits docs/THESIS.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"Observation window in days (default: {DEFAULT_WINDOW_DAYS}).",
    )
    p.add_argument(
        "--max-receipts",
        type=int,
        default=DEFAULT_MAX_RECEIPTS,
        help=(
            "Maximum receipts to inspect in this run "
            f"(default: {DEFAULT_MAX_RECEIPTS}). Bounds the GitHub fanout."
        ),
    )
    p.add_argument(
        "--per-receipt-event-cap",
        type=int,
        default=DEFAULT_PER_RECEIPT_EVENT_CAP,
        help=(
            "Maximum timeline events fetched per receipt "
            f"(default: {DEFAULT_PER_RECEIPT_EVENT_CAP})."
        ),
    )
    p.add_argument(
        "--review-queue-root",
        default=None,
        help=(
            "Override the review-queue store root used for settlement "
            "receipts. Defaults to <repo>/.aragora/review-queue."
        ),
    )
    p.add_argument(
        "--write",
        action="store_true",
        help=(
            "OPT-IN: actually write v2 outcome fields back into receipt "
            "JSON files. Default is dry-run preview only."
        ),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output the run summary as JSON.",
    )


# ---------------------------------------------------------------------------
# CLI dispatcher entry point lives in aragora.cli.commands.observe_outcomes_cmd
# (T201 per-file-ignore covers print-rendering there). This module keeps the
# pipeline pure-function-shaped.
# ---------------------------------------------------------------------------
