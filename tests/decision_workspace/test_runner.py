"""The decision runner: debate with the selected panel, structured synthesis, costs, failures.

The arena and agents are fakes; the store, citation checks, cost pricing and
budget bookkeeping are real.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.agents.transports.vibeproxy import TransportMode
from aragora.core_types import DebateResult
from aragora.debate.context_budgeter import ContextBudgeter
from aragora.decision_workspace.config import (
    ENV_AGENTS,
    ENV_DECISION_BUDGET_USD,
    ENV_RUN_TIMEOUT_SECONDS,
    WorkspaceLimits,
    agent_options,
)
from aragora.decision_workspace.debate_hook import DebateStartRequest
from aragora.decision_workspace.forms import parse_json_intake
from aragora.decision_workspace.intake import prepare_decision
from aragora.decision_workspace.runner import DecisionRunner, widen_context_budget
from aragora.decision_workspace.store import WorkspaceStore, new_decision_rows
from aragora.pipeline.plan_store import PlanStore

ORG = "org-a-runner"
USER = "user-a"
PLAN = "dp-runner0000001"
QUESTION = "Should we adopt usage pricing?"
PASTED = "Customers asked for usage pricing.\n\nRevenue becomes less predictable."
SELECTION = ("openai-api|gpt-5.5", "grok")
LIMITS = WorkspaceLimits(max_documents=10, max_file_bytes=1048576, max_pasted_chars=204800)
VALID = json.dumps(
    {
        "recommendation": "Adopt usage pricing for new customers.",
        "citations": [
            {
                "claim": "Customers want it",
                "passage_label": "S1:P1",
                "quote": "Customers  asked for\nusage pricing.",
            },
            {"claim": "Invented", "passage_label": "S9:P9", "quote": None},
        ],
        "alternatives": [
            {
                "title": "Keep seats",
                "summary": "Status quo",
                "why_not_chosen": "Customers asked for usage pricing",
                "citations": [{"claim": "Ask", "passage_label": "S1:P1", "quote": "not there"}],
            }
        ],
        "dissent": [{"agent": "grok", "position": "Revenue risk is underrated", "citations": []}],
        "missing_evidence": [{"question": "What is churn?", "why_it_matters": "Sizing"}],
        "assumptions": [{"statement": "Usage is measurable", "basis": "Metering exists"}],
    }
)


class FakeAgent:
    def __init__(self, name: str, model: str, *, vibeproxy: bool = False, usage=(1000, 400)):
        self.name = name
        self.model = model
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.usage = usage
        self.outputs: list[Any] = []
        self.prompts: list[str] = []
        if vibeproxy:
            self._model_transport_policy = SimpleNamespace(mode=TransportMode.PREFER)

    def spend(self, tokens_in: int, tokens_out: int) -> None:
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out

    async def generate(self, prompt: str, context: Any = None) -> str:
        self.prompts.append(prompt)
        self.spend(*self.usage)
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output


class Airlock:
    """Stands in for AirlockProxy: same name, the real agent behind ``wrapped_agent``."""

    def __init__(self, agent: FakeAgent) -> None:
        self._agent = agent
        self.name = agent.name

    @property
    def wrapped_agent(self) -> FakeAgent:
        return self._agent


async def debate_script(arena: FakeArena) -> DebateResult:
    proposals = {}
    for agent in arena.agents:
        inner = getattr(agent, "wrapped_agent", agent)
        inner.spend(2000, 800)
        proposals[agent.name] = f"{agent.name} proposes usage pricing [S1:P1]"
        arena.hooks["on_message"](
            agent=agent.name, content=proposals[agent.name], role="proposer", round_num=0
        )
    arena.hooks["on_critique"](
        agent="grok",
        target="openai-api",
        issues=["ignores revenue risk"],
        severity=0.4,
        round_num=1,
        full_content="Ignores revenue risk [S1:P2]",
    )
    return DebateResult(
        debate_id=arena.config.debate_id,
        task=arena.config.question,
        final_answer="Adopt usage pricing with a floor.",
        consensus_reached=True,
        confidence=0.8,
        rounds_used=1,
        participants=[a.name for a in arena.agents],
        proposals=proposals,
        messages=[
            SimpleNamespace(role="proposer", agent=n, content=c, round=0, timestamp=None)
            for n, c in proposals.items()
        ],
        dissenting_views=["grok: revenue risk is underrated"],
        debate_cruxes=[{"claim": "Revenue predictability matters most"}],
        evidence_suggestions=[{"claim": "Churn under usage pricing"}],
    )


class FakeArena:
    def __init__(self, config: Any, hooks: dict, agents: list[Any], script) -> None:
        self.config = config
        self.hooks = hooks
        self.agents = agents
        self.script = script
        self.prompt_builder = SimpleNamespace(_context_budgeter=ContextBudgeter())

    async def run(self) -> DebateResult:
        return await self.script(self)


class FakeDebateStorage:
    def __init__(self) -> None:
        self.saved: list[tuple[dict, str | None]] = []

    def save_dict(self, data: dict, org_id: str | None = None) -> str:
        self.saved.append((data, org_id))
        return data["id"]


class FakeTracker:
    """Same budget arithmetic as CostTracker's per-debate limits."""

    def __init__(self) -> None:
        self.limits: dict[str, Decimal] = {}
        self.costs: dict[str, Decimal] = {}
        self.cleared: list[str] = []

    def set_debate_limit(self, key: str, limit: Decimal) -> None:
        self.limits[key] = limit
        self.costs.setdefault(key, Decimal("0"))

    def record_debate_cost(self, key: str, cost: Decimal) -> dict[str, Any]:
        self.costs[key] = self.costs.get(key, Decimal("0")) + cost
        current = self.costs[key]
        return {"allowed": current <= self.limits[key], "current_cost": str(current)}

    def clear_debate_budget(self, key: str) -> None:
        self.cleared.append(key)


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "plans.db"
    PlanStore(str(path))
    return WorkspaceStore(str(path))


