"""Regression coverage for the required typecheck workflow aggregator."""

from __future__ import annotations

from itertools import product
from pathlib import Path
import subprocess

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
LINT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lint.yml"
RESULTS = ("success", "failure", "cancelled", "skipped")
PYTHON_CHANGED = ("true", "false")


def _aggregator_script() -> str:
    workflow = yaml.safe_load(LINT_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["typecheck"]

    assert job["needs"] == ["changes", "typecheck-run"]
    assert job["if"] == "always()"
    steps = [step for step in job["steps"] if step.get("name") == "Evaluate typecheck result"]
    assert len(steps) == 1
    return steps[0]["run"]


def _run_aggregator(
    script: str,
    *,
    changes_result: str,
    python_changed: str,
    typecheck_result: str,
) -> subprocess.CompletedProcess[str]:
    substitutions = {
        "${{ needs.changes.result }}": changes_result,
        "${{ needs.changes.outputs.python }}": python_changed,
        "${{ needs.typecheck-run.result }}": typecheck_result,
    }
    rendered = script
    for expression, value in substitutions.items():
        assert rendered.count(expression) == 1
        rendered = rendered.replace(expression, value)

    return subprocess.run(
        ["bash", "-c", rendered],
        text=True,
        capture_output=True,
        check=False,
    )


def _expected_success(
    changes_result: str,
    python_changed: str,
    typecheck_result: str,
) -> bool:
    return changes_result == "success" and (
        (python_changed == "true" and typecheck_result == "success")
        or (python_changed == "false" and typecheck_result == "skipped")
    )


def _assert_aggregator_case(
    script: str,
    *,
    changes_result: str,
    python_changed: str,
    typecheck_result: str,
) -> None:
    proc = _run_aggregator(
        script,
        changes_result=changes_result,
        python_changed=python_changed,
        typecheck_result=typecheck_result,
    )
    expected_success = _expected_success(changes_result, python_changed, typecheck_result)

    assert (proc.returncode == 0) is expected_success, (
        f"unexpected aggregator result for changes={changes_result}, "
        f"python={python_changed}, worker={typecheck_result}: "
        f"exit={proc.returncode}, stdout={proc.stdout!r}, stderr={proc.stderr!r}"
    )


CASES = tuple(product(RESULTS, PYTHON_CHANGED, RESULTS))


@pytest.mark.parametrize(
    ("changes_result", "python_changed", "typecheck_result"),
    CASES,
    ids=("changes=%s-python=%s-worker=%s" % case for case in CASES),
)
def test_required_typecheck_aggregator_truth_table(
    changes_result: str,
    python_changed: str,
    typecheck_result: str,
) -> None:
    _assert_aggregator_case(
        _aggregator_script(),
        changes_result=changes_result,
        python_changed=python_changed,
        typecheck_result=typecheck_result,
    )


def test_truth_table_detects_a_fail_open_worker_guard() -> None:
    script = _aggregator_script()
    weakened = script.replace(
        '&& "$typecheck_result" == "success"',
        '&& "$typecheck_result" != "failure"',
        1,
    )
    assert weakened != script

    with pytest.raises(AssertionError, match="unexpected aggregator result"):
        _assert_aggregator_case(
            weakened,
            changes_result="success",
            python_changed="true",
            typecheck_result="cancelled",
        )
