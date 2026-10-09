"""Run the grounded debate and the structured synthesis for one decision run.

Each run is scheduled with ``schedule_coroutine`` (from a request thread that
means its own thread and event loop), so the request does not wait on it, and
its total time is bounded by
``ARAGORA_WORKSPACE_RUN_TIMEOUT_SECONDS``. The debate goes through the stock
``DebateFactory`` with exactly the selected agents and only the decision's
passages as context; the first selected agent then turns the debate into
the structured result. Whatever happens, the run row ends in a final status
with its partial record, so the decision never stays ``debating``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import Counter
from collections.abc import Callable, Coroutine, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from aragora.decision_workspace import config as workspace_config
from aragora.decision_workspace.citations import check_result
from aragora.decision_workspace.context import build_debate_context, new_nonce
from aragora.decision_workspace.costs import (
    CostLedger,
    phase_tokens,
    price,
    token_usage,
    unwrap_agent,
)
from aragora.decision_workspace.debate_hook import DebateStartRequest
from aragora.decision_workspace.store import (
    RUN_BUDGET_EXCEEDED,
    RUN_COMPLETED,
    RUN_FAILED,
    WorkspaceStore,
)
from aragora.decision_workspace.synthesis import (
    SynthesisOutcome,
    build_synthesis_prompt,
    synthesize,
)
from aragora.utils.error_sanitizer import sanitize_error

logger = logging.getLogger(__name__)

DEBATE_SOURCE = "decision_workspace"
MAX_TRANSCRIPT_ENTRIES = 200
MAX_ENTRY_CHARS = 8000
CONTEXT_TOKEN_MARGIN = 1000
MAX_AGENT_NAME_CHARS = 32

ArenaFactory = Callable[[Any, dict[str, Callable[..., None]]], Any]
Spawner = Callable[[Coroutine[Any, Any, Any], str], object]


class _RunFailure(Exception):
    """Ends the run with ``status`` and a message that is safe to show."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def default_arena_factory(config: Any, hooks: dict[str, Callable[..., None]]) -> Any:
    from aragora.server.debate_factory import DebateFactory

    return DebateFactory().create_arena(config, event_hooks=hooks, enable_rlm_training=False)


def default_spawn(coro: Coroutine[Any, Any, Any], name: str) -> object:
    from aragora.pipeline.canonical_execution import schedule_coroutine

    return schedule_coroutine(coro, name=name)


def panel_specs(selection: Sequence[str]) -> str:
    """The selection as explicit agent specs (JSON) whose names are all distinct.

    Agents are named after their provider, so two VibeProxy models (both
    ``openai-api``) would share a name, and the arena keys proposals,
    critiques and votes by name: one agent's work would be lost. Agents whose
    default names clash are named after their model instead, within the
    agent-name rules (``SAFE_AGENT_PATTERN``).
    """
    from aragora.agents.spec import AgentSpec

    specs = [AgentSpec.parse(entry, _warn=False) for entry in selection]
    counts = Counter(str(spec.name) for spec in specs)
    taken = {name for name, count in counts.items() if count == 1}
    panel: list[dict[str, str | None]] = []
    for spec in specs:
        name = str(spec.name)
        if counts[name] > 1:
            label = spec.model or spec.provider
            name, number = _agent_name(label), 2
            while name in taken:
                name, number = _agent_name(label, f"-{number}"), number + 1
            taken.add(name)
        panel.append(
            {
                "provider": spec.provider,
                "model": spec.model,
                "persona": spec.persona,
                "role": spec.role,
                "name": name,
            }
        )
    return json.dumps(panel)


def _agent_name(label: str, suffix: str = "") -> str:
    name = re.sub(r"\.{2,}", ".", re.sub(r"[^A-Za-z0-9._-]+", "-", label)).strip(".")
    return (name or "agent")[: MAX_AGENT_NAME_CHARS - len(suffix)].rstrip(".") + suffix


def default_cost_tracker() -> Any | None:
    try:
        from aragora.billing.cost_tracker import get_cost_tracker

        return get_cost_tracker()
    except Exception:  # noqa: BLE001 - the runner enforces the budget itself without one
        logger.warning("CostTracker unavailable; decision budgets are checked locally")
        return None


