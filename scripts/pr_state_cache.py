#!/usr/bin/env python3
"""Shared PR-state cache: ONE budgeted REST-only poller, many cheap readers (#8315).

The automation fleet shares a single GitHub identity. N concurrent lanes each
re-polling identical PR state via GraphQL-backed ``gh pr view`` / ``gh pr list``
exhausts the 5,000-point/hour GraphQL budget. This module replaces that fan-out
with a single REST-only poller that maintains an atomically-written JSON cache;
lanes read the cache and spend exactly one targeted REST call to verify the
exact head immediately before any mutation.

READER CONTRACT (explicit, binding for every lane):

  Lanes MUST: (1) read from cache for routine state, (2) call ``verify`` for
  the exact head immediately before any mutation, (3) never treat cache as
  authority for settlement/merge gates — merge-packet remains the gate
  authority.

Subcommands:

- ``poll``   — list pass + delta detail pass. Dry-run by default: prints the
  would-write cache JSON to stdout and touches nothing; ``--apply`` writes
  ``--cache-file`` atomically (mkstemp + os.replace, never a partial file).
- ``read``   — cheap lane path: prints the cached entry plus a freshness
  verdict (``fresh``/``stale``/``missing``); exit 3 when stale or missing.
  Every read is self-describing: the cache carries ``generated_at`` and a
  per-PR ``checks_fetched_at``. Staleness policy is the READER's job, bounded
  here by ``--max-age-seconds``.
- ``verify`` — the only always-live command: exactly ONE REST call
  (``gh api repos/{repo}/pulls/N``) returning current head/state for the
  just-before-mutation check.

List pass (REST, conditional requests):

- ``gh api -i "repos/{repo}/pulls?state=open&per_page=100"`` — ``-i`` captures
  the HTTP status line and headers, so the ETag can be stored per endpoint and
  replayed via ``-H "If-None-Match: <etag>"`` on subsequent polls. ``gh``
  exits nonzero on a 304, so the status is parsed from the captured ``-i``
  output rather than trusted from the exit code: a parsed 304 means
  "unchanged, zero rate-limit cost" and terminates the list pass reusing
  cached data. Pagination follows pages until a short page or ``--max-pages``.

Delta detail pass:

- Only PRs whose head moved since the cached entry (or with no cached checks)
  cost a ``repos/{repo}/commits/{sha}/check-runs?per_page=100`` call; the
  latest run per check name (by run id, with creation-time fallback) is stored
  as ``{name: conclusion-or-status}``. At most ``--max-detail`` fetches per
  run; over-cap PRs are annotated ``detail_deferred:<n>``.

Safety model (mirrors scripts/auto_evidence_cycle.py):

- ``--max-requests`` per poll run (default 30); exceeding it stops the run,
  annotates ``budget_exhausted``, exit 3.
- Identical-error breaker: 3 consecutive identical gh failures abort, exit 2,
  nothing written.
- A gh transport/HTTP failure on the list pass keeps the previous cache file
  byte-for-byte intact, annotates, exit 1 — a partial or empty cache is never
  written over a good one.
- Fail-closed exits: 0 clean, 1 failure, 2 breaker, 3 budget/stale/missing.

Stdlib-only by design so it can run anywhere ``gh`` is authenticated. All I/O
boundaries (the gh runner, the clock) are injectable for tests.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

DEFAULT_REPO = "synaptent/aragora"
DEFAULT_CACHE_FILE = os.path.join(".aragora", "pr-state-cache.json")
DEFAULT_MAX_PAGES = 5
DEFAULT_MAX_DETAIL = 10
DEFAULT_MAX_REQUESTS = 30
DEFAULT_MAX_AGE_SECONDS = 300
BREAKER_THRESHOLD = 3
PER_PAGE = 100
SCHEMA_VERSION = 1
GH_TIMEOUT_SECONDS = 60

EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_BREAKER = 2
EXIT_STALE = 3  # also: budget exhausted (bounded-cap outcome, not a fault)

# Same owner/name shape every repo-taking automation script here validates.
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_STATUS_LINE_RE = re.compile(r"^HTTP/[0-9.]+\s+(\d{3})")

GhRunner = Callable[[list[str]], tuple[int, str, str]]


# --- gh transport ----------------------------------------------------------------


def default_run_gh(args: list[str]) -> tuple[int, str, str]:
    """Run ``gh <args>``; returns (returncode, stdout, stderr). Never raises."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"
    return proc.returncode, proc.stdout, proc.stderr


