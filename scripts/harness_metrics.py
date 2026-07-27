#!/usr/bin/env python3
"""Build the read-only harness metrics scoreboard for long-run agents.

Definitions:
- ``first_round_gate_pass_rate`` is the share of records with an explicit
  first-round gate result whose value is pass/true.
- ``rounds_to_merge_average`` is the mean explicit round count for merged PR
  records; missing round data is reported as insufficient data.
- ``external_progress_per_cycle`` is the share of cycles with explicit
  external-progress observations that record externally-visible progress such
  as a push, merge, evidence post, or issue comment.
- ``token_cost_per_merged_pr`` divides explicit token/cost observations by the
  number of merged PRs for the lane.

The script never calls an LLM and never mutates inputs. Missing or ambiguous
fields are reported as insufficient data instead of being guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "harness_metrics.v1"
DEFAULT_LEDGER = ".aragora/conductor_cycles/long_run_ledger.jsonl"
DEFAULT_RECEIPT_DIR = ".aragora/review-queue/receipts"
DEFAULT_EVAL_FIXTURE = "tests/governance/fixtures/adjudicator_eval_cases.json"


@dataclass
class HarnessEvent:
    """Normalized cycle/receipt event used by the scoreboard."""

    source: str
    lane: str
    counts_as_cycle: bool = True
    timestamp: datetime | None = None
    external_progress: bool | None = None
    first_round_gate_pass: bool | None = None
    merged_pr: int | None = None
    rounds_to_merge: float | None = None
    token_cost: float | None = None
    token_cost_key: str | None = None


@dataclass
class LaneAccumulator:
    """Incrementally aggregates events for one lane."""

    lane: str
    cycles: int = 0
    external_progress_cycles: int = 0
    external_progress_observations: int = 0
    first_round_gate_passes: int = 0
    first_round_gate_observations: int = 0
    merged_prs: set[int] = field(default_factory=set)
    rounds_to_merge_prs: set[int] = field(default_factory=set)
    rounds_to_merge_values: list[float] = field(default_factory=list)
    token_cost_event_keys: set[str] = field(default_factory=set)
    token_cost_total: float = 0.0
    token_cost_observations: int = 0

    def add(self, event: HarnessEvent) -> None:
        if event.counts_as_cycle:
            self.cycles += 1
            if event.external_progress is not None:
                self.external_progress_observations += 1
                if event.external_progress:
                    self.external_progress_cycles += 1
        if event.first_round_gate_pass is not None:
            self.first_round_gate_observations += 1
            if event.first_round_gate_pass:
                self.first_round_gate_passes += 1
        if event.merged_pr is not None:
            self.merged_prs.add(event.merged_pr)
        if (
            event.merged_pr is not None
            and event.rounds_to_merge is not None
            and event.merged_pr not in self.rounds_to_merge_prs
        ):
            self.rounds_to_merge_values.append(event.rounds_to_merge)
            self.rounds_to_merge_prs.add(event.merged_pr)
        if event.token_cost is not None:
            if event.token_cost_key is not None:
                event_key = f"id:{event.token_cost_key}"
            elif event.merged_pr is not None:
                event_key = f"pr:{event.merged_pr}:cost:{event.token_cost}"
            else:
                event_time = _iso(event.timestamp) if event.timestamp is not None else ""
                event_key = f"time:{event_time}:cost:{event.token_cost}"
            if event_key not in self.token_cost_event_keys:
                self.token_cost_event_keys.add(event_key)
                self.token_cost_total += event.token_cost
                self.token_cost_observations += 1


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.endswith(("Z", "z")):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _get_path(mapping: dict[str, Any], path: str) -> Any:
    if path in mapping:
        return mapping[path]
    current: Any = mapping
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _first_present(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = _get_path(mapping, key)
        if value not in (None, ""):
            return value
    return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {
            "true",
            "yes",
            "y",
            "1",
            "pass",
            "passed",
            "success",
            "posted",
            "pushed",
            "merged",
        }:
            return True
        if normalized in {"false", "no", "n", "0", "fail", "failed", "blocked"}:
            return False
    return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_pr_number(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        candidate = value.strip()
        match = re.fullmatch(
            r"(?i)(?:pr|pull request)?\s*#?\s*(\d+)",
            candidate,
        )
        if match:
            pr_number = int(match.group(1))
            return pr_number if pr_number > 0 else None
    return None


def _read_json_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.is_dir():
        return []
    text = path.read_text(encoding="utf-8")

    def parse_jsonl_lines() -> list[dict[str, Any]]:
        records = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
        return records

    if path.suffix == ".jsonl":
        return parse_jsonl_lines()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return parse_jsonl_lines()
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        if isinstance(parsed.get("entries"), list):
            wrapper = {key: value for key, value in parsed.items() if key != "entries"}
            return [{**wrapper, **item} for item in parsed["entries"] if isinstance(item, dict)]
        if isinstance(parsed.get("records"), list):
            return [item for item in parsed["records"] if isinstance(item, dict)]
        if isinstance(parsed.get("cycles"), list):
            return [item for item in parsed["cycles"] if isinstance(item, dict)]
        return [parsed]
    return []


def _iter_receipt_records(receipt_dir: Path) -> list[dict[str, Any]]:
    if not receipt_dir.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            for record in _read_json_records(path):
                record = dict(record)
                record.setdefault("_source_path", str(path))
                records.append(record)
        except json.JSONDecodeError:
            continue
    return records


def _within_window(event_time: datetime | None, *, as_of: datetime, window_days: int) -> bool:
    if event_time is None:
        return False
    return as_of - timedelta(days=window_days) <= event_time <= as_of


def _lane_for(record: dict[str, Any], source_type: str) -> str:
    lane = _first_present(
        record,
        (
            "lane",
            "lane_id",
            "owner_lane",
            "owner_session",
            "worker",
            "agent",
            "branch",
        ),
    )
    if lane is None and source_type == "receipt":
        lane = "receipt_store"
    return str(lane or "unknown")


def _timestamp_for(record: dict[str, Any]) -> datetime | None:
    value = _first_present(
        record,
        (
            "timestamp",
            "ts",
            "generated_at",
            "created_at",
            "createdAt",
            "reviewed_at",
            "reviewedAt",
            "updated_at",
            "updatedAt",
            "mergedAt",
            "completed_at",
        ),
    )
    return parse_timestamp(value)


def _event_has_external_progress(record: dict[str, Any]) -> bool | None:
    explicit = _first_present(
        record,
        (
            "external_progress",
            "progress.external",
            "external_progress_cycle",
            "has_external_progress",
        ),
    )
    coerced = _coerce_bool(explicit)
    if coerced is not None:
        return coerced

    if _event_merged_pr(record) is not None:
        return True

    mutation_keys = (
        "mutations.push",
        "mutations.merge",
        "mutations.evidence_posted",
        "mutations.issue_comment",
        "mutations.github_status",
        "direct_pr_merged",
    )
    mutation_false_seen = False
    for key in mutation_keys:
        value = _first_present(record, (key,))
        if value is None:
            continue
        coerced_mutation = _coerce_bool(value)
        if coerced_mutation is True:
            return True
        if coerced_mutation is False:
            mutation_false_seen = True
            continue

    outcome_value = _first_present(record, ("outcome", "result", "status", "decision"))
    outcome = "" if outcome_value is None else str(outcome_value)
    if outcome:
        normalized = outcome.strip().lower()
        tokens = set(re.findall(r"[a-z0-9]+", normalized))
        negative_tokens = {
            "blocked",
            "cancelled",
            "canceled",
            "fail",
            "failed",
            "failure",
            "false",
            "0",
            "no",
            "not",
            "unmerged",
            "unsuccessful",
        }
        positive_tokens = {
            "complete",
            "completed",
            "merged",
            "posted",
            "pushed",
            "repaired",
            "success",
            "succeeded",
            "true",
            "1",
            "yes",
            "y",
        }
        if tokens & negative_tokens:
            return False
        if tokens & positive_tokens:
            return True

    if mutation_false_seen:
        return False

    return None


def _event_gate_pass(record: dict[str, Any]) -> bool | None:
    explicit = _first_present(
        record,
        (
            "first_round_gate_pass",
            "first_round_gate_passed",
            "gate.first_round_pass",
            "gate.first_round_passed",
        ),
    )
    coerced = _coerce_bool(explicit)
    if coerced is not None:
        return coerced

    round_value = _coerce_float(_first_present(record, ("gate_round", "round")))
    if round_value != 1:
        return None
    verdict = str(_first_present(record, ("verdict", "gate.verdict")) or "").lower()
    if verdict in {"admin_squash_allowed", "satisfied", "pass", "passed"}:
        return True
    if verdict in {"blocked", "repair_or_wait", "fail", "failed"}:
        return False
    return None


def _event_merged_pr(record: dict[str, Any]) -> int | None:
    action = str(_first_present(record, ("action", "event", "mutation")) or "").strip().lower()
    if action in {
        "admin_squash_merge",
        "squash_merge",
        "merge",
        "merged",
        "pr_merged",
    }:
        for fallback_key in ("pr_number", "pr", "target_pr"):
            pr_number = _coerce_pr_number(_first_present(record, (fallback_key,)))
            if pr_number is not None:
                return pr_number

    merge_keys = ("direct_pr_merged", "merged_pr", "pr_merged", "mutations.merged_pr")
    pr_reference_keys = ("pr_number", "pr", "target_pr")
    for key in merge_keys:
        value = _first_present(record, (key,))
        if value is None:
            continue
        pr_number = _coerce_pr_number(value)
        if pr_number is not None:
            return pr_number
        sentinel = _coerce_bool(value)
        if sentinel is not None:
            if not sentinel:
                continue
            for fallback_key in pr_reference_keys:
                pr_number = _coerce_pr_number(_first_present(record, (fallback_key,)))
                if pr_number is not None:
                    return pr_number
            continue
    return None


def _event_rounds_to_merge(record: dict[str, Any]) -> float | None:
    return _coerce_float(
        _first_present(
            record,
            (
                "rounds_to_merge",
                "review_rounds_to_merge",
                "review_rounds",
                "evidence_rounds",
                "rounds",
                "merge.rounds",
            ),
        )
    )


def _event_token_cost(record: dict[str, Any]) -> float | None:
    return _coerce_float(
        _first_present(
            record,
            (
                "token_cost",
                "tokens_cost",
                "cost_usd",
                "total_cost_usd",
                "usage.cost_usd",
                "token_usage.cost_usd",
                "token_usage.total_cost_usd",
                "cost_summary.total_cost_usd",
            ),
        )
    )


def _event_token_cost_key(record: dict[str, Any]) -> str | None:
    value = _first_present(
        record,
        (
            "event_id",
            "cycle_id",
            "run_id",
            "review_id",
            "receipt_id",
            "check_run_id",
            "job_id",
        ),
    )
    if value in (None, "") or isinstance(value, bool):
        return None
    return str(value)


def normalize_event(record: dict[str, Any], *, source: str, source_type: str) -> HarnessEvent:
    return HarnessEvent(
        source=source,
        lane=_lane_for(record, source_type),
        counts_as_cycle=source_type == "ledger",
        timestamp=_timestamp_for(record),
        external_progress=_event_has_external_progress(record),
        first_round_gate_pass=_event_gate_pass(record),
        merged_pr=_event_merged_pr(record),
        rounds_to_merge=_event_rounds_to_merge(record),
        token_cost=_event_token_cost(record),
        token_cost_key=_event_token_cost_key(record),
    )


def _load_eval_cases(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.is_dir():
        return []
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict) and isinstance(parsed.get("cases"), list):
        return [case for case in parsed["cases"] if isinstance(case, dict)]
    if isinstance(parsed, list):
        return [case for case in parsed if isinstance(case, dict)]
    return []


def _case_passed(case: dict[str, Any]) -> bool | None:
    for key in ("passed", "pass", "fixture_passed", "adjudicator_passed"):
        coerced = _coerce_bool(case.get(key))
        if coerced is not None:
            return coerced

    expected = case.get("expected_adjudicator_verdict")
    disposition = _get_path(case, "ground_truth.disposition")
    mapping = {
        "adjudicated_settle": "settle",
        "adjudicated_block": "block",
        "adjudicated_escalate": "escalate",
    }
    if expected in mapping and isinstance(disposition, str):
        return mapping[expected] == disposition
    return None


def fixture_performance(path: Path) -> dict[str, Any]:
    cases = _load_eval_cases(path)
    observations = [_case_passed(case) for case in cases]
    known = [passed for passed in observations if passed is not None]
    pass_rate = sum(1 for passed in known if passed) / len(known) if known else None
    return {
        "fixture_path": str(path),
        "available": path.exists(),
        "case_count": len(cases),
        "observed_case_count": len(known),
        "fixture_pass_rate": pass_rate,
    }


def lane_summary(
    accumulator: LaneAccumulator,
    *,
    fixture: dict[str, Any],
    drift_threshold: float,
) -> dict[str, Any]:
    merged_count = len(accumulator.merged_prs)
    first_round_rate = (
        accumulator.first_round_gate_passes / accumulator.first_round_gate_observations
        if accumulator.first_round_gate_observations
        else None
    )
    external_rate = (
        accumulator.external_progress_cycles / accumulator.external_progress_observations
        if accumulator.external_progress_observations
        else None
    )
    rounds_average = (
        sum(accumulator.rounds_to_merge_values) / len(accumulator.rounds_to_merge_values)
        if accumulator.rounds_to_merge_values
        else None
    )
    token_cost_per_merge = (
        accumulator.token_cost_total / merged_count
        if merged_count and accumulator.token_cost_observations
        else None
    )

    insufficient: list[str] = []
    if not accumulator.first_round_gate_observations:
        insufficient.append("first_round_gate_pass_rate")
    if not accumulator.external_progress_observations:
        insufficient.append("external_progress_per_cycle")
    if not merged_count:
        insufficient.append("rounds_to_merge_average:no_merged_prs")
        insufficient.append("token_cost_per_merged_pr:no_merged_prs")
    elif not accumulator.rounds_to_merge_values:
        insufficient.append("rounds_to_merge_average")
    if merged_count and not accumulator.token_cost_observations:
        insufficient.append("token_cost_per_merged_pr")

    fixture_rate = fixture.get("fixture_pass_rate")
    drift_delta = (
        abs(first_round_rate - fixture_rate)
        if first_round_rate is not None and fixture_rate is not None
        else None
    )
    drift_alarm = drift_delta is not None and drift_delta >= drift_threshold
    drift_check = {
        "fixture_pass_rate": fixture_rate,
        "live_first_round_gate_pass_rate": first_round_rate,
        "delta": drift_delta,
        "alarm": drift_alarm,
        "threshold": drift_threshold,
        "post_hoc_rereview_sampling_required": bool(drift_alarm),
        "note": (
            "Pair pass-rate gains with frozen-fixture performance before "
            "treating gate pass-rate improvements as quality improvements."
        ),
    }

    return {
        "lane": accumulator.lane,
        "cycles": accumulator.cycles,
        "external_progress_cycles": accumulator.external_progress_cycles,
        "external_progress_per_cycle": external_rate,
        "merged_prs": merged_count,
        "first_round_gate_pass_rate": first_round_rate,
        "rounds_to_merge_average": rounds_average,
        "token_cost_total": (
            accumulator.token_cost_total if accumulator.token_cost_observations else None
        ),
        "token_cost_per_merged_pr": token_cost_per_merge,
        "insufficient_data": insufficient,
        "drift_check": drift_check,
    }


def build_report(
    *,
    ledger_paths: list[Path],
    receipt_dirs: list[Path],
    eval_fixture: Path,
    as_of: datetime,
    window_days: int,
    drift_threshold: float = 0.25,
) -> dict[str, Any]:
    fixture = fixture_performance(eval_fixture)
    accumulators: dict[str, LaneAccumulator] = {}
    missing_sources: list[str] = []
    source_event_counts: dict[str, int] = {}

    def add_event(event: HarnessEvent) -> None:
        if not _within_window(event.timestamp, as_of=as_of, window_days=window_days):
            return
        accumulator = accumulators.setdefault(event.lane, LaneAccumulator(lane=event.lane))
        accumulator.add(event)

    for ledger in ledger_paths:
        if not ledger.exists():
            missing_sources.append(str(ledger))
            source_event_counts[str(ledger)] = 0
            continue
        records = _read_json_records(ledger)
        source_event_counts[str(ledger)] = len(records)
        for record in records:
            add_event(normalize_event(record, source=str(ledger), source_type="ledger"))

    for receipt_dir in receipt_dirs:
        if not receipt_dir.exists():
            missing_sources.append(str(receipt_dir))
            source_event_counts[str(receipt_dir)] = 0
            continue
        records = _iter_receipt_records(receipt_dir)
        source_event_counts[str(receipt_dir)] = len(records)
        for record in records:
            add_event(normalize_event(record, source=str(receipt_dir), source_type="receipt"))

    lanes = [
        lane_summary(
            accumulator,
            fixture=fixture,
            drift_threshold=drift_threshold,
        )
        for accumulator in sorted(accumulators.values(), key=lambda item: item.lane)
    ]

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso(_utc_now()),
        "window": {"days": window_days, "as_of": _iso(as_of)},
        "sources": {
            "ledgers": [str(path) for path in ledger_paths],
            "receipt_dirs": [str(path) for path in receipt_dirs],
            "eval_fixture": str(eval_fixture),
            "missing": missing_sources,
            "event_counts": source_event_counts,
        },
        "fixture_performance": fixture,
        "lanes": lanes,
    }


def _fmt_number(value: float | int | None, *, percent: bool = False) -> str:
    if value is None:
        return "insufficient"
    if percent:
        return f"{value:.0%}"
    if isinstance(value, int):
        return str(value)
    return f"{value:.2f}"


def _markdown_cell(value: Any) -> str:
    return str(value).replace("\n", " ").replace("|", "\\|")


def render_markdown(report: dict[str, Any]) -> str:
    """Render the scoreboard as a single Markdown table."""

    rows = [
        "| Lane | Cycles | External progress/cycle | First-round gate pass | "
        "Avg rounds to merge | Token cost/merged PR | Merged PRs | "
        "Drift alarm | Insufficient data |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for lane in report["lanes"]:
        insufficient = ", ".join(lane["insufficient_data"]) or "none"
        rows.append(
            "| {lane} | {cycles} | {external} | {pass_rate} | {rounds} | "
            "{cost} | {merged} | {alarm} | {insufficient} |".format(
                lane=_markdown_cell(lane["lane"]),
                cycles=lane["cycles"],
                external=_fmt_number(lane["external_progress_per_cycle"], percent=True),
                pass_rate=_fmt_number(lane["first_round_gate_pass_rate"], percent=True),
                rounds=_fmt_number(lane["rounds_to_merge_average"]),
                cost=_fmt_number(lane["token_cost_per_merged_pr"]),
                merged=lane["merged_prs"],
                alarm="yes" if lane["drift_check"]["alarm"] else "no",
                insufficient=_markdown_cell(insufficient),
            )
        )
    return "\n".join(rows) + "\n"


def _resolve_paths(repo_root: Path, values: list[str], default: str) -> list[Path]:
    raw_values = values or [default]
    paths = []
    for value in raw_values:
        path = Path(value)
        paths.append(path if path.is_absolute() else repo_root / path)
    return paths


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root.")
    parser.add_argument(
        "--ledger",
        action="append",
        default=[],
        help="JSON or JSONL conductor ledger path. May be repeated.",
    )
    parser.add_argument(
        "--receipt-dir",
        action="append",
        default=[],
        help="Receipt directory containing JSON files. May be repeated.",
    )
    parser.add_argument("--eval-fixture", default=DEFAULT_EVAL_FIXTURE)
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--drift-threshold", type=float, default=0.25)
    parser.add_argument("--json-out", default=None)
    parser.add_argument("--markdown-out", default=None)
    parser.add_argument(
        "--print-markdown",
        action="store_true",
        help="Print the Markdown table instead of the JSON report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    as_of = parse_timestamp(args.as_of) if args.as_of else _utc_now()
    if as_of is None:
        raise SystemExit("--as-of must be an ISO-8601 timestamp")

    report = build_report(
        ledger_paths=_resolve_paths(repo_root, args.ledger, DEFAULT_LEDGER),
        receipt_dirs=_resolve_paths(repo_root, args.receipt_dir, DEFAULT_RECEIPT_DIR),
        eval_fixture=_resolve_paths(repo_root, [args.eval_fixture], DEFAULT_EVAL_FIXTURE)[0],
        as_of=as_of,
        window_days=args.window_days,
        drift_threshold=args.drift_threshold,
    )
    json_text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    markdown_text = render_markdown(report)

    if args.json_out:
        json_out = Path(args.json_out)
        if not json_out.is_absolute():
            json_out = repo_root / json_out
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(json_text, encoding="utf-8")
    if args.markdown_out:
        markdown_out = Path(args.markdown_out)
        if not markdown_out.is_absolute():
            markdown_out = repo_root / markdown_out
        markdown_out.parent.mkdir(parents=True, exist_ok=True)
        markdown_out.write_text(markdown_text, encoding="utf-8")

    sys.stdout.write(markdown_text if args.print_markdown else json_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
