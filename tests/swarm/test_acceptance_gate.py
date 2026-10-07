"""Unit tests for :mod:`aragora.swarm.acceptance_gate`.

These tests exercise the post-delivery acceptance-criteria gate (v1.3).
The gate is conservative: it must reject tangential deliverables and
accept deliverables that genuinely satisfy the spec.

Fixtures inspired by Cycle 1 drift cases #5904, #5899, #5895.
"""

from __future__ import annotations

import pytest

from aragora.swarm.acceptance_gate import (
    AcceptanceGateResult,
    evaluate_acceptance,
    inject_closes_into_pr_body,
    pr_body_already_closes,
)


# ---------------------------------------------------------------------------
# Pass / null cases
# ---------------------------------------------------------------------------


def test_evaluate_empty_inputs_passes() -> None:
    """With no criteria and no changes, the gate has nothing to check."""
    result = evaluate_acceptance(
        acceptance_criteria=[],
        file_scope_hints=[],
        changed_paths=[],
    )
    assert result.passed is True
    assert result.checks_run == ()
    assert result.failure_classes == ()


def test_evaluate_deliverable_with_test_file_passes() -> None:
    """A deliverable that adds a test file satisfies a 'test' criterion."""
    result = evaluate_acceptance(
        acceptance_criteria=["pytest tests/swarm/test_helper.py -q"],
        file_scope_hints=["tests/swarm/test_helper.py", "aragora/swarm/helper.py"],
        changed_paths=["tests/swarm/test_helper.py", "aragora/swarm/helper.py"],
    )
    assert result.passed, result
    assert "test_presence" in result.checks_run
    assert result.failure_classes == ()


def test_evaluate_companion_test_accepted_even_when_not_in_scope() -> None:
    """Editing a test file for a source in scope is allowed via companion rule."""
    result = evaluate_acceptance(
        acceptance_criteria=["pytest tests/swarm/test_helper.py -q"],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=[
            "aragora/swarm/helper.py",
            "tests/swarm/test_helper.py",
        ],
    )
    assert result.passed, result


# ---------------------------------------------------------------------------
# File-scope adherence check
# ---------------------------------------------------------------------------


def test_evaluate_rejects_out_of_scope_edits() -> None:
    """Editing an unrelated file must trigger ``file_scope_out_of_bounds``."""
    result = evaluate_acceptance(
        acceptance_criteria=["Keep lane scoped to aragora/swarm/helper.py"],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=[
            "aragora/swarm/helper.py",
            "aragora/other/module.py",
        ],
    )
    assert result.passed is False
    assert "file_scope_out_of_bounds" in result.failure_classes
    assert "aragora/other/module.py" in result.out_of_scope_paths


def test_evaluate_empty_scope_disables_adherence_check() -> None:
    """No scope hints means no enforcement (existing supervisor behaviour)."""
    result = evaluate_acceptance(
        acceptance_criteria=[],
        file_scope_hints=[],
        changed_paths=["aragora/anything.py"],
    )
    assert result.passed
    assert "file_scope_adherence" not in result.checks_run


def test_evaluate_scope_directory_prefix_allows_subpaths() -> None:
    """A directory scope hint accepts any file under that directory."""
    result = evaluate_acceptance(
        acceptance_criteria=["keep the lane scoped"],
        file_scope_hints=["aragora/swarm/"],
        changed_paths=[
            "aragora/swarm/helper.py",
            "aragora/swarm/sub/inner.py",
        ],
    )
    assert result.passed, result


# ---------------------------------------------------------------------------
# Test-presence check
# ---------------------------------------------------------------------------


def test_evaluate_rejects_no_tests_when_criteria_demand_tests() -> None:
    """Cycle 1 pattern: issue asked for tests, worker edited prod only."""
    # This mirrors #5899 (asked: tests for scripts/reconcile_b0_pr_truth.py;
    # PR delivered: +14/-6 in scripts/reconcile_b0_pr_truth.py, no tests).
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/scripts/test_reconcile_b0_pr_truth.py -v passes",
        ],
        file_scope_hints=["scripts/reconcile_b0_pr_truth.py"],
        changed_paths=["scripts/reconcile_b0_pr_truth.py"],
    )
    assert result.passed is False
    assert "test_presence_missing" in result.failure_classes


def test_evaluate_passes_when_tests_added_even_via_companion() -> None:
    result = evaluate_acceptance(
        acceptance_criteria=["Add pytest coverage"],
        file_scope_hints=["aragora/swarm/module.py"],
        changed_paths=[
            "aragora/swarm/module.py",
            "tests/swarm/test_module.py",
        ],
    )
    assert result.passed, result