def widen_context_budget(arena: Any, context: str) -> None:
    """Let the prompt builder carry the whole evidence block.

    The stock budget trims the debate context to about 5,600 characters; the
    workspace has already chosen which passages fit, so trimming here would
    silently drop passages the decision reports as in context.
    """
    builder = getattr(arena, "prompt_builder", None)
    if builder is None or not hasattr(builder, "_context_budgeter"):
        return
    from aragora.debate.context_budgeter import (
        ContextBudgeter,
        get_section_limits,
        get_total_tokens,
    )

    needed = (len("Context: ") + len(context)) // 4 + CONTEXT_TOKEN_MARGIN
    limits = get_section_limits()
    if needed <= limits.get("env_context", 0):
        return
    limits["env_context"] = needed
    builder._context_budgeter = ContextBudgeter(
        total_tokens=get_total_tokens() + needed, section_limits=limits
    )


class _DebateWatch:
    """Event hooks that keep the partial transcript and stop the debate at the budget."""

    def __init__(self, budget_usd: float) -> None:
        self.budget = Decimal(str(budget_usd))
        self.transcript: list[dict[str, Any]] = []
        self.budget_stopped = False
        self.spent_at_stop = Decimal("0")
        self._agents: list[Any] = []
        self._baselines: list[tuple[int, int]] = []
        self._task: asyncio.Future[Any] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def hooks(self) -> dict[str, Callable[..., None]]:
        return {"on_message": self._on_message, "on_critique": self._on_critique}

    def bind(self, agents: Sequence[Any]) -> None:
        self._agents = list(agents)
        self._baselines = [token_usage(agent) for agent in self._agents]

    def watch(self, task: asyncio.Future[Any]) -> None:
        self._task = task
        self._loop = asyncio.get_running_loop()

    def usage(self, index: int) -> tuple[int, int, bool]:
        """Debate-phase tokens of agent ``index`` (approximated when unreported)."""
        tokens_in, tokens_out = token_usage(self._agents[index])
        base_in, base_out = self._baselines[index]
        name = str(getattr(self._agents[index], "name", ""))
        chars_out = sum(
            len(entry.get("content") or "") for entry in self.transcript if entry["agent"] == name
        )
        return phase_tokens(tokens_in - base_in, tokens_out - base_out, chars_out=chars_out)

    def spent(self) -> Decimal:
        total = Decimal("0")
        for index, agent in enumerate(self._agents):
            tokens_in, tokens_out, _ = self.usage(index)
            total += price(
                str(getattr(unwrap_agent(agent), "model", "") or ""), tokens_in, tokens_out
            )
        return total

    def _record(self, entry: dict[str, Any]) -> None:
        try:
            if len(self.transcript) < MAX_TRANSCRIPT_ENTRIES:
                self.transcript.append(entry)
            self._check_budget()
        except Exception:  # noqa: BLE001 - a hook must never break the debate
            logger.debug("Decision run hook failed", exc_info=True)

    def _check_budget(self) -> None:
        if self.budget_stopped or self._task is None or not self._agents:
            return
        spent = self.spent()
        if spent <= self.budget:
            return
        self.budget_stopped = True
        self.spent_at_stop = spent
        logger.warning("Decision debate reached its budget (%s > %s); stopping", spent, self.budget)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)

    def _on_message(
        self, agent: str = "", content: str = "", role: str = "", round_num: int = 0, **_: Any
    ) -> None:
        self._record(
            {
                "kind": "message",
                "agent": str(agent),
                "role": str(role),
                "round": round_num,
                "content": _clip(content),
            }
        )

    def _on_critique(
        self,
        agent: str = "",
        target: str = "",
        issues: Sequence[str] | None = None,
        round_num: int = 0,
        full_content: str | None = None,
        error: str | None = None,
        **_: Any,
    ) -> None:
        self._record(
            {
                "kind": "critique",
                "agent": str(agent),
                "target": str(target),
                "round": round_num,
                "content": _clip(full_content or "; ".join(str(i) for i in issues or [])),
                "error": None if error is None else sanitize_error(str(error), max_length=300),
            }
        )


