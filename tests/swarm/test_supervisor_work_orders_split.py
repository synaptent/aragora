"""Pin the move of the work-order scope helpers into ``aragora.swarm.supervisor_work_orders``."""

from __future__ import annotations

import ast
import inspect

import pytest

from aragora.nomic.approval import ApprovalPolicy
from aragora.nomic.pipeline_bridge import BoundedWorkOrder
from aragora.swarm import supervisor, supervisor_work_orders
from aragora.swarm.spec import SwarmSpec

MODULE_NAMES = [
    "_TRUTHY_BOOL_STRINGS",
    "_FALSY_BOOL_STRINGS",
    "_is_concrete_repo_path",
    "_strict_bool",
    "_coerce_bool",
    "_docs_only_scope_supports_hint",
    "_narrow_scope_to_explicit_paths",
    "_narrow_docs_only_scope",
    "_NON_ACTIONABLE_EXPLICIT_SPEC_TITLES",
    "_looks_like_non_actionable_explicit_spec_work_order",
    "_looks_like_umbrella_explicit_spec_work_order",
    "_ensure_work_order_scope",
]
MIXIN_MEMBERS = [
    "_explicit_work_orders_from_spec",
    "_tests_from_acceptance",
    "_default_tests",
    "_risk_level_for_scope",
]


@pytest.mark.parametrize("name", MODULE_NAMES)
def test_module_names_are_reexported_from_the_supervisor(name: str) -> None:
    assert getattr(supervisor, name) is getattr(supervisor_work_orders, name)


@pytest.mark.parametrize("name", MIXIN_MEMBERS)
def test_supervisor_inherits_members_from_the_mixin(name: str) -> None:
    mixin = supervisor_work_orders.SwarmSupervisorWorkOrderMixin
    assert name in vars(mixin)
    assert name not in vars(supervisor.SwarmSupervisor)
    assert getattr(supervisor.SwarmSupervisor, name) is getattr(mixin, name)


def test_mixin_is_a_supervisor_base() -> None:
    assert supervisor.SwarmSupervisorWorkOrderMixin is (
        supervisor_work_orders.SwarmSupervisorWorkOrderMixin
    )
    assert (
        supervisor_work_orders.SwarmSupervisorWorkOrderMixin in supervisor.SwarmSupervisor.__mro__
    )


def test_work_orders_module_does_not_import_the_supervisor_facade() -> None:
    tree = ast.parse(inspect.getsource(supervisor_work_orders))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "aragora.swarm.supervisor" not in imported


def test_moved_helpers_log_under_the_supervisor_logger() -> None:
    assert supervisor_work_orders.logger.name == "aragora.swarm.supervisor"


def test_bool_helpers() -> None:
    assert supervisor._strict_bool(True) is True
    assert supervisor._strict_bool("true") is None
    assert supervisor._coerce_bool(" Yes ", default=False) is True
    assert supervisor._coerce_bool("off", default=True) is False
    assert supervisor._coerce_bool("maybe", default=True) is True


def test_ensure_work_order_scope_backfills_spec_hints() -> None:
    item = BoundedWorkOrder(
        work_order_id="wo-1", pipeline_task_id="t-1", title="Edit", description=""
    )
    spec = SwarmSpec(raw_goal="goal", file_scope_hints=["aragora/swarm/spec.py"])
    result = supervisor._ensure_work_order_scope(item, spec)
    assert result.file_scope == ["aragora/swarm/spec.py"]


def test_default_tests_and_risk_level_through_the_supervisor() -> None:
    sup = supervisor.SwarmSupervisor.__new__(supervisor.SwarmSupervisor)
    sup.approval_policy = ApprovalPolicy()
    spec = SwarmSpec(raw_goal="goal", acceptance_criteria=["pytest tests/swarm -q", "docs updated"])
    item = BoundedWorkOrder(
        work_order_id="wo-2",
        pipeline_task_id="t-2",
        title="Tests",
        description="",
        file_scope=["tests/swarm/test_spec.py", "aragora/swarm/spec.py"],
    )
    assert sup._default_tests(item, spec) == ["python -m pytest tests/swarm/test_spec.py -q"]
    item.file_scope = ["aragora/swarm/spec.py"]
    assert sup._default_tests(item, spec) == ["pytest tests/swarm -q"]
    assert sup._risk_level_for_scope([]) == "review"
    assert sup._risk_level_for_scope(["docs/guide.md"]) == "info"
    assert sup._risk_level_for_scope(["aragora/swarm/spec.py"]) == "review"
    assert sup._risk_level_for_scope(["docs/guide.md", "aragora/__init__.py"]) == "critical"
