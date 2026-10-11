"""Pins the dev-coordination blocker and rehabilitation predicates to their own module.

Blocker-metadata inference, verification-plan backfill, dependency-deferred
verification, clean-exit rehabilitation, review reclassification and the
receipt/file-scope backfill predicates live in
``aragora.nomic.dev_coordination.work_order_rehabilitation``. ``core``, the
package and ``dev_receipts`` keep exposing the same objects under the old names.
"""

from __future__ import annotations

import pytest

from aragora.nomic import dev_coordination, dev_receipts, dev_receipts_merge_gate
from aragora.nomic.dev_coordination import core
from aragora.nomic.dev_coordination import work_order_rehabilitation as rehab

MOVED_FUNCTIONS = (
    "_default_blocking_question_for_reason",
    "_merge_gate_verification_target_missing",
    "_infer_missing_failure_reason_for_work_order",
    "_backfill_work_order_blocker_metadata",
    "_work_order_should_backfill_verification_plan",
    "_work_order_should_rehabilitate_docs_only_missing_verification_plan",
    "_work_order_is_validation_successor",
    "_work_order_rehabilitation_identifier",
    "_dependency_deferred_verification_ids_for_work_order",
    "_work_order_dependency_ids",
    "_work_order_matches_dependency_id",
    "_resolve_dependency_work_order",
    "_work_order_has_passed_verification_results",
    "_work_order_should_rehabilitate_dependency_validated_clean_exit_no_deliverable",
    "_work_order_should_rehabilitate_deliverable_backed_clean_exit_no_deliverable",
    "_work_order_should_reclassify_branch_snapshot_stale_review",
    "_work_order_should_reclassify_deliverable_changes_requested",
    "_merge_gate_replay_matches_task_keys",
    "_work_order_should_backfill_file_scope_from_changed_paths",
    "_work_order_should_backfill_receipt",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_core_and_package_expose_the_moved_function(name: str) -> None:
    moved = getattr(rehab, name)
    assert moved.__module__ == rehab.__name__
    assert getattr(core, name) is moved
    assert getattr(dev_coordination, name) is moved


def test_dev_receipts_aliases_resolve_to_the_module() -> None:
    assert dev_receipts._backfill_work_order_blocker_metadata is (
        rehab._backfill_work_order_blocker_metadata
    )
    assert dev_receipts._dependency_deferred_verification_ids_for_work_order is (
        rehab._dependency_deferred_verification_ids_for_work_order
    )
    assert dev_receipts_merge_gate._merge_gate_replay_matches_task_keys is (
        rehab._merge_gate_replay_matches_task_keys
    )


def test_blocker_metadata_backfill_infers_reason_and_question() -> None:
    work_order = {
        "status": "needs_human",
        "dispatch_error": "Merge gate failed: missing verification plan",
    }
    assert rehab._backfill_work_order_blocker_metadata(work_order) is True
    assert work_order["failure_reason"] == "missing_verification_plan"
    question = rehab._default_blocking_question_for_reason("missing_verification_plan")
    assert work_order["blocking_question"] == question
    assert work_order["blocker"] == {"reason": "missing_verification_plan", "question": question}
    assert rehab._backfill_work_order_blocker_metadata(work_order) is False
    assert rehab._backfill_work_order_blocker_metadata({"status": "queued"}) is False


def test_verification_target_missing_is_read_from_results() -> None:
    work_order = {
        "worker_outcome": "merge_gate_failed",
        "verification_results": [{"stderr": "ERROR: file or directory not found: tests/x.py"}],
    }
    assert rehab._merge_gate_verification_target_missing(work_order)
    assert (
        rehab._infer_missing_failure_reason_for_work_order(work_order)
        == "verification_target_missing"
    )
    assert rehab._infer_missing_failure_reason_for_work_order({}) == "needs_human"


def test_dependency_deferred_verification_ids() -> None:
    parent = {
        "work_order_id": "wo-1",
        "status": "needs_human",
        "dispatch_error": "missing verification plan",
        "branch": "feature/x",
        "commit_shas": ["abc123"],
    }
    successor = {
        "work_order_id": "wo-2",
        "dependency_ids": ["wo-1"],
        "expected_tests": ["tests/test_x.py"],
    }
    unrelated = {"work_order_id": "wo-3", "dependency_ids": ["wo-9"], "expected_tests": ["t"]}
    ids = rehab._dependency_deferred_verification_ids_for_work_order(
        parent, work_orders=[parent, successor, unrelated]
    )
    assert ids == ["wo-2"]
    assert rehab._resolve_dependency_work_order([parent, successor], "wo-1") is parent
    assert rehab._resolve_dependency_work_order([parent], "missing") is None


def test_receipt_and_file_scope_backfill_predicates() -> None:
    assert rehab._work_order_should_backfill_file_scope_from_changed_paths(
        {"status": "completed", "changed_paths": ["a.py"]}
    )
    assert not rehab._work_order_should_backfill_file_scope_from_changed_paths(
        {"status": "completed", "changed_paths": ["a.py"], "file_scope": ["a.py"]}
    )
    assert not rehab._work_order_should_backfill_receipt({"status": "queued", "lease_id": "l-1"})
    assert rehab._merge_gate_replay_matches_task_keys("run-1", {"work_order_id": "wo-1"}, set())
    assert rehab._merge_gate_replay_matches_task_keys(
        "run-1", {"work_order_id": "wo-1"}, {"run-1:wo-1"}
    )
    assert not rehab._merge_gate_replay_matches_task_keys(
        "run-1", {"work_order_id": "wo-1"}, {"run-1:wo-2"}
    )


def test_receipt_backfill_needs_a_leased_unreceipted_deliverable() -> None:
    adopted = {"status": "completed", "lease_id": "l-1", "adopted_pr": "https://example/pr/1"}
    assert rehab._work_order_should_backfill_receipt(adopted)
    delivered = {
        "status": "needs_human",
        "lease_id": "l-1",
        "branch": "feature/x",
        "commit_shas": ["abc123"],
    }
    assert rehab._work_order_should_backfill_receipt(delivered)
    assert not rehab._work_order_should_backfill_receipt({**adopted, "receipt_id": "r-1"})
    assert not rehab._work_order_should_backfill_receipt({**adopted, "lease_id": ""})
    assert not rehab._work_order_should_backfill_receipt({"status": "completed", "lease_id": "l-1"})
