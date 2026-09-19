from __future__ import annotations

import json
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


@pytest.mark.parametrize("generated_at", ["2026-09-04T13:28:39Z", "2026-09-05T13:28:39Z"])
def test_snapshot_disclosure_survives_regeneration_without_changing_inputs(
    tmp_path: Path, generated_at: str
) -> None:
    report = mod._load_json(mod.DEFAULT_REPORT_ROOT / "rescue-productization-20260904T132839Z.json")
    report["generated_at"] = generated_at
    source = tmp_path / "source"
    source.mkdir()
    latest = source / "latest.json"
    original = json.dumps(report, sort_keys=True)
    latest.write_text(original, encoding="utf-8")
    output = tmp_path / "TW03.md"
    args = ["--report-root", str(source), "--output", str(output)]
    assert mod.main(args) == 0
    rendered = output.read_bytes()
    assert mod.main(args) == 0
    assert output.read_bytes() == rendered
    assert latest.read_text(encoding="utf-8") == original
    text = rendered.decode()
    assert "Zero current observations do not erase historical rescues" in text
    assert "do not establish zero execution time" in text
    affected = generated_at == "2026-09-04T13:28:39Z"
    assert ("Snapshot-specific disclosure" in text) is affected
    assert "Observation availability warning" in text
    assert "raw inputs: `unavailable`" in text
    assert "rescue history: `incomplete`" in text
    if affected:
        assert "omits observations present in prior published snapshots" in text
        assert "2026-09-01T13:38:29Z" in text
        assert "rescue_worker_crash" in text
        assert "reset or replacement has not been independently proven" in text


@pytest.mark.parametrize("generated_at", ["2026-09-04T13:28:39Z", "2027-01-02T00:00:00Z"])
@pytest.mark.parametrize(
    "status,rows,warning",
    [
        ({}, [], "rescue history: `unknown`"),
        (
            {"raw_inputs": "unavailable", "rescue_history": "incomplete"},
            [{"class": "crash", "count": 1}],
            "raw inputs: `unavailable`",
        ),
        ({"raw_inputs": "available", "rescue_history": "complete"}, [], None),
        ({}, [{"class": "crash", "count": 1}], None),
    ],
)
def test_observation_warning_uses_report_data_not_timestamp(
    tmp_path: Path,
    generated_at: str,
    status: dict[str, str],
    rows: list[dict[str, object]],
    warning: str | None,
) -> None:
    payload = {"generated_at": generated_at, "observation_status": status, "one_off_classes": rows}
    before = json.dumps(payload, sort_keys=True)
    rendered = mod.render_status_markdown(report_path=tmp_path / "report.json", payload=payload)
    if warning:
        assert "Observation availability warning" in rendered
        assert warning in rendered
    else:
        assert "Observation availability warning" not in rendered
    assert json.dumps(payload, sort_keys=True) == before


@pytest.mark.parametrize("filename", ["latest.json", "rescue-productization-20260904T132839Z.json"])
def test_published_rescue_json_marks_unavailable_observations(filename: str) -> None:
    payload = mod._load_json(mod.DEFAULT_REPORT_ROOT / filename)
    assert payload["observation_status"] == {
        "raw_inputs": "unavailable",
        "elapsed_time": "unmeasured",
        "rescue_history": "incomplete",
        "raw_input_replay": "unmeasured",
    }
    assert {"summary", "repeated_classes", "one_off_classes", "below_threshold_classes"} <= set(
        payload["observation_limits"]["non_authoritative_fields"]
    )
    for reference in payload["observation_limits"]["historical_artifacts"]:
        assert (mod.REPO_ROOT / reference).is_file()
    assert payload == mod._load_json(mod.DEFAULT_REPORT_ROOT / "latest.json")


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


def test_tracked_legacy_report_does_not_claim_available_rescue_ledger() -> None:
    # Every publish rewrites latest.json, so the legacy shape is read from the
    # timestamped publication, which the publisher never overwrites.
    report_path = mod.DEFAULT_REPORT_ROOT / "rescue-productization-20260904T132839Z.json"
    payload = mod._load_json(report_path)
    assert "source" not in payload
    assert payload["observation_status"]["raw_inputs"] == "unavailable"

    markdown = mod.render_status_markdown(report_path=report_path, payload=payload)

    assert "Rescue ledger status: `available`" not in markdown
    assert "Rescue ledger status: `unavailable`" in markdown
    assert "Observation availability warning" in markdown
    assert "raw inputs: `unavailable`" in markdown
    # A legacy report carries no source error block, so no error detail may be invented.
    assert "Rescue ledger error" not in markdown

    summary = payload["summary"]
    linked = (
        summary["linked_fixture_count"]
        + summary["linked_issue_count"]
        + summary["linked_other_count"]
    )
    assert f"- Repeated rescue classes: `{summary['repeated_class_count']}`" in markdown
    assert f"- Linked repeated classes: `{linked}`" in markdown
    assert f"- Unlinked repeated classes: `{summary['unlinked_repeated_class_count']}`" in markdown
    assert f"- One-off classes: `{summary['one_off_class_count']}`" in markdown
    assert f"- Below-threshold classes: `{summary['below_threshold_class_count']}`" in markdown
    assert f"- Issue drafts remaining: `{len(payload['issue_drafts'])}`" in markdown
    assert "`n/a`" not in markdown
    assert "Not evaluated because the source ledger is unavailable." not in markdown


def test_tracked_latest_report_status_never_contradicts_its_observations() -> None:
    report_path = mod.DEFAULT_REPORT_ROOT / "latest.json"
    payload = mod._load_json(report_path)

    markdown = mod.render_status_markdown(report_path=report_path, payload=payload)

    assert "- Rescue ledger status: `" in markdown
    raw_inputs = (payload.get("observation_status") or {}).get("raw_inputs")
    if isinstance(raw_inputs, str) and raw_inputs != "available":
        assert "Rescue ledger status: `available`" not in markdown


