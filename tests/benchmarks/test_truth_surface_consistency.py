from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tests.benchmarks.test_rescue_productization import (
    expected_counted_class_bullets,
    expected_issue_drafts,
    expected_issue_linkage_actions,
    expected_repeated_class_rows,
    parse_counted_class_bullets,
    parse_issue_drafts,
    parse_issue_linkage_actions,
    parse_repeated_class_rows,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rel_path(raw: str) -> Path:
    return REPO_ROOT / raw


def _last_updated(markdown: str) -> str:
    match = re.search(r"^Last updated:\s*(\S+)$", markdown, flags=re.MULTILINE)
    assert match is not None
    return match.group(1)


def _bullet_value(markdown: str, label: str) -> str:
    match = re.search(
        rf"^- {re.escape(label)}:\s*(.+)$",
        markdown,
        flags=re.MULTILINE,
    )
    assert match is not None, f"missing bullet: {label}"
    value = match.group(1).strip()
    if re.fullmatch(r"`[^`]+`", value):
        return value[1:-1]
    return value


def _published_path(markdown: str, label: str) -> Path:
    return _rel_path(_bullet_value(markdown, label))


def _table(markdown: str, section: str) -> dict[str, str]:
    match = re.search(
        rf"^## {re.escape(section)}\n\n(?P<table>(?:\| .+\n)+)",
        markdown,
        flags=re.MULTILINE,
    )
    assert match is not None, f"missing table: {section}"
    rows: dict[str, str] = {}
    for line in match.group("table").splitlines():
        columns = [column.strip() for column in line.strip("|").split("|")]
        if len(columns) != 2 or columns[0] in {"---", "Metric"}:
            continue
        rows[columns[0]] = columns[1]
    return rows


def _section_bullets(markdown: str, section: str) -> dict[str, int]:
    match = re.search(
        rf"^## {re.escape(section)}\n\n(?P<body>.*?)(?=\n## |\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"missing section: {section}"
    body = match.group("body").strip()
    if body == "- none":
        return {}
    result: dict[str, int] = {}
    for line in body.splitlines():
        item = re.match(r"^- `(?P<name>.+)`: (?P<count>\d+)$", line)
        assert item is not None, f"unexpected section row in {section}: {line}"
        result[item.group("name")] = int(item.group("count"))
    return result


def _optional_section_bullets(markdown: str, section: str) -> dict[str, int]:
    if re.search(rf"^## {re.escape(section)}$", markdown, flags=re.MULTILINE) is None:
        return {}
    return _section_bullets(markdown, section)


def _format_percent(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1%}"
    return "n/a"


def _int_value(value: str) -> int:
    return int(value.replace(",", ""))


def _issue_numbers(value: str) -> list[int]:
    return [int(match) for match in re.findall(r"#(\d+)", value)]


def test_b0_benchmark_truth_status_matches_latest_json_artifacts() -> None:
    markdown = (REPO_ROOT / "docs/status/B0_BENCHMARK_TRUTH_STATUS.md").read_text(encoding="utf-8")
    truth_path = _published_path(markdown, "Corpus-scoped truth pointer")
    scorecard_path = _published_path(markdown, "Corpus-scoped scorecard pointer")
    revision_truth_path = _published_path(markdown, "Revision-scoped truth pointer")
    revision_scorecard_path = _published_path(markdown, "Revision-scoped scorecard pointer")

    truth_payload = _read_json(truth_path)
    scorecard_payload = _read_json(scorecard_path)

    assert _read_json(revision_truth_path) == truth_payload
    assert _read_json(revision_scorecard_path) == scorecard_payload
    assert _last_updated(markdown) == scorecard_payload["generated_at"]

    corpus = scorecard_payload["corpus"]
    truth_corpus = truth_payload["corpus"]
    assert truth_corpus["corpus_id"] == corpus["corpus_id"]
    assert truth_corpus["revision"] == corpus["revision"]
    assert truth_corpus["recorded_on"] == corpus["recorded_on"]
    assert truth_corpus["success_contract"] == corpus["success_contract"]
    assert truth_corpus["issue_count"] == corpus["issue_count"]

    assert _bullet_value(markdown, "Corpus id") == corpus["corpus_id"]
    assert int(_bullet_value(markdown, "Revision")) == corpus["revision"]
    assert _bullet_value(markdown, "Recorded on") == corpus["recorded_on"]
    assert _bullet_value(markdown, "Success contract") == corpus["success_contract"]
    assert int(_bullet_value(markdown, "Verified expected issues")) == truth_corpus.get(
        "verified_expected_count", 0
    )
    assert int(_bullet_value(markdown, "In-progress expected issues")) == truth_corpus.get(
        "in_progress_expected_count", 0
    )

    coverage = scorecard_payload["coverage"]
    assert _bullet_value(markdown, "Coverage status") == coverage["status"]
    coverage_match = re.fullmatch(
        r"`(?P<attempted>\d+)`/`(?P<total>\d+)` issues attempted",
        _bullet_value(markdown, "Coverage"),
    )
    assert coverage_match is not None
    assert int(coverage_match.group("attempted")) == coverage["attempted_issue_count"]
    assert int(coverage_match.group("total")) == corpus["issue_count"]

    truth_metrics = _table(markdown, "Truth Metrics")
    assert truth_metrics["Verified truth success rate (primary)"] == _format_percent(
        scorecard_payload["truth_metrics"]["truth_success_rate_verified"]
    )
    assert truth_metrics["Full-corpus truth success rate (legacy/context)"] == _format_percent(
        scorecard_payload["truth_metrics"]["truth_success_rate"]
    )
    assert truth_metrics["No-rescue truth success rate"] == _format_percent(
        scorecard_payload["truth_metrics"]["no_rescue_truth_success_rate"]
    )
    assert truth_metrics["Merged-only rate"] == _format_percent(
        scorecard_payload["truth_metrics"]["merged_only_rate"]
    )
    assert scorecard_payload["truth_metrics"] == truth_payload["primary_metrics"]
    assert scorecard_payload["truth_artifact_generated_at"] == truth_payload["generated_at"]

    in_flight_metrics = _table(markdown, "In-Flight Graduation Metrics")
    in_flight_payload = truth_payload["in_flight_metrics"]
    assert (
        _int_value(in_flight_metrics["In-progress expected issues"])
        == in_flight_payload["in_progress_expected_count"]
    )
    assert (
        _int_value(in_flight_metrics["In-progress attempted issues"])
        == in_flight_payload["in_progress_attempted_count"]
    )
    assert (
        _int_value(in_flight_metrics["In-progress successful issues"])
        == in_flight_payload["in_progress_success_count"]
    )
    assert in_flight_metrics["In-progress graduation rate"] == _format_percent(
        in_flight_payload["in_progress_graduation_rate"]
    )
    assert (
        _issue_numbers(in_flight_metrics["Expected in-progress issue numbers"])
        == (in_flight_payload["in_progress_issue_numbers"])
    )
    in_progress_records = [
        record
        for record in truth_payload["issues"]
        if record.get("expected_status") == "in_progress"
    ]
    assert _issue_numbers(in_flight_metrics["Live-open expected issue numbers"]) == sorted(
        record["issue_number"]
        for record in in_progress_records
        if record.get("issue_state") == "OPEN"
    )
    assert _issue_numbers(in_flight_metrics["Live-closed expected issue numbers"]) == sorted(
        record["issue_number"]
        for record in in_progress_records
        if record.get("issue_state") == "CLOSED"
    )

    proxy_metrics = _table(markdown, "Proxy Metrics")
    proxy_payload = scorecard_payload["proxy_metrics"]
    assert proxy_metrics["Proxy no-rescue success rate"] == _format_percent(
        proxy_payload["no_rescue_success_rate"]
    )
    assert (
        _int_value(proxy_metrics["Unique issues attempted"])
        == proxy_payload["unique_issues_attempted"]
    )
    assert (
        _int_value(proxy_metrics["Unique issues succeeded"])
        == proxy_payload["unique_issues_succeeded"]
    )
    assert (
        _int_value(proxy_metrics["Unique issues failed"]) == proxy_payload["unique_issues_failed"]
    )
    assert (
        _int_value(proxy_metrics["Unique issues neutral"]) == proxy_payload["unique_issues_neutral"]
    )
    assert _int_value(proxy_metrics["Total ticks"]) == proxy_payload["total_ticks"]
    assert (
        _optional_section_bullets(markdown, "Proxy Neutral Class Distribution")
        == proxy_payload["neutral_classes"]
    )
    assert (
        _section_bullets(markdown, "Failure Class Distribution")
        == scorecard_payload["failure_class_distribution"]
    )
    assert (
        _section_bullets(markdown, "Rescue Counts By Type")
        == scorecard_payload["rescue_counts_by_type"]
    )


def test_tw03_rescue_productization_status_matches_latest_report_json() -> None:
    markdown = (REPO_ROOT / "docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md").read_text(
        encoding="utf-8"
    )
    report_path = _published_path(markdown, "Latest report")
    report_payload = _read_json(report_path)

    assert _last_updated(markdown) == report_payload["generated_at"]
    assert _bullet_value(markdown, "Rescue ledger path") == report_payload["ledger_path"]
    assert (
        _bullet_value(markdown, "Productization map") == report_payload["productization_map_path"]
    )

    # A publication whose rescue ledger was unavailable asserts no counts at all,
    # so the rendered surface must stay free of numbers rather than agree with them.
    # Legacy publications predate `source` entirely and keep the numeric contract.
    source = report_payload.get("source")
    if isinstance(source, dict) and source.get("status") != "available":
        assert report_payload["ok"] is False
        assert _bullet_value(markdown, "Rescue ledger status") != "available"
        for label in (
            "Repeated rescue classes",
            "Linked repeated classes",
            "Unlinked repeated classes",
            "One-off classes",
            "Below-threshold classes",
            "Issue drafts remaining",
        ):
            assert _bullet_value(markdown, label) == "n/a"
        assert report_payload["summary"] == {}
        assert report_payload["repeated_classes"] == []
        assert report_payload["issue_drafts"] == []
        return

    summary = report_payload["summary"]
    linked_repeated_count = (
        summary["linked_fixture_count"]
        + summary["linked_issue_count"]
        + summary["linked_other_count"]
    )
    assert (
        int(_bullet_value(markdown, "Repeated rescue classes")) == summary["repeated_class_count"]
    )
    assert int(_bullet_value(markdown, "Linked repeated classes")) == linked_repeated_count
    assert (
        int(_bullet_value(markdown, "Unlinked repeated classes"))
        == summary["unlinked_repeated_class_count"]
    )
    assert int(_bullet_value(markdown, "One-off classes")) == summary["one_off_class_count"]
    assert (
        int(_bullet_value(markdown, "Below-threshold classes"))
        == summary["below_threshold_class_count"]
    )
    assert int(_bullet_value(markdown, "Issue drafts remaining")) == len(
        report_payload["issue_drafts"]
    )

    assert parse_repeated_class_rows(markdown) == expected_repeated_class_rows(
        report_payload["repeated_classes"]
    )
    assert parse_issue_linkage_actions(markdown) == expected_issue_linkage_actions(
        report_payload["issue_linkage_results"]
    )
    assert parse_issue_drafts(markdown) == expected_issue_drafts(report_payload["issue_drafts"])
    assert parse_counted_class_bullets(markdown, "One-Off Rescue Classes") == (
        expected_counted_class_bullets(report_payload["one_off_classes"])
    )
    assert parse_counted_class_bullets(markdown, "Below-Threshold Rescue Classes") == (
        expected_counted_class_bullets(report_payload["below_threshold_classes"])
    )
