"""Decision workspace startup: runs a restart cut off end interrupted, then the runner is registered."""

from __future__ import annotations

import dataclasses
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import aragora.pipeline.plan_store as plan_store_module
from aragora.decision_workspace import debate_hook
from aragora.decision_workspace import store as workspace_store
from aragora.decision_workspace.config import ENV_AGENTS, WorkspaceLimits, agent_options
from aragora.decision_workspace.forms import parse_json_intake
from aragora.decision_workspace.intake import prepare_decision
from aragora.decision_workspace.runner import DecisionRunner
from aragora.decision_workspace.store import (
    INTERRUPTED_RUN_ERROR,
    ORPHANED_DECISION_ERROR,
    get_workspace_store,
    new_decision_rows,
)
from aragora.pipeline.plan_store import PlanStore
from aragora.server.startup.decision_workspace import init_decision_workspace

ORG = "org-startup"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(debate_hook, "_starter", None)
    monkeypatch.setattr(workspace_store, "_stores", {})
    plans = PlanStore(str(tmp_path / "plans.db"))
    monkeypatch.setattr(plan_store_module, "_store", plans)
    return get_workspace_store(plans.db_path)


def _insert(store, plan_id, *, with_run=True):
    body = json.dumps({"question": "Q?", "pasted_text": "One.", "agents": ["grok"]}).encode()
    prepared = prepare_decision(
        parse_json_intake(body),
        options=agent_options({ENV_AGENTS: "grok"}),
        limits=WorkspaceLimits(max_documents=1, max_file_bytes=10, max_pasted_chars=100),
    )
    rows = new_decision_rows(prepared, plan_id=plan_id, org_id=ORG, user_id="u", document_ids={})
    if not with_run:
        rows = dataclasses.replace(rows, run=None)
    store.insert_decision(rows)
    return rows


def test_runs_left_running_become_interrupted_and_their_decisions_failed(workspace, tmp_path):
    running = _insert(workspace, "dp-running")
    _insert(workspace, "dp-orphan", with_run=False)

    status = init_decision_workspace(tmp_path)

    assert (status["runs_interrupted"], status["decisions_failed"]) == (1, 2)
    run = workspace.get_run(running.run.run_id, ORG)
    assert (run.status, run.error) == ("interrupted", INTERRUPTED_RUN_ERROR)
    assert workspace.get_decision("dp-running", ORG).status == "failed"
    (orphan_run,) = workspace.list_runs("dp-orphan", ORG)
    assert (orphan_run.status, orphan_run.error) == ("interrupted", ORPHANED_DECISION_ERROR)
    assert workspace.get_decision("dp-orphan", ORG).status == "failed"
    for plan_id in ("dp-running", "dp-orphan"):
        assert workspace.start_run(plan_id, ORG, "u").status == "running"


def test_the_runner_is_registered_after_the_sweep(workspace, tmp_path):
    status = init_decision_workspace(tmp_path)
    assert status["runner"] is True
    assert isinstance(debate_hook.get_decision_debate_starter(), DecisionRunner)

    fresh = _insert(workspace, "dp-fresh")
    init_decision_workspace(tmp_path)
    assert workspace.get_run(fresh.run.run_id, ORG).status == "interrupted"


def test_a_failing_sweep_still_registers_the_runner(workspace, tmp_path, monkeypatch):
    def broken(self, *, started_before):
        raise OSError("database is locked")

    monkeypatch.setattr(workspace_store.WorkspaceStore, "sweep_after_restart", broken)
    status = init_decision_workspace(tmp_path)
    assert (status["runner"], status["sweep_error"]) == (True, "OSError")


async def test_parallel_startup_runs_the_workspace_init_with_the_nomic_dir(tmp_path, monkeypatch):
    import aragora.server.startup.decision_workspace as startup_module
    import aragora.server.startup.workers as workers
    from aragora.server.startup.parallel import ParallelInitializer

    for name in (
        "init_workflow_checkpoint_persistence",
        "init_webhook_dispatcher",
        "init_slo_webhooks",
        "init_gauntlet_run_recovery",
    ):
        monkeypatch.setattr(workers, name, MagicMock(return_value=0))
    for name in (
        "init_durable_job_queue_recovery",
        "init_gauntlet_worker",
        "init_backup_scheduler",
        "init_notification_worker",
    ):
        monkeypatch.setattr(workers, name, AsyncMock(return_value=False))
    init = MagicMock(return_value={"runner": True})
    monkeypatch.setattr(startup_module, "init_decision_workspace", init)

    results = await ParallelInitializer(nomic_dir=tmp_path)._init_workers()

    init.assert_called_once_with(tmp_path)
    assert results["decision_workspace"] == {"runner": True}
