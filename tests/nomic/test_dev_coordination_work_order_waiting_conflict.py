"""Pins the dev-coordination waiting-conflict predicates to their own module.

The waiting-conflict archive, rehabilitation, scope-narrowing, duplicate
priority and blocking-sibling helpers live in
``aragora.nomic.dev_coordination.work_order_waiting_conflict``. ``core`` and
``dev_receipts`` keep exposing the same objects under the old names.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aragora.nomic import dev_coordination, dev_receipts
from aragora.nomic.dev_coordination import core
from aragora.nomic.dev_coordination import work_order_waiting_conflict as waiting

MOVED_FUNCTIONS = (
    "_work_order_identifier",
    "_work_order_should_archive_superseded_waiting_conflict",
    "_work_order_should_rehabilitate_narrowed_waiting_conflict",
    "_waiting_conflict_staleness_anchor",
    "_duplicate_branch_deliverable_priority",
    "_duplicate_waiting_conflict_priority",
    "_containing_waiting_conflict_priority",
    "_is_concrete_repo_path_hint",
    "_waiting_conflict_inference_text",
    "_explicit_scope_paths_for_waiting_conflict",
    "_docs_only_scope_hints_for_waiting_conflict",
    "_narrow_waiting_conflict_scope_from_explicit_paths",
    "_waiting_conflict_sibling_can_be_ignored",
    "_blocking_waiting_conflict_siblings",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_core_and_package_expose_the_moved_function(name: str) -> None:
    moved = getattr(waiting, name)
    assert moved.__module__ == waiting.__name__
    assert getattr(core, name) is moved
    assert getattr(dev_coordination, name) is moved


def test_dev_receipts_aliases_resolve_to_the_module() -> None:
    assert (
        dev_receipts._work_order_should_archive_superseded_waiting_conflict
        is waiting._work_order_should_archive_superseded_waiting_conflict
    )
    assert (
        dev_receipts._narrow_waiting_conflict_scope_from_explicit_paths
        is waiting._narrow_waiting_conflict_scope_from_explicit_paths
    )


def test_identifier_and_concrete_path_hints() -> None:
    assert waiting._work_order_identifier({"work_order_id": " wo-1 ", "task_id": "t"}) == "wo-1"
    assert waiting._work_order_identifier({"task_id": "t-2"}) == "t-2"
    assert waiting._is_concrete_repo_path_hint("aragora/nomic/core.py", repo_root=None)
    assert not waiting._is_concrete_repo_path_hint("aragora/nomic/*.py", repo_root=None)
    assert not waiting._is_concrete_repo_path_hint("aragora/nomic", repo_root=None)


def test_superseded_waiting_conflict_archive_predicate() -> None:
    stale = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    work_order = {
        "status": "waiting_conflict",
        "file_scope": ["aragora/nomic/"],
        "last_observed_at": stale,
    }
    assert waiting._work_order_should_archive_superseded_waiting_conflict(
        work_order, run={}, cutoff=cutoff, lease_status=None
    )
    assert not waiting._work_order_should_archive_superseded_waiting_conflict(
        work_order, run={}, cutoff=cutoff, lease_status="active"
    )
    assert not waiting._work_order_should_archive_superseded_waiting_conflict(
        {**work_order, "receipt_id": "r-1"}, run={}, cutoff=cutoff, lease_status=None
    )


def test_wider_waiting_conflict_sibling_is_ignored() -> None:
    candidate = {"status": "queued", "file_scope": ["aragora/nomic/core.py"]}
    wider = {"status": "waiting_conflict", "file_scope": ["aragora/nomic/"]}
    assert waiting._waiting_conflict_sibling_can_be_ignored(candidate, wider)
    assert not waiting._waiting_conflict_sibling_can_be_ignored(wider, candidate)
