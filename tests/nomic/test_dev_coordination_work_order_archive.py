"""Pins the dev-coordination work-order archive predicates to their own module.

The reaped, scope-violation, failed, clean-exit, leasing-failed and superseded
archive predicates live in ``aragora.nomic.dev_coordination.work_order_archive``.
``core`` and ``dev_receipts`` keep exposing the same objects under the old
names, so ``core._work_order_should_archive_reaped_no_receipt`` and the
package-level fallthrough keep working.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aragora.nomic import dev_coordination, dev_receipts
from aragora.nomic.dev_coordination import core
from aragora.nomic.dev_coordination import work_order_archive as archive

MOVED_FUNCTIONS = (
    "_developer_task_blockers",
    "_work_order_reap_failure_reason",
    "_work_order_should_archive_reaped_no_receipt",
    "_work_order_has_scope_violation",
    "_work_order_should_archive_scope_violation_no_deliverable",
    "_work_order_failed_no_deliverable_reason",
    "_terminal_dependency_failure_for_work_order",
    "_work_order_clean_exit_no_deliverable_reason",
    "_work_order_should_archive_failed_no_deliverable",
    "_work_order_should_archive_clean_exit_no_deliverable",
    "_work_order_should_archive_work_order_leasing_failed",
    "_work_order_should_archive_worker_type_blocked",
    "_work_order_leasing_failed_staleness_anchor",
    "_work_order_clean_exit_no_deliverable_staleness_anchor",
    "_work_order_should_archive_superseded_clean_exit_no_deliverable",
    "_looks_like_helper_clean_exit_no_deliverable",
    "_work_order_should_archive_superseded_stale_lease_reaped",
    "_work_order_receipt_outcome",
)
MOVED_CONSTANTS = (
    "_OPEN_DEVELOPER_TASK_STATUSES",
    "_REAPED_NO_RECEIPT_BLOCKERS",
    "_HELPER_CLEAN_EXIT_TITLE_PREFIXES",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_core_and_package_expose_the_moved_function(name: str) -> None:
    moved = getattr(archive, name)
    assert moved.__module__ == archive.__name__
    assert getattr(core, name) is moved
    assert getattr(dev_coordination, name) is moved


@pytest.mark.parametrize("name", MOVED_CONSTANTS)
def test_core_exposes_the_moved_constant(name: str) -> None:
    assert getattr(core, name) is getattr(archive, name)


def test_dev_receipts_aliases_resolve_to_the_moved_functions() -> None:
    assert dev_receipts._developer_task_blockers is archive._developer_task_blockers
    assert (
        dev_receipts._work_order_should_archive_reaped_no_receipt
        is archive._work_order_should_archive_reaped_no_receipt
    )


def test_reaped_lease_without_receipt_is_archived_after_cutoff() -> None:
    work_order = {
        "status": "active",
        "blockers": ["stale_lease_reaped"],
        "last_observed_at": "2026-01-01T00:00:00+00:00",
    }
    cutoff = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert archive._work_order_reap_failure_reason(work_order) == "stale_lease_reaped"
    assert archive._work_order_should_archive_reaped_no_receipt(
        work_order, run={}, cutoff=cutoff, lease_status="released"
    )
    assert not archive._work_order_should_archive_reaped_no_receipt(
        work_order, run={}, cutoff=cutoff, lease_status="active"
    )
    assert not archive._work_order_should_archive_reaped_no_receipt(
        {**work_order, "receipt_id": "r-1"}, run={}, cutoff=cutoff, lease_status="released"
    )


def test_blockers_and_receipt_outcome() -> None:
    work_order = {
        "blockers": [" waiting ", "waiting"],
        "failure_reason": "boom",
        "scope_violation": {"path": "x"},
    }
    assert archive._developer_task_blockers(work_order) == ["waiting", "boom", "scope_violation"]
    assert archive._work_order_has_scope_violation(work_order)
    assert archive._work_order_receipt_outcome({"adopted_pr": "12"}) == "pr_adopted"
    assert archive._work_order_receipt_outcome({}) == "clean_exit_no_deliverable"


def test_helper_titles_mark_stale_lease_reaped_orders_as_superseded() -> None:
    helper = {
        "status": "needs_human",
        "failure_reason": "stale_lease_reaped",
        "title": "Inspect  existing lease code",
    }
    assert archive._work_order_should_archive_superseded_stale_lease_reaped(helper)
    assert not archive._work_order_should_archive_superseded_stale_lease_reaped(
        {**helper, "title": "Fix the lease reaper"}
    )
