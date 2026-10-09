"""Pins the merge-gate failure replay functions to their own module.

The replay, branch-stale reclassification and reconciliation passes for
merge-gate failures live in ``aragora.nomic.dev_receipts_merge_gate``.
``dev_receipts`` re-exports the same function objects, so the store methods
in ``core`` that import them lazily from ``dev_receipts`` keep working.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aragora.nomic import dev_receipts
from aragora.nomic import dev_receipts_merge_gate as merge_gate
from aragora.nomic.dev_coordination import DevCoordinationStore

MOVED_FUNCTIONS = (
    "_replay_merge_gate_failures",
    "replay_missing_verification_for_merge_gate_failures",
    "replay_environment_blocked_merge_gate_failures",
    "replay_docs_only_merge_gate_failures",
    "replay_missing_required_merge_gate_failures",
    "replay_narrow_pytest_merge_gate_failures",
    "replay_targeted_merge_gate_failures",
    "reclassify_branch_stale_merge_gate_failures",
    "reconcile_merge_gate_failed_work_orders",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_function_is_defined_in_the_merge_gate_module(name: str) -> None:
    func = getattr(merge_gate, name)
    assert func.__module__ == "aragora.nomic.dev_receipts_merge_gate"
    assert getattr(dev_receipts, name) is func


def test_directly_imported_helper_is_the_one_core_uses() -> None:
    from aragora.nomic.dev_coordination import core

    assert merge_gate._canonical_verification_command is core._canonical_verification_command


@pytest.mark.parametrize(
    "name",
    [
        "replay_missing_verification_for_merge_gate_failures",
        "replay_environment_blocked_merge_gate_failures",
        "replay_docs_only_merge_gate_failures",
        "replay_missing_required_merge_gate_failures",
        "replay_narrow_pytest_merge_gate_failures",
        "replay_targeted_merge_gate_failures",
        "reclassify_branch_stale_merge_gate_failures",
        "reconcile_merge_gate_failed_work_orders",
    ],
)
def test_store_methods_run_the_moved_functions_on_an_empty_store(name: str, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = DevCoordinationStore(repo_root=tmp_path)
    assert getattr(store, name)() == 0
