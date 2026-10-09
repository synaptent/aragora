"""Handing a run to the debate runner: a run that cannot start ends failed, never debating."""

from __future__ import annotations

import json

import pytest

from aragora.decision_workspace import debate_hook
from aragora.decision_workspace.config import ENV_AGENTS, WorkspaceLimits, agent_options
from aragora.decision_workspace.debate_hook import (
    NO_RUNNER_ERROR,
    DebateNotStartedError,
    DebateStartRequest,
    launch_decision_run,
    start_decision_debate,
)
from aragora.decision_workspace.forms import parse_json_intake
from aragora.decision_workspace.intake import prepare_decision
from aragora.decision_workspace.store import WorkspaceStore, new_decision_rows
from aragora.pipeline.plan_store import PlanStore

ORG = "org-hook"


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(debate_hook, "_starter", None)
    path = tmp_path / "plans.db"
    PlanStore(str(path))
    store = WorkspaceStore(str(path))
    body = json.dumps({"question": "Q?", "pasted_text": "One.", "agents": ["grok"]}).encode()
    prepared = prepare_decision(
        parse_json_intake(body),
        options=agent_options({ENV_AGENTS: "grok"}),
        limits=WorkspaceLimits(max_documents=1, max_file_bytes=10, max_pasted_chars=100),
    )
    rows = new_decision_rows(prepared, plan_id="dp-hook", org_id=ORG, user_id="u", document_ids={})
    store.insert_decision(rows)
    request = DebateStartRequest(
        plan_id="dp-hook",
        org_id=ORG,
        user_id="u",
        question="Q?",
        agents=("grok",),
        rounds=1,
        run_id=rows.run.run_id,
    )
    return store, request


def test_missing_runner_is_an_error_naming_the_cause(monkeypatch):
    request = DebateStartRequest("p", ORG, "u", "Q?", ("grok",), 1, "run_x")
    monkeypatch.setattr(debate_hook, "_starter", None)
    with pytest.raises(DebateNotStartedError, match="runner is not available"):
        start_decision_debate(request)


def test_launch_without_a_runner_fails_the_run_and_the_decision(seeded):
    store, request = seeded
    assert launch_decision_run(store, request) is False
    run = store.get_run(request.run_id, ORG)
    assert (run.status, run.error) == ("failed", NO_RUNNER_ERROR)
    assert store.get_decision("dp-hook", ORG).status == "failed"


def test_launch_with_a_raising_runner_fails_the_run_with_the_reason(seeded):
    store, request = seeded

    def starter(_request):
        raise OSError("can't start new thread")

    debate_hook.set_decision_debate_starter(starter)
    assert launch_decision_run(store, request) is False
    run = store.get_run(request.run_id, ORG)
    assert run.status == "failed"
    assert run.error == "The debate could not be started: OSError: can't start new thread"
    assert store.get_decision("dp-hook", ORG).status == "failed"


def test_launch_with_a_runner_leaves_the_run_to_it(seeded):
    store, request = seeded
    taken: list[DebateStartRequest] = []
    debate_hook.set_decision_debate_starter(taken.append)
    assert launch_decision_run(store, request) is True
    assert taken == [request]
    assert store.get_run(request.run_id, ORG).status == "running"
    assert store.get_decision("dp-hook", ORG).status == "debating"