def test_regression_only_criterion_does_not_demand_new_tests() -> None:
    """A refactor whose criteria only guard existing tests must be gateable.

    Real case from #9638: every auto-generated exception-narrowing issue ends
    with "Existing tests still pass". Treating that as a request for new tests
    made the whole class structurally ungateable — a correct one-line narrowing
    could never pass, and four such deliverables (#9631/#9633/#9635/#9637) were
    published and then marked needs_human.
    """
    result = evaluate_acceptance(
        acceptance_criteria=[
            "No `except Exception:` without `# noqa: BLE001` justification",
            "`ruff check aragora/agents/performance_monitor.py` passes",
            "Existing tests still pass",
        ],
        file_scope_hints=["aragora/agents/performance_monitor.py"],
        changed_paths=["aragora/agents/performance_monitor.py"],
    )
    assert result.passed, result
    assert "test_presence_missing" not in result.failure_classes


@pytest.mark.parametrize(
    "criterion",
    [
        "Existing tests still pass",
        "All tests pass",
        "Current tests still passing",
        "Do not break existing tests",
        "No new test failures",
        "without breaking existing tests",
        "Existing unit tests still pass",
    ],
)
def test_regression_phrasings_do_not_trigger_test_presence(criterion: str) -> None:
    result = evaluate_acceptance(
        acceptance_criteria=[criterion],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=["aragora/swarm/helper.py"],
    )
    assert result.passed, criterion
    assert "test_presence" not in result.checks_run


@pytest.mark.parametrize(
    "criterion",
    [
        "Add unit tests for aragora/utils/error_sanitizer.py",
        "Write regression tests covering the new branch",
        "Add tests and ensure existing tests still pass",
        "Test coverage for the new branch is added",
        "pytest tests/swarm/test_helper.py passes",
        # Passive/past forms: the guard subtracts phrases, it does not depend
        # on a verb list, so these must still demand tests.
        "Tests are added for the new branch",
        "Test coverage was extended",
        # "the new tests pass" presupposes tests that must be written, so a
        # bare tests-pass phrase is deliberately not treated as a guard.
        "New tests pass",
        # A creation verb in front of a guard noun is a request to edit test
        # files: only "existing tests ... pass" is a guard, not "existing
        # tests" alone.
        "Extend existing tests",
        "Update existing tests to cover the new branch",
        "Add cases to existing tests",
    ],
)
def test_creation_criteria_still_demand_tests(criterion: str) -> None:
    """Narrowing the match must not weaken the real 'asked for tests' case."""
    result = evaluate_acceptance(
        acceptance_criteria=[criterion],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=["aragora/swarm/helper.py"],
    )
    assert result.passed is False, criterion
    assert "test_presence_missing" in result.failure_classes


def test_guard_phrase_is_subtracted_not_whole_criterion() -> None:
    """Only the guard phrase is removed; the rest still faces the fallback.

    Discarding the entire criterion on a guard match would suppress the
    conservative default for everything else in the same sentence.
    """
    result = evaluate_acceptance(
        acceptance_criteria=["Add pytest coverage, and existing tests still pass"],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=["aragora/swarm/helper.py"],
    )
    assert result.passed is False
    assert "test_presence_missing" in result.failure_classes


def test_refactor_criterion_carrying_a_guard_is_not_gated_on_tests() -> None:
    result = evaluate_acceptance(
        acceptance_criteria=["Update the retry helper so existing tests still pass"],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=["aragora/swarm/helper.py"],
    )
    assert result.passed, result
    assert "test_presence" not in result.checks_run


def test_unanticipated_test_phrasing_keeps_conservative_default() -> None:
    """Neither pattern matching must still fall through to requiring tests."""
    result = evaluate_acceptance(
        acceptance_criteria=["The assert helper is exercised end to end"],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=["aragora/swarm/helper.py"],
    )
    assert result.passed is False
    assert "test_presence_missing" in result.failure_classes


def test_evaluate_test_presence_skipped_when_no_test_criterion() -> None:
    """If criteria don't mention tests, presence check is skipped."""
    result = evaluate_acceptance(
        acceptance_criteria=["ruff check passes"],
        file_scope_hints=["aragora/swarm/helper.py"],
        changed_paths=["aragora/swarm/helper.py"],
    )
    assert result.passed, result
    assert "test_presence" not in result.checks_run


