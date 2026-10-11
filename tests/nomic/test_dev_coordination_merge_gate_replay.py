"""Pins the dev-coordination merge-gate replay predicates to their own module.

The merge-gate state, replay, reconcile and branch-stale reclassification
predicates live in ``aragora.nomic.dev_coordination.merge_gate_replay``.
``core`` and ``dev_receipts`` keep exposing the same objects under the old
names, so ``core._merge_gate_state_for_work_order`` and the package-level
fallthrough keep working.
"""

from __future__ import annotations

import pytest

from aragora.nomic import dev_coordination, dev_receipts
from aragora.nomic.dev_coordination import core
from aragora.nomic.dev_coordination import merge_gate_replay as replay

MOVED_FUNCTIONS = (
    "_is_docs_only_path",
    "_merge_gate_state_for_work_order",
    "_work_order_should_replay_missing_verification",
    "_verification_result_looks_environment_blocked",
    "_docs_only_verification_script_path",
    "_is_docs_only_verification_command",
    "_docs_only_merge_gate_needs_capability_matrix_generation",
    "_docs_only_replay_commands_for_work_order",
    "_work_order_should_replay_docs_only_merge_gate_failure",
    "_missing_required_replay_commands_for_work_order",
    "_work_order_should_replay_missing_required_merge_gate_failure",
    "_narrow_pytest_replay_commands_for_work_order",
    "_work_order_should_replay_narrow_pytest_merge_gate_failure",
    "_work_order_should_replay_environment_blocked_verification",
    "_targeted_replay_expected_tests_for_work_order",
    "_work_order_should_replay_targeted_merge_gate_failure",
    "_mainline_verification_commands_for_work_order",
    "_mainline_candidate_repo_paths_for_work_order",
    "_mainline_missing_repo_paths_for_work_order",
    "_work_order_should_reclassify_branch_stale_verification_target_missing",
    "_work_order_should_reclassify_branch_stale_merge_gate_failure",
    "_work_order_should_reconcile_merge_gate_failure",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_core_and_package_expose_the_moved_function(name: str) -> None:
    moved = getattr(replay, name)
    assert moved.__module__ == replay.__name__
    assert getattr(core, name) is moved
    assert getattr(dev_coordination, name) is moved


def test_moved_constant_and_dev_receipts_alias_resolve_to_the_module() -> None:
    assert (
        core._DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS
        is replay._DOCS_ONLY_GENERATE_CAPABILITY_MATRIX_COMMANDS
    )
    assert dev_receipts._merge_gate_state_for_work_order is replay._merge_gate_state_for_work_order


def test_docs_only_paths_and_verification_commands() -> None:
    assert replay._is_docs_only_path("./docs/guide.md")
    assert replay._is_docs_only_path("README.rst")
    assert not replay._is_docs_only_path("aragora/core.py")
    assert replay._is_docs_only_verification_command("python3 scripts/check_version_alignment.py")
    assert not replay._is_docs_only_verification_command("python3 -m pytest tests/x.py")


def test_environment_blocked_results_and_reconcile_gate() -> None:
    blocked = {
        "passed": False,
        "stderr": "ModuleNotFoundError: No module named 'pydantic_settings'",
    }
    assert replay._verification_result_looks_environment_blocked(blocked)
    assert not replay._verification_result_looks_environment_blocked({**blocked, "passed": True})
    work_order = {
        "status": "needs_human",
        "failure_reason": "merge_gate_failed",
        "receipt_id": "r-1",
        "verification_results": [{"command": "python3 -m pytest tests/x.py", "passed": False}],
    }
    assert replay._work_order_should_reconcile_merge_gate_failure(work_order)
    assert not replay._work_order_should_reconcile_merge_gate_failure(
        {**work_order, "status": "queued"}
    )