@dataclass
class GhResponse:
    """Parsed ``gh api -i`` output: HTTP status, headers, body."""

    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    error: str = ""


def parse_gh_api_response(returncode: int, stdout: str, stderr: str) -> GhResponse:
    """Parse ``gh api -i`` output into status/headers/body.

    ``gh api`` exits nonzero for any non-2xx status — including 304 Not
    Modified, which for conditional requests is the *success* path (unchanged,
    zero rate-limit cost). So the exit code is never trusted directly: the
    status line is parsed out of the captured ``-i`` output, and only output
    with no parseable HTTP status at all is a transport failure.
    """
    text = stdout or ""
    match = _STATUS_LINE_RE.match(text)
    if match is None:
        detail = (stderr or stdout or "").strip()[:300]
        return GhResponse(
            status=None,
            error=detail or f"gh exited {returncode} with no HTTP status line",
        )
    status = int(match.group(1))
    head, sep, body = text.partition("\r\n\r\n")
    if not sep:
        head, _, body = text.partition("\n\n")
    headers: dict[str, str] = {}
    for line in head.splitlines()[1:]:
        name, colon, value = line.partition(":")
        if colon:
            headers[name.strip().lower()] = value.strip()
    return GhResponse(status=status, headers=headers, body=body.strip())


# --- cache I/O -------------------------------------------------------------------


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON atomically: mkstemp in the target dir, then os.replace.

    A failure mid-write can never leave a partial cache at ``path``; the
    temp file is always cleaned up.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # already replaced into place (common case) or never created


def load_cache(path: str) -> dict[str, Any] | None:
    """Load the cache file; None when missing, unreadable, or malformed."""
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: Any) -> float | None:
    try:
        parsed = datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc).timestamp()


# --- normalization ---------------------------------------------------------------


def list_endpoint(repo: str, page: int) -> str:
    base = f"repos/{repo}/pulls?state=open&per_page={PER_PAGE}"
    return base if page <= 1 else f"{base}&page={page}"


def check_runs_endpoint(repo: str, sha: str) -> str:
    return f"repos/{repo}/commits/{sha}/check-runs?per_page={PER_PAGE}"


