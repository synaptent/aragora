"""Pin the import-layer contract wiring of the required ``lint`` workflow.

Job ``lint-run`` must run ``scripts/ci/check_import_contracts.py`` as a
hard-fail step right after the Boundary 2 module-edge policy, install
import-linter and grimp at pinned versions, and run the TYPE_CHECKING policy
tests so their import-linter probes execute instead of skipping.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "lint.yml"

_PYTHON_BIN = '"${{ steps.lint_python.outputs.python_bin }}"'
_BOUNDARY_STEP = "Enforce Boundary 2 module-edge policy"
_CONTRACT_STEP = "Import layer contract (fail on new violations)"
_CONTRACT_RUN = f"{_PYTHON_BIN} scripts/ci/check_import_contracts.py"
_POLICY_STEP = "Import layer TYPE_CHECKING policy tests"
# --noconftest: tests/conftest.py imports most of aragora, which on the hosted runner pulls the
# system boto3/pyOpenSSL into conflict with the user-site cryptography; the policy tests need
# only built-in fixtures.
_POLICY_RUN = f"{_PYTHON_BIN} -m pytest --noconftest tests/ci/test_importlinter_tc_policy.py -q -rs"

_IMPORT_LINTER_VERSION = "2.15"
_GRIMP_VERSION = "3.17"
_PYTEST_VERSION = "9.1.1"
_LINTER_PIN_LINE = (
    f'{_PYTHON_BIN} -m pip install --user "import-linter=={_IMPORT_LINTER_VERSION}"'
    f' "grimp=={_GRIMP_VERSION}"'
)
_PYTEST_PIN_LINE = f'{_PYTHON_BIN} -m pip install --user "pytest=={_PYTEST_VERSION}"'
_PREVIOUS_INSTALL_LINES = (
    f"{_PYTHON_BIN} -m pip install --user ruff==0.14.14",
    f"{_PYTHON_BIN} -m pip install --user -e .",
)


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))["jobs"]


def _lint_run_steps() -> list[dict[str, Any]]:
    return _jobs()["lint-run"]["steps"]


def _step_index(steps: list[dict[str, Any]], name: str) -> int:
    matches = [i for i, step in enumerate(steps) if step.get("name") == name]
    assert len(matches) == 1, (name, matches)
    return matches[0]


def _install_lines() -> list[str]:
    steps = _lint_run_steps()
    run = steps[_step_index(steps, "Install linters")]["run"]
    return [line.strip() for line in run.splitlines() if line.strip()]


def test_contract_checker_runs_in_exactly_one_step() -> None:
    runs = [str(step.get("run", "")) for step in _lint_run_steps()]
    matching = [run for run in runs if "check_import_contracts" in run]
    assert len(matching) == 1, matching


def test_contract_step_is_the_exact_unflagged_command() -> None:
    steps = _lint_run_steps()
    step = steps[_step_index(steps, _CONTRACT_STEP)]
    assert set(step) == {"name", "run"}, step
    assert step["run"].strip() == _CONTRACT_RUN


def test_contract_step_directly_follows_boundary_step() -> None:
    steps = _lint_run_steps()
    assert _step_index(steps, _CONTRACT_STEP) == _step_index(steps, _BOUNDARY_STEP) + 1


def test_contract_failure_fails_the_required_lint_check() -> None:
    jobs = _jobs()
    steps = jobs["lint-run"]["steps"]
    step = steps[_step_index(steps, _CONTRACT_STEP)]
    assert "if" not in step and "continue-on-error" not in step, step
    assert "continue-on-error" not in jobs["lint-run"]
    assert "continue-on-error" not in jobs["lint"]
    assert "lint-run" in jobs["lint"]["needs"]


def test_install_linters_pins_import_linter_and_grimp() -> None:
    lines = _install_lines()
    assert lines.count(_LINTER_PIN_LINE) == 1, lines
    for previous in _PREVIOUS_INSTALL_LINES:
        assert previous in lines, (previous, lines)


def test_policy_tests_run_after_the_contract_step() -> None:
    steps = _lint_run_steps()
    index = _step_index(steps, _POLICY_STEP)
    step = steps[index]
    assert set(step) == {"name", "run"}, step
    assert step["run"].strip() == _POLICY_RUN
    assert index == _step_index(steps, _CONTRACT_STEP) + 1
    assert _install_lines().count(_PYTEST_PIN_LINE) == 1
