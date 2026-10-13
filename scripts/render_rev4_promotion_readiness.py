#!/usr/bin/env python3
"""Render H1-01 rev-4 benchmark promotion readiness from local boss metrics."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aragora.swarm.dispatch_evidence import issues_dispatched_via_pr  # noqa: E402
from aragora.utils.git_paths import git_common_repo_root, resolve_repo_fallback_path  # noqa: E402

DEFAULT_CORPUS_PATH = REPO_ROOT / "tests" / "benchmarks" / "corpus_rev4.json"
DEFAULT_METRICS_PATH = REPO_ROOT / ".aragora" / "overnight" / "boss_metrics.jsonl"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "status" / "H1_01_REV4_PROMOTION_READINESS.md"
DEFAULT_MIN_DISPATCHED = 15


def _repo_stable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _normalize_generated_at(value: str | None = None) -> str:
    if value:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        parsed = dt.datetime.now(dt.UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_metrics_path(candidate: Path) -> Path:
    return resolve_repo_fallback_path(
        candidate,
        repo_root=REPO_ROOT,
        common_root=git_common_repo_root(REPO_ROOT),
    )


def load_corpus(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Corpus at {path} must be a JSON object")
    issues = payload.get("issues")
    if not isinstance(issues, list) or not issues:
        raise ValueError(f"Corpus at {path} must contain a non-empty issues list")
    return payload


def load_metrics(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _issue_id(issue: dict[str, Any]) -> int:
    return int(issue.get("issue_id", 0) or 0)


def build_readiness(
    *,
    corpus: dict[str, Any],
    metrics_rows: list[dict[str, Any]],
    min_dispatched: int = DEFAULT_MIN_DISPATCHED,
    pr_records: list[dict[str, Any]] | None = None,
    pr_lookup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues = [
        dict(issue)
        for issue in corpus.get("issues", [])
        if isinstance(issue, dict) and _issue_id(issue) > 0
    ]
    issues.sort(key=_issue_id)
    issue_ids = {_issue_id(issue) for issue in issues}
    rows_by_issue: dict[int, list[dict[str, Any]]] = defaultdict(list)
    dispatch_rows_by_issue: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in metrics_rows:
        issue_number = row.get("issue_number")
        if isinstance(issue_number, int) and issue_number in issue_ids:
            rows_by_issue[issue_number].append(row)
            if str(row.get("worker_outcome") or "").strip():
                dispatch_rows_by_issue[issue_number].append(row)

    # Cross-reference GitHub PR state. A merged or open PR on the
    # boss-loop's deterministic branch pattern is dispatch evidence
    # even when the metrics ledger has no row for the issue (e.g. the
    # row pre-dates the ledger or was lost in rotation).
    pr_record_list = pr_records or []
    pr_evidence: dict[int, dict[str, Any]] = (
        issues_dispatched_via_pr(list(issue_ids), pr_records=pr_record_list) if pr_records else {}
    )
    pr_evidence_lookup = dict(pr_lookup or {})
    if not pr_evidence_lookup:
        pr_evidence_lookup["status"] = "checked" if pr_records is not None else "not_checked"
    pr_evidence_lookup.setdefault("record_count", len(pr_record_list))

    metrics_dispatched_set = set(dispatch_rows_by_issue)
    pr_dispatched_set = {n for n, verdict in pr_evidence.items() if bool(verdict.get("dispatched"))}
    advisory_dispatched_ids = sorted(metrics_dispatched_set | pr_dispatched_set)
    dispatched_ids = sorted(metrics_dispatched_set)
    missing_ids = sorted(issue_ids - metrics_dispatched_set)
    advisory_missing_ids = sorted(issue_ids - set(advisory_dispatched_ids))
    needed_for_minimum = max(int(min_dispatched) - len(dispatched_ids), 0)
    recommended_ids = missing_ids[: needed_for_minimum or min(10, len(missing_ids))]

    dispatch_source_by_issue: dict[int, str] = {}
    for issue_id in advisory_dispatched_ids:
        in_metrics = issue_id in metrics_dispatched_set
        in_pr = issue_id in pr_dispatched_set
        if in_metrics and in_pr:
            dispatch_source_by_issue[issue_id] = "metrics+pr"
        elif in_metrics:
            dispatch_source_by_issue[issue_id] = "metrics"
        else:
            dispatch_source_by_issue[issue_id] = "pr"

    pr_dispatched_only_ids = sorted(pr_dispatched_set - metrics_dispatched_set)

    class_totals = Counter(str(issue.get("execution_class") or "unknown") for issue in issues)
    class_dispatched: Counter[str] = Counter()
    latest_terminal_by_issue: dict[int, str] = {}
    for issue in issues:
        issue_number = _issue_id(issue)
        execution_class = str(issue.get("execution_class") or "unknown")
        if issue_number in metrics_dispatched_set:
            class_dispatched[execution_class] += 1
        rows = rows_by_issue.get(issue_number, [])
        latest_terminal = ""
        for row in rows:
            terminal_class = str(row.get("terminal_class") or "").strip()
            if terminal_class:
                latest_terminal = terminal_class
        if not latest_terminal and issue_number in pr_dispatched_set:
            verdict = pr_evidence.get(issue_number) or {}
            best_state = verdict.get("best_state")
            if best_state == "MERGED":
                latest_terminal = "deliverable_pr_merged"
            elif best_state == "OPEN":
                latest_terminal = "deliverable_pr_open"
        if latest_terminal:
            latest_terminal_by_issue[issue_number] = latest_terminal

    status = "promotion_ready" if needed_for_minimum == 0 else "needs_more_dispatch_evidence"
    if len(issues) < 30:
        status = "manifest_below_h1_floor"

    return {
        "status": status,
        "min_dispatched_for_first_slice": int(min_dispatched),
        "needed_for_minimum": needed_for_minimum,
        "corpus": {
            "corpus_id": str(corpus.get("corpus_id") or "").strip(),
            "revision": int(corpus.get("revision", 0) or 0),
            "status": str(corpus.get("status") or "").strip(),
            "recorded_on": str(corpus.get("recorded_on") or "").strip(),
            "issue_count": len(issues),
            "promotion_target": str(corpus.get("promotion_target") or "").strip(),
        },
        "dispatch": {
            "dispatched_issue_count": len(dispatched_ids),
            "missing_issue_count": len(missing_ids),
            "dispatched_issue_ids": dispatched_ids,
            "missing_issue_ids": missing_ids,
            "recommended_next_issue_ids": recommended_ids,
            "advisory_any_source_dispatched_issue_count": len(advisory_dispatched_ids),
            "advisory_any_source_missing_issue_count": len(advisory_missing_ids),
            "advisory_any_source_dispatched_issue_ids": advisory_dispatched_ids,
            "advisory_any_source_missing_issue_ids": advisory_missing_ids,
            "latest_terminal_by_issue": latest_terminal_by_issue,
            "dispatch_source_by_issue": dispatch_source_by_issue,
            "pr_dispatched_only_ids": pr_dispatched_only_ids,
            "pr_evidence_lookup": pr_evidence_lookup,
            "metrics_dispatched_only_ids": sorted(metrics_dispatched_set - pr_dispatched_set),
        },
        "execution_classes": {
            execution_class: {
                "total": class_totals[execution_class],
                "dispatched": class_dispatched[execution_class],
                "missing": class_totals[execution_class] - class_dispatched[execution_class],
            }
            for execution_class in sorted(class_totals)
        },
    }


def _format_issue_ids(issue_ids: list[int]) -> str:
    if not issue_ids:
        return "none"
    return ", ".join(f"`#{issue_id}`" for issue_id in issue_ids)


def _format_pr_lookup_status(pr_lookup: dict[str, Any]) -> str:
    status = str(pr_lookup.get("status") or "unknown").strip()
    reason = str(pr_lookup.get("reason") or "").strip()
    record_count = int(pr_lookup.get("record_count", 0) or 0)
    if status == "checked":
        return f"checked ({record_count} record(s))"
    if status == "provided":
        return f"provided ({record_count} record(s))"
    if status == "not_checked":
        return f"not checked{f' ({reason})' if reason else ''}"
    if status == "unavailable":
        return f"unavailable{f' ({reason})' if reason else ''}"
    return status or "unknown"


def _format_pr_dispatched_only_value(dispatch: dict[str, Any]) -> str:
    pr_dispatched_only_ids = list(dispatch.get("pr_dispatched_only_ids") or [])
    pr_lookup = dict(dispatch.get("pr_evidence_lookup") or {})
    status = str(pr_lookup.get("status") or "").strip()
    if not pr_dispatched_only_ids and status in {"not_checked", "unavailable"}:
        return _format_pr_lookup_status(pr_lookup)
    return str(len(pr_dispatched_only_ids))


def render_markdown(
    *,
    readiness: dict[str, Any],
    corpus_path: Path,
    metrics_path: Path,
    metrics_display_path: Path | None = None,
    generated_at: str,
) -> str:
    corpus = dict(readiness.get("corpus") or {})
    dispatch = dict(readiness.get("dispatch") or {})
    classes = dict(readiness.get("execution_classes") or {})
    status = str(readiness.get("status") or "unknown")
    pr_lookup = dict(dispatch.get("pr_evidence_lookup") or {})
    needed = int(readiness.get("needed_for_minimum", 0) or 0)
    min_dispatched = int(readiness.get("min_dispatched_for_first_slice", 0) or 0)
    verdict = (
        "Ready to promote the first canonical rev-4 slice."
        if status == "promotion_ready"
        else f"Not ready: needs {needed} more metrics-backed dispatched issue(s) to reach the {min_dispatched}-issue promotion floor."
    )

    lines = [
        "# H1-01 Rev-4 Promotion Readiness",
        "",
        f"Last updated: {generated_at}",
        "",
        "This is the operator-facing readiness surface for promoting the staged rev-4 benchmark corpus into the canonical B0 truth loop.",
        "",
        "## Verdict",
        "",
        f"- Status: `{status}`",
        f"- Decision: {verdict}",
        f"- Staging corpus: `{_repo_stable_path(corpus_path)}`",
        f"- Metrics source: `{_repo_stable_path(metrics_display_path or metrics_path)}`",
        f"- Promotion target: `{corpus.get('promotion_target') or 'n/a'}`",
        "",
        "## Corpus",
        "",
        f"- Corpus id: `{corpus.get('corpus_id') or 'n/a'}`",
        f"- Revision: `{corpus.get('revision') or 'n/a'}`",
        f"- Manifest status: `{corpus.get('status') or 'n/a'}`",
        f"- Recorded on: `{corpus.get('recorded_on') or 'n/a'}`",
        f"- Total staged issues: `{corpus.get('issue_count') or 0}`",
        "",
        "## Dispatch Evidence",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Dispatch floor for first canonical slice | {min_dispatched} |",
        f"| Metrics-backed staged issues eligible for canonical promotion | {dispatch.get('dispatched_issue_count') or 0} |",
        f"| Staged issues still missing metrics-backed evidence | {dispatch.get('missing_issue_count') or 0} |",
        f"| Additional metrics-backed dispatches needed | {needed} |",
        f"| Advisory dispatch evidence from any source | {dispatch.get('advisory_any_source_dispatched_issue_count') or 0} |",
        f"| ...via metrics ledger only | {len(list(dispatch.get('metrics_dispatched_only_ids') or []))} |",
        f"| ...via merged/open boss-harvest PR only (advisory) | {_format_pr_dispatched_only_value(dispatch)} |",
        f"| Boss-harvest PR evidence lookup | {_format_pr_lookup_status(pr_lookup)} |",
        "",
        "## Next Metrics Evidence Gaps",
        "",
        _format_issue_ids(list(dispatch.get("recommended_next_issue_ids") or [])),
        "",
        "These are the earliest staged issues missing metrics-backed `worker_outcome` rows; verify live issue state before dispatching new work.",
        "",
        "## Execution-Class Coverage",
        "",
        "| Execution class | Dispatched | Total | Missing |",
        "| --- | ---: | ---: | ---: |",
    ]
    for execution_class, values in classes.items():
        value_map = dict(values)
        lines.append(
            f"| `{execution_class}` | {int(value_map.get('dispatched', 0) or 0)} | "
            f"{int(value_map.get('total', 0) or 0)} | {int(value_map.get('missing', 0) or 0)} |"
        )

    lines.extend(
        [
            "",
            "## Dispatched Issues",
            "",
            _format_issue_ids(list(dispatch.get("dispatched_issue_ids") or [])),
            "",
            "## Missing Evidence",
            "",
            _format_issue_ids(list(dispatch.get("missing_issue_ids") or [])),
            "",
            "## Promotion Rule",
            "",
            "Promote only a first canonical rev-4 slice after at least 15 staged entries have metrics-backed dispatch evidence: at least one `boss_metrics.jsonl` row for the issue with a recorded `worker_outcome`. Merged or open boss-harvest PRs are useful advisory evidence, but they are not sufficient for canonical corpus promotion because `tests/benchmarks/test_corpus_freshness.py` requires metrics-backed dispatch history for every `in_progress` entry.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_pr_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _coerce_issue_ids(issue_ids: Iterable[int]) -> list[int]:
    coerced: set[int] = set()
    for raw_issue_id in issue_ids or []:
        try:
            issue_id = int(raw_issue_id)
        except (TypeError, ValueError):
            continue
        if issue_id > 0:
            coerced.add(issue_id)
    return sorted(coerced)


def _gh_failure_lookup(
    reason: str,
    error: str = "",
    *,
    record_count: int = 0,
) -> dict[str, Any]:
    lookup: dict[str, Any] = {
        "status": "unavailable",
        "reason": reason,
        "record_count": int(record_count),
    }
    if error:
        lookup["error"] = error[:500]
    return lookup


def fetch_boss_harvest_pr_records_with_status(
    issue_ids: Iterable[int],
    *,
    repo: str | None = None,
    per_issue_limit: int = 10,
    timeout_seconds: int = 15,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_prs: set[int] = set()
    issue_id_list = _coerce_issue_ids(issue_ids)
    for issue_id in issue_id_list:
        cmd = [
            "gh",
            "pr",
            "list",
            "--state",
            "all",
            "--limit",
            str(max(int(per_issue_limit), 1)),
            "--search",
            f"head:aragora/boss-harvest/issue-{issue_id}",
            "--json",
            "number,state,headRefName",
        ]
        if repo:
            cmd.extend(["--repo", repo])
        try:
            proc = subprocess.run(
                cmd,
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return records, _gh_failure_lookup("gh_timeout", record_count=len(records))
        except OSError as exc:
            return records, _gh_failure_lookup(
                "gh_unavailable",
                str(exc),
                record_count=len(records),
            )
        if proc.returncode != 0:
            return records, _gh_failure_lookup(
                "gh_failed",
                (proc.stderr or proc.stdout or "").strip(),
                record_count=len(records),
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return records, _gh_failure_lookup(
                "gh_invalid_json",
                proc.stdout,
                record_count=len(records),
            )
        if not isinstance(payload, list):
            return records, _gh_failure_lookup(
                "gh_invalid_json",
                proc.stdout,
                record_count=len(records),
            )
        for item in payload:
            if not isinstance(item, dict):
                continue
            number = item.get("number")
            if isinstance(number, int):
                if number in seen_prs:
                    continue
                seen_prs.add(number)
            records.append(item)
    return records, {
        "status": "checked",
        "reason": "gh",
        "record_count": len(records),
        "issue_lookup_count": len(issue_id_list),
    }


def fetch_boss_harvest_pr_records(
    issue_ids: Iterable[int],
    *,
    repo: str | None = None,
    per_issue_limit: int = 10,
    timeout_seconds: int = 15,
) -> list[dict[str, Any]]:
    records, _lookup = fetch_boss_harvest_pr_records_with_status(
        issue_ids,
        repo=repo,
        per_issue_limit=per_issue_limit,
        timeout_seconds=timeout_seconds,
    )
    return records


def _corpus_issue_ids(corpus: dict[str, Any]) -> list[int]:
    return [
        _issue_id(issue)
        for issue in corpus.get("issues", [])
        if isinstance(issue, dict) and _issue_id(issue) > 0
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS_PATH)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-dispatched", type=int, default=DEFAULT_MIN_DISPATCHED)
    parser.add_argument("--generated-at", help=argparse.SUPPRESS)
    parser.add_argument(
        "--pr-records",
        type=Path,
        default=None,
        help=(
            "Optional path to a JSON file with `gh pr list "
            "--json number,state,headRefName` output. When provided, "
            "merged/open PRs on the boss-harvest branch pattern count "
            "as dispatch evidence in addition to boss_metrics rows."
        ),
    )
    parser.add_argument(
        "--no-gh-pr-records",
        action="store_true",
        help=(
            "Disable the default non-fatal gh lookup for boss-harvest PR evidence "
            "when --pr-records is omitted."
        ),
    )
    parser.add_argument(
        "--gh-repo",
        default=None,
        help="Optional owner/repo passed to gh when auto-loading boss-harvest PR evidence.",
    )
    parser.add_argument(
        "--gh-per-issue-limit",
        type=int,
        default=10,
        help="Maximum PR records to fetch per staged issue during the default gh lookup.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit readiness JSON instead of Markdown"
    )
    parser.add_argument(
        "--fail-not-ready",
        action="store_true",
        help="Exit non-zero when the promotion floor has not been met",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    corpus_path = args.corpus.resolve()
    metrics_path = resolve_metrics_path(args.metrics)
    corpus = load_corpus(corpus_path)
    pr_records: list[dict[str, Any]] | None
    if args.pr_records is not None:
        pr_records = _load_pr_records(args.pr_records)
        pr_lookup = {
            "status": "provided",
            "reason": _repo_stable_path(args.pr_records),
            "record_count": len(pr_records),
        }
    elif args.no_gh_pr_records:
        pr_records = None
        pr_lookup = {
            "status": "not_checked",
            "reason": "--no-gh-pr-records",
            "record_count": 0,
        }
    else:
        pr_records, pr_lookup = fetch_boss_harvest_pr_records_with_status(
            _corpus_issue_ids(corpus),
            repo=args.gh_repo,
            per_issue_limit=args.gh_per_issue_limit,
        )
    readiness = build_readiness(
        corpus=corpus,
        metrics_rows=load_metrics(metrics_path),
        min_dispatched=args.min_dispatched,
        pr_records=pr_records,
        pr_lookup=pr_lookup,
    )
    generated_at = _normalize_generated_at(args.generated_at)

    if args.json:
        print(json.dumps(readiness, indent=2, sort_keys=True))
    else:
        markdown = render_markdown(
            readiness=readiness,
            corpus_path=corpus_path,
            metrics_path=metrics_path,
            metrics_display_path=args.metrics,
            generated_at=generated_at,
        )
        output_path = args.output.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        print(str(output_path))

    if args.fail_not_ready and readiness.get("status") != "promotion_ready":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
