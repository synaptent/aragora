"""Pin the SwarmSupervisor requeue and waiting-state mixin split.

The work-order requeue predicates live in ``aragora.swarm.supervisor_requeue`` and the
needs-human / waiting-state helpers live in ``aragora.swarm.supervisor_waiting``.
``SwarmSupervisor`` inherits both, so ``self._x`` and ``SwarmSupervisor._x`` keep
resolving for the supervisor and its delegate modules.
"""

from __future__ import annotations

import inspect

import pytest

from aragora.swarm import supervisor_requeue, supervisor_waiting
from aragora.swarm.supervisor import SwarmSupervisor
from aragora.swarm.supervisor_requeue import SwarmSupervisorRequeueMixin
from aragora.swarm.supervisor_waiting import SwarmSupervisorWaitingStateMixin

REQUEUE_HELPERS = """
    _should_requeue_stale_work_order _should_requeue_conflict_only_needs_human
    _should_requeue_reaped_needs_human _should_requeue_recoverable_work_order_leasing_failed
    _should_requeue_terminal_dependency_failure _should_requeue_ignorable_scope_violation
    _reset_work_order_for_requeue
""".split()

WAITING_HELPERS = """
    _default_blocking_question _infer_failure_reason _mark_needs_human
    _mark_waiting_conflict _mark_waiting_resource _clear_waiting_state
""".split()


def test_supervisor_inherits_both_mixins() -> None:
    assert issubclass(SwarmSupervisor, SwarmSupervisorRequeueMixin)
    assert issubclass(SwarmSupervisor, SwarmSupervisorWaitingStateMixin)


@pytest.mark.parametrize(
    ("mixin", "name"),
    [(SwarmSupervisorRequeueMixin, name) for name in REQUEUE_HELPERS]
    + [(SwarmSupervisorWaitingStateMixin, name) for name in WAITING_HELPERS],
)
def test_helper_is_defined_once_on_its_mixin(mixin: type, name: str) -> None:
    assert name in vars(mixin)
    assert name not in vars(SwarmSupervisor)
    assert inspect.getattr_static(SwarmSupervisor, name) is vars(mixin)[name]


def test_mixin_modules_carry_no_supervisor_import() -> None:
    for module in (supervisor_requeue, supervisor_waiting):
        assert "aragora.swarm.supervisor " not in inspect.getsource(module)
        assert not hasattr(module, "SwarmSupervisor")


def test_mark_needs_human_then_requeue_resets_through_supervisor() -> None:
    item: dict[str, object] = {
        "status": "dispatched",
        "lease_id": "lease-1",
        "pid": 4242,
        "receipt_id": "r-1",
    }
    SwarmSupervisor._mark_needs_human(item, "worker exited without a deliverable")
    assert item["status"] == "needs_human"
    assert item["blocker"] == {
        "reason": item["failure_reason"],
        "question": item["blocking_question"],
    }
    assert "receipt_id" not in item and "pid" not in item

    SwarmSupervisor._reset_work_order_for_requeue(item)
    assert item["status"] == "queued"
    assert item["review_status"] == "pending"
    assert "lease_id" not in item and "blocking_question" not in item


def test_waiting_conflict_marks_and_clears() -> None:
    item: dict[str, object] = {"status": "queued"}
    SwarmSupervisor._mark_waiting_conflict(item, [{"path": "aragora/swarm/x.py"}])
    assert item["status"] == "waiting_conflict"
    assert item["failure_reason"] == "waiting_conflict"
    assert item["blocking_question"] == SwarmSupervisor._default_blocking_question(
        "waiting_conflict"
    )
    SwarmSupervisor._clear_waiting_state(item)
    assert "conflicts" not in item
