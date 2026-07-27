from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_module() -> Any:
    script = Path(__file__).resolve().parents[2] / "scripts" / "harness_metrics.py"
    spec = importlib.util.spec_from_file_location("harness_metrics_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness_metrics = _load_module()
AS_OF = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def _write_eval_fixture(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "adjudicator_eval_cases.v1",
                "cases": [
                    {"id": "a", "passed": True},
                    {"id": "b", "passed": False},
                    {"id": "c", "passed": False},
                    {"id": "d", "passed": False},
                ],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_build_report_computes_lane_metrics_and_drift_alarm(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "external_progress": True,
                "first_round_gate_pass": True,
                "direct_pr_merged": 1001,
                "rounds_to_merge": 2,
                "token_cost": 12.5,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "external_progress": False,
                "first_round_gate_pass": False,
            },
            {
                "timestamp": "2026-07-08T11:30:00Z",
                "lane": "scout",
                "external_progress": True,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[tmp_path / "missing-receipts"],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=30,
        drift_threshold=0.2,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert report["schema_version"] == "harness_metrics.v1"
    assert report["fixture_performance"]["fixture_pass_rate"] == 0.25
    assert lanes["conductor"]["cycles"] == 2
    assert lanes["conductor"]["external_progress_per_cycle"] == 0.5
    assert lanes["conductor"]["first_round_gate_pass_rate"] == 0.5
    assert lanes["conductor"]["rounds_to_merge_average"] == 2.0
    assert lanes["conductor"]["token_cost_per_merged_pr"] == 12.5
    assert lanes["conductor"]["drift_check"]["alarm"] is True
    assert lanes["scout"]["insufficient_data"] == [
        "first_round_gate_pass_rate",
        "rounds_to_merge_average:no_merged_prs",
        "token_cost_per_merged_pr:no_merged_prs",
    ]


def test_window_filtering_and_receipt_store_support(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-06-01T00:00:00Z",
                "lane": "old",
                "external_progress": True,
            },
            {
                "timestamp": "2026-07-08T00:00:00Z",
                "lane": "recent",
                "external_progress": "success",
                "first_round_gate_pass": "passed",
            },
        ],
    )
    (receipts / "merge.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-08T01:00:00Z",
                "action": "admin_squash_merge",
                "direct_pr_merged": "#2002",
                "token_usage": {"total_cost_usd": 4.0},
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert "old" not in lanes
    assert lanes["recent"]["first_round_gate_pass_rate"] == 1.0
    assert lanes["receipt_store"]["first_round_gate_pass_rate"] is None
    assert lanes["receipt_store"]["merged_prs"] == 1
    assert lanes["receipt_store"]["token_cost_total"] == 4.0


def test_receipt_gate_pass_observations_are_counted(tmp_path: Path) -> None:
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    (receipts / "gate.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-08T01:00:00Z",
                "first_round_gate_pass": True,
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 0
    assert lane["first_round_gate_pass_rate"] == 1.0


def test_receipts_use_reviewed_at_timestamp(tmp_path: Path) -> None:
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    (receipts / "merge.json").write_text(
        json.dumps(
            {
                "reviewed_at": "2026-07-08T01:00:00Z",
                "action": "admin_squash_merge",
                "direct_pr_merged": "#2002",
                "token_usage": {"total_cost_usd": 4.0},
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert lanes["receipt_store"]["merged_prs"] == 1
    assert lanes["receipt_store"]["token_cost_total"] == 4.0


def test_receipt_admin_squash_merge_action_counts_pr_number(
    tmp_path: Path,
) -> None:
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    (receipts / "merge.json").write_text(
        json.dumps(
            {
                "reviewed_at": "2026-07-08T01:00:00Z",
                "action": "admin_squash_merge",
                "pr_number": 2002,
                "rounds_to_merge": 3,
                "token_usage": {"total_cost_usd": 4.0},
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 1
    assert lane["rounds_to_merge_average"] == 3.0
    assert lane["token_cost_per_merged_pr"] == 4.0


def test_external_progress_negative_outcomes_are_not_positive_substrings(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {"timestamp": "2026-07-08T08:00:00Z", "lane": "a", "outcome": "unmerged"},
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "outcome": "pushed_failed",
            },
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "a",
                "outcome": "not completed",
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "a",
                "outcome": "repaired: false",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 4
    assert lane["external_progress_per_cycle"] == 0.0


def test_external_progress_positive_outcome_tokens_are_counted(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {"timestamp": "2026-07-08T08:00:00Z", "lane": "a", "outcome": "true"},
            {"timestamp": "2026-07-08T09:00:00Z", "lane": "a", "status": "yes"},
            {"timestamp": "2026-07-08T10:00:00Z", "lane": "a", "result": "y"},
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 3
    assert lane["external_progress_cycles"] == 3
    assert lane["external_progress_per_cycle"] == 1.0


def test_external_progress_false_and_zero_outcomes_are_observed(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {"timestamp": "2026-07-08T08:00:00Z", "lane": "a", "outcome": False},
            {"timestamp": "2026-07-08T09:00:00Z", "lane": "a", "status": 0},
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["external_progress_cycles"] == 0
    assert lane["external_progress_per_cycle"] == 0.0


def test_external_progress_mutation_fields_coerce_string_false(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T08:00:00Z",
                "lane": "a",
                "mutations": {"push": "false"},
            },
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "mutations": {"merge": "yes"},
            },
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "a",
                "mutations": {"github_status": "posted"},
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 3
    assert lane["external_progress_cycles"] == 2
    assert lane["external_progress_per_cycle"] == 2 / 3


def test_external_progress_mutation_fields_use_or_semantics(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T08:00:00Z",
                "lane": "a",
                "mutations": {"push": "false", "merge": "true"},
            },
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "mutations": {"push": False, "issue_comment": "posted"},
            },
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "a",
                "mutations": {"push": "false", "merge": "no"},
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 3
    assert lane["external_progress_cycles"] == 2
    assert lane["external_progress_per_cycle"] == 2 / 3


def test_merged_pr_references_count_as_external_progress(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T08:00:00Z",
                "lane": "a",
                "direct_pr_merged": 1001,
            },
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "direct_pr_merged": "#1002",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 2
    assert lane["external_progress_cycles"] == 2
    assert lane["external_progress_per_cycle"] == 1.0


def test_external_progress_positive_outcome_overrides_false_mutation_sentinel(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T08:00:00Z",
                "lane": "a",
                "direct_pr_merged": False,
                "outcome": "success",
            },
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "mutations": {"push": False},
                "status": "complete",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 2
    assert lane["external_progress_cycles"] == 2
    assert lane["external_progress_per_cycle"] == 1.0


def test_external_progress_mutations_override_failed_outcome(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T08:00:00Z",
                "lane": "a",
                "outcome": "failed",
                "mutations": {"issue_comment": "posted"},
            },
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "status": "failed",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 2
    assert lane["external_progress_cycles"] == 1
    assert lane["external_progress_per_cycle"] == 0.5


def test_external_progress_unknown_mutation_values_are_insufficient(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T08:00:00Z",
                "lane": "a",
                "mutations": {"push": "pending"},
            },
            {
                "timestamp": "2026-07-08T09:00:00Z",
                "lane": "a",
                "mutations": {"merge": []},
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 2
    assert lane["external_progress_cycles"] == 0
    assert lane["external_progress_per_cycle"] is None


def test_pr_number_parsing_requires_whole_pr_token() -> None:
    assert harness_metrics._coerce_pr_number("#1234") == 1234
    assert harness_metrics._coerce_pr_number("PR #1234") == 1234
    assert harness_metrics._coerce_pr_number("0") is None
    assert harness_metrics._coerce_pr_number("9790cdd") is None
    assert harness_metrics._coerce_pr_number("v2-migration") is None


def test_malformed_jsonl_records_are_skipped(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    ledger.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-07-08T10:00:00Z",
                        "lane": "valid",
                        "external_progress": True,
                    }
                ),
                "{not-json",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert lanes["valid"]["cycles"] == 1


def test_extensionless_jsonl_records_are_parsed(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "valid",
                "external_progress": True,
            }
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    assert report["lanes"][0]["lane"] == "valid"


def test_numeric_timestamp_overflow_returns_none() -> None:
    assert harness_metrics.parse_timestamp(999999999999999999999) is None


def test_boolean_timestamp_returns_none() -> None:
    assert harness_metrics.parse_timestamp(True) is None
    assert harness_metrics.parse_timestamp(False) is None


def test_lowercase_z_timestamp_is_accepted() -> None:
    parsed = harness_metrics.parse_timestamp("2026-07-08T10:00:00z")
    assert parsed is not None
    assert parsed.isoformat() == "2026-07-08T10:00:00+00:00"


def test_malformed_eval_fixture_degrades_to_no_cases(tmp_path: Path) -> None:
    fixture = tmp_path / "eval.json"
    fixture.write_text("{not-json", encoding="utf-8")

    result = harness_metrics.fixture_performance(fixture)

    assert result["available"] is True
    assert result["case_count"] == 0
    assert result["fixture_pass_rate"] is None


def test_directory_eval_fixture_degrades_to_no_cases(tmp_path: Path) -> None:
    result = harness_metrics.fixture_performance(tmp_path)

    assert result["available"] is True
    assert result["case_count"] == 0
    assert result["fixture_pass_rate"] is None


def test_flat_dotted_record_keys_are_resolved(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "progress.external": True,
                "first_round_gate_pass": True,
                "direct_pr_merged": "#1001",
                "rounds_to_merge": 2,
                "token_usage.total_cost_usd": 7.5,
            }
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["external_progress_per_cycle"] == 1.0
    assert lane["token_cost_total"] == 7.5


def test_duplicate_merged_pr_records_do_not_double_count_merge_metrics(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": 1001,
                "rounds_to_merge": 2,
                "token_cost": 12.5,
            }
        ],
    )
    (receipts / "merge.json").write_text(
        json.dumps(
            {
                "reviewed_at": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": "#1001",
                "token_usage": {"total_cost_usd": 12.5},
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 1
    assert lane["rounds_to_merge_average"] == 2.0
    assert lane["token_cost_total"] == 12.5


def test_distinct_cost_events_for_same_merged_pr_are_preserved(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "cycle_id": "cycle-a",
                "direct_pr_merged": 1001,
                "token_cost": 2.0,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "cycle_id": "cycle-b",
                "direct_pr_merged": 1001,
                "token_cost": 2.0,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 1
    assert lane["token_cost_total"] == 4.0
    assert lane["token_cost_per_merged_pr"] == 4.0


def test_decision_receipt_cost_summary_is_counted(tmp_path: Path) -> None:
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    (receipts / "decision.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": 1001,
                "cost_summary": {"total_cost_usd": "4.25"},
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["token_cost_total"] == 4.25
    assert lane["token_cost_per_merged_pr"] == 4.25


def test_repeated_non_merge_pr_cycles_keep_token_cost_observations(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "pr_number": 1001,
                "token_cost": 2.0,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "pr_number": "#1001",
                "token_cost": 3.0,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 2
    assert lane["merged_prs"] == 0
    assert lane["token_cost_total"] == 5.0


def test_repeated_non_merge_pr_cycles_with_same_cost_are_not_pr_deduped(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "pr_number": 1001,
                "token_cost": 2.0,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "pr_number": "#1001",
                "token_cost": 2.0,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 2
    assert lane["merged_prs"] == 0
    assert lane["token_cost_total"] == 4.0


def test_duplicate_non_merge_token_cost_records_are_not_double_counted(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "cycle_id": "cycle-1",
                "token_cost": 2.0,
            }
        ],
    )
    (receipts / "cost.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "cycle_id": "cycle-1",
                "token_cost": 2.0,
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 1
    assert lane["merged_prs"] == 0
    assert lane["token_cost_total"] == 2.0


def test_merge_sentinel_token_cost_uses_stable_non_merge_identity(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "cycle_id": "cycle-1",
                "direct_pr_merged": True,
                "token_cost": 2.0,
            }
        ],
    )
    (receipts / "cost.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "cycle_id": "cycle-1",
                "direct_pr_merged": True,
                "token_cost": 2.0,
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 0
    assert lane["token_cost_total"] == 2.0


def test_receipts_do_not_count_as_lane_cycles(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "external_progress": False,
            }
        ],
    )
    (receipts / "merge.json").write_text(
        json.dumps(
            {
                "created_at": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "action": "admin_squash_merge",
                "direct_pr_merged": "#2002",
                "token_usage": {"total_cost_usd": 4.0},
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = {lane["lane"]: lane for lane in report["lanes"]}["conductor"]
    assert lane["cycles"] == 1
    assert lane["external_progress_per_cycle"] == 0.0
    assert lane["merged_prs"] == 1
    assert lane["token_cost_total"] == 4.0


def test_receipt_packet_entries_are_flattened(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "receipt_store",
            }
        ],
    )
    (receipts / "packet.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-07-08T11:00:00Z",
                "entries": [
                    {
                        "action": "admin_squash_merge",
                        "pr_number": 2002,
                        "rounds_to_merge": 3,
                        "token_usage": {"total_cost_usd": 4.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[receipts],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = {lane["lane"]: lane for lane in report["lanes"]}["receipt_store"]
    assert lane["cycles"] == 1
    assert lane["merged_prs"] == 1
    assert lane["rounds_to_merge_average"] == 3.0
    assert lane["token_cost_total"] == 4.0


def test_external_progress_rate_uses_observed_lane_cycles(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "external_progress": True,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 2
    assert lane["external_progress_per_cycle"] == 1.0


def test_external_progress_rate_is_insufficient_without_observations(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lane = report["lanes"][0]
    assert lane["cycles"] == 1
    assert lane["external_progress_per_cycle"] is None
    assert "external_progress_per_cycle" in lane["insufficient_data"]


def test_window_filtering_excludes_future_events(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "current",
                "external_progress": True,
            },
            {
                "timestamp": "2026-07-09T00:00:00Z",
                "lane": "future",
                "external_progress": True,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert "current" in lanes
    assert "future" not in lanes


def test_window_filtering_excludes_undated_events(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "dated",
                "external_progress": True,
            },
            {
                "lane": "undated",
                "external_progress": True,
            },
            {
                "timestamp": "not-a-timestamp",
                "lane": "ambiguous",
                "external_progress": True,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=7,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert "dated" in lanes
    assert "undated" not in lanes
    assert "ambiguous" not in lanes


def test_rounds_to_merge_average_uses_only_merged_records(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": 1001,
                "rounds_to_merge": 2,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "rounds_to_merge": 8,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=30,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 1
    assert lane["rounds_to_merge_average"] == 2.0


def test_merged_pr_detection_ignores_boolean_sentinel_before_pr_number(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": True,
                "pr_number": 1001,
                "rounds_to_merge": 2,
                "token_cost": 12.5,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=30,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 1
    assert lane["rounds_to_merge_average"] == 2.0
    assert lane["token_cost_per_merged_pr"] == 12.5


def test_merged_pr_detection_coerces_string_sentinels_before_pr_number(
    tmp_path: Path,
) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": "true",
                "pr_number": "1001",
                "rounds_to_merge": 2,
                "token_cost": 12.5,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "conductor",
                "direct_pr_merged": "false",
                "pr_number": "1002",
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=30,
    )

    lane = report["lanes"][0]
    assert lane["merged_prs"] == 1
    assert lane["rounds_to_merge_average"] == 2.0
    assert lane["token_cost_per_merged_pr"] == 12.5


def test_merged_pr_detection_preserves_pr_one_values(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "numeric",
                "direct_pr_merged": 1,
                "rounds_to_merge": 2,
            },
            {
                "timestamp": "2026-07-08T11:00:00Z",
                "lane": "string",
                "direct_pr_merged": "1",
                "rounds_to_merge": 3,
            },
        ],
    )

    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=30,
    )

    lanes = {lane["lane"]: lane for lane in report["lanes"]}
    assert lanes["numeric"]["merged_prs"] == 1
    assert lanes["numeric"]["rounds_to_merge_average"] == 2.0
    assert lanes["string"]["merged_prs"] == 1
    assert lanes["string"]["rounds_to_merge_average"] == 3.0


def test_render_markdown_escapes_table_cells() -> None:
    report = {
        "lanes": [
            {
                "lane": "lane|with\nbreak",
                "cycles": 1,
                "external_progress_per_cycle": None,
                "first_round_gate_pass_rate": None,
                "rounds_to_merge_average": None,
                "token_cost_per_merged_pr": None,
                "merged_prs": 0,
                "drift_check": {"alarm": False},
                "insufficient_data": ["needs|data\nagain"],
            }
        ]
    }

    markdown = harness_metrics.render_markdown(report)

    assert "lane\\|with break" in markdown
    assert "needs\\|data again" in markdown
    assert len(markdown.strip().splitlines()) == 3


def test_render_markdown_is_single_table(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    fixture = tmp_path / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "external_progress": True,
                "first_round_gate_pass": True,
            }
        ],
    )
    report = harness_metrics.build_report(
        ledger_paths=[ledger],
        receipt_dirs=[],
        eval_fixture=fixture,
        as_of=AS_OF,
        window_days=30,
    )

    markdown = harness_metrics.render_markdown(report)

    assert len(markdown.strip().splitlines()) == 3
    assert "| conductor | 1 | 100% | 100% |" in markdown
    assert "first_round_gate_pass_rate" not in markdown


def test_cli_writes_one_json_document_and_one_markdown_table(tmp_path: Path) -> None:
    repo = tmp_path
    ledger = repo / "ledger.jsonl"
    fixture = repo / "eval.json"
    json_out = repo / "nested" / "latest.json"
    md_out = repo / "nested" / "latest.md"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "external_progress": True,
                "first_round_gate_pass": True,
            }
        ],
    )

    exit_code = harness_metrics.main(
        [
            "--repo-root",
            str(repo),
            "--ledger",
            str(ledger),
            "--receipt-dir",
            str(repo / "missing"),
            "--eval-fixture",
            str(fixture),
            "--as-of",
            "2026-07-08T12:00:00Z",
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(md_out),
        ]
    )

    assert exit_code == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["lanes"][0]["lane"] == ("conductor")
    markdown = md_out.read_text(encoding="utf-8")
    assert markdown.startswith("| Lane |")
    assert markdown.count("| conductor |") == 1


def test_cli_relative_outputs_resolve_against_repo_root(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    repo.mkdir()
    outside.mkdir()
    ledger = repo / "ledger.jsonl"
    fixture = repo / "eval.json"
    _write_eval_fixture(fixture)
    _write_jsonl(
        ledger,
        [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "lane": "conductor",
                "external_progress": True,
                "first_round_gate_pass": True,
            }
        ],
    )
    monkeypatch.chdir(outside)

    exit_code = harness_metrics.main(
        [
            "--repo-root",
            str(repo),
            "--ledger",
            "ledger.jsonl",
            "--eval-fixture",
            "eval.json",
            "--as-of",
            "2026-07-08T12:00:00Z",
            "--json-out",
            "nested/latest.json",
            "--markdown-out",
            "nested/latest.md",
        ]
    )

    assert exit_code == 0
    assert (repo / "nested" / "latest.json").exists()
    assert (repo / "nested" / "latest.md").exists()
    assert not (outside / "nested").exists()