class DecisionRunner:
    """The debate starter registered with :mod:`aragora.decision_workspace.debate_hook`."""

    def __init__(
        self,
        *,
        store_provider: Callable[[], WorkspaceStore],
        debate_storage_provider: Callable[[], Any | None] | None = None,
        arena_factory: ArenaFactory = default_arena_factory,
        cost_tracker_provider: Callable[[], Any | None] = default_cost_tracker,
        spawn: Spawner = default_spawn,
    ) -> None:
        self._store_provider = store_provider
        self._debate_storage_provider = debate_storage_provider or (lambda: None)
        self._arena_factory = arena_factory
        self._cost_tracker_provider = cost_tracker_provider
        self._spawn = spawn

    def __call__(self, request: DebateStartRequest) -> None:
        coro = self.run(request)
        try:
            self._spawn(coro, f"decision-run-{request.run_id}")
        except BaseException:
            coro.close()
            raise

    async def run(self, request: DebateStartRequest) -> str:
        """Run the debate and synthesis; returns the run's final status."""
        store = self._store_provider()
        tracker = self._cost_tracker_provider()
        budget_key = f"decision-run:{request.run_id}"
        state: dict[str, Any] = {"result": {}, "ledger": None, "debate_id": None}
        try:
            return await self._run(store, tracker, budget_key, request, state)
        except _RunFailure as failure:
            self._finish(store, request, state, failure.status, failure.message)
            return failure.status
        except Exception as exc:  # noqa: BLE001 - every run must end in a final status
            logger.exception("Decision run %s failed", request.run_id)
            self._finish(store, request, state, RUN_FAILED, _error_text("The run failed", exc))
            return RUN_FAILED
        finally:
            if tracker is not None:
                try:
                    tracker.clear_debate_budget(budget_key)
                except Exception:  # noqa: BLE001 - cleanup only
                    logger.debug("Could not clear decision run budget", exc_info=True)

    async def _run(
        self,
        store: WorkspaceStore,
        tracker: Any | None,
        budget_key: str,
        request: DebateStartRequest,
        state: dict[str, Any],
    ) -> str:
        from aragora.server.debate_factory import DebateConfig

        decision = store.get_decision(request.plan_id, request.org_id)
        if decision is None:
            raise _RunFailure(RUN_FAILED, "The decision no longer exists.")
        sources = store.list_sources(request.plan_id, request.org_id)
        passages = store.list_passages(request.plan_id, request.org_id)
        in_context = [p for p in passages if p.in_context]
        context = build_debate_context(
            sources, [(p.source_label, p) for p in in_context], nonce=new_nonce()
        )
        budget = workspace_config.decision_budget_usd()
        timeout = workspace_config.run_timeout_seconds()
        deadline = time.monotonic() + timeout
        debate_id = f"ws_{uuid.uuid4().hex[:16]}"
        state["debate_id"] = debate_id
        result: dict[str, Any] = state["result"]
        result["context"] = {
            "passages_in_context": len(in_context),
            "passages_omitted": len(passages) - len(in_context),
            "chars": len(context),
        }
        if not store.update_run(
            request.run_id, request.org_id, debate_id=debate_id, budget_usd=budget
        ):
            logger.info("Decision run %s is no longer running; not starting it", request.run_id)
            return "abandoned"
        if tracker is not None:
            tracker.set_debate_limit(budget_key, Decimal(str(budget)))

        watch = _DebateWatch(budget)
        config = DebateConfig(
            question=request.question,
            agents_str=panel_specs(request.agents),
            rounds=request.rounds,
            debate_format="light",
            debate_id=debate_id,
            enable_verticals=False,
            auto_trim_unavailable=False,
            context=context,
            org_id=request.org_id,
            created_by=request.user_id,
            context_only=True,
        )
        try:
            arena = self._arena_factory(config, watch.hooks())
        except ValueError as exc:
            raise _RunFailure(RUN_FAILED, _error_text("The debate could not start", exc)) from exc
        agents = list(getattr(arena, "agents", []) or [])
        if len(agents) != len(request.agents):
            raise _RunFailure(
                RUN_FAILED,
                f"Only {len(agents)} of the {len(request.agents)} selected agents could be "
                "started, so the debate did not run.",
            )
        widen_context_budget(arena, context)
        watch.bind(agents)
        ledger = CostLedger(agents, list(request.agents))
        state["ledger"] = ledger

        debate_result, failure = await self._debate(arena, watch, timeout)
        for index in range(len(agents)):
            tokens_in, tokens_out, approximated = watch.usage(index)
            ledger.charge(index, tokens_in, tokens_out, approximated=approximated)
        result["debate"] = _debate_record(debate_result, watch.transcript)
        result["costs"] = ledger.to_list()
        result["debate_persisted"] = self._persist_debate(
            debate_id, request, debate_result, watch.transcript
        )
        self._save_progress(store, request, state)
        if failure is not None:
            raise failure

        spent = _charge_budget(tracker, budget_key, ledger.total_usd, budget)
        if spent is not None:
            raise _RunFailure(
                RUN_BUDGET_EXCEEDED,
                f"The run used ${spent:.4f} of its ${budget:.2f} budget during the debate, "
                "so the synthesis step did not run.",
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _RunFailure(RUN_FAILED, _timeout_text(timeout))
        synthesizer = unwrap_agent(agents[0])
        before = token_usage(synthesizer)
        prompts: list[str] = []

        async def generate(prompt: str) -> str:
            prompts.append(prompt)
            return await synthesizer.generate(prompt)

        prompt = build_synthesis_prompt(
            question=request.question,
            context=context,
            final_answer=getattr(debate_result, "final_answer", "") or "",
            proposals=dict(getattr(debate_result, "proposals", {}) or {}),
            dissenting_views=list(getattr(debate_result, "dissenting_views", []) or []),
            cruxes=list(getattr(debate_result, "debate_cruxes", []) or []),
        )
        synthesis_record: dict[str, Any] = {"agent": ledger.to_list()[0]["agent"]}
        result["synthesis"] = synthesis_record
        outcome: SynthesisOutcome | None = None
        try:
            outcome = await asyncio.wait_for(synthesize(generate, prompt), timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise _RunFailure(RUN_FAILED, _timeout_text(timeout)) from exc
        except Exception as exc:  # noqa: BLE001 - the run records the failure
            raise _RunFailure(RUN_FAILED, _error_text("The synthesis request failed", exc)) from exc
        finally:
            after = token_usage(synthesizer)
            tokens_in, tokens_out, approximated = phase_tokens(
                after[0] - before[0],
                after[1] - before[1],
                chars_in=sum(len(p) for p in prompts),
                chars_out=sum(len(o) for o in outcome.raw_outputs) if outcome else 0,
            )
            phase_cost = ledger.charge(0, tokens_in, tokens_out, approximated=approximated)
            result["costs"] = ledger.to_list()
        synthesis_record.update(
            {
                "attempts": outcome.attempts,
                "raw_outputs": outcome.raw_outputs,
                "error": outcome.error,
            }
        )
        spent = _charge_budget(tracker, budget_key, phase_cost, budget, total=ledger.total_usd)
        if spent is not None:
            raise _RunFailure(
                RUN_BUDGET_EXCEEDED,
                f"The run used ${spent:.4f} of its ${budget:.2f} budget, so its result "
                "was not made a revision.",
            )
        if outcome.result is None:
            raise _RunFailure(RUN_FAILED, outcome.error or "The synthesis produced no result.")

        content = check_result(outcome.result, passages)
        self._finish(store, request, state, RUN_COMPLETED, None, revision_content=content)
        return RUN_COMPLETED

    @staticmethod
    async def _debate(
        arena: Any, watch: _DebateWatch, timeout: float
    ) -> tuple[Any | None, _RunFailure | None]:
        task = asyncio.ensure_future(arena.run())
        watch.watch(task)
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return None, _RunFailure(RUN_FAILED, _timeout_text(timeout))
        if task.cancelled():
            if watch.budget_stopped:
                return None, _RunFailure(
                    RUN_BUDGET_EXCEEDED,
                    f"The debate was stopped after using ${watch.spent_at_stop:.4f}, more than "
                    f"its ${watch.budget:.2f} budget.",
                )
            return None, _RunFailure(RUN_FAILED, "The debate was cancelled before it finished.")
        exc = task.exception()
        if exc is not None:
            logger.warning("Decision debate failed: %s", exc, exc_info=exc)
            return None, _RunFailure(RUN_FAILED, _error_text("The debate failed", exc))
        return task.result(), None

    def _persist_debate(
        self,
        debate_id: str,
        request: DebateStartRequest,
        debate_result: Any | None,
        transcript: list[dict[str, Any]],
    ) -> bool:
        """Store the debate (or what was captured of it) as a private debate of the org."""
        storage = self._debate_storage_provider()
        if storage is None:
            logger.warning("No debate storage; debate %s is not persisted", debate_id)
            return False
        if debate_result is not None:
            messages = [_message_dict(m) for m in getattr(debate_result, "messages", None) or []]
        else:
            messages = [
                {
                    "role": entry.get("role") or entry["kind"],
                    "agent": entry["agent"],
                    "content": entry["content"],
                    "round": entry["round"],
                }
                for entry in transcript
            ]
        data = {
            "id": debate_id,
            "task": request.question,
            "agents": list(request.agents),
            "rounds": request.rounds,
            "final_answer": getattr(debate_result, "final_answer", "") or "",
            "consensus_reached": bool(getattr(debate_result, "consensus_reached", False)),
            "confidence": float(getattr(debate_result, "confidence", 0.0) or 0.0),
            "messages": messages,
            "status": "completed" if debate_result is not None else "incomplete",
            "source": DEBATE_SOURCE,
            "decision_id": request.plan_id,
        }
        try:
            storage.save_dict(_json_safe(data), org_id=request.org_id)
        except Exception:  # noqa: BLE001 - the run keeps its own copy of the record
            logger.exception("Could not persist workspace debate %s", debate_id)
            return False
        return True

    @staticmethod
    def _save_progress(
        store: WorkspaceStore, request: DebateStartRequest, state: dict[str, Any]
    ) -> None:
        ledger: CostLedger | None = state["ledger"]
        store.update_run(
            request.run_id,
            request.org_id,
            cost_actual_usd=float(ledger.actual_usd) if ledger else None,
            cost_estimated_usd=float(ledger.estimated_usd) if ledger else None,
            result=_json_safe(state["result"]),
        )

    @staticmethod
    def _finish(
        store: WorkspaceStore,
        request: DebateStartRequest,
        state: dict[str, Any],
        status: str,
        error: str | None,
        *,
        revision_content: Mapping[str, Any] | None = None,
    ) -> None:
        ledger: CostLedger | None = state["ledger"]
        try:
            finished = store.finish_run(
                request.run_id,
                request.org_id,
                status=status,
                error=error,
                result=_json_safe(state["result"]) if state["result"] else None,
                debate_id=state["debate_id"],
                cost_actual_usd=float(ledger.actual_usd) if ledger else None,
                cost_estimated_usd=float(ledger.estimated_usd) if ledger else None,
                revision_content=revision_content,
            )
        except Exception:  # noqa: BLE001 - logged; the restart sweep settles the run
            logger.exception("Could not record the end of decision run %s", request.run_id)
            return
        if not finished:
            logger.info("Decision run %s was already settled; result dropped", request.run_id)
        else:
            logger.info("Decision run %s ended %s", request.run_id, status)


def _charge_budget(
    tracker: Any | None,
    key: str,
    cost: Decimal,
    budget: float,
    *,
    total: Decimal | None = None,
) -> Decimal | None:
    """Record ``cost`` against the run budget; the total spent when it is exceeded."""
    spent = cost if total is None else total
    if tracker is not None:
        status = tracker.record_debate_cost(key, cost)
        if status.get("allowed", True):
            return None
        return Decimal(str(status.get("current_cost", spent)))
    return spent if spent > Decimal(str(budget)) else None


def _debate_record(debate_result: Any | None, transcript: list[dict[str, Any]]) -> dict[str, Any]:
    if debate_result is None:
        return {"completed": False, "transcript": transcript}
    return {
        "completed": True,
        "final_answer": getattr(debate_result, "final_answer", "") or "",
        "consensus_reached": bool(getattr(debate_result, "consensus_reached", False)),
        "confidence": getattr(debate_result, "confidence", None),
        "rounds_used": getattr(debate_result, "rounds_used", None),
        "winner": getattr(debate_result, "winner", None),
        "participants": list(getattr(debate_result, "participants", []) or []),
        "proposals": dict(getattr(debate_result, "proposals", {}) or {}),
        "dissenting_views": list(getattr(debate_result, "dissenting_views", []) or []),
        "debate_cruxes": list(getattr(debate_result, "debate_cruxes", []) or []),
        "evidence_suggestions": list(getattr(debate_result, "evidence_suggestions", []) or []),
        "agent_failures": dict(getattr(debate_result, "agent_failures", {}) or {}),
    }


def _message_dict(message: Any) -> dict[str, Any]:
    timestamp = getattr(message, "timestamp", None)
    if isinstance(timestamp, datetime):
        timestamp = timestamp.isoformat()
    return {
        "role": getattr(message, "role", ""),
        "agent": getattr(message, "agent", ""),
        "content": getattr(message, "content", ""),
        "round": getattr(message, "round", 0),
        "timestamp": None if timestamp is None else str(timestamp),
    }


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _clip(text: Any) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= MAX_ENTRY_CHARS else text[:MAX_ENTRY_CHARS] + " [...]"


def _error_text(prefix: str, exc: BaseException) -> str:
    detail = sanitize_error(f"{type(exc).__name__}: {exc}", max_length=400)
    return f"{prefix}: {detail}"


def _timeout_text(timeout: float) -> str:
    return f"The run did not finish within {int(timeout)} seconds and was stopped."


__all__ = [
    "DecisionRunner",
    "default_arena_factory",
    "default_spawn",
    "widen_context_budget",
]
