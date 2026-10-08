#!/usr/bin/env python3
"""Render a report-only live dashboard for the July decision-integrity proof."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_REPO = "synaptent/aragora"
SOURCE_ARTIFACT = "docs/artifacts/2026-07-decision-integrity-dogfooding.md"
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "docs"
    / "status"
    / "generated"
    / "decision_integrity_dogfood_dashboard"
    / "latest.md"
)
DEFAULT_JSON_OUTPUT = DEFAULT_OUTPUT.with_suffix(".json")
SETTLEMENT_RECEIPT_BRANCH = "elves/close-the-loop-20260701"
SETTLEMENT_RECEIPT_PATHS = (
    "docs/elves/receipts/b3-8767-settlement.json",
    "docs/elves/receipts/b4-8768-settlement.json",
    "docs/elves/receipts/b6-cleanup-batch1.json",
)
DEFAULT_LOCAL_MERGE_RECEIPT_ROOTS = (
    REPO_ROOT / ".aragora" / "merge_executor" / "receipts",
    Path.home() / ".aragora" / "merge-executor-receipts",
)

CommandRunner = Callable[[Sequence[str], int], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class SearchSpec:
    metric_id: str
    label: str
    query: str
    caveat: str


@dataclass
class DashboardMetric:
    metric_id: str
    label: str
    value: str
    status: str
    last_updated_at: str
    source_query: str
    command: str
    stale_after_hours: int
    failure_behavior: str
    caveat: str = ""
    error: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_utc_timestamp(value: str) -> dt.datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = dt.datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _iso_z(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _default_window(now: dt.datetime) -> tuple[str, str]:
    end = now.astimezone(dt.timezone.utc).date()
    start = end - dt.timedelta(days=30)
    return start.isoformat(), end.isoformat()


def _repo_stable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        pass
    home = Path.home().resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return str(resolved)


def _run_command(args: Sequence[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _search_specs(*, repo: str, window_start: str, window_end: str) -> list[SearchSpec]:
    base = f"repo:{repo} is:pr is:merged merged:{window_start}..{window_end}"
    search_caveat = (
        "GitHub Search API total_count is a live search-index marker count, not a "
        "hand-audited exact truth set."
    )
    return [
        SearchSpec(
            metric_id="merged_prs",
            label="Merged PRs",
            query=base,
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="independent_model_review_comments",
            label='Merged PRs with "independent model review" comments',
            query=f'{base} "independent model review" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="verdict_pass_comments",
            label='Merged PRs with "Verdict: PASS" comments',
            query=f'{base} "Verdict: PASS" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="merge_quorum_comments",
            label='Merged PRs mentioning "merge-quorum"',
            query=f'{base} "merge-quorum" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="changes_requested_comments",
            label='Merged PRs with "CHANGES-REQUESTED" comments',
            query=f'{base} "CHANGES-REQUESTED" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="p0_dissent_comments",
            label="Merged PRs with [P0] comment markers",
            query=f'{base} "[P0]" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="p1_dissent_comments",
            label="Merged PRs with [P1] comment markers",
            query=f'{base} "[P1]" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="p2_dissent_comments",
            label="Merged PRs with [P2] comment markers",
            query=f'{base} "[P2]" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="p3_dissent_comments",
            label="Merged PRs with [P3] comment markers",
            query=f'{base} "[P3]" in:comments',
            caveat=search_caveat,
        ),
        SearchSpec(
            metric_id="exact_head_marker_comments",
            label='Merged PRs with "exact-head" comment markers',
            query=f'{base} "exact-head" in:comments',
            caveat=(
                f"{search_caveat} This is a phrase marker only; it does not prove the "
                "comment SHA matched the PR head."
            ),
        ),
    ]


def _github_search_command(query: str) -> list[str]:
    return ["gh", "api", "-X", "GET", "search/issues", "-f", f"q={query}", "--jq", ".total_count"]


def _apply_staleness(metric: DashboardMetric, *, now: dt.datetime) -> DashboardMetric:
    if not metric.last_updated_at or metric.status in {"failed", "missing"}:
        return metric
    try:
        updated = _parse_utc_timestamp(metric.last_updated_at)
    except ValueError:
        return metric
    age_hours = (now - updated).total_seconds() / 3600
    if age_hours <= metric.stale_after_hours:
        return metric
    metric.status = "stale"
    stale_note = (
        f"Last update is {age_hours:.1f}h old, exceeding the "
        f"{metric.stale_after_hours}h freshness SLA."
    )
    metric.caveat = f"{metric.caveat} {stale_note}".strip()
    return metric


def collect_github_search_metrics(
    *,
    repo: str,
    window_start: str,
    window_end: str,
    now: dt.datetime,
    runner: CommandRunner = _run_command,
    stale_after_hours: int = 24,
) -> list[DashboardMetric]:
    metrics: list[DashboardMetric] = []
    for spec in _search_specs(repo=repo, window_start=window_start, window_end=window_end):
        command = _github_search_command(spec.query)
        proc = runner(command, 120)
        command_text = " ".join(command)
        if proc.returncode != 0:
            metric = DashboardMetric(
                metric_id=spec.metric_id,
                label=spec.label,
                value="n/a",
                status="failed",
                last_updated_at="",
                source_query=spec.query,
                command=command_text,
                stale_after_hours=stale_after_hours,
                failure_behavior="Mark this metric failed; do not carry forward an older count.",
                caveat=spec.caveat,
                error=(proc.stderr or proc.stdout or "GitHub search command failed").strip(),
            )
            metrics.append(metric)
            continue
        try:
            count = int((proc.stdout or "").strip())
        except ValueError:
            metric = DashboardMetric(
                metric_id=spec.metric_id,
                label=spec.label,
                value="n/a",
                status="failed",
                last_updated_at="",
                source_query=spec.query,
                command=command_text,
                stale_after_hours=stale_after_hours,
                failure_behavior="Mark this metric failed; do not carry forward an older count.",
                caveat=spec.caveat,
                error=f"Could not parse GitHub search total_count from: {proc.stdout!r}",
            )
            metrics.append(metric)
            continue
        metric = DashboardMetric(
            metric_id=spec.metric_id,
            label=spec.label,
            value=str(count),
            status="limited",
            last_updated_at=_iso_z(now),
            source_query=spec.query,
            command=command_text,
            stale_after_hours=stale_after_hours,
            failure_behavior="Mark stale after SLA; if the query fails, show failed and rerun manually.",
            caveat=spec.caveat,
            details={"count": count},
        )
        metrics.append(_apply_staleness(metric, now=now))
    return metrics


def _metric_count(metrics_by_id: dict[str, DashboardMetric], metric_id: str) -> int | None:
    metric = metrics_by_id.get(metric_id)
    if not metric or metric.status == "failed":
        return None
    count = metric.details.get("count")
    return count if isinstance(count, int) else None


def _coverage_metric(
    *,
    metric_id: str,
    label: str,
    numerator_id: str,
    denominator_id: str,
    metrics_by_id: dict[str, DashboardMetric],
    now: dt.datetime,
    caveat: str,
) -> DashboardMetric:
    numerator = _metric_count(metrics_by_id, numerator_id)
    denominator = _metric_count(metrics_by_id, denominator_id)
    if numerator is None or denominator is None:
        return DashboardMetric(
            metric_id=metric_id,
            label=label,
            value="n/a",
            status="failed",
            last_updated_at="",
            source_query=f"derived from {numerator_id}/{denominator_id}",
            command="n/a",
            stale_after_hours=24,
            failure_behavior="Derived metric is failed when either input count failed.",
            caveat=caveat,
            error="Missing successful input metric.",
        )
    value = (
        "n/a" if denominator == 0 else f"{numerator}/{denominator} ({numerator / denominator:.1%})"
    )
    return DashboardMetric(
        metric_id=metric_id,
        label=label,
        value=value,
        status="limited",
        last_updated_at=_iso_z(now),
        source_query=f"derived from {numerator_id}/{denominator_id}",
        command="n/a",
        stale_after_hours=24,
        failure_behavior="Derived metric follows the staleness/failure behavior of its inputs.",
        caveat=caveat,
        details={"numerator": numerator, "denominator": denominator},
    )


def build_coverage_metrics(
    *, search_metrics: list[DashboardMetric], now: dt.datetime
) -> list[DashboardMetric]:
    by_id = {metric.metric_id: metric for metric in search_metrics}
    return [
        _coverage_metric(
            metric_id="independent_model_review_coverage",
            label="Independent-review marker coverage",
            numerator_id="independent_model_review_comments",
            denominator_id="merged_prs",
            metrics_by_id=by_id,
            now=now,
            caveat=(
                "Coverage is based on GitHub Search comment markers and is not a "
                "thread-by-thread audit."
            ),
        ),
        _coverage_metric(
            metric_id="verdict_pass_coverage",
            label="Verdict PASS marker coverage",
            numerator_id="verdict_pass_comments",
            denominator_id="merged_prs",
            metrics_by_id=by_id,
            now=now,
            caveat=(
                "Coverage is based on GitHub Search comment markers and is not a "
                "thread-by-thread audit."
            ),
        ),
        _coverage_metric(
            metric_id="merge_quorum_marker_coverage",
            label="Merge-quorum marker coverage",
            numerator_id="merge_quorum_comments",
            denominator_id="merged_prs",
            metrics_by_id=by_id,
            now=now,
            caveat=(
                "Coverage is based on GitHub Search comment markers and is not a "
                "thread-by-thread audit."
            ),
        ),
        _coverage_metric(
            metric_id="exact_head_marker_coverage",
            label="Exact-head marker coverage",
            numerator_id="exact_head_marker_comments",
            denominator_id="merged_prs",
            metrics_by_id=by_id,
            now=now,
            caveat=(
                "This is only a live phrase-marker proxy. The remaining stronger "
                "grounding gap is a per-PR audit that resolves each evidence comment "
                "SHA against the actual merged head."
            ),
        ),
    ]


def _artifact_receipt_command() -> str:
    names = " ".join(path.split("/")[-1].removesuffix(".json") for path in SETTLEMENT_RECEIPT_PATHS)
    return (
        f"git fetch origin {SETTLEMENT_RECEIPT_BRANCH}; "
        f"for f in {names}; do git show FETCH_HEAD:docs/elves/receipts/$f.json; done; "
        "python3 - <<'EOF' ... DecisionReceipt.from_dict(...).verify_integrity() ... EOF"
    )


def collect_settlement_receipt_metric(
    *,
    now: dt.datetime,
    runner: CommandRunner = _run_command,
    stale_after_hours: int = 168,
) -> DashboardMetric:
    command = _artifact_receipt_command()
    fetch = runner(["git", "fetch", "origin", SETTLEMENT_RECEIPT_BRANCH], 300)
    if fetch.returncode != 0:
        return DashboardMetric(
            metric_id="settlement_receipts_verified",
            label="Committed settlement receipts verified",
            value="n/a",
            status="failed",
            last_updated_at="",
            source_query=f"{SETTLEMENT_RECEIPT_BRANCH}:{','.join(SETTLEMENT_RECEIPT_PATHS)}",
            command=command,
            stale_after_hours=stale_after_hours,
            failure_behavior="Mark failed; receipt proof is not refreshed until the branch fetch succeeds.",
            error=(fetch.stderr or fetch.stdout or "git fetch failed").strip(),
        )

    try:
        from aragora.gauntlet.receipt_models import DecisionReceipt
    except Exception as exc:
        return DashboardMetric(
            metric_id="settlement_receipts_verified",
            label="Committed settlement receipts verified",
            value="n/a",
            status="failed",
            last_updated_at="",
            source_query=f"{SETTLEMENT_RECEIPT_BRANCH}:{','.join(SETTLEMENT_RECEIPT_PATHS)}",
            command=command,
            stale_after_hours=stale_after_hours,
            failure_behavior="Mark failed; verifier import must work before publishing the count.",
            error=f"DecisionReceipt import failed: {exc}",
        )

    verified: list[str] = []
    failed: list[dict[str, str]] = []
    for receipt_path in SETTLEMENT_RECEIPT_PATHS:
        show = runner(["git", "show", f"FETCH_HEAD:{receipt_path}"], 120)
        if show.returncode != 0:
            failed.append(
                {
                    "path": receipt_path,
                    "error": (show.stderr or show.stdout or "git show failed").strip(),
                }
            )
            continue
        try:
            payload = json.loads(show.stdout)
            receipt = DecisionReceipt.from_dict(payload)
            if receipt.verify_integrity():
                verified.append(receipt_path)
            else:
                failed.append({"path": receipt_path, "error": "verify_integrity returned False"})
        except Exception as exc:
            failed.append({"path": receipt_path, "error": str(exc)})

    status = "ok" if not failed else "failed"
    metric = DashboardMetric(
        metric_id="settlement_receipts_verified",
        label="Committed settlement receipts verified",
        value=f"{len(verified)}/{len(SETTLEMENT_RECEIPT_PATHS)}",
        status=status,
        last_updated_at=_iso_z(now) if status == "ok" else "",
        source_query=f"{SETTLEMENT_RECEIPT_BRANCH}:{','.join(SETTLEMENT_RECEIPT_PATHS)}",
        command=command,
        stale_after_hours=stale_after_hours,
        failure_behavior="If any receipt is missing or fails integrity verification, mark the metric failed.",
        caveat="These are committed settlement receipts, not operator-local merge-executor receipts.",
        error="; ".join(f"{item['path']}: {item['error']}" for item in failed),
        details={"verified": verified, "failed": failed},
    )
    return _apply_staleness(metric, now=now)


def _load_merge_executor_receipt(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != "merge-executor-receipt/v1":
        return None
    return payload


def collect_local_merge_executor_receipt_metric(
    *,
    now: dt.datetime,
    receipt_roots: Sequence[Path] = DEFAULT_LOCAL_MERGE_RECEIPT_ROOTS,
    stale_after_hours: int = 168,
) -> DashboardMetric:
    receipt_paths: list[Path] = []
    valid_payloads: list[dict[str, Any]] = []
    for root in receipt_roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            payload = _load_merge_executor_receipt(path)
            if payload is None:
                continue
            receipt_paths.append(path)
            valid_payloads.append(payload)

    exact_head_count = 0
    newest_mtime: float | None = None
    prs: list[int] = []
    for path, payload in zip(receipt_paths, valid_payloads, strict=True):
        try:
            newest_mtime = max(newest_mtime or 0.0, path.stat().st_mtime)
        except OSError:
            pass
        if isinstance(payload.get("pr"), int):
            prs.append(int(payload["pr"]))
        head_sha = str(payload.get("head_sha") or "").strip()
        raw_packet = payload.get("packet_entry")
        packet = raw_packet if isinstance(raw_packet, dict) else {}
        packet_head = str(packet.get("head_sha") or "").strip()
        if head_sha and packet_head and head_sha == packet_head:
            exact_head_count += 1

    if newest_mtime is not None:
        last_updated = _iso_z(dt.datetime.fromtimestamp(newest_mtime, tz=dt.timezone.utc))
    else:
        last_updated = _iso_z(now)
    root_text = ", ".join(_display_path(root) for root in receipt_roots)
    command = f"find {root_text} -maxdepth 1 -type f -name '*.json'"
    status = "local_only" if receipt_paths else "missing"
    value = str(len(receipt_paths)) if receipt_paths else "0"
    metric = DashboardMetric(
        metric_id="operator_local_merge_executor_receipts",
        label="Operator-local merge-executor receipts observed",
        value=value,
        status=status,
        last_updated_at=last_updated,
        source_query=root_text,
        command=command,
        stale_after_hours=stale_after_hours,
        failure_behavior=(
            "If local paths are absent, mark missing; do not infer public receipt counts from "
            "operator-local storage."
        ),
        caveat=(
            "Operator merge-executor receipts are local machine artifacts, not repo-visible "
            "public proof."
        ),
        details={
            "roots": [_display_path(root) for root in receipt_roots],
            "receipt_count": len(receipt_paths),
            "exact_head_receipt_count": exact_head_count,
            "prs": sorted(prs),
        },
    )
    return _apply_staleness(metric, now=now)


def build_payload(
    *,
    repo: str,
    window_start: str,
    window_end: str,
    now: dt.datetime,
    runner: CommandRunner = _run_command,
    receipt_roots: Sequence[Path] = DEFAULT_LOCAL_MERGE_RECEIPT_ROOTS,
) -> dict[str, Any]:
    search_metrics = collect_github_search_metrics(
        repo=repo,
        window_start=window_start,
        window_end=window_end,
        now=now,
        runner=runner,
    )
    metrics = [
        *search_metrics,
        *build_coverage_metrics(search_metrics=search_metrics, now=now),
        collect_settlement_receipt_metric(now=now, runner=runner),
        collect_local_merge_executor_receipt_metric(now=now, receipt_roots=receipt_roots),
    ]
    known_gaps = [
        {
            "metric_id": "github_search_counts",
            "status": "limited",
            "gap": (
                "GitHub Search API counts are live, regenerable marker counts; exact audited "
                "truth still requires thread-by-thread PR evidence enumeration."
            ),
        }
    ]
    for metric in metrics:
        is_true_gap = metric.status in {
            "failed",
            "missing",
            "local_only",
            "stale",
        } or metric.metric_id in {
            "exact_head_marker_comments",
            "exact_head_marker_coverage",
        }
        if is_true_gap and (metric.error or metric.caveat):
            known_gaps.append(
                {
                    "metric_id": metric.metric_id,
                    "status": metric.status,
                    "gap": metric.error or metric.caveat,
                }
            )
    return {
        "schema": "decision-integrity-dogfood-dashboard/v1",
        "generated_at": _iso_z(now),
        "report_only": True,
        "repo": repo,
        "issue": 8861,
        "source_artifact": SOURCE_ARTIFACT,
        "window": {
            "start": window_start,
            "end": window_end,
            "note": "Rolling 30-day GitHub search window using the July artifact query shapes.",
        },
        "metrics": [asdict(metric) for metric in metrics],
        "known_gaps": known_gaps,
    }


def _format_value(value: Any) -> str:
    if value is None or value == "":
        return "n/a"
    return str(value)


def _render_metric_table(metrics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Metric | Value | Status | Last updated | Source |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for metric in metrics:
        source = str(metric.get("source_query") or "").replace("|", "\\|")
        lines.append(
            "| "
            f"{_format_value(metric.get('label'))} | "
            f"`{_format_value(metric.get('value'))}` | "
            f"`{_format_value(metric.get('status'))}` | "
            f"`{_format_value(metric.get('last_updated_at'))}` | "
            f"`{source}` |"
        )
    return lines


def _render_metric_behavior(metrics: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Metric | Stale after | Failure behavior | Caveat |",
        "| --- | ---: | --- | --- |",
    ]
    for metric in metrics:
        caveat = str(metric.get("caveat") or "").replace("|", "\\|")
        failure = str(metric.get("failure_behavior") or "").replace("|", "\\|")
        lines.append(
            "| "
            f"{_format_value(metric.get('label'))} | "
            f"{_format_value(metric.get('stale_after_hours'))}h | "
            f"{failure} | "
            f"{caveat or '-'} |"
        )
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    metrics = [metric for metric in payload.get("metrics", []) if isinstance(metric, dict)]
    gaps = [gap for gap in payload.get("known_gaps", []) if isinstance(gap, dict)]
    local_receipts = next(
        (
            metric
            for metric in metrics
            if metric.get("metric_id") == "operator_local_merge_executor_receipts"
        ),
        {},
    )
    local_details = local_receipts.get("details") if isinstance(local_receipts, dict) else {}
    if not isinstance(local_details, dict):
        local_details = {}

    lines = [
        "# Decision-Integrity Dogfood Dashboard",
        "",
        f"Last updated: {payload.get('generated_at', 'unknown')}",
        "",
        "Report-only generated companion for the frozen July dogfood proof artifact. It does not schedule publishing, mutate queues, post comments, or authorize merges.",
        "",
        "## Scope",
        "",
        f"- Repo: `{payload.get('repo', DEFAULT_REPO)}`",
        f"- Tracking issue: `#{payload.get('issue', 8861)}`",
        f"- Source artifact: `{payload.get('source_artifact', SOURCE_ARTIFACT)}`",
        (
            f"- GitHub search window: `{payload.get('window', {}).get('start')}`.."
            f"`{payload.get('window', {}).get('end')}`"
        ),
        "- Query shape: reused from the July artifact, with the window made regenerable.",
        "",
        "## Metrics",
        "",
        *_render_metric_table(metrics),
        "",
        "## Stale And Failure Behavior",
        "",
        *_render_metric_behavior(metrics),
        "",
        "## Local Receipt Notes",
        "",
        (
            "- Operator-local exact-head receipts observed: "
            f"`{local_details.get('exact_head_receipt_count', 0)}`/"
            f"`{local_details.get('receipt_count', 0)}`"
        ),
        "- These local receipts are useful operator proof, but not outsider-verifiable until promoted into repo-visible signed or hash-verifiable artifacts.",
        "",
        "## Known Gaps",
        "",
    ]
    if gaps:
        for gap in gaps:
            lines.append(
                f"- `{gap.get('metric_id')}` status `{gap.get('status')}`: {gap.get('gap')}"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Regenerate",
            "",
            "```bash",
            (
                "python3 scripts/render_decision_integrity_dogfood_dashboard.py "
                f"--output {_repo_stable_path(DEFAULT_OUTPUT)} "
                f"--json-output {_repo_stable_path(DEFAULT_JSON_OUTPUT)}"
            ),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_dashboard(
    *, payload: dict[str, Any], output: Path, json_output: Path
) -> tuple[Path, Path]:
    output.parent.mkdir(parents=True, exist_ok=True)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(payload), encoding="utf-8")
    json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return output, json_output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--window-start", default="")
    parser.add_argument("--window-end", default="")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Markdown dashboard output path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_JSON_OUTPUT,
        help=f"JSON dashboard output path (default: {DEFAULT_JSON_OUTPUT})",
    )
    parser.add_argument(
        "--now",
        default="",
        help="UTC timestamp override for deterministic tests, for example 2026-07-05T12:00:00Z",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = _parse_utc_timestamp(args.now) if args.now else _utcnow()
    default_start, default_end = _default_window(now)
    window_start = args.window_start or default_start
    window_end = args.window_end or default_end
    payload = build_payload(
        repo=str(args.repo),
        window_start=window_start,
        window_end=window_end,
        now=now,
    )
    output, json_output = write_dashboard(
        payload=payload,
        output=args.output.resolve(),
        json_output=args.json_output.resolve(),
    )
    print(str(output))
    print(str(json_output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
