#!/usr/bin/env python3
"""Publish recurring TW-03 rescue productization artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# NOTE: ``scripts.rescue_to_fixtures`` (and ``scripts.harvest_rescue_classes``)
# import ``aragora.swarm.rescue_events``, which triggers ``aragora.swarm``'s
# package ``__init__`` and its heavy commander/supervisor/worker-launcher/agents
# import chain. Importing those eagerly at module load made this publisher hang
# on the swarm/agents stack (observed 300s+), forcing a fall-back to a
# timestamp-only refresh. The rescue-fixture helpers are therefore imported
# lazily inside ``_rescue_fixtures()`` so the publisher's pure-Python surface
# (path normalization, JSON IO, argument parsing) loads instantly and the swarm
# dependency is only paid — and only required — when a report is actually built.

# ``DEFAULT_PRODUCTIZATION_MAP_PATH`` is a trivial repo-relative constant in
# ``scripts.harvest_rescue_classes``; re-deriving it here avoids importing that
# module (and its swarm dependency) merely to build the argument parser.
DEFAULT_PRODUCTIZATION_MAP_PATH = REPO_ROOT / "docs" / "benchmarks" / "rescue_productization.json"

DEFAULT_RESCUE_LEDGER_PATH = Path.home() / ".aragora" / "rescue_events.jsonl"
DEFAULT_PUBLISH_DIR = REPO_ROOT / ".aragora" / "rescue_productization"


class RescueLedgerValidationError(ValueError):
    """Raised when the TW-03 source ledger cannot support a truthful report."""

    def __init__(self, *, code: str, path: Path, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.path = path
        self.detail = detail

    def to_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": _repo_stable_path(self.path),
            "detail": self.detail,
        }


def _rescue_fixtures() -> Any:
    """Lazily import the rescue-fixture helpers from ``scripts.rescue_to_fixtures``.

    Deferred to call time so the swarm/agents import chain is only loaded when a
    report is genuinely being built. Raises a clear, actionable error if the
    dependency stack is unavailable rather than hanging or failing opaquely.
    """
    try:
        from scripts import rescue_to_fixtures
    except ImportError as exc:  # pragma: no cover - defensive guard
        raise RuntimeError(
            "rescue productization helpers are unavailable: "
            "scripts.rescue_to_fixtures could not be imported "
            "(the aragora.swarm dependency stack may be missing). "
            f"original error: {exc}"
        ) from exc
    return rescue_to_fixtures


def _coerce_utc_datetime(value: str | None = None) -> dt.datetime:
    if value:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = dt.datetime.now(dt.UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).replace(microsecond=0)


def normalize_generated_at(value: str | None = None) -> str:
    return _coerce_utc_datetime(value).isoformat().replace("+00:00", "Z")


def _home_relative_path(raw: str) -> str:
    """Collapse a ``$HOME``-rooted absolute path to its ``~``-prefixed form.

    The published report is a committed truth surface in a public repo, so an
    absolute home-dir path (``/Users/<name>/.aragora/...``) would leak the local
    username, re-introduce the leak #7706 fixed, and trip both
    ``scripts/check_portability.py`` and the truth-surface consistency test
    (which expects ``~/.aragora/...``). Mirror
    ``benchmarks/bench_readiness/write_manifest._portable_path``: rewrite a
    ``$HOME``-rooted path to ``~``; leave non-home / CI paths untouched.
    """
    home = os.path.expanduser("~")
    if home and home != "~" and (raw == home or raw.startswith(home + os.sep)):
        return "~" + raw[len(home) :]
    return raw


def _repo_stable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return _home_relative_path(str(resolved))


def _safe_os_error_detail(exc: OSError) -> str:
    """Describe an IO failure without re-emitting a local absolute path."""
    return str(exc.strerror or type(exc).__name__)


def _is_incomplete_trailing_json_record(
    *,
    exc: json.JSONDecodeError,
    line: str,
    is_last_nonempty_line: bool,
    source_ends_with_newline: bool,
) -> bool:
    """Recognize only a torn final append, never arbitrary malformed JSON.

    ``RescueEventLedger.record`` writes one JSON object and its newline in two
    writes. A concurrent snapshot can therefore end inside the final object.
    Complete lines, earlier lines, and invalid tokens remain hard failures.
    """
    if not is_last_nonempty_line or source_ends_with_newline:
        return False
    message = exc.msg.lower()
    if message.startswith("unterminated string"):
        return True
    incomplete_messages = (
        "expecting value",
        "expecting ',' delimiter",
        "expecting ':' delimiter",
        "expecting property name enclosed in double quotes",
    )
    return message.startswith(incomplete_messages) and exc.pos >= max(0, len(line.rstrip()) - 1)


def _read_validated_rescue_ledger(path: Path) -> tuple[dict[str, Any], bytes]:
    """Read one validated ledger snapshot and return provenance plus bytes.

    A missing or malformed ledger is not equivalent to an observed empty
    ledger. Fail closed so TW-03 never publishes an authoritative-looking zero
    when its source is unavailable.
    """
    stable_path = _repo_stable_path(path)
    try:
        if not path.exists():
            raise RescueLedgerValidationError(
                code="rescue_ledger_missing",
                path=path,
                detail=f"rescue event ledger does not exist: {stable_path}",
            )
        if not path.is_file():
            raise RescueLedgerValidationError(
                code="rescue_ledger_not_file",
                path=path,
                detail=f"rescue event ledger is not a regular file: {stable_path}",
            )
        raw = path.read_bytes()
    except RescueLedgerValidationError:
        raise
    except OSError as exc:
        raise RescueLedgerValidationError(
            code="rescue_ledger_unreadable",
            path=path,
            detail=(
                f"rescue event ledger is unreadable: {stable_path}: {_safe_os_error_detail(exc)}"
            ),
        ) from exc

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RescueLedgerValidationError(
            code="rescue_ledger_invalid_utf8",
            path=path,
            detail=f"rescue event ledger is not valid UTF-8: {stable_path}",
        ) from exc

    lines = text.splitlines()
    nonempty_line_numbers = [
        line_number for line_number, line in enumerate(lines, start=1) if line.strip()
    ]
    last_nonempty_line = nonempty_line_numbers[-1] if nonempty_line_numbers else None
    source_ends_with_newline = raw.endswith((b"\n", b"\r"))
    event_count = 0
    skipped_trailing_partial_line = False
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            if event_count > 0 and _is_incomplete_trailing_json_record(
                exc=exc,
                line=line,
                is_last_nonempty_line=line_number == last_nonempty_line,
                source_ends_with_newline=source_ends_with_newline,
            ):
                skipped_trailing_partial_line = True
                continue
            raise RescueLedgerValidationError(
                code="rescue_ledger_malformed",
                path=path,
                detail=(
                    f"rescue event ledger has invalid JSON on line {line_number}: {stable_path}"
                ),
            ) from exc
        if not isinstance(event, dict):
            raise RescueLedgerValidationError(
                code="rescue_ledger_malformed",
                path=path,
                detail=(
                    f"rescue event ledger line {line_number} must be a JSON object: {stable_path}"
                ),
            )
        if (
            "event_type" not in event
            or not isinstance(event["event_type"], str)
            or "reason" not in event
            or not isinstance(event["reason"], str)
        ):
            raise RescueLedgerValidationError(
                code="rescue_ledger_malformed",
                path=path,
                detail=(
                    f"rescue event ledger line {line_number} requires string "
                    f"event_type and reason fields: {stable_path}"
                ),
            )
        event_count += 1

    source = {
        "status": "available",
        "event_count": event_count,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if skipped_trailing_partial_line:
        source["skipped_trailing_partial_line_count"] = 1
    return source, raw


def validate_rescue_ledger(path: Path) -> dict[str, Any]:
    """Validate the rescue ledger and return provenance for the observed bytes."""
    source, _ = _read_validated_rescue_ledger(path)
    return source


def resolve_published_report_path(
    *,
    publish_dir: Path,
    generated_at: str,
) -> Path:
    timestamp = _coerce_utc_datetime(generated_at).strftime("%Y%m%dT%H%M%SZ")
    return publish_dir / f"rescue-productization-{timestamp}.json"


def resolve_latest_report_path(*, publish_dir: Path) -> Path:
    return publish_dir / "latest.json"


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _validate_productization_map_schema_version(path: Path, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Productization map at {path} schema_version must be a positive integer")
    return value


def _validate_productization_map_entries(path: Path, entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError(f"Productization map at {path} must contain an 'entries' list")

    validated: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict) or not str(entry.get("class") or "").strip():
            raise ValueError(
                f"Productization map at {path} entries must be JSON objects "
                "with a non-empty `class`"
            )
        validated.append(entry)
    return validated


def load_productization_map_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "entries": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Productization map at {path} must be a JSON object")
    schema_version = _validate_productization_map_schema_version(
        path,
        payload.get("schema_version", 1),
    )
    entries = _validate_productization_map_entries(path, payload.get("entries"))
    return {
        "schema_version": schema_version,
        "entries": entries,
    }


def write_productization_map_payload(path: Path, payload: dict[str, Any]) -> Path:
    schema_version = _validate_productization_map_schema_version(
        path,
        payload.get("schema_version", 1),
    )
    raw_entries = payload.get("entries", [])
    entries = _validate_productization_map_entries(path, [] if raw_entries is None else raw_entries)
    entries.sort(key=lambda entry: str(entry.get("class") or "").strip())
    normalized = {
        "schema_version": schema_version,
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _issue_ref(number: int) -> str:
    return f"#{number}"


def find_existing_issue_by_title(*, repo: str, title: str) -> dict[str, Any] | None:
    result = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            repo,
            "--state",
            "all",
            "--search",
            title,
            "--json",
            "number,title,url,state",
            "--limit",
            "100",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh issue list failed")
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        if str(item.get("title") or "").strip() != title:
            continue
        number = int(item.get("number", 0) or 0)
        if number <= 0:
            continue
        return {
            "number": number,
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "state": str(item.get("state") or "").strip().lower(),
        }
    return None


def create_issue_for_draft(*, repo: str, draft: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            str(draft.get("title") or "").strip(),
            "--body",
            str(draft.get("body") or "").strip(),
            "--label",
            "boss-ready",
            "--label",
            "autonomous",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh issue create failed")
    url = str(result.stdout or "").strip().splitlines()[-1].strip()
    match = re.search(r"/issues/(\d+)$", url)
    if not match:
        raise RuntimeError(f"could not parse issue URL from gh output: {url}")
    return {
        "number": int(match.group(1)),
        "title": str(draft.get("title") or "").strip(),
        "url": url,
        "state": "open",
    }


def _upsert_issue_entry(
    *,
    entries_by_class: dict[str, dict[str, Any]],
    class_name: str,
    issue: dict[str, Any],
) -> None:
    existing = dict(entries_by_class.get(class_name, {}) or {})
    notes = str(existing.get("notes") or "").strip()
    entries_by_class[class_name] = {
        "class": class_name,
        "target_kind": "issue",
        "target": _issue_ref(int(issue["number"])),
        "title": str(issue.get("title") or "").strip(),
        "notes": notes or "Auto-linked by recurring TW-03 harvest.",
    }


def ensure_issue_linkage(
    *,
    issue_drafts: list[dict[str, Any]],
    productization_map_path: Path,
    repo: str,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    payload = load_productization_map_payload(productization_map_path)
    entries_by_class = {
        str(entry.get("class") or "").strip(): dict(entry)
        for entry in list(payload.get("entries") or [])
        if isinstance(entry, dict) and str(entry.get("class") or "").strip()
    }
    results: list[dict[str, Any]] = []
    changed = False

    for draft in issue_drafts:
        class_name = str(draft.get("class") or "").strip()
        title = str(draft.get("title") or "").strip() or _rescue_fixtures().build_issue_title(
            class_name
        )
        if not class_name or not title:
            continue
        try:
            existing = find_existing_issue_by_title(repo=repo, title=title)
            if existing:
                _upsert_issue_entry(
                    entries_by_class=entries_by_class, class_name=class_name, issue=existing
                )
                results.append(
                    {
                        "class": class_name,
                        "action": "linked_existing_issue",
                        "target_kind": "issue",
                        "target": _issue_ref(existing["number"]),
                        "url": existing["url"],
                    }
                )
                changed = True
                continue
            if dry_run:
                results.append(
                    {
                        "class": class_name,
                        "action": "dry_run_issue_create",
                        "target_kind": "issue",
                        "target": title,
                    }
                )
                continue
            created = create_issue_for_draft(repo=repo, draft=draft)
            _upsert_issue_entry(
                entries_by_class=entries_by_class, class_name=class_name, issue=created
            )
            results.append(
                {
                    "class": class_name,
                    "action": "created_issue",
                    "target_kind": "issue",
                    "target": _issue_ref(created["number"]),
                    "url": created["url"],
                }
            )
            changed = True
        except (RuntimeError, subprocess.TimeoutExpired, OSError, json.JSONDecodeError) as exc:
            results.append(
                {
                    "class": class_name,
                    "action": "error",
                    "error": str(exc),
                }
            )

    if changed and not dry_run:
        write_productization_map_payload(
            productization_map_path,
            {
                "schema_version": int(payload.get("schema_version", 1) or 1),
                "entries": list(entries_by_class.values()),
            },
        )
    return results


def build_published_report(
    *,
    ledger_path: Path,
    productization_map_path: Path,
    repo: str,
    generated_at: str | None = None,
    threshold: int = 2,
    recent_limit: int = 500,
    example_limit: int = 5,
    one_off_limit: int = 20,
    ensure_issues: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    normalized_generated_at = normalize_generated_at(generated_at)
    source, ledger_snapshot = _read_validated_rescue_ledger(ledger_path)
    source["summary_event_limit"] = recent_limit
    source["summary_truncated"] = int(source["event_count"]) > recent_limit
    fixtures = _rescue_fixtures()
    with tempfile.TemporaryDirectory(prefix="aragora-rescue-ledger-") as temp_dir:
        snapshot_path = Path(temp_dir) / "rescue_events.jsonl"
        snapshot_path.write_bytes(ledger_snapshot)
        initial_report = fixtures.load_rescue_productization_report(
            ledger_path=snapshot_path,
            threshold=threshold,
            recent_limit=recent_limit,
            example_limit=example_limit,
            one_off_limit=one_off_limit,
            productization_map_path=productization_map_path,
        )
        initial_issue_drafts = fixtures.build_issue_drafts(initial_report)

        issue_linkage_results: list[dict[str, Any]] = []
        if ensure_issues and initial_issue_drafts:
            issue_linkage_results = ensure_issue_linkage(
                issue_drafts=initial_issue_drafts,
                productization_map_path=productization_map_path,
                repo=repo,
                dry_run=dry_run,
            )

        final_report = fixtures.load_rescue_productization_report(
            ledger_path=snapshot_path,
            threshold=threshold,
            recent_limit=recent_limit,
            example_limit=example_limit,
            one_off_limit=one_off_limit,
            productization_map_path=productization_map_path,
        )
        final_issue_drafts = fixtures.build_issue_drafts(final_report)
    return {
        "ok": True,
        "generated_at": normalized_generated_at,
        "repo": repo,
        "ledger_path": _repo_stable_path(ledger_path),
        "source": source,
        "productization_map_path": _repo_stable_path(productization_map_path),
        "summary": final_report.get("summary") or {},
        "repeated_classes": final_report.get("repeated_classes") or [],
        "one_off_classes": final_report.get("one_off_classes") or [],
        "below_threshold_classes": final_report.get("below_threshold_classes") or [],
        "initial_issue_drafts": initial_issue_drafts,
        "issue_linkage_results": issue_linkage_results,
        "issue_drafts": final_issue_drafts,
    }


def build_unavailable_source_report(
    *,
    ledger_path: Path,
    productization_map_path: Path,
    repo: str,
    error: RescueLedgerValidationError,
    generated_at: str | None = None,
    recent_limit: int = 500,
) -> dict[str, Any]:
    """Build a truthful publication that makes unavailable input explicit."""
    return {
        "ok": False,
        "generated_at": normalize_generated_at(generated_at),
        "repo": repo,
        "ledger_path": _repo_stable_path(ledger_path),
        "source": {
            "status": "unavailable",
            "event_count": None,
            "sha256": None,
            "summary_event_limit": recent_limit,
            "summary_truncated": None,
            "error": error.to_dict(),
        },
        "productization_map_path": _repo_stable_path(productization_map_path),
        "summary": {},
        "repeated_classes": [],
        "one_off_classes": [],
        "below_threshold_classes": [],
        "initial_issue_drafts": [],
        "issue_linkage_results": [],
        "issue_drafts": [],
    }


def publish_report_bundle(
    *,
    publish_dir: Path,
    payload: dict[str, Any],
) -> dict[str, Path]:
    timestamped_path = write_json(
        resolve_published_report_path(
            publish_dir=publish_dir,
            generated_at=str(payload.get("generated_at") or ""),
        ),
        payload,
    )
    return {
        "timestamped": timestamped_path,
        "latest": write_json(resolve_latest_report_path(publish_dir=publish_dir), payload),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_RESCUE_LEDGER_PATH,
        help=f"Path to the RescueEvent ledger (default: {DEFAULT_RESCUE_LEDGER_PATH})",
    )
    parser.add_argument(
        "--productization-map",
        type=Path,
        default=DEFAULT_PRODUCTIZATION_MAP_PATH,
        help=f"Tracked rescue-productization map (default: {DEFAULT_PRODUCTIZATION_MAP_PATH})",
    )
    parser.add_argument(
        "--publish-dir",
        type=Path,
        default=DEFAULT_PUBLISH_DIR,
        help=f"Directory for latest/timestamped report JSON (default: {DEFAULT_PUBLISH_DIR})",
    )
    parser.add_argument("--repo", default="synaptent/aragora")
    parser.add_argument("--threshold", type=int, default=2)
    parser.add_argument("--recent-limit", type=int, default=500)
    parser.add_argument("--example-limit", type=int, default=5)
    parser.add_argument("--one-off-limit", type=int, default=20)
    parser.add_argument(
        "--ensure-issues",
        action="store_true",
        help="Create or relink bounded follow-on issues for unlinked repeated rescue classes.",
    )
    parser.add_argument(
        "--require-source",
        action="store_true",
        help="Exit 3 without publishing when the rescue ledger is unavailable or invalid.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = build_published_report(
            ledger_path=args.path,
            productization_map_path=args.productization_map,
            repo=str(args.repo),
            threshold=max(1, args.threshold),
            recent_limit=max(1, args.recent_limit),
            example_limit=max(1, args.example_limit),
            one_off_limit=max(0, args.one_off_limit),
            ensure_issues=bool(args.ensure_issues),
            dry_run=bool(args.dry_run),
        )
    except RescueLedgerValidationError as exc:
        print(f"error: [{exc.code}] {exc.detail}", file=sys.stderr)
        if args.require_source:
            error_payload = {"ok": False, "error": exc.to_dict()}
            print(json.dumps(error_payload, indent=2))
            return 3
        payload = build_unavailable_source_report(
            ledger_path=args.path,
            productization_map_path=args.productization_map,
            repo=str(args.repo),
            error=exc,
            recent_limit=max(1, args.recent_limit),
        )
    published = None
    if not args.dry_run:
        published = publish_report_bundle(
            publish_dir=args.publish_dir.resolve(),
            payload=payload,
        )
    if args.json:
        print(json.dumps(payload, indent=2))
    elif args.dry_run:
        print("dry-run: not published")
    else:
        if published is None:
            print("dry-run: report bundle not published")
        else:
            print(str(published["timestamped"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