# ---------------------------------------------------------------------------
# File-creation check (from issue body `(new)` markers)
# ---------------------------------------------------------------------------


def test_evaluate_rejects_missing_new_file_declared_in_issue_body() -> None:
    """Cycle 1 pattern: issue declared a new test file, worker didn't create it."""
    issue_body = (
        "## Scope\nAdd tests for reconcile_b0_pr_truth.py\n\n"
        "## Files\n- `tests/scripts/test_reconcile_b0_pr_truth.py` (new)\n\n"
        "## Acceptance\n- pytest tests/scripts/test_reconcile_b0_pr_truth.py -v passes\n"
    )
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/scripts/test_reconcile_b0_pr_truth.py -v passes",
        ],
        file_scope_hints=["scripts/reconcile_b0_pr_truth.py"],
        changed_paths=["scripts/reconcile_b0_pr_truth.py"],
        issue_body=issue_body,
    )
    assert result.passed is False
    assert "expected_file_not_created" in result.failure_classes
    assert "tests/scripts/test_reconcile_b0_pr_truth.py" in result.missing_expected_files


def test_evaluate_accepts_sibling_test_file_under_same_directory() -> None:
    """If the issue names a test file but the worker created a close sibling, accept."""
    issue_body = "## Files\n- `tests/scripts/test_reconcile_b0_pr_truth.py` (new)\n"
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/scripts/test_reconcile_b0_pr_truth.py -v passes",
        ],
        file_scope_hints=["scripts/reconcile_b0_pr_truth.py"],
        changed_paths=[
            "scripts/reconcile_b0_pr_truth.py",
            # Worker chose a more descriptive file name — same directory, same subject.
            "tests/scripts/test_reconcile_b0_pr_truth_classification.py",
        ],
        issue_body=issue_body,
    )
    assert result.passed, result


def test_evaluate_file_creation_uses_pytest_target_from_criteria() -> None:
    """Explicit `pytest <path>` in criteria should seed expected files."""
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/benchmarks/test_rescue_productization.py -v passes",
        ],
        file_scope_hints=[],
        changed_paths=["docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md"],
    )
    assert result.passed is False
    assert "expected_file_not_created" in result.failure_classes
    assert "tests/benchmarks/test_rescue_productization.py" in result.missing_expected_files


# ---------------------------------------------------------------------------
# Cycle 1 fixtures — the three concrete failures we are closing
# ---------------------------------------------------------------------------


def test_fixture_issue_5904_tangential_delivery_rejected() -> None:
    """#5904 requested tests for boss_worker_lifecycle.py; got +1 line in source."""
    issue_body = (
        "## Scope\nAdd unit tests for `aragora/swarm/boss_worker_lifecycle.py`\n\n"
        "## Files\n"
        "- Tests already exist at `tests/swarm/test_boss_worker_lifecycle.py` — "
        "verify coverage or add missing cases\n"
        "- Source: `aragora/swarm/boss_worker_lifecycle.py`\n\n"
        "## Acceptance\n"
        "- `pytest tests/swarm/test_boss_worker_lifecycle.py -v` passes\n"
    )
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/swarm/test_boss_worker_lifecycle.py -v passes",
        ],
        file_scope_hints=[
            "tests/swarm/test_boss_worker_lifecycle.py",
            "aragora/swarm/boss_worker_lifecycle.py",
        ],
        changed_paths=["aragora/swarm/boss_worker_lifecycle.py"],
        issue_body=issue_body,
    )
    assert result.passed is False
    assert "test_presence_missing" in result.failure_classes


def test_fixture_issue_5899_missing_test_file_rejected() -> None:
    """#5899 requested a new test file; PR delivered prod edit only."""
    issue_body = (
        "## Scope\nAdd tests for `scripts/reconcile_b0_pr_truth.py`.\n\n"
        "## Files\n- `tests/scripts/test_reconcile_b0_pr_truth.py` (new)\n\n"
        "## Acceptance\n"
        "- `pytest tests/scripts/test_reconcile_b0_pr_truth.py -v` passes\n"
    )
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/scripts/test_reconcile_b0_pr_truth.py -v passes",
        ],
        file_scope_hints=["scripts/reconcile_b0_pr_truth.py"],
        changed_paths=["scripts/reconcile_b0_pr_truth.py"],
        issue_body=issue_body,
    )
    assert result.passed is False
    assert "expected_file_not_created" in result.failure_classes