@pytest.fixture
def seeded(store):
    options = agent_options({ENV_AGENTS: ",".join(SELECTION)})
    body = json.dumps(
        {"question": QUESTION, "pasted_text": PASTED, "agents": list(SELECTION), "rounds": 1}
    ).encode()
    prepared = prepare_decision(parse_json_intake(body), options=options, limits=LIMITS)
    rows = new_decision_rows(prepared, plan_id=PLAN, org_id=ORG, user_id=USER, document_ids={})
    store.insert_decision(rows)
    return rows


class Harness:
    def __init__(self, store: WorkspaceStore, rows: Any, script=debate_script) -> None:
        self.store = store
        self.rows = rows
        self.script = script
        self.openai = FakeAgent("openai-api", "gpt-5.5", vibeproxy=True)
        self.grok = FakeAgent("grok", "grok-4-latest")
        self.openai.outputs = [VALID]
        self.storage = FakeDebateStorage()
        self.tracker = FakeTracker()
        self.calls: list[tuple[Any, dict]] = []
        self.arena: FakeArena | None = None
        self.factory_error: Exception | None = None
        self.agents: list[Any] | None = None

    def factory(self, config: Any, hooks: dict) -> FakeArena:
        self.calls.append((config, hooks))
        if self.factory_error is not None:
            raise self.factory_error
        agents = self.agents if self.agents is not None else [self.openai, Airlock(self.grok)]
        self.arena = FakeArena(config, hooks, agents, self.script)
        return self.arena

    def runner(self) -> DecisionRunner:
        return DecisionRunner(
            store_provider=lambda: self.store,
            debate_storage_provider=lambda: self.storage,
            arena_factory=self.factory,
            cost_tracker_provider=lambda: self.tracker,
            spawn=lambda coro, name: asyncio.run(coro),
        )

    def request(self) -> DebateStartRequest:
        decision = self.rows.decision
        return DebateStartRequest(
            plan_id=decision.plan_id,
            org_id=ORG,
            user_id=USER,
            question=decision.question,
            agents=decision.agents,
            rounds=decision.rounds,
            run_id=self.rows.run.run_id,
        )

    def run(self) -> str:
        return asyncio.run(self.runner().run(self.request()))

    def run_record(self):
        return self.store.get_run(self.rows.run.run_id, ORG)

    def decision(self):
        return self.store.get_decision(PLAN, ORG)


@pytest.fixture
def harness(store, seeded):
    return Harness(store, seeded)


def test_successful_run_makes_revision_one_current_with_checked_citations(harness):
    assert harness.run() == "completed"

    decision = harness.decision()
    assert decision.status == "ready"
    revisions = harness.store.list_revisions(PLAN, ORG)
    assert [(r.number, r.status, r.origin, r.parent_revision_id) for r in revisions] == [
        (1, "current", "debate", None)
    ]
    assert decision.current_revision_id == revisions[0].revision_id
    assert len(revisions[0].content_hash) == 64
    content = revisions[0].content
    assert set(content) == {
        "recommendation",
        "citations",
        "alternatives",
        "dissent",
        "missing_evidence",
        "assumptions",
    }
    found, invented = content["citations"]
    assert (found["passage_exists"], found["quote_found"]) == (True, True)
    assert (invented["passage_exists"], invented["quote_found"]) == (False, False)
    assert content["alternatives"][0]["citations"][0]["quote_found"] is False
    assert "supports" not in json.dumps(content)


