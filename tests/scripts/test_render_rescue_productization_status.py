from __future__ import annotations

import sys
from pathlib import Path

import pytest

_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import render_rescue_productization_status as mod  # noqa: E402

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


def test_render_status_markdown_includes_repeated_classes_and_actions(tmp_path: Path) -> None:
    report_path = tmp_path / "latest.json"
    payload = {
        "generated_at": "2026-04-14T18:40:00Z",
        "ledger_path": "/Users/test/.aragora/rescue_events.jsonl",
        "productization_map_path": "docs/benchmarks/rescue_productization.json",
        "summary": {
            "repeated_class_count": 2,
            "linked_fixture_count": 0,
            "linked_issue_count": 1,
            "linked_other_count": 0,
            "unlinked_repeated_class_count": 1,
            "one_off_class_count": 1,
            "below_threshold_class_count": 0,
        },
        "repeated_classes": [
            {
                "class": "followup_prompt:needs explicit next step from founder",
                "count": 2,
                "productization_status": "linked_issue",
                "productization_target": "#6001",
                "issue_numbers": [5512, 5515],
            },
            {
                "class": "manual_merge:required review gate",
                "count": 2,
                "productization_status": "unlinked",
                "productization_target": "",
                "issue_numbers": [5617],
            },
        ],
        "issue_linkage_results": [
            {
                "class": "followup_prompt:needs explicit next step from founder",
                "action": "linked_existing_issue",
                "target": "#6001",
                "url": "https://github.com/synaptent/aragora/issues/6001",
            }
        ],
        "issue_drafts": [
            {
                "class": "manual_merge:required review gate",
                "title": "[TW-03] Productize repeated rescue class: manual-merge-required-review-gate",
            }
        ],
        "one_off_classes": [
            {"class": "issue_rewrite:scope contradicted itself", "count": 1},
        ],
        "below_threshold_classes": [],
    }

    markdown = mod.render_status_markdown(report_path=report_path, payload=payload)

    assert "# TW-03 Rescue Productization Status" in markdown
    assert parse_repeated_class_rows(markdown) == expected_repeated_class_rows(
        payload["repeated_classes"]
    )
    assert parse_issue_linkage_actions(markdown) == expected_issue_linkage_actions(
        payload["issue_linkage_results"]
    )
    assert parse_issue_drafts(markdown) == expected_issue_drafts(payload["issue_drafts"])
    assert parse_counted_class_bullets(markdown, "One-Off Rescue Classes") == (
        expected_counted_class_bullets(payload["one_off_classes"])
    )
    assert parse_counted_class_bullets(markdown, "Below-Threshold Rescue Classes") == []
    assert "Issue drafts remaining: `1`" in markdown


def test_main_writes_output_from_latest_report(tmp_path: Path) -> None:
    report_root = tmp_path / "generated" / "rescue_productization"
    report_root.mkdir(parents=True)
    latest_path = report_root / "latest.json"
    latest_path.write_text(
        """{
  "generated_at": "2026-04-14T18:42:00Z",
  "ledger_path": "/Users/test/.aragora/rescue_events.jsonl",
  "productization_map_path": "docs/benchmarks/rescue_productization.json",
  "summary": {
    "repeated_class_count": 0,
    "linked_fixture_count": 0,
    "linked_issue_count": 0,
    "linked_other_count": 0,
    "unlinked_repeated_class_count": 0,
    "one_off_class_count": 0,
    "below_threshold_class_count": 0
  },
  "repeated_classes": [],
  "issue_linkage_results": [],
  "issue_drafts": [],
  "one_off_classes": [],
  "below_threshold_classes": []
}
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "TW03_RESCUE_PRODUCTIZATION_STATUS.md"

    exit_code = mod.main(
        [
            "--report-root",
            str(report_root),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    rendered = output_path.read_text(encoding="utf-8")
    assert "No repeated rescue classes found in the current ledger window." in rendered
    assert "Last updated: 2026-04-14T18:42:00Z" in rendered


def test_render_unavailable_source_does_not_claim_zero_rescue_classes(tmp_path: Path) -> None:
    report_path = tmp_path / "latest.json"
    payload = {
        "ok": False,
        "generated_at": "2026-08-30T01:30:00Z",
        "ledger_path": "~/.aragora/rescue_events.jsonl",
        "productization_map_path": "docs/benchmarks/rescue_productization.json",
        "source": {
            "status": "unavailable",
            "event_count": None,
            "sha256": None,
            "error": {
                "code": "rescue_ledger_missing",
                "detail": "rescue event ledger does not exist",
            },
        },
        "summary": {},
        "repeated_classes": [],
        "issue_linkage_results": [],
        "issue_drafts": [],
        "one_off_classes": [],
        "below_threshold_classes": [],
    }

    markdown = mod.render_status_markdown(report_path=report_path, payload=payload)

    assert "Rescue ledger status: `unavailable`" in markdown
    assert "Repeated rescue classes: `n/a`" in markdown
    assert "Issue drafts remaining: `n/a`" in markdown
    assert "No rescue-class conclusion is asserted" in markdown
    assert markdown.count("Not evaluated because the source ledger is unavailable.") == 4
    assert "No repeated rescue classes found" not in markdown


def test_main_refuses_to_downgrade_existing_status_from_stale_report(tmp_path: Path) -> None:
    report_root = tmp_path / "generated" / "rescue_productization"
    report_root.mkdir(parents=True)
    latest_path = report_root / "latest.json"
    latest_path.write_text(
        """{
  "generated_at": "2026-06-04T13:31:36Z",
  "ledger_path": "/Users/test/.aragora/rescue_events.jsonl",
  "productization_map_path": "docs/benchmarks/rescue_productization.json",
  "summary": {
    "repeated_class_count": 0,
    "linked_fixture_count": 0,
    "linked_issue_count": 0,
    "linked_other_count": 0,
    "unlinked_repeated_class_count": 0,
    "one_off_class_count": 0,
    "below_threshold_class_count": 0
  },
  "repeated_classes": [],
  "issue_linkage_results": [],
  "issue_drafts": [],
  "one_off_classes": [],
  "below_threshold_classes": []
}
""",
        encoding="utf-8",
    )
    output_path = tmp_path / "TW03_RESCUE_PRODUCTIZATION_STATUS.md"
    original = "# TW-03 Rescue Productization Status\n\nLast updated: 2026-06-14T03:48:49Z\n"
    output_path.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to render stale rescue productization report"):
        mod.main(
            [
                "--report-root",
                str(report_root),
                "--output",
                str(output_path),
            ]
        )

    assert output_path.read_text(encoding="utf-8") == original