def test_recorded_source_without_status_is_not_reported_available(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-08-30T03:00:00Z",
        "ledger_path": "~/.aragora/rescue_events.jsonl",
        "productization_map_path": "docs/benchmarks/rescue_productization.json",
        "source": {"event_count": None, "sha256": None},
        "summary": {"repeated_class_count": 4},
        "repeated_classes": [],
        "one_off_classes": [],
        "below_threshold_classes": [],
        "issue_linkage_results": [],
        "issue_drafts": [],
    }

    markdown = mod.render_status_markdown(report_path=tmp_path / "latest.json", payload=payload)

    assert "Rescue ledger status: `unknown`" in markdown
    assert "Rescue ledger status: `available`" not in markdown
    assert "- Repeated rescue classes: `n/a`" in markdown
    assert "No rescue-class conclusion is asserted" in markdown


def test_legacy_unavailable_report_preserves_numeric_values(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-05-01T00:00:00Z",
        "ledger_path": "~/.aragora/rescue_events.jsonl",
        "productization_map_path": "docs/benchmarks/rescue_productization.json",
        "observation_status": {"raw_inputs": "unavailable", "rescue_history": "incomplete"},
        "summary": {
            "repeated_class_count": 3,
            "linked_fixture_count": 1,
            "linked_issue_count": 1,
            "linked_other_count": 0,
            "unlinked_repeated_class_count": 1,
            "one_off_class_count": 2,
            "below_threshold_class_count": 1,
        },
        "repeated_classes": [
            {
                "class": "manual_merge:required review gate",
                "count": 4,
                "productization_status": "unlinked",
                "productization_target": "",
                "issue_numbers": [],
            }
        ],
        "one_off_classes": [{"class": "issue_rewrite:scope drift", "count": 1}],
        "below_threshold_classes": [{"class": "flake:timeout", "count": 1}],
        "issue_linkage_results": [],
        "issue_drafts": [],
    }

    markdown = mod.render_status_markdown(report_path=tmp_path / "latest.json", payload=payload)

    assert "Rescue ledger status: `unavailable`" in markdown
    assert "Rescue ledger status: `available`" not in markdown
    assert "Rescue ledger error" not in markdown
    assert "- Repeated rescue classes: `3`" in markdown
    assert "- Linked repeated classes: `2`" in markdown
    assert "- One-off classes: `2`" in markdown
    assert "- Below-threshold classes: `1`" in markdown
    assert parse_repeated_class_rows(markdown) == expected_repeated_class_rows(
        payload["repeated_classes"]
    )
    assert parse_counted_class_bullets(markdown, "One-Off Rescue Classes") == (
        expected_counted_class_bullets(payload["one_off_classes"])
    )
    assert "Not evaluated because the source ledger is unavailable." not in markdown


def test_legacy_report_without_provenance_markers_reports_unknown_status(tmp_path: Path) -> None:
    payload = {
        "generated_at": "2026-04-14T18:45:47Z",
        "ledger_path": "~/.aragora/rescue_events.jsonl",
        "productization_map_path": "docs/benchmarks/rescue_productization.json",
        "summary": {
            "repeated_class_count": 1,
            "linked_fixture_count": 0,
            "linked_issue_count": 0,
            "linked_other_count": 0,
            "unlinked_repeated_class_count": 1,
            "one_off_class_count": 0,
            "below_threshold_class_count": 0,
        },
        "repeated_classes": [
            {
                "class": "manual_merge:required review gate",
                "count": 2,
                "productization_status": "unlinked",
                "productization_target": "",
                "issue_numbers": [],
            }
        ],
        "one_off_classes": [],
        "below_threshold_classes": [],
        "issue_linkage_results": [],
        "issue_drafts": [],
    }

    markdown = mod.render_status_markdown(report_path=tmp_path / "latest.json", payload=payload)

    assert "Rescue ledger status: `unknown`" in markdown
    assert "Rescue ledger status: `available`" not in markdown
    assert "Rescue ledger error" not in markdown
    assert "- Repeated rescue classes: `1`" in markdown
    assert parse_repeated_class_rows(markdown) == expected_repeated_class_rows(
        payload["repeated_classes"]
    )


def test_recorded_available_source_still_renders_available(tmp_path: Path) -> None:
    payload = {
        "ok": True,
        "generated_at": "2026-08-30T02:00:00Z",
        "ledger_path": "~/.aragora/rescue_events.jsonl",
        "productization_map_path": "docs/benchmarks/rescue_productization.json",
        "source": {"status": "available", "event_count": 5, "sha256": "a" * 64},
        "observation_status": {"raw_inputs": "available", "rescue_history": "complete"},
        "summary": {
            "repeated_class_count": 1,
            "linked_fixture_count": 0,
            "linked_issue_count": 0,
            "linked_other_count": 0,
            "unlinked_repeated_class_count": 1,
            "one_off_class_count": 0,
            "below_threshold_class_count": 0,
        },
        "repeated_classes": [
            {
                "class": "manual_merge:required review gate",
                "count": 2,
                "productization_status": "unlinked",
                "productization_target": "",
                "issue_numbers": [],
            }
        ],
        "one_off_classes": [],
        "below_threshold_classes": [],
        "issue_linkage_results": [],
        "issue_drafts": [],
    }

    markdown = mod.render_status_markdown(report_path=tmp_path / "latest.json", payload=payload)

    assert "Rescue ledger status: `available`" in markdown
    assert "Rescue ledger error" not in markdown
    assert "- Repeated rescue classes: `1`" in markdown
    assert "Observation availability warning" not in markdown


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
