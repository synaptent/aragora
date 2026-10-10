"""Pin the SwarmSupervisor duplicate-work mixin split.

The duplicate-open-work-order suppression and redundant-work-order collapse helpers
live in ``aragora.swarm.supervisor_duplicates``. ``SwarmSupervisor`` inherits them,
and ``aragora.swarm.supervisor`` re-exports the module-level names that moved with them.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.swarm import supervisor, supervisor_duplicates
from aragora.swarm.supervisor import SwarmSupervisor
from aragora.swarm.supervisor_duplicates import SwarmSupervisorDuplicateWorkMixin

DUPLICATE_HELPERS = """
    _normalized_scope_signature _normalized_goal_signature _task_has_concrete_deliverable
    _duplicate_open_work_order_group_key _scope_signature_contains _work_order_candidate_text
    _duplicate_candidate_is_current_batch_dependency
    _duplicate_candidate_has_stale_reaped_dependency
    _duplicate_candidate_receiptless_failure_is_stale _duplicate_candidate_should_block
    _looks_like_broad_explicit_pytest_umbrella _looks_like_specific_pytest_child
    _suppress_duplicate_open_work_orders _collapse_redundant_work_orders
""".split()

MOVED_MODULE_NAMES = [
    "_path_in_scope",
    "_parse_iso_timestamp",
    "DEFAULT_RECEIPTLESS_DUPLICATE_STALE_SECONDS",
]


def test_supervisor_inherits_the_mixin() -> None:
    assert issubclass(SwarmSupervisor, SwarmSupervisorDuplicateWorkMixin)


@pytest.mark.parametrize("name", DUPLICATE_HELPERS)
def test_helper_is_defined_once_on_the_mixin(name: str) -> None:
    assert name in vars(SwarmSupervisorDuplicateWorkMixin)
    assert name not in vars(SwarmSupervisor)
    assert (
        inspect.getattr_static(SwarmSupervisor, name)
        is vars(SwarmSupervisorDuplicateWorkMixin)[name]
    )


@pytest.mark.parametrize("name", MOVED_MODULE_NAMES)
def test_moved_module_name_is_reexported_by_the_facade(name: str) -> None:
    assert getattr(supervisor, name) is getattr(supervisor_duplicates, name)


def test_mixin_module_does_not_import_the_supervisor_facade() -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(supervisor_duplicates))):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "aragora.swarm.supervisor" not in imported
    assert supervisor_duplicates.logger.name == "aragora.swarm.supervisor"


def test_new_work_order_matching_an_open_task_is_discarded() -> None:
    open_task = SimpleNamespace(
        status="leased",
        goal="Fix the parser. Then add tests.",
        allowed_paths=["aragora/parser.py"],
        metadata={},
        task_key="task-1",
        title="Fix the parser",
        receipt_id=None,
    )
    store = SimpleNamespace(
        rehabilitate_dependency_deferred_missing_verification_plan_work_orders=lambda: None,
        archive_failed_no_deliverable_work_orders=lambda **_: None,
        archive_clean_exit_no_deliverable_work_orders=lambda **_: None,
        archive_terminal_dependency_failure_work_orders=lambda: None,
        list_developer_tasks=lambda **_: [open_task],
    )
    sup = object.__new__(SwarmSupervisor)
    sup.store = store  # type: ignore[assignment]
    item: dict[str, Any] = {
        "status": "queued",
        "work_order_id": "wo-2",
        "file_scope": ["aragora/parser.py"],
    }
    sup._suppress_duplicate_open_work_orders("Fix the parser.", [item])
    assert item["status"] == "discarded"
    assert item["metadata"]["canonical_task_key"] == "task-1"
    assert item["metadata"]["previous_status"] == "queued"


def test_receiptless_failure_staleness_uses_the_moved_timestamp_parser() -> None:
    fresh = datetime.now(timezone.utc).isoformat()
    is_stale = SwarmSupervisor._duplicate_candidate_receiptless_failure_is_stale
    assert is_stale({"last_observed_at": "2020-01-01T00:00:00Z"}, run_record={})
    assert not is_stale({"last_observed_at": fresh}, run_record={})
    assert not is_stale({}, run_record={})
