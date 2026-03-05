#!/usr/bin/env python3
"""Nightly adversarial regression suite for execution safety gate policy."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.debate.execution_safety import (
    ExecutionSafetyPolicy,
    evaluate_auto_execution_safety,
)
from scripts.tune_execution_gate import _build_scenarios, _make_agents, _make_result


@dataclass(frozen=True)
class ScenarioExpectation:
    expected_allow: bool
    required_reasons: tuple[str, ...] = ()


DEFAULT_EXPECTATIONS: dict[str, ScenarioExpectation] = {
    "safe_frontier_triad": ScenarioExpectation(expected_allow=True),
    "safe_frontier_dual": ScenarioExpectation(expected_allow=True),
    "safe_frontier_quartet": ScenarioExpectation(expected_allow=True),
    "safe_low_dissent_acceptable": ScenarioExpectation(expected_allow=True),
    "safe_mixed_openweight": ScenarioExpectation(expected_allow=True),
    "risk_single_provider_cluster": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("provider_diversity_below_minimum", "correlated_failure_risk"),
    ),
    "risk_single_provider_multi_family": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("provider_diversity_below_minimum", "correlated_failure_risk"),
    ),
    "risk_single_family_unknown": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("model_family_diversity_below_minimum", "correlated_failure_risk"),
    ),
    "risk_context_taint": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("tainted_context_detected",),
    ),
    "risk_high_dissent_borderline": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("high_severity_dissent_detected",),
    ),
    "risk_suspicious_unanimity": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("suspicious_unanimity_risk",),
    ),
    "risk_taint_and_low_diversity": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("tainted_context_detected", "correlated_failure_risk"),
    ),
    "risk_high_dissent_severe": ScenarioExpectation(
        expected_allow=False,
        required_reasons=("high_severity_dissent_detected",),
    ),
}


def _build_policy() -> ExecutionSafetyPolicy:
    return ExecutionSafetyPolicy(
        require_verified_signed_receipt=True,
        require_receipt_signer_allowlist=False,
        allowed_receipt_signer_keys=(),
        require_signed_receipt_timestamp=True,
        receipt_max_age_seconds=86400,
        receipt_max_future_skew_seconds=120,
        min_provider_diversity=2,
        min_model_family_diversity=2,
        block_on_context_taint=True,
        block_on_high_severity_dissent=True,
        high_severity_dissent_threshold=0.7,
    )


def run_suite() -> tuple[int, list[dict[str, Any]]]:
    policy = _build_policy()
    scenarios = _build_scenarios()
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    for scenario in scenarios:
        expectation = DEFAULT_EXPECTATIONS.get(
            scenario.name,
            ScenarioExpectation(expected_allow=scenario.expected_allow),
        )
        result = _make_result(scenario)
        agents = _make_agents(scenario)
        decision = evaluate_auto_execution_safety(result, agents=agents, policy=policy)

        reason_set = set(decision.reason_codes)
        missing_reasons = sorted(set(expectation.required_reasons) - reason_set)
        allow_mismatch = decision.allow_auto_execution != expectation.expected_allow
        reason_mismatch = bool(missing_reasons)
        status = "pass"
        if allow_mismatch or reason_mismatch:
            status = "fail"
            failures.append(
                {
                    "scenario": scenario.name,
                    "expected_allow": expectation.expected_allow,
                    "actual_allow": decision.allow_auto_execution,
                    "required_reasons": list(expectation.required_reasons),
                    "missing_reasons": missing_reasons,
                    "actual_reasons": sorted(reason_set),
                }
            )

        rows.append(
            {
                "scenario": scenario.name,
                "status": status,
                "expected_allow": expectation.expected_allow,
                "actual_allow": decision.allow_auto_execution,
                "required_reasons": list(expectation.required_reasons),
                "actual_reasons": sorted(reason_set),
            }
        )

    return len(failures), rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Run execution-gate adversarial regression suite")
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional JSON output path for CI artifacts",
    )
    args = parser.parse_args()

    failures, rows = run_suite()

    print("Execution gate adversarial suite results:")
    for row in rows:
        print(
            f"- {row['scenario']}: {row['status']} "
            f"(expected_allow={row['expected_allow']}, actual_allow={row['actual_allow']}, "
            f"reasons={','.join(row['actual_reasons']) or 'none'})"
        )

    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"failures": failures, "results": rows}
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"JSON report written to {args.json_output}")

    if failures:
        print(f"Execution gate adversarial suite failed: {failures} scenario(s) regressed")
        return 1

    print(f"Execution gate adversarial suite passed ({len(rows)} scenarios)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
