#!/usr/bin/env python3
"""Render a repo-tracked B0 benchmark truth status summary."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORPUS_PATH = REPO_ROOT / "docs" / "benchmarks" / "corpus.json"
DEFAULT_TRUTH_ROOT = REPO_ROOT / "docs" / "status" / "generated" / "benchmark_truth_artifacts"
DEFAULT_SCORECARD_ROOT = REPO_ROOT / "docs" / "status" / "generated" / "benchmark_scorecards"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "status" / "B0_BENCHMARK_TRUTH_STATUS.md"

SUCCESS_CLASSES = frozenset(
    {
        "success_merged",
        "success_pr_created",
        "deliverable_pr_created",
    }
)
FAILURE_CLASSES = frozenset(
    {
        "rescue_timeout",
        "rescue_worker_crash",
        "rescue_no_deliverable",
        "blocked_not_dispatch_bounded",
        "blocked_validation_target_missing",
        "blocked_sanitation_failed",
        "blocked_auth_failure",
        "blocked_no_runner",
    }
)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return slug.strip("-") or "benchmark-corpus"


def _repo_stable_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON payload at {path} must be an object")
    return payload


def _positive_revision(value: Any, *, path: Path) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Corpus at {path} must contain a positive integer revision")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Corpus at {path} must contain a positive integer revision") from exc
    if revision <= 0:
        raise ValueError(f"Corpus at {path} must contain a positive integer revision")
    return revision


def load_corpus(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    issues = payload.get("issues")
    if not isinstance(issues, list) or not issues:
        raise ValueError(f"Corpus at {path} must contain a non-empty 'issues' list")
    corpus_id = str(payload.get("corpus_id") or "").strip()
    if not corpus_id:
        raise ValueError(f"Corpus at {path} must contain a non-empty corpus_id")
    payload["corpus_id"] = corpus_id
    payload["revision"] = _positive_revision(payload.get("revision"), path=path)
    return payload


def resolve_latest_paths(
    *,
    corpus_path: Path,
    truth_root: Path,
    scorecard_root: Path,
) -> dict[str, Path]:
    corpus = load_corpus(corpus_path)
    corpus_id = str(corpus.get("corpus_id") or "").strip()
    revision = int(corpus.get("revision", 0) or 0)
    slug = _slugify(corpus_id)
    return {
        "truth_corpus_latest": truth_root / slug / "latest.json",
        "truth_revision_latest": truth_root / slug / f"rev-{revision}" / "latest.json",
        "scorecard_corpus_latest": scorecard_root / slug / "latest.json",
        "scorecard_revision_latest": scorecard_root / slug / f"rev-{revision}" / "latest.json",
    }


def _payload_corpus_identity(payload: dict[str, Any]) -> tuple[str, int]:
    corpus = dict(payload.get("corpus") or {})
    return (
        str(corpus.get("corpus_id") or "").strip(),
        int(corpus.get("revision", 0) or 0),
    )


def _load_expected_latest_payload(
    *,
    path: Path,
    label: str,
    expected_corpus_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"{label} not found: {path}")
    payload = _load_json(path)
    payload_corpus_id, payload_revision = _payload_corpus_identity(payload)
    if payload_corpus_id != expected_corpus_id:
        raise SystemExit(
            f"{label} corpus_id mismatch: expected {expected_corpus_id!r}, "
            f"got {payload_corpus_id!r} at {path}"
        )
    if payload_revision != expected_revision:
        raise SystemExit(
            f"{label} revision mismatch: expected {expected_revision}, "
            f"got {payload_revision} at {path}"
        )
    return payload


def _require_matching_latest_payloads(
    *,
    corpus_latest_payload: dict[str, Any],
    revision_latest_payload: dict[str, Any],
    corpus_latest_path: Path,
    revision_latest_path: Path,
    label: str,
) -> None:
    if corpus_latest_payload == revision_latest_payload:
        return
    raise SystemExit(
        f"{label} latest pointer mismatch: "
        f"{corpus_latest_path} does not match {revision_latest_path}"
    )


def _format_percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1%}"
    return "n/a"


def _format_value(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    if value is None or value == "":
        return "n/a"
    return str(value)


def _format_bool(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return "unknown"


def _render_mapping(mapping: dict[str, Any]) -> list[str]:
    if not mapping:
        return ["- none"]
    return [f"- `{key}`: {_format_value(value)}" for key, value in mapping.items()]


_DELTA_LABELS = {
    "truth_success_rate": "Full-corpus truth success rate (legacy/context)",
    "truth_success_rate_verified": "Verified truth success rate (primary)",
    "no_rescue_truth_success_rate": "No-rescue truth success rate",
    "merged_only_rate": "Merged-only rate",
    "proxy_no_rescue_success_rate": "Proxy no-rescue success rate",
    "unique_issues_attempted": "Unique issues attempted",
}


def _render_delta_mapping(mapping: dict[str, Any]) -> list[str]:
    if not mapping:
        return ["- none"]
    lines: list[str] = []
    for key, value in mapping.items():
        label = _DELTA_LABELS.get(key)
        if label:
            lines.append(f"- {label} (`{key}`): {_format_value(value)}")
        else:
            lines.append(f"- `{key}`: {_format_value(value)}")
    return lines


def _format_issue_numbers(values: Any) -> str:
    issue_numbers = [
        int(value) for value in list(values or []) if isinstance(value, int) and int(value) > 0
    ]
    if not issue_numbers:
        return "none"
    return ", ".join(f"`#{value}`" for value in sorted(issue_numbers))


def _issue_numbers_for_records(records: list[dict[str, Any]], *, state: str) -> list[int]:
    normalized_state = state.strip().upper()
    issue_numbers: list[int] = []
    for record in records:
        if str(record.get("expected_status") or "").strip() != "in_progress":
            continue
        if str(record.get("issue_state") or "").strip().upper() != normalized_state:
            continue
        issue_number = record.get("issue_number")
        if isinstance(issue_number, int) and issue_number > 0:
            issue_numbers.append(issue_number)
    return sorted(issue_numbers)


def _render_stale_closed_issues(issues: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        issue_number = _format_value(issue.get("issue_number"))
        title = _format_value(issue.get("issue_title"))
        closed_at = _format_value(issue.get("issue_closed_at"))
        state_reason = _format_value(issue.get("issue_state_reason"))
        truth_state = _format_value(issue.get("truth_state"))
        lines.append(
            f"- `#{issue_number}` `{title}`: closed `{closed_at}`, "
            f"reason `{state_reason}`, truth `{truth_state}`"
        )
    return lines or ["- none"]


def _render_closure_hygiene_issues(issues: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        issue_number = _format_value(issue.get("issue_number"))
        title = _format_value(issue.get("issue_title"))
        issue_state = _format_value(issue.get("issue_state"))
        state_reason = _format_value(issue.get("issue_state_reason"))
        truth_state = _format_value(issue.get("truth_state"))
        lines.append(
            f"- `#{issue_number}` `{title}`: state `{issue_state}`, "
            f"reason `{state_reason}`, truth `{truth_state}`"
        )
    return lines or ["- none"]


def _render_linkage_errors(issues: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        issue_number = _format_value(issue.get("issue_number"))
        title = _format_value(issue.get("issue_title"))
        closed_at = _format_value(issue.get("issue_closed_at"))
        state_reason = _format_value(issue.get("issue_state_reason"))
        truth_state = _format_value(issue.get("truth_state"))
        linkage_status = _format_value(issue.get("linkage_status"))
        linkage_error = _format_value(issue.get("linkage_error"))
        lines.append(
            f"- `#{issue_number}` `{title}`: closed `{closed_at}`, "
            f"reason `{state_reason}`, truth `{truth_state}`, "
            f"linkage `{linkage_status}`, error `{linkage_error}`"
        )
    return lines or ["- none"]


def _render_linked_issues(issues: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        target = _format_value(issue.get("target"))
        title = _format_value(issue.get("title"))
        url = str(issue.get("url") or "").strip()
        if url and target != "n/a":
            lines.append(f"- [{target}]({url}) `{title}`")
            continue
        if url:
            lines.append(f"- [link]({url}) `{title}`")
            continue
        lines.append(f"- `{target}` `{title}`")
    return lines or ["- none"]


def _render_issue_linkage_results(results: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for result in results:
        action = _format_value(result.get("action"))
        target = _format_value(result.get("target"))
        url = str(result.get("url") or "").strip()
        if url and target != "n/a":
            lines.append(f"- `{action}` -> [{target}]({url})")
            continue
        error = str(result.get("error") or "").strip()
        if error:
            lines.append(f"- `{action}` -> `{error}`")
            continue
        lines.append(f"- `{action}` -> `{target}`")
    return lines or ["- none"]


def _render_issue_drafts(drafts: list[dict[str, Any]]) -> list[str]:
    return [
        f"- `{_format_value(draft.get('title'))}`" for draft in drafts if isinstance(draft, dict)
    ] or ["- none"]


def _proxy_count(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"proxy metric `{field}` must be an integer count")
    if value < 0:
        raise ValueError(f"proxy metric `{field}` must be non-negative")
    return value


def _normalize_proxy_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    proxy_metrics = dict(payload)
    terminal_class_distribution = dict(proxy_metrics.get("terminal_class_distribution") or {})

    attempted = _proxy_count(
        proxy_metrics.get("unique_issues_attempted"),
        field="unique_issues_attempted",
    )
    succeeded = _proxy_count(
        proxy_metrics.get("unique_issues_succeeded"),
        field="unique_issues_succeeded",
    )
    failed = _proxy_count(
        proxy_metrics.get("unique_issues_failed"),
        field="unique_issues_failed",
    )
    if attempted is not None and succeeded is not None and failed is not None:
        neutral = _proxy_count(
            proxy_metrics.get("unique_issues_neutral"),
            field="unique_issues_neutral",
        )
        expected_neutral = attempted - succeeded - failed
        if expected_neutral < 0:
            raise ValueError(
                "proxy metrics inconsistent: unique_issues_succeeded + "
                "unique_issues_failed exceeds unique_issues_attempted"
            )
        if neutral is None:
            proxy_metrics["unique_issues_neutral"] = expected_neutral
        elif neutral != expected_neutral:
            raise ValueError(
                "proxy metrics inconsistent: unique_issues_neutral must equal "
                "unique_issues_attempted - unique_issues_succeeded - unique_issues_failed"
            )

    if "neutral_classes" not in proxy_metrics and terminal_class_distribution:
        proxy_metrics["neutral_classes"] = {
            key: value
            for key, value in terminal_class_distribution.items()
            if key not in SUCCESS_CLASSES and key not in FAILURE_CLASSES
        }

    return proxy_metrics


def render_status_markdown(
    *,
    corpus_path: Path,
    truth_path: Path,
    scorecard_path: Path,
    truth_payload: dict[str, Any],
    scorecard_payload: dict[str, Any],
    latest_paths: dict[str, Path],
) -> str:
    truth_corpus = dict(truth_payload.get("corpus") or {})
    scorecard_corpus = dict(scorecard_payload.get("corpus") or {})
    corpus = {**truth_corpus, **scorecard_corpus}
    coverage = dict(scorecard_payload.get("coverage") or truth_payload.get("coverage") or {})
    truth_metrics = dict(
        scorecard_payload.get("truth_metrics") or truth_payload.get("primary_metrics") or {}
    )
    in_flight_metrics = dict(
        truth_payload.get("in_flight_metrics") or scorecard_payload.get("in_flight_metrics") or {}
    )
    proxy_metrics = _normalize_proxy_metrics(dict(scorecard_payload.get("proxy_metrics") or {}))
    previous_artifact = dict(scorecard_payload.get("previous_artifact") or {})
    deltas = dict(scorecard_payload.get("deltas") or {})
    failure_distribution = dict(scorecard_payload.get("failure_class_distribution") or {})
    rescue_counts = dict(scorecard_payload.get("rescue_counts_by_type") or {})
    metrics_provenance = dict(
        scorecard_payload.get("metrics_provenance") or truth_payload.get("metrics_provenance") or {}
    )
    neutral_classes = dict(proxy_metrics.get("neutral_classes") or {})
    issue_records = [
        item for item in list(truth_payload.get("issues") or []) if isinstance(item, dict)
    ]
    corpus_freshness = dict(truth_payload.get("corpus_freshness") or {})
    stale_closed_issues = [
        item
        for item in list(corpus_freshness.get("stale_closed_issues") or [])
        if isinstance(item, dict)
    ]
    closure_hygiene_issues = [
        item
        for item in list(corpus_freshness.get("closure_hygiene_issues") or [])
        if isinstance(item, dict)
    ]
    linkage_errors = [
        item
        for item in list(corpus_freshness.get("linkage_errors") or [])
        if isinstance(item, dict)
    ]
    linked_issues = [
        item for item in list(corpus_freshness.get("linked_issues") or []) if isinstance(item, dict)
    ]
    issue_linkage_results = [
        item
        for item in list(corpus_freshness.get("issue_linkage_results") or [])
        if isinstance(item, dict)
    ]
    issue_drafts = [
        item for item in list(corpus_freshness.get("issue_drafts") or []) if isinstance(item, dict)
    ]
    issue_map_path = str(corpus_freshness.get("issue_map_path") or "").strip()
    generated_at = (
        str(scorecard_payload.get("generated_at") or "").strip()
        or str(truth_payload.get("generated_at") or "").strip()
        or "unknown"
    )

    lines = [
        "# B0 Benchmark Truth Status",
        "",
        f"Last updated: {generated_at}",
        "",
        "This is the repo-tracked recurring `TW-02` publication surface for the fixed benchmark corpus.",
        "",
        "## Corpus",
        "",
        f"- Corpus manifest: `{_repo_stable_path(corpus_path)}`",
        f"- Corpus id: `{_format_value(corpus.get('corpus_id'))}`",
        f"- Revision: `{_format_value(corpus.get('revision'))}`",
        f"- Recorded on: `{_format_value(corpus.get('recorded_on'))}`",
        f"- Success contract: `{_format_value(corpus.get('success_contract'))}`",
        f"- Verified expected issues: `{_format_value(corpus.get('verified_expected_count'))}`",
        f"- In-progress expected issues: `{_format_value(corpus.get('in_progress_expected_count'))}`",
        f"- Coverage status: `{_format_value(coverage.get('status'))}`",
        (
            f"- Coverage: `{_format_value(coverage.get('attempted_issue_count'))}`/"
            f"`{_format_value(corpus.get('issue_count'))}` issues attempted"
        ),
    ]
    missing_issue_numbers = list(coverage.get("missing_issue_numbers") or [])
    if missing_issue_numbers:
        lines.append(
            "- Missing corpus issues: " + ", ".join(f"`{item}`" for item in missing_issue_numbers)
        )
    lines.extend(
        [
            "",
            "## Published Paths",
            "",
            f"- Corpus-scoped truth pointer: `{_repo_stable_path(truth_path)}`",
            f"- Corpus-scoped scorecard pointer: `{_repo_stable_path(scorecard_path)}`",
            f"- Revision-scoped truth pointer: `{_repo_stable_path(latest_paths['truth_revision_latest'])}`",
            f"- Revision-scoped scorecard pointer: `{_repo_stable_path(latest_paths['scorecard_revision_latest'])}`",
            "",
            "## Evidence Provenance",
            "",
            f"- Metrics input: `{_format_value(metrics_provenance.get('path'))}`",
            f"- Capture scope: `{_format_value(metrics_provenance.get('capture_scope'))}`",
            f"- Content SHA-256: `{_format_value(metrics_provenance.get('content_sha256'))}`",
            f"- Repository HEAD: `{_format_value(metrics_provenance.get('repository_head_sha'))}`",
            "- Tracked in this repository: "
            f"`{_format_bool(metrics_provenance.get('repository_tracked'))}`",
            "- Reproducible from this repository: "
            f"`{_format_bool(metrics_provenance.get('repository_reproducible'))}`",
            f"- Source workflow run: `{_format_value(metrics_provenance.get('source_run_url'))}`",
        ]
    )
    if metrics_provenance.get("repository_reproducible") is False:
        lines.extend(
            [
                "",
                "Provenance warning: proxy, failure, and rescue counts come from a "
                "runner-local metrics window that is not tracked in this repository. "
                "Treat those counts as an observation from the cited run, not as a "
                "repository-reproducible benchmark receipt.",
            ]
        )
    lines.extend(
        [
            "",
            "## Truth Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            (
                "| Verified truth success rate (primary) | "
                f"{_format_percent(truth_metrics.get('truth_success_rate_verified'))} |"
            ),
            (
                "| Full-corpus truth success rate (legacy/context) | "
                f"{_format_percent(truth_metrics.get('truth_success_rate'))} |"
            ),
            f"| No-rescue truth success rate | {_format_percent(truth_metrics.get('no_rescue_truth_success_rate'))} |",
            f"| Merged-only rate | {_format_percent(truth_metrics.get('merged_only_rate'))} |",
        ]
    )
    proxy_attempted = proxy_metrics.get("unique_issues_attempted")
    all_neutral_window = (
        isinstance(proxy_attempted, int)
        and proxy_attempted > 0
        and proxy_metrics.get("unique_issues_succeeded") == 0
        and proxy_metrics.get("unique_issues_failed") == 0
        and proxy_metrics.get("unique_issues_neutral") == proxy_attempted
    )
    if all_neutral_window:
        preamble = (
            "the verified rates above reflect the previously graduated cohort, "
            "not fresh autonomy proof. All "
            f"`{proxy_attempted}`/`{proxy_attempted}` proxy corpus rows in the "
            "current window were neutral with `0` fresh successes"
        )
        corpus_exhausted = bool(neutral_classes) and set(neutral_classes) == {
            "issue_already_resolved"
        }
        if corpus_exhausted:
            note = (
                f"Corpus exhaustion note: {preamble} (`issue_already_resolved`) — "
                "corpus revision "
                f"`{_format_value(corpus.get('revision'))}` is exhausted and "
                "generates no new execution evidence until the corpus is restocked."
            )
        else:
            note = f"Freshness note: {preamble} — this window produced no fresh execution evidence."
        lines.extend(["", note])
    if in_flight_metrics:
        lines.extend(
            [
                "",
                "## In-Flight Graduation Metrics",
                "",
                "| Metric | Value |",
                "| --- | --- |",
                (
                    "| In-progress expected issues | "
                    f"{_format_value(in_flight_metrics.get('in_progress_expected_count'))} |"
                ),
                (
                    "| In-progress attempted issues | "
                    f"{_format_value(in_flight_metrics.get('in_progress_attempted_count'))} |"
                ),
                (
                    "| In-progress successful issues | "
                    f"{_format_value(in_flight_metrics.get('in_progress_success_count'))} |"
                ),
                (
                    "| In-progress graduation rate | "
                    f"{_format_percent(in_flight_metrics.get('in_progress_graduation_rate'))} |"
                ),
                (
                    "| Expected in-progress issue numbers | "
                    f"{_format_issue_numbers(in_flight_metrics.get('in_progress_issue_numbers'))} |"
                ),
                (
                    "| Live-open expected issue numbers | "
                    f"{_format_issue_numbers(_issue_numbers_for_records(issue_records, state='OPEN'))} |"
                ),
                (
                    "| Live-closed expected issue numbers | "
                    f"{_format_issue_numbers(_issue_numbers_for_records(issue_records, state='CLOSED'))} |"
                ),
            ]
        )
    lines.extend(
        [
            "",
            "## Proxy Metrics",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Proxy no-rescue success rate | {_format_percent(proxy_metrics.get('no_rescue_success_rate'))} |",
            f"| Unique issues attempted | {_format_value(proxy_metrics.get('unique_issues_attempted'))} |",
            f"| Unique issues succeeded | {_format_value(proxy_metrics.get('unique_issues_succeeded'))} |",
            f"| Unique issues failed | {_format_value(proxy_metrics.get('unique_issues_failed'))} |",
            f"| Unique issues neutral | {_format_value(proxy_metrics.get('unique_issues_neutral'))} |",
            f"| Total ticks | {_format_value(proxy_metrics.get('total_ticks'))} |",
        ]
    )
    if neutral_classes:
        lines.extend(
            [
                "",
                "Proxy note: neutral issue outcomes are current-corpus rows that were neither fresh success nor failure, such as `issue_already_resolved`.",
                "",
                "## Proxy Neutral Class Distribution",
                "",
                *_render_mapping(neutral_classes),
            ]
        )
    if stale_closed_issues:
        lines.extend(
            [
                "",
                "## Corpus Freshness Alerts",
                "",
                "Truth metrics still reflect the frozen corpus revision. Closed issues without linked PR truth should be retired or replaced in the next corpus revision.",
                "",
                *_render_stale_closed_issues(stale_closed_issues),
            ]
        )
        if issue_map_path or linked_issues or issue_drafts or issue_linkage_results:
            lines.extend(
                [
                    "",
                    "## Corpus Freshness Follow-Up",
                    "",
                    f"- Freshness map: `{_format_value(issue_map_path)}`",
                    f"- Linked issues: `{len(linked_issues)}`",
                    f"- Pending issue drafts: `{len(issue_drafts)}`",
                ]
            )
            if linked_issues:
                lines.extend(
                    [
                        "",
                        "Linked issues:",
                        *_render_linked_issues(linked_issues),
                    ]
                )
            if issue_linkage_results:
                lines.extend(
                    [
                        "",
                        "Latest issue linkage actions:",
                        *_render_issue_linkage_results(issue_linkage_results),
                    ]
                )
            if issue_drafts:
                lines.extend(
                    [
                        "",
                        "Pending issue drafts:",
                        *_render_issue_drafts(issue_drafts),
                    ]
                )
    if closure_hygiene_issues:
        lines.extend(
            [
                "",
                "## Closure Hygiene Alerts",
                "",
                "These verified corpus issues show deliverable or PR-shaped signals in automation metrics, but strict benchmark linkage still resolves to `no_linked_pr`.",
                "",
                *_render_closure_hygiene_issues(closure_hygiene_issues),
            ]
        )
    if linkage_errors:
        lines.extend(
            [
                "",
                "## Corpus Freshness Verification Warnings",
                "",
                "Closed issues with failed GitHub linkage checks were excluded from stale-corpus alerts until verification can be retried cleanly.",
                "",
                *_render_linkage_errors(linkage_errors),
            ]
        )
    lines.extend(
        [
            "",
            "## Failure Class Distribution",
            "",
            *_render_mapping(failure_distribution),
            "",
            "## Rescue Counts By Type",
            "",
            *_render_mapping(rescue_counts),
        ]
    )
    if previous_artifact:
        lines.extend(
            [
                "",
                "## Previous Published Artifact",
                "",
                f"- Previous artifact path: `{_format_value(previous_artifact.get('path'))}`",
                f"- Previous generated_at: `{_format_value(previous_artifact.get('generated_at'))}`",
            ]
        )
    if deltas:
        lines.extend(
            [
                "",
                "## Deltas",
                "",
                *_render_delta_mapping(deltas),
            ]
        )
    lines.append("")
    return "\n".join(lines)


def write_output(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=DEFAULT_CORPUS_PATH,
        help=f"Benchmark corpus manifest (default: {DEFAULT_CORPUS_PATH})",
    )
    parser.add_argument(
        "--truth-root",
        type=Path,
        default=DEFAULT_TRUTH_ROOT,
        help=f"Tracked truth-artifact root (default: {DEFAULT_TRUTH_ROOT})",
    )
    parser.add_argument(
        "--scorecard-root",
        type=Path,
        default=DEFAULT_SCORECARD_ROOT,
        help=f"Tracked scorecard root (default: {DEFAULT_SCORECARD_ROOT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Markdown status output path (default: {DEFAULT_OUTPUT})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    corpus_path = args.corpus.resolve()
    truth_root = args.truth_root.resolve()
    scorecard_root = args.scorecard_root.resolve()
    output_path = args.output.resolve()
    if not corpus_path.exists():
        raise SystemExit(f"corpus file not found: {corpus_path}")

    corpus = load_corpus(corpus_path)
    latest_paths = resolve_latest_paths(
        corpus_path=corpus_path,
        truth_root=truth_root,
        scorecard_root=scorecard_root,
    )
    expected_corpus_id = str(corpus.get("corpus_id") or "").strip()
    expected_revision = int(corpus.get("revision", 0) or 0)
    truth_path = latest_paths["truth_corpus_latest"]
    scorecard_path = latest_paths["scorecard_corpus_latest"]
    truth_payload = _load_expected_latest_payload(
        path=truth_path,
        label="truth artifact latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    truth_revision_payload = _load_expected_latest_payload(
        path=latest_paths["truth_revision_latest"],
        label="truth artifact revision latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    _require_matching_latest_payloads(
        corpus_latest_payload=truth_payload,
        revision_latest_payload=truth_revision_payload,
        corpus_latest_path=truth_path,
        revision_latest_path=latest_paths["truth_revision_latest"],
        label="truth artifact",
    )
    scorecard_payload = _load_expected_latest_payload(
        path=scorecard_path,
        label="scorecard latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    scorecard_revision_payload = _load_expected_latest_payload(
        path=latest_paths["scorecard_revision_latest"],
        label="scorecard revision latest.json",
        expected_corpus_id=expected_corpus_id,
        expected_revision=expected_revision,
    )
    _require_matching_latest_payloads(
        corpus_latest_payload=scorecard_payload,
        revision_latest_payload=scorecard_revision_payload,
        corpus_latest_path=scorecard_path,
        revision_latest_path=latest_paths["scorecard_revision_latest"],
        label="scorecard",
    )

    content = render_status_markdown(
        corpus_path=corpus_path,
        truth_path=truth_path,
        scorecard_path=scorecard_path,
        truth_payload=truth_payload,
        scorecard_payload=scorecard_payload,
        latest_paths=latest_paths,
    )
    written = write_output(output_path, content)
    print(str(written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
