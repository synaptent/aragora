"""Pins the dev-coordination work-order overlap helpers to their own module.

The overlap, duplicate-detection and scope-matching helpers live in
``aragora.nomic.dev_coordination.work_order_overlap``. ``core`` and
``dev_receipts`` keep exposing the same function objects under the old names,
so attribute lookups such as ``core._work_orders_overlap_by_scope`` and the
package-level fallthrough keep working.
"""

from __future__ import annotations

import pytest

from aragora.nomic import dev_coordination, dev_receipts
from aragora.nomic.dev_coordination import core
from aragora.nomic.dev_coordination import work_order_overlap as overlap

MOVED_NAMES = (
    "_optional_text",
    "_work_order_has_concrete_deliverable",
    "_work_order_is_live_overlap_sibling",
    "_live_overlap_sibling_priority",
    "_work_order_is_duplicate_work_order_leasing_failed_candidate",
    "_work_order_is_duplicate_waiting_conflict_candidate",
    "_waiting_conflict_candidate_text",
    "_work_order_source_name",
    "_work_order_is_broad_explicit_pytest_umbrella",
    "_work_order_is_specific_pytest_child",
    "_duplicate_waiting_conflict_group_key",
    "_superseded_waiting_conflict_group_key",
    "_duplicate_work_order_leasing_failed_priority",
    "_work_order_should_archive_duplicate_branch_deliverable",
    "_work_order_scope_patterns",
    "_canonical_work_order_scope_key",
    "_canonical_scope_pattern",
    "_collapse_scope_patterns",
    "_canonical_goal_key",
    "_claim_contains",
    "_work_order_scope_contains",
    "_work_orders_overlap_by_scope",
    "_developer_task_updated_at",
    "_path_matches_glob",
    "_glob_overlap",
    "_globs_overlap_any",
    "_claims_overlap",
)


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_core_and_package_expose_the_moved_function(name: str) -> None:
    moved = getattr(overlap, name)
    assert moved.__module__ == overlap.__name__
    assert getattr(core, name) is moved
    assert getattr(dev_coordination, name) is moved


def test_dev_receipts_aliases_resolve_to_the_moved_functions() -> None:
    assert dev_receipts._work_orders_overlap_by_scope is overlap._work_orders_overlap_by_scope
    assert dev_receipts._canonical_goal_key is overlap._canonical_goal_key


def test_scope_overlap_matches_globs_and_changed_paths() -> None:
    docs = {"file_scope": ["docs/**"]}
    guide = {"changed_paths": ["docs/guides/setup.md"]}
    server = {"file_scope": ["aragora/server/**"]}
    assert overlap._work_orders_overlap_by_scope(docs, guide)
    assert not overlap._work_orders_overlap_by_scope(docs, server)
    assert not overlap._work_orders_overlap_by_scope(docs, {})
    assert overlap._work_order_scope_contains(docs, guide)
    assert not overlap._work_order_scope_contains(guide, docs)


def test_scope_patterns_are_canonical_and_collapsed() -> None:
    work_order = {"file_scope": ["docs/**", "docs/guides/setup.md", "docs/**", "README.md"]}
    assert overlap._work_order_scope_patterns(work_order) == ["docs", "README.md"]
    assert overlap._canonical_work_order_scope_key(work_order) == ("README.md", "docs")


def test_canonical_goal_key_skips_section_headers() -> None:
    goal = "## Context\n\nFix the flaky   lease reaper.  Then add a test.\n\nAcceptance criteria: x"
    assert overlap._canonical_goal_key(goal) == "fix the flaky lease reaper."