def test_fixture_issue_5895_doc_only_delivery_rejected() -> None:
    """#5895 requested a new test file; PR delivered a doc timestamp bump."""
    issue_body = (
        "## Scope\nAdd tests for rescue productization pipeline.\n\n"
        "## Files\n- `tests/benchmarks/test_rescue_productization.py` (new)\n\n"
        "## Acceptance\n"
        "- `pytest tests/benchmarks/test_rescue_productization.py -v` passes\n"
    )
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/benchmarks/test_rescue_productization.py -v passes",
        ],
        file_scope_hints=[],
        changed_paths=["docs/status/TW03_RESCUE_PRODUCTIZATION_STATUS.md"],
        issue_body=issue_body,
    )
    assert result.passed is False
    assert "expected_file_not_created" in result.failure_classes


def test_fixture_issue_5899_satisfying_delivery_accepted() -> None:
    """A satisfying deliverable for #5899 must pass the gate."""
    issue_body = (
        "## Files\n- `tests/scripts/test_reconcile_b0_pr_truth.py` (new)\n\n"
        "## Acceptance\n"
        "- `pytest tests/scripts/test_reconcile_b0_pr_truth.py -v` passes\n"
    )
    result = evaluate_acceptance(
        acceptance_criteria=[
            "pytest tests/scripts/test_reconcile_b0_pr_truth.py -v passes",
        ],
        file_scope_hints=["scripts/reconcile_b0_pr_truth.py"],
        changed_paths=[
            "scripts/reconcile_b0_pr_truth.py",
            "tests/scripts/test_reconcile_b0_pr_truth.py",
        ],
        issue_body=issue_body,
    )
    assert result.passed, result


# ---------------------------------------------------------------------------
# Closes #N helpers
# ---------------------------------------------------------------------------


def test_pr_body_already_closes_detects_variants() -> None:
    assert pr_body_already_closes("Closes #42") is True
    assert pr_body_already_closes("closes #42") is True
    assert pr_body_already_closes("Fixes #42") is True
    assert pr_body_already_closes("resolves #42") is True
    assert pr_body_already_closes("Closed #42") is True
    assert pr_body_already_closes("Fixed #42") is True


def test_pr_body_already_closes_with_specific_issue_number() -> None:
    assert pr_body_already_closes("Closes #42", issue_number=42) is True
    assert pr_body_already_closes("Closes #42", issue_number=43) is False
    assert pr_body_already_closes("Closes #99\nCloses #42", issue_number=42) is True


def test_pr_body_already_closes_returns_false_for_empty() -> None:
    assert pr_body_already_closes("") is False
    assert pr_body_already_closes(None) is False


def test_inject_closes_prepends_when_absent() -> None:
    body = "Brief summary of the change."
    result = inject_closes_into_pr_body(body, issue_number=42)
    assert result == "Closes #42\n\nBrief summary of the change."


def test_inject_closes_is_idempotent() -> None:
    body = "Closes #42\n\nExisting body."
    assert inject_closes_into_pr_body(body, issue_number=42) == body


def test_inject_closes_idempotent_even_with_keyword_variant() -> None:
    body = "Fixes #42\n\nExisting body."
    assert inject_closes_into_pr_body(body, issue_number=42) == body


def test_inject_closes_handles_empty_body() -> None:
    assert inject_closes_into_pr_body("", issue_number=42) == "Closes #42"
    assert inject_closes_into_pr_body(None, issue_number=42) == "Closes #42"


def test_inject_closes_ignores_invalid_issue_numbers() -> None:
    body = "Body"
    # ``int()`` conversion in the impl rejects 0 and negative numbers.
    assert inject_closes_into_pr_body(body, issue_number=0) == body


def test_inject_closes_preserves_different_issue_reference() -> None:
    body = "Closes #99\n\nHandles another issue."
    # When the body already closes a DIFFERENT issue, we still add ours.
    result = inject_closes_into_pr_body(body, issue_number=42)
    assert result.startswith("Closes #42")
    assert "Closes #99" in result


# ---------------------------------------------------------------------------
# Result serialisation (for telemetry)
# ---------------------------------------------------------------------------


def test_acceptance_result_to_dict_is_json_friendly() -> None:
    res = AcceptanceGateResult(
        passed=False,
        failure_classes=("test_presence_missing",),
        reasons=("tests required",),
        checks_run=("test_presence",),
        out_of_scope_paths=(),
        missing_expected_files=(),
    )
    data = res.to_dict()
    assert data["passed"] is False
    assert data["failure_classes"] == ["test_presence_missing"]
    assert data["reasons"] == ["tests required"]
    assert data["checks_run"] == ["test_presence"]
