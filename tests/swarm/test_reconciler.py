"""Tests for periodic swarm reconciliation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.swarm.reconciler import SwarmReconciler
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.supervisor import SupervisorRun, SwarmApprovalPolicy


def _run(status: str, work_order_statuses: list[str]) -> SupervisorRun:
    return SupervisorRun(
        run_id="run-123",
        goal="goal",
        target_branch="main",
        status=status,
        supervisor_agents={"planner": "codex", "judge": "claude"},
        approval_policy=SwarmApprovalPolicy(),
        spec=SwarmSpec(raw_goal="goal", refined_goal="goal"),
        work_orders=[
            {"work_order_id": f"wo-{idx}", "status": item_status}
            for idx, item_status in enumerate(work_order_statuses, start=1)
        ],
    )


@pytest.mark.asyncio
async def test_tick_run_dispatches_collects_and_syncs_queue() -> None:
    supervisor = MagicMock()
    supervisor.refresh_run.side_effect = [_run("active", ["leased"])]
    supervisor.dispatch_workers = AsyncMock(return_value=[])
    supervisor.collect_finished_results = AsyncMock(return_value=[])
    supervisor.store.sync_pending_work_queue = AsyncMock(return_value={"created": 0})
    supervisor.store.get_supervisor_run.return_value = _run("active", ["dispatched"]).to_dict()

    reconciler = SwarmReconciler(supervisor=supervisor)
    result = await reconciler.tick_run("run-123")

    assert result.run_id == "run-123"
    supervisor.refresh_run.assert_called_once_with("run-123")
    supervisor.dispatch_workers.assert_awaited_once_with("run-123")
    supervisor.collect_finished_results.assert_awaited_once_with("run-123")
    supervisor.store.sync_pending_work_queue.assert_awaited_once()


@pytest.mark.asyncio
async def test_watch_run_stops_when_completed() -> None:
    active = _run("active", ["dispatched"])
    completed = _run("completed", ["merged"])

    reconciler = SwarmReconciler(supervisor=MagicMock())
    reconciler.tick_run = AsyncMock(side_effect=[active, completed])

    result = await reconciler.watch_run("run-123", interval_seconds=0.01, max_ticks=3)

    assert result.status == "completed"
    assert reconciler.tick_run.await_count == 2
