#!/usr/bin/env python3
"""Build the fixed harness-improvement scoreboard from local evidence.

Metric definitions are intentionally narrow so the harness cannot redefine its
own utility while optimizing against this script:

* first-round gate pass rate: count of explicit first-review PASS observations
  divided by all explicit first-review PASS/FAIL observations;
* rounds to merge: mean highest explicit review round for merged PRs, reported
  only when every merged PR in the group has a round observation;
* external progress per cycle: explicit ``external_progress=true`` cycles
  divided by cycles with an explicit boolean progress observation;
* token cost per merged PR: sum of the highest explicit cumulative token-cost
  observation for each merged PR divided by merged PR count, reported only with
  complete merged-PR cost coverage.

Records are grouped independently by conductor lane, fleet, and agent type.
Missing dimensions are retained as ``unknown``. Conflicting duplicate
observations become insufficient data instead of being guessed. Inputs are
read-only and deterministic; optional GitHub metadata is obtained only through
``gh``. The JSON report is the stable machine interface and Markdown is the
operator view.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "aragora.harness-metrics.v1"
DIMENSIONS = ("conductor_lane", "fleet", "agent_type")
GH_METADATA_SEARCH_LIMIT = 1_000


@dataclass(frozen=True)
class Event:
    timestamp: datetime
    conductor_lane: str
    fleet: str
    agent_type: str
    cycle_key: str
    pr_number: int | None
    external_progress: bool | None
    first_round_gate_pass: bool | None
    review_round: int | None
    merged: bool
    token_cost_total: float | None


def _nested(record: dict[str, Any], path: str) -> Any:
    value: Any = record
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _first(record: dict[str, Any], *paths: str) -> Any:
    for path in paths:
        value = _nested(record, path)
        if value not in (None, ""):
            return value
    return None


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "pass", "passed", "success"}:
            return True
        if normalized in {"false", "fail", "failed", "changes-requested"}:
            return False
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _pr_number(record: dict[str, Any]) -> int | None:
    value = _first(record, "pr_number", "pr", "target_pr", "direct_pr_merged", "number")
    if isinstance(value, dict):
        value = value.get("number") or value.get("pr")
    if isinstance(value, str):
        value = value.removeprefix("#")
    return _positive_int(value)


def _timestamp(record: dict[str, Any]) -> datetime | None:
    value = _first(
        record,
        "timestamp",
        "ts",
        "generated_at",
        "created_at",
        "reviewed_at",
        "outcome_observed_at",
        "mergedAt",
        "merged_at",
    )
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _stable_key(record: dict[str, Any], source: str) -> str:
    explicit = _first(record, "cycle_id", "cycle", "receipt_id", "event_id", "id")
    if explicit is not None:
        return f"explicit:{explicit}"
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"), default=str).encode()
    return f"{source}:{hashlib.sha256(encoded).hexdigest()}"


def _merged(record: dict[str, Any]) -> bool:
    explicit = _bool(_first(record, "merged", "merged_improvement"))
    if explicit is not None:
        return explicit
    return bool(
        _positive_int(record.get("direct_pr_merged"))
        or str(record.get("result", "")).lower() == "merged"
        or str(_nested(record, "mutation.merge")).lower()
        in {"protected_squash", "normal_squash", "squash"}
        or _first(record, "mergedAt", "merged_at")
    )


def _first_round_result(record: dict[str, Any], review_round: int | None) -> bool | None:
    direct = _bool(_first(record, "first_round_gate_pass", "gate.first_round_pass"))
    if direct is not None:
        return direct
    if review_round != 1:
        return None
    return _bool(_first(record, "gate_passed", "checks_passed", "verdict"))


def _token_total(record: dict[str, Any]) -> float | None:
    value = _first(
        record,
        "token_cost_total",
        "total_cost_usd",
        "token_usage.total_cost_usd",
        "cost.total_usd",
    )
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def normalize_event(record: dict[str, Any], source: str) -> Event | None:
    timestamp = _timestamp(record)
    if timestamp is None:
        return None
    review_round = _positive_int(_first(record, "review_round", "round", "round_number"))
    lane = _first(record, "lane_id", "owner.lane_id", "headRefName", "head_ref_name")
    fleet = _first(record, "fleet", "source", "owner.source")
    agent_type = _first(record, "agent_type", "agent", "owner.agent", "author.login")
    direct_merged_pr = _positive_int(record.get("direct_pr_merged"))
    return Event(
        timestamp=timestamp,
        conductor_lane=str(lane or "unknown"),
        fleet=str(fleet or "unknown"),
        agent_type=str(agent_type or "unknown"),
        cycle_key=_stable_key(record, source),
        pr_number=direct_merged_pr or _pr_number(record),
        external_progress=_bool(record.get("external_progress")),
        first_round_gate_pass=_first_round_result(record, review_round),
        review_round=review_round,
        merged=_merged(record),
        token_cost_total=_token_total(record),
    )


def _read_records(path: Path, warnings: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        warnings.append(f"missing source: {path}")
        return []
    records: list[dict[str, Any]] = []
    try:
        if path.suffix == ".jsonl":
            with path.open(encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, 1):
                    if not line.strip():
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        warnings.append(f"invalid JSONL: {path}:{line_number}")
                        continue
                    if isinstance(value, dict):
                        records.append(value)
            return records
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"unreadable source: {path}: {exc.__class__.__name__}")
        return []
    if isinstance(value, dict):
        records.extend(
            value.get("records", [value]) if isinstance(value.get("records"), list) else [value]
        )
    elif isinstance(value, list):
        records.extend(item for item in value if isinstance(item, dict))
    else:
        warnings.append(f"unsupported JSON root: {path}")
    return records


def load_local_records(
    ledgers: Iterable[Path], receipt_dirs: Iterable[Path], warnings: list[str]
) -> list[tuple[dict[str, Any], str]]:
    loaded: list[tuple[dict[str, Any], str]] = []
    for path in ledgers:
        loaded.extend((record, str(path)) for record in _read_records(path, warnings))
    for directory in receipt_dirs:
        if not directory.exists():
            warnings.append(f"missing receipt directory: {directory}")
            continue
        for path in sorted(directory.rglob("*.json")):
            loaded.extend((record, str(path)) for record in _read_records(path, warnings))
    return loaded


def load_gh_metadata(repo: str, since: datetime, warnings: list[str]) -> list[dict[str, Any]]:
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--limit",
        str(GH_METADATA_SEARCH_LIMIT),
        "--search",
        f"merged:>={since.date().isoformat()}",
        "--json",
        "number,mergedAt,headRefName,author",
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        warnings.append(f"gh metadata unavailable: {exc.__class__.__name__}")
        return []
    if result.returncode:
        warnings.append(f"gh metadata unavailable: exit {result.returncode}")
        return []
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        warnings.append("gh metadata unavailable: invalid JSON")
        return []
    records = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    if len(records) >= GH_METADATA_SEARCH_LIMIT:
        warnings.append(
            "gh metadata may be truncated: "
            f"GitHub search returned its {GH_METADATA_SEARCH_LIMIT}-result ceiling"
        )
    return records


def _resolved_observations(pairs: Iterable[tuple[str, bool | None]]) -> list[bool]:
    by_key: dict[str, set[bool]] = {}
    for key, value in pairs:
        if value is not None:
            by_key.setdefault(key, set()).add(value)
    return [next(iter(values)) for values in by_key.values() if len(values) == 1]


def summarize_group(events: list[Event], key: str) -> dict[str, Any]:
    progress = _resolved_observations(
        (event.cycle_key, event.external_progress) for event in events
    )
    first_round = _resolved_observations(
        (
            f"pr:{event.pr_number}" if event.pr_number else event.cycle_key,
            event.first_round_gate_pass,
        )
        for event in events
    )
    merged_prs = {
        event.pr_number for event in events if event.merged and event.pr_number is not None
    }
    rounds: dict[int, int] = {}
    costs: dict[int, float] = {}
    for event in events:
        if event.pr_number not in merged_prs:
            continue
        if event.review_round is not None:
            rounds[event.pr_number] = max(rounds.get(event.pr_number, 0), event.review_round)
        if event.token_cost_total is not None:
            costs[event.pr_number] = max(costs.get(event.pr_number, 0.0), event.token_cost_total)

    insufficient: list[str] = []
    if not progress:
        insufficient.append("external_progress_per_cycle")
    if not first_round:
        insufficient.append("first_round_gate_pass_rate")
    if not merged_prs:
        insufficient.extend(
            ["rounds_to_merge:no_merged_prs", "token_cost_per_merged_pr:no_merged_prs"]
        )
    elif set(rounds) != merged_prs:
        insufficient.append("rounds_to_merge:incomplete_coverage")
    if merged_prs and set(costs) != merged_prs:
        insufficient.append("token_cost_per_merged_pr:incomplete_coverage")

    return {
        "key": key,
        "event_count": len(events),
        "external_progress_observations": len(progress),
        "external_progress_per_cycle": sum(progress) / len(progress) if progress else None,
        "first_round_observations": len(first_round),
        "first_round_gate_pass_rate": sum(first_round) / len(first_round) if first_round else None,
        "merged_pr_count": len(merged_prs),
        "rounds_to_merge_average": (
            sum(rounds.values()) / len(merged_prs)
            if merged_prs and set(rounds) == merged_prs
            else None
        ),
        "token_cost_per_merged_pr": (
            sum(costs.values()) / len(merged_prs)
            if merged_prs and set(costs) == merged_prs
            else None
        ),
        "insufficient_data": insufficient,
    }


def _overall_first_round(events: list[Event]) -> float | None:
    observations = _resolved_observations(
        (
            f"pr:{event.pr_number}" if event.pr_number else event.cycle_key,
            event.first_round_gate_pass,
        )
        for event in events
    )
    return sum(observations) / len(observations) if observations else None


def _fixture_rate(path: Path | None, warnings: list[str]) -> float | None:
    if path is None:
        return None
    records = _read_records(path, warnings)
    outcomes = [_bool(_first(record, "passed", "pass", "verdict")) for record in records]
    known = [outcome for outcome in outcomes if outcome is not None]
    return sum(known) / len(known) if known else None


def build_report(
    events: list[Event],
    *,
    as_of: datetime,
    window_days: int,
    fixture_rate: float | None,
    drift_threshold: float,
    warnings: list[str],
    sources: list[str],
) -> dict[str, Any]:
    dimensions: dict[str, list[dict[str, Any]]] = {}
    for dimension in DIMENSIONS:
        groups: dict[str, list[Event]] = {}
        for event in events:
            groups.setdefault(getattr(event, dimension), []).append(event)
        dimensions[dimension] = [summarize_group(groups[key], key) for key in sorted(groups)]

    live_rate = _overall_first_round(events)
    if live_rate is None or fixture_rate is None:
        drift = {
            "status": "insufficient_data",
            "live_rate": live_rate,
            "fixture_rate": fixture_rate,
        }
    else:
        delta = live_rate - fixture_rate
        drift = {
            "status": "alarm" if abs(delta) >= drift_threshold else "ok",
            "live_rate": live_rate,
            "fixture_rate": fixture_rate,
            "delta": delta,
            "threshold": drift_threshold,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": as_of.isoformat().replace("+00:00", "Z"),
        "window": {
            "days": window_days,
            "start": (as_of - timedelta(days=window_days)).isoformat().replace("+00:00", "Z"),
            "end": as_of.isoformat().replace("+00:00", "Z"),
        },
        "sources": sorted(set(sources)),
        "warnings": sorted(set(warnings)),
        "judge_drift": drift,
        "dimensions": dimensions,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "| Dimension | Group | First-round pass | Rounds to merge | External progress | Token cost / merge | Insufficient data |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for dimension in DIMENSIONS:
        for row in report["dimensions"][dimension]:

            def fmt(value: Any, percent: bool = False) -> str:
                if value is None:
                    return "insufficient"
                return f"{value:.1%}" if percent else f"{value:.2f}"

            lines.append(
                f"| {dimension} | {row['key']} | "
                f"{fmt(row['first_round_gate_pass_rate'], True)} | "
                f"{fmt(row['rounds_to_merge_average'])} | "
                f"{fmt(row['external_progress_per_cycle'], True)} | "
                f"{fmt(row['token_cost_per_merged_pr'])} | "
                f"{', '.join(row['insufficient_data']) or '-'} |"
            )
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--repo", default="synaptent/aragora")
    parser.add_argument("--ledger", action="append", type=Path)
    parser.add_argument("--receipt-dir", action="append", type=Path)
    parser.add_argument("--pr-metadata", type=Path, help="Offline JSON replacement for gh metadata")
    parser.add_argument("--eval-results", type=Path, help="Frozen adjudicator result records")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--as-of", help="UTC ISO-8601 window end for reproducible runs")
    parser.add_argument("--drift-threshold", type=float, default=0.15)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--markdown-out", type=Path)
    parser.add_argument("--skip-gh", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.window_days <= 0 or not 0 <= args.drift_threshold <= 1:
        raise SystemExit("window-days must be positive and drift-threshold must be between 0 and 1")
    as_of = (
        datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
        if args.as_of
        else datetime.now(UTC)
    )
    as_of = as_of.replace(tzinfo=UTC) if as_of.tzinfo is None else as_of.astimezone(UTC)
    root = args.repo_root.resolve()
    ledgers = args.ledger or [root / ".aragora/conductor_cycles/long_run_ledger.jsonl"]
    receipt_dirs = args.receipt_dir or [root / ".aragora/review-queue/receipts"]
    warnings: list[str] = []
    records = load_local_records(ledgers, receipt_dirs, warnings)
    if args.pr_metadata:
        metadata = _read_records(args.pr_metadata, warnings)
        records.extend((record, str(args.pr_metadata)) for record in metadata)
    elif not args.skip_gh:
        metadata = load_gh_metadata(args.repo, as_of - timedelta(days=args.window_days), warnings)
        records.extend((record, "gh:merged-prs") for record in metadata)
    else:
        warnings.append("gh metadata skipped")

    start = as_of - timedelta(days=args.window_days)
    events: list[Event] = []
    seen: set[Event] = set()
    missing_timestamps: dict[str, int] = {}
    for record, source in records:
        event = normalize_event(record, source)
        if event is None:
            missing_timestamps[source] = missing_timestamps.get(source, 0) + 1
            continue
        if not start <= event.timestamp <= as_of or event in seen:
            continue
        seen.add(event)
        events.append(event)
    warnings.extend(
        f"records missing valid timestamp: {source}: {count}"
        for source, count in sorted(missing_timestamps.items())
    )
    report = build_report(
        events,
        as_of=as_of,
        window_days=args.window_days,
        fixture_rate=_fixture_rate(args.eval_results, warnings),
        drift_threshold=args.drift_threshold,
        warnings=warnings,
        sources=[source for _, source in records],
    )
    json_out = args.json_out or root / ".aragora/harness_metrics/latest.json"
    atomic_write(json_out, json.dumps(report, indent=2, sort_keys=True) + "\n")
    markdown = render_markdown(report)
    if args.markdown_out:
        atomic_write(args.markdown_out, markdown)
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
