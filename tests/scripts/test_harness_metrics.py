from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import harness_metrics


AS_OF = datetime(2026, 8, 29, tzinfo=UTC)


def _event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "timestamp": "2026-08-20T00:00:00Z",
        "lane_id": "conductor-a",
        "fleet": "codex",
        "agent_type": "codex",
        "cycle_id": "cycle-1",
        "pr_number": 101,
        "external_progress": True,
        "first_round_gate_pass": True,
        "review_round": 1,
        "merged": True,
        "token_cost_total": 2.5,
    }
    event.update(overrides)
    return event


def _normalized(records: list[dict[str, object]]) -> list[harness_metrics.Event]:
    return [
        normalized
        for index, record in enumerate(records)
        if (normalized := harness_metrics.normalize_event(record, f"fixture:{index}")) is not None
    ]


def test_scoreboard_computes_four_metrics_and_reports_insufficient_groups() -> None:
    records = [
        _event(),
        _event(
            cycle_id="cycle-2",
            pr_number=102,
            external_progress=False,
            first_round_gate_pass=False,
            review_round=3,
            token_cost_total=5.0,
        ),
        _event(
            lane_id="conductor-b",
            fleet="claude",
            agent_type="claude",
            cycle_id="cycle-3",
            pr_number=None,
            external_progress=False,
            first_round_gate_pass=None,
            review_round=None,
            merged=False,
            token_cost_total=None,
        ),
    ]
    report = harness_metrics.build_report(
        _normalized(records),
        as_of=AS_OF,
        window_days=30,
        fixture_rate=0.5,
        drift_threshold=0.15,
        warnings=[],
        sources=["fixture"],
    )

    lanes = {row["key"]: row for row in report["dimensions"]["conductor_lane"]}
    assert lanes["conductor-a"]["first_round_gate_pass_rate"] == 0.5
    assert lanes["conductor-a"]["rounds_to_merge_average"] == 2.0
    assert lanes["conductor-a"]["external_progress_per_cycle"] == 0.5
    assert lanes["conductor-a"]["token_cost_per_merged_pr"] == 3.75
    assert lanes["conductor-b"]["first_round_gate_pass_rate"] is None
    assert "first_round_gate_pass_rate" in lanes["conductor-b"]["insufficient_data"]
    assert report["judge_drift"]["status"] == "ok"


def test_duplicate_pr_observations_are_monotone_and_conflicts_are_excluded() -> None:
    records = [
        _event(),
        _event(cycle_id="cycle-1", review_round=2, token_cost_total=3.0),
        _event(cycle_id="cycle-1", external_progress=False, review_round=2, token_cost_total=3.0),
    ]
    summary = harness_metrics.summarize_group(_normalized(records), "conductor-a")

    assert summary["merged_pr_count"] == 1
    assert summary["rounds_to_merge_average"] == 2.0
    assert summary["token_cost_per_merged_pr"] == 3.0
    assert summary["external_progress_observations"] == 0
    assert summary["external_progress_per_cycle"] is None


def test_github_metadata_top_level_number_joins_pr_inventory() -> None:
    github_record = {
        "number": 101,
        "mergedAt": "2026-08-21T00:00:00Z",
        "headRefName": "conductor-a",
        "author": {"login": "codex"},
    }
    github_event = harness_metrics.normalize_event(github_record, "github")
    ledger_event = harness_metrics.normalize_event(_event(), "ledger")

    assert github_event is not None
    assert ledger_event is not None
    assert github_event.pr_number == ledger_event.pr_number == 101
    assert harness_metrics.summarize_group([github_event], "conductor-a")["merged_pr_count"] == 1

    summary = harness_metrics.summarize_group([ledger_event, github_event], "conductor-a")
    assert summary["merged_pr_count"] == 1
    assert summary["rounds_to_merge_average"] == 1.0
    assert summary["token_cost_per_merged_pr"] == 2.5


def test_github_metadata_warns_when_search_result_reaches_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {
            "number": number,
            "mergedAt": "2026-08-21T00:00:00Z",
            "headRefName": f"branch-{number}",
            "author": {"login": "codex"},
        }
        for number in range(harness_metrics.GH_METADATA_SEARCH_LIMIT)
    ]
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_: object) -> object:
        commands.append(command)
        return harness_metrics.subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(rows),
            stderr="",
        )

    monkeypatch.setattr(harness_metrics.subprocess, "run", fake_run)
    warnings: list[str] = []

    records = harness_metrics.load_gh_metadata("synaptent/aragora", AS_OF, warnings)

    assert len(records) == harness_metrics.GH_METADATA_SEARCH_LIMIT
    assert commands[0][commands[0].index("--limit") + 1] == str(
        harness_metrics.GH_METADATA_SEARCH_LIMIT
    )
    assert warnings == [
        "gh metadata may be truncated: GitHub search returned its "
        f"{harness_metrics.GH_METADATA_SEARCH_LIMIT}-result ceiling"
    ]


def test_cli_is_offline_deterministic_and_emits_one_json_and_one_table(
    tmp_path: Path, capsys: object
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(_event()) + "\n{broken\n", encoding="utf-8")
    metadata = tmp_path / "prs.json"
    metadata.write_text(
        json.dumps(
            [
                {
                    "number": 101,
                    "mergedAt": "2026-08-21T00:00:00Z",
                    "headRefName": "conductor-a",
                    "author": {"login": "codex"},
                }
            ]
        ),
        encoding="utf-8",
    )
    eval_results = tmp_path / "eval.json"
    eval_results.write_text(json.dumps([{"passed": True}, {"passed": False}]), encoding="utf-8")
    json_out = tmp_path / "latest.json"

    result = harness_metrics.main(
        [
            "--repo-root",
            str(tmp_path),
            "--ledger",
            str(ledger),
            "--receipt-dir",
            str(tmp_path / "missing-receipts"),
            "--pr-metadata",
            str(metadata),
            "--eval-results",
            str(eval_results),
            "--as-of",
            "2026-08-29T00:00:00Z",
            "--json-out",
            str(json_out),
        ]
    )

    assert result == 0
    report = json.loads(json_out.read_text(encoding="utf-8"))
    assert report["schema_version"] == harness_metrics.SCHEMA_VERSION
    assert any("invalid JSONL" in warning for warning in report["warnings"])
    assert any("missing receipt directory" in warning for warning in report["warnings"])
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    assert captured.out.count("| Dimension | Group |") == 1
    assert "conductor_lane" in captured.out


def test_out_of_window_and_missing_timestamp_records_do_not_enter_report(tmp_path: Path) -> None:
    warnings: list[str] = []
    records = [
        (_event(timestamp="2026-06-01T00:00:00Z"), "old"),
        ({"external_progress": True}, "missing-time"),
    ]
    events = []
    start = AS_OF.replace(day=1)
    for record, source in records:
        event = harness_metrics.normalize_event(record, source)
        if event is None:
            warnings.append(source)
        elif start <= event.timestamp <= AS_OF:
            events.append(event)

    report = harness_metrics.build_report(
        events,
        as_of=AS_OF,
        window_days=28,
        fixture_rate=None,
        drift_threshold=0.15,
        warnings=warnings,
        sources=[source for _, source in records],
    )
    assert report["dimensions"]["conductor_lane"] == []
    assert report["judge_drift"]["status"] == "insufficient_data"
    assert warnings == ["missing-time"]