def normalize_pr(row: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one REST pulls-list row into the cache PR schema."""
    try:
        number = int(row["number"])
    except (KeyError, TypeError, ValueError):
        return None
    head = row.get("head") if isinstance(row.get("head"), dict) else {}
    base = row.get("base") if isinstance(row.get("base"), dict) else {}
    labels = [
        str(label.get("name"))
        for label in (row.get("labels") or [])
        if isinstance(label, dict) and label.get("name")
    ]
    return {
        "number": number,
        "head_sha": str(head.get("sha") or ""),
        "head_ref": str(head.get("ref") or ""),
        "base_ref": str(base.get("ref") or ""),
        "draft": bool(row.get("draft")),
        "state": str(row.get("state") or ""),
        "updated_at": str(row.get("updated_at") or ""),
        "labels": labels,
        "checks": None,
        "checks_fetched_at": None,
    }


def extract_checks(payload: dict[str, Any]) -> dict[str, str]:
    """Latest check-run per name: ``{name: conclusion-or-status}``.

    GitHub returns every attempt. Run ids identify attempt creation order;
    timestamps are only a fallback for incomplete fixtures or payloads. Using
    completion time as the primary key can hide a newer queued attempt whose
    ``started_at`` and ``completed_at`` fields are still null.
    """
    latest: dict[str, tuple[dict[str, Any], int, str]] = {}
    for index, run in enumerate(payload.get("check_runs") or []):
        if not isinstance(run, dict):
            continue
        name = str(run.get("name") or "")
        if not name:
            continue
        value = str(run.get("conclusion") or run.get("status") or "")
        previous = latest.get(name)
        if previous is None or _check_run_is_newer(run, index, previous[0], previous[1]):
            latest[name] = (run, index, value)
    return {name: value for name, (_, _, value) in sorted(latest.items())}


def _check_run_is_newer(
    candidate: dict[str, Any],
    candidate_index: int,
    current: dict[str, Any],
    current_index: int,
) -> bool:
    def run_id(run: dict[str, Any]) -> int:
        try:
            return int(run.get("id") or 0)
        except (TypeError, ValueError):
            return 0

    candidate_id = run_id(candidate)
    current_id = run_id(current)
    if candidate_id and current_id and candidate_id != current_id:
        return candidate_id > current_id

    def timestamp(run: dict[str, Any]) -> str:
        return str(run.get("created_at") or run.get("started_at") or run.get("completed_at") or "")

    candidate_timestamp = timestamp(candidate)
    current_timestamp = timestamp(current)
    if candidate_timestamp != current_timestamp:
        return candidate_timestamp > current_timestamp
    return candidate_index > current_index


# --- poll ------------------------------------------------------------------------


def run_poll(
    *,
    repo: str,
    previous: dict[str, Any] | None,
    run_gh: GhRunner,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_detail: int = DEFAULT_MAX_DETAIL,
    max_requests: int = DEFAULT_MAX_REQUESTS,
    breaker_threshold: int = BREAKER_THRESHOLD,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """One bounded poll: list pass, merge, delta detail pass.

    Returns ``{"cache": dict | None, "exit_code": int, "annotations": [...],
    "requests_used": int}``. ``cache`` is None exactly when nothing may be
    written (list failure → exit 1, breaker → exit 2, budget exhausted before
    the list completed → exit 3): the previous cache file must stay intact.
    """
    annotations: list[str] = []
    requests_used = 0
    prev = previous if isinstance(previous, dict) else {}
    prev_endpoints = prev.get("endpoints") if isinstance(prev.get("endpoints"), dict) else {}
    prev_prs = prev.get("prs") if isinstance(prev.get("prs"), dict) else {}

    def summary(cache: dict[str, Any] | None, exit_code: int) -> dict[str, Any]:
        return {
            "cache": cache,
            "exit_code": exit_code,
            "annotations": annotations,
            "requests_used": requests_used,
        }

    # --- LIST PASS (conditional REST; any failure keeps the previous cache) ---
    endpoints: dict[str, Any] = {}
    fetched: dict[str, dict[str, Any]] = {}
    saw_304 = False
    for page in range(1, max(1, max_pages) + 1):
        if requests_used >= max_requests:
            annotations.append("budget_exhausted")
            return summary(None, EXIT_STALE)
        endpoint = list_endpoint(repo, page)
        prev_meta = prev_endpoints.get(endpoint)
        etag = str(prev_meta.get("etag") or "") if isinstance(prev_meta, dict) else ""
        args = ["api", "-i", endpoint]
        if etag:
            args += ["-H", f"If-None-Match: {etag}"]
        requests_used += 1
        response = parse_gh_api_response(*run_gh(args))
        now_iso = _iso(clock())
        if response.status == 304:
            # Unchanged, zero rate-limit cost: reuse cached data from here on.
            saw_304 = True
            endpoints[endpoint] = {"etag": etag, "last_status": 304, "fetched_at": now_iso}
            break
        if response.status != 200:
            reason = response.error or f"http {response.status}"
            annotations.append(f"list_fetch_failed:{endpoint}:{reason[:160]}")
            return summary(None, EXIT_FAILURES)
        try:
            rows = json.loads(response.body or "[]")
        except json.JSONDecodeError:
            annotations.append(f"list_fetch_failed:{endpoint}:unparseable body")
            return summary(None, EXIT_FAILURES)
        if not isinstance(rows, list):
            annotations.append(f"list_fetch_failed:{endpoint}:expected a list")
            return summary(None, EXIT_FAILURES)
        endpoints[endpoint] = {
            "etag": response.headers.get("etag") or etag or None,
            "last_status": 200,
            "fetched_at": now_iso,
        }
        for row in rows:
            entry = normalize_pr(row) if isinstance(row, dict) else None
            if entry is not None:
                fetched[str(entry["number"])] = entry
        if len(rows) < PER_PAGE:
            break
    else:
        annotations.append(f"pages_capped:{max_pages}")

    # --- MERGE: carry checks forward for unchanged heads -----------------------
    prs: dict[str, dict[str, Any]] = {}
    if saw_304:
        # Cannot enumerate closed PRs without a fresh full listing; keep all.
        prs.update({num: dict(entry) for num, entry in prev_prs.items()})
    for num, entry in fetched.items():
        old = prev_prs.get(num)
        if isinstance(old, dict) and old.get("head_sha") == entry["head_sha"]:
            entry["checks"] = old.get("checks")
            entry["checks_fetched_at"] = old.get("checks_fetched_at")
        prs[num] = entry

    # --- DELTA DETAIL PASS: only moved heads / missing checks cost a request ---
    budget_exhausted = False
    detail_done = 0
    identical_errors = 0
    last_error: str | None = None
    for num in sorted(prs, key=int):
        entry = prs[num]
        if entry.get("checks") is not None or not entry.get("head_sha"):
            continue
        if detail_done >= max_detail or requests_used >= max_requests:
            if requests_used >= max_requests:
                budget_exhausted = True
            annotations.append(f"detail_deferred:{num}")
            continue
        requests_used += 1
        returncode, stdout, stderr = run_gh(
            ["api", check_runs_endpoint(repo, str(entry["head_sha"]))]
        )
        error = ""
        if returncode != 0:
            error = (stderr or stdout).strip()[:200] or f"gh exited {returncode}"
        else:
            try:
                payload = json.loads(stdout or "{}")
                if not isinstance(payload, dict):
                    raise ValueError("non-object payload")
            except (json.JSONDecodeError, ValueError):
                error = "unparseable check-runs body"
            else:
                entry["checks"] = extract_checks(payload)
                entry["checks_fetched_at"] = _iso(clock())
                detail_done += 1
                identical_errors = 0
                last_error = None
                continue
        annotations.append(f"detail_failed:{num}:{error[:160]}")
        identical_errors = identical_errors + 1 if error == last_error else 1
        last_error = error
        if identical_errors >= breaker_threshold:
            annotations.append("breaker_tripped")
            return summary(None, EXIT_BREAKER)

    if budget_exhausted:
        annotations.append("budget_exhausted")

    cache = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(clock()),
        "repo": repo,
        "endpoints": {**prev_endpoints, **endpoints},
        "prs": prs,
        "annotations": annotations,
    }
    return summary(cache, EXIT_STALE if budget_exhausted else EXIT_OK)


# --- read (lanes' cheap path) ------------------------------------------------------


def run_read(
    cache: dict[str, Any] | None,
    pr: int,
    *,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    clock: Callable[[], float] = time.time,
) -> tuple[dict[str, Any], int]:
    """Freshness-verdicted cache read; never touches the network.

    Verdicts: ``fresh`` (exit 0), ``stale`` / ``missing`` (exit 3 — the lane
    must wait for the poller or escalate to ``verify``).
    """
    entry = None
    if isinstance(cache, dict):
        prs = cache.get("prs")
        if isinstance(prs, dict):
            entry = prs.get(str(pr))
    if entry is None:
        return {"pr": pr, "verdict": "missing", "entry": None}, EXIT_STALE
    generated = _parse_iso(cache.get("generated_at")) if isinstance(cache, dict) else None
    age = clock() - generated if generated is not None else None
    report = {
        "pr": pr,
        "generated_at": cache.get("generated_at") if isinstance(cache, dict) else None,
        "age_seconds": round(age, 1) if age is not None else None,
        "max_age_seconds": max_age_seconds,
        "checks_fetched_at": entry.get("checks_fetched_at"),
        "entry": entry,
    }
    if age is None or age > max_age_seconds:
        report["verdict"] = "stale"
        return report, EXIT_STALE
    report["verdict"] = "fresh"
    return report, EXIT_OK


# --- verify (the only always-live command) -----------------------------------------


def run_verify(repo: str, pr: int, run_gh: GhRunner) -> tuple[dict[str, Any], int]:
    """Exactly ONE live REST call returning current head/state for PR ``pr``.

    This is the lane's just-before-mutation check; it is deliberately the only
    code path here that always spends a request.
    """
    returncode, stdout, stderr = run_gh(["api", f"repos/{repo}/pulls/{pr}"])
    if returncode != 0:
        error = (stderr or stdout).strip()[:300] or f"gh exited {returncode}"
        return {"pr": pr, "error": error}, EXIT_FAILURES
    try:
        payload = json.loads(stdout or "{}")
        if not isinstance(payload, dict):
            raise ValueError("non-object payload")
    except (json.JSONDecodeError, ValueError):
        return {"pr": pr, "error": "unparseable gh api body"}, EXIT_FAILURES
    head = payload.get("head") if isinstance(payload.get("head"), dict) else {}
    base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
    return {
        "pr": pr,
        "number": payload.get("number"),
        "head_sha": str(head.get("sha") or ""),
        "head_ref": str(head.get("ref") or ""),
        "base_ref": str(base.get("ref") or ""),
        "state": str(payload.get("state") or ""),
        "draft": bool(payload.get("draft")),
        "merged": bool(payload.get("merged")),
        "mergeable": payload.get("mergeable"),
        "updated_at": str(payload.get("updated_at") or ""),
        "live": True,
    }, EXIT_OK


# --- CLI ---------------------------------------------------------------------------


def _repo_type(value: str) -> str:
    if not _REPO_RE.match(value):
        raise argparse.ArgumentTypeError(f"malformed repo {value!r} (expected owner/name)")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", type=_repo_type, default=DEFAULT_REPO, help="owner/name")
    parser.add_argument(
        "--cache-file",
        default=DEFAULT_CACHE_FILE,
        help=f"cache file path (default: {DEFAULT_CACHE_FILE})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    poll = sub.add_parser("poll", help="budgeted REST list + delta detail pass")
    poll.add_argument(
        "--apply",
        action="store_true",
        help="write the cache file (default: dry-run, print would-write JSON)",
    )
    poll.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    poll.add_argument("--max-detail", type=int, default=DEFAULT_MAX_DETAIL)
    poll.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)

    read = sub.add_parser("read", help="cached entry + freshness verdict (no network)")
    read.add_argument("--pr", type=int, required=True)
    read.add_argument("--max-age-seconds", type=float, default=DEFAULT_MAX_AGE_SECONDS)

    verify = sub.add_parser("verify", help="ONE live REST call for the exact current head")
    verify.add_argument("--pr", type=int, required=True)

    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    run_gh: GhRunner = default_run_gh,
    clock: Callable[[], float] = time.time,
) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "poll":
        previous = load_cache(args.cache_file)
        summary = run_poll(
            repo=args.repo,
            previous=previous,
            run_gh=run_gh,
            max_pages=max(1, args.max_pages),
            max_detail=max(0, args.max_detail),
            max_requests=max(0, args.max_requests),
            clock=clock,
        )
        cache = summary["cache"]
        if cache is None:
            print(
                json.dumps(
                    {
                        "action": "poll",
                        "wrote": False,
                        "annotations": summary["annotations"],
                        "requests_used": summary["requests_used"],
                        "exit_code": summary["exit_code"],
                    }
                ),
                file=sys.stderr,
            )
            return int(summary["exit_code"])
        if not args.apply:
            print(json.dumps(cache, indent=2, sort_keys=True))
            return int(summary["exit_code"])
        try:
            atomic_write_json(Path(args.cache_file), cache)
        except OSError as exc:
            print(
                json.dumps({"action": "poll", "wrote": False, "error": str(exc)[:300]}),
                file=sys.stderr,
            )
            return EXIT_FAILURES
        print(
            json.dumps(
                {
                    "action": "poll",
                    "wrote": True,
                    "cache_file": args.cache_file,
                    "prs": len(cache["prs"]),
                    "annotations": summary["annotations"],
                    "requests_used": summary["requests_used"],
                    "exit_code": summary["exit_code"],
                }
            )
        )
        return int(summary["exit_code"])

    if args.command == "read":
        report, exit_code = run_read(
            load_cache(args.cache_file),
            args.pr,
            max_age_seconds=args.max_age_seconds,
            clock=clock,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return exit_code

    # verify
    report, exit_code = run_verify(args.repo, args.pr, run_gh)
    print(json.dumps(report, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