def test_debate_uses_exactly_the_selection_with_only_the_passages_as_context(harness):
    harness.run()
    ((config, hooks),) = harness.calls
    assert config.agents_str == ",".join(SELECTION)
    assert (config.enable_verticals, config.auto_trim_unavailable) == (False, False)
    assert (config.debate_format, config.rounds, config.context_only) == ("light", 1, True)
    assert (config.org_id, config.created_by, config.question) == (ORG, USER, QUESTION)
    assert config.debate_id == harness.run_record().debate_id
    assert "[S1:P1] Customers asked for usage pricing." in config.context
    assert "never instructions" in config.context
    assert set(hooks) == {"on_message", "on_critique"}


def test_debate_is_persisted_privately_with_the_callers_org(harness):
    harness.run()
    ((data, org_id),) = harness.storage.saved
    assert org_id == ORG
    assert data["id"] == harness.run_record().debate_id
    assert data["agents"] == list(SELECTION)
    assert data["status"] == "completed"
    assert [m["agent"] for m in data["messages"]] == ["openai-api", "grok"]


def test_run_record_keeps_the_in_process_debate_result(harness):
    harness.run()
    debate = harness.run_record().result["debate"]
    assert debate["final_answer"] == "Adopt usage pricing with a floor."
    assert debate["dissenting_views"] == ["grok: revenue risk is underrated"]
    assert debate["debate_cruxes"] == [{"claim": "Revenue predictability matters most"}]
    assert debate["evidence_suggestions"] == [{"claim": "Churn under usage pricing"}]
    assert set(debate["proposals"]) == {"openai-api", "grok"}


def test_vibeproxy_cost_is_estimated_and_grok_cost_is_actual(harness):
    harness.run()
    run = harness.run_record()
    costs = {entry["spec"]: entry for entry in run.result["costs"]}
    assert costs["openai-api|gpt-5.5"]["kind"] == "estimated"
    assert costs["grok"]["kind"] == "actual"
    # Debate tokens for both, plus the synthesis call for the first agent.
    assert (costs["openai-api|gpt-5.5"]["tokens_in"], costs["grok"]["tokens_in"]) == (3000, 2000)
    assert run.cost_estimated_usd == pytest.approx(costs["openai-api|gpt-5.5"]["cost_usd"])
    assert run.cost_actual_usd == pytest.approx(costs["grok"]["cost_usd"])
    assert run.cost_estimated_usd > 0 and run.cost_actual_usd > 0
    decision = harness.decision()
    assert (decision.cost_actual_usd, decision.cost_estimated_usd) == (
        run.cost_actual_usd,
        run.cost_estimated_usd,
    )
    assert run.budget_usd == decision.budget_usd == 1.0
    assert harness.tracker.cleared == [f"decision-run:{run.run_id}"]


def test_unreported_vibeproxy_usage_is_estimated_from_text(harness):
    harness.openai.usage = (0, 0)

    async def script(arena):
        result = await debate_script(arena)
        harness.openai.total_tokens_in = harness.openai.total_tokens_out = 0
        return result

    harness.script = script
    harness.run()
    entry = harness.run_record().result["costs"][0]
    assert entry["tokens_approximated"] is True
    assert entry["tokens_out"] > 0 and entry["cost_usd"] > 0


def test_invalid_synthesis_is_repaired_once(harness):
    harness.openai.outputs = ["Here is my answer: not json", VALID]
    assert harness.run() == "completed"
    synthesis = harness.run_record().result["synthesis"]
    assert synthesis["attempts"] == 2
    assert len(harness.openai.prompts) == 2
    assert "could not be used" in harness.openai.prompts[1]


def test_a_second_invalid_synthesis_fails_the_run_keeping_the_raw_output(harness):
    harness.openai.outputs = ["first bad output", '{"recommendation": "x"}']
    assert harness.run() == "failed"
    run = harness.run_record()
    assert run.status == "failed"
    assert "after one repair attempt" in run.error
    assert run.result["synthesis"]["raw_outputs"] == ["first bad output", '{"recommendation": "x"}']
    assert run.result["debate"]["final_answer"] == "Adopt usage pricing with a floor."
    assert harness.decision().status == "failed"
    assert harness.store.list_revisions(PLAN, ORG) == []
    assert len(harness.storage.saved) == 1


