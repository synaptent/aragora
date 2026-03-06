"""Tests for scripts/run_dogfood_benchmark.py hard-check enforcement semantics."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is importable.
_scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

import run_dogfood_benchmark  # noqa: E402


def _run_template(checks: dict[str, bool | None]) -> dict[str, object]:
    return {
        "timed_out": False,
        "exit_code": 0,
        "duration_seconds": 1.0,
        "quality": {
            "present": False,
            "verdict": None,
            "score": None,
            "practicality": None,
            "loops": None,
            "upgraded": None,
        },
        "pipeline_checks": {
            "present": True,
            "checks": checks,
            "required_checks_present": all(v is not None for v in checks.values()),
            "hard_checks_pass": all(v is True for v in checks.values()),
        },
        "runtime_blockers": [],
    }


class TestExtractPipelineChecks:
    def test_missing_required_checks_never_passes_hard_checks(self) -> None:
        stdout = "  1. [core] Tighten planning contract\n"
        checks = run_dogfood_benchmark._extract_pipeline_checks(stdout)

        assert checks["present"] is True
        assert checks["required_checks_present"] is False
        assert checks["hard_checks_pass"] is False

    def test_all_required_checks_present_and_true_passes(self) -> None:
        stdout = "\n".join(
            [
                "Execution path: live",
                "[QUALITY GATE] PASS",
                "  1. [core] Tighten planning contract",
            ]
        )
        checks = run_dogfood_benchmark._extract_pipeline_checks(stdout)

        assert checks["present"] is True
        assert checks["required_checks_present"] is True
        assert checks["checks"]["execution_path_live"] is True
        assert checks["checks"]["quality_gate_pass"] is True
        assert checks["checks"]["top_track_is_infra_or_security"] is True
        assert checks["checks"]["no_cross_track_clones"] is True
        assert checks["hard_checks_pass"] is True


class TestSummarizeHardCheckRates:
    def test_missing_values_count_as_failed_rate(self) -> None:
        runs = [
            _run_template(
                {
                    "execution_path_live": None,
                    "quality_gate_pass": True,
                    "top_track_is_infra_or_security": True,
                    "no_cross_track_clones": True,
                }
            )
        ]

        summary = run_dogfood_benchmark._summarize(runs)
        hard_checks = summary["pipeline_hard_checks"]

        assert hard_checks["present_runs"] == 1
        assert hard_checks["required_checks_present_runs"] == 0
        assert hard_checks["hard_check_pass_runs"] == 0
        assert hard_checks["check_pass_rates"]["execution_path_live"] == 0.0
        assert hard_checks["check_pass_rates"]["quality_gate_pass"] == 1.0