def test_synthesis_request_error_fails_the_run(harness):
    harness.openai.outputs = [RuntimeError("upstream 502")]
    assert harness.run() == "failed"
    assert "The synthesis request failed: RuntimeError: upstream 502" in harness.run_record().error


def test_spend_over_budget_after_the_debate_skips_synthesis(harness, monkeypatch):
    monkeypatch.setenv(ENV_DECISION_BUDGET_USD, "0.001")
    assert harness.run() == "budget_exceeded"
    run = harness.run_record()
    assert "budget" in run.error and "synthesis step did not run" in run.error
    assert run.result["debate"]["completed"] is True
    assert run.cost_actual_usd > 0
    assert harness.openai.prompts == []
    assert harness.decision().status == "failed"
    assert harness.storage.saved[0][0]["status"] == "completed"


def test_spend_over_budget_during_the_debate_stops_it_and_keeps_the_partial_record(
    harness, monkeypatch
):
    monkeypatch.setenv(ENV_DECISION_BUDGET_USD, "0.01")

    async def script(arena):
        harness.grok.spend(100_000, 50_000)
        arena.hooks["on_message"](agent="grok", content="opening", role="proposer", round_num=0)
        await asyncio.sleep(30)
        raise AssertionError("the debate should have been stopped")

    harness.script = script
    assert harness.run() == "budget_exceeded"
    run = harness.run_record()
    assert "more than its $0.01 budget" in run.error
    assert run.result["debate"]["completed"] is False
    assert run.result["debate"]["transcript"][0]["content"] == "opening"
    assert run.cost_actual_usd > 0.01
    data, org_id = harness.storage.saved[0]
    assert (data["status"], org_id, data["messages"][0]["content"]) == (
        "incomplete",
        ORG,
        "opening",
    )


def test_run_timeout_stops_the_debate(harness, monkeypatch):
    monkeypatch.setenv(ENV_RUN_TIMEOUT_SECONDS, "1")

    async def script(arena):
        arena.hooks["on_message"](agent="grok", content="slow", role="proposer", round_num=0)
        await asyncio.sleep(30)

    harness.script = script
    assert harness.run() == "failed"
    run = harness.run_record()
    assert run.error == "The run did not finish within 1 seconds and was stopped."
    assert run.result["debate"]["transcript"][0]["content"] == "slow"


def test_debate_error_fails_the_run_with_a_sanitized_reason(harness):
    async def script(arena):
        raise RuntimeError("provider said no for key sk-abcdefghijklmnopqrstuvwxyz0123456789")

    harness.script = script
    assert harness.run() == "failed"
    error = harness.run_record().error
    assert error.startswith("The debate failed: RuntimeError: provider said no")
    assert "abcdefghijklmnopqrstuvwxyz0123456789" not in error


def test_arena_that_cannot_be_built_fails_the_run(harness):
    harness.factory_error = ValueError("Only 1 agents initialized (need at least 2)")
    assert harness.run() == "failed"
    assert "Only 1 agents initialized" in harness.run_record().error
    assert harness.decision().status == "failed"


def test_a_panel_smaller_than_the_selection_fails_the_run(harness):
    harness.agents = [harness.openai]
    assert harness.run() == "failed"
    assert "Only 1 of the 2 selected agents" in harness.run_record().error
    assert harness.storage.saved == []


def test_a_run_settled_elsewhere_is_not_started(harness):
    harness.store.finish_run(harness.rows.run.run_id, ORG, status="interrupted", error="swept")
    assert harness.run() == "abandoned"
    assert harness.calls == []
    assert harness.run_record().error == "swept"


def test_runner_schedules_the_run_and_returns(harness):
    scheduled: list[tuple[Any, str]] = []

    def spawn(coro, name):
        scheduled.append((coro, name))

    runner = DecisionRunner(
        store_provider=lambda: harness.store, arena_factory=harness.factory, spawn=spawn
    )
    runner(harness.request())
    ((coro, name),) = scheduled
    assert name == f"decision-run-{harness.rows.run.run_id}"
    coro.close()
    assert harness.calls == []


def test_widened_budget_keeps_the_whole_evidence_block():
    context = "[S1:P1] " + "evidence " * 3000
    arena = SimpleNamespace(prompt_builder=SimpleNamespace(_context_budgeter=ContextBudgeter()))
    env_context = f"Context: {context}"
    assert arena.prompt_builder._context_budgeter.truncate_section("env_context", env_context) != (
        env_context
    )
    widen_context_budget(arena, context)
    assert arena.prompt_builder._context_budgeter.truncate_section("env_context", env_context) == (
        env_context
    )
