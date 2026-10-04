"""DebateController must honor the configured finite debate deadline.

Server-run debates go through ``run_async``, whose own timeout defaults to
30 s. These tests check that the controller passes the debate's configured
deadline (plus small cleanup margins) instead, that the arena's own deadline
stops an overrunning debate and is recorded as a timeout, that the controller
backstop still fires when the arena has no limit, and that missing or invalid
deadline configuration falls back to a finite value.

Time is virtual: the event loops below jump their clock forward whenever
they would otherwise sleep, so a 45 s or 10,000 s fake debate completes in
milliseconds and the tests stay deterministic.
"""

from __future__ import annotations

import asyncio
import inspect
import math
import selectors
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

import aragora.agents.api_agents.common as api_common
import aragora.server.debate_controller as dc
from aragora.debate.orchestrator import Arena
from aragora.protocols.debate import DebateProtocol
from aragora.server.debate_controller import DebateController
from aragora.server.debate_factory import DebateConfig
from aragora.server.state import get_state_manager
from aragora.server.stream import StreamEventType
from aragora.utils import async_utils

RUN_ASYNC_DEFAULT_TIMEOUT = 30.0


class _VirtualClock:
    def __init__(self) -> None:
        self.now = 0.0


class _JumpingSelector(selectors.DefaultSelector):
    """Selector that advances the virtual clock instead of blocking on timers."""

    def __init__(self, clock: _VirtualClock) -> None:
        super().__init__()
        self._clock = clock

    def select(self, timeout: float | None = None) -> list[Any]:
        if timeout is not None and timeout > 0:
            self._clock.now += timeout
            timeout = 0
        return super().select(timeout)


class _VirtualTimeLoop(asyncio.SelectorEventLoop):
    def __init__(self) -> None:
        self.clock = _VirtualClock()
        super().__init__(selector=_JumpingSelector(self.clock))

    def time(self) -> float:
        return self.clock.now


class _VirtualTimePolicy(asyncio.DefaultEventLoopPolicy):
    """Makes ``asyncio.run`` (the no-pool path of ``run_async``) use virtual time."""

    def __init__(self) -> None:
        super().__init__()
        self.loops: list[_VirtualTimeLoop] = []

    def new_event_loop(self) -> asyncio.AbstractEventLoop:
        loop = _VirtualTimeLoop()
        self.loops.append(loop)
        return loop


@dataclass
class _SharedPoolPath:
    name: str
    loop: _VirtualTimeLoop

    def ran_on_this_path(self, arena: _FakeArena) -> bool:
        return arena.loop is self.loop

    def leftover_tasks(self) -> list[asyncio.Task[Any]]:
        async def _others() -> list[asyncio.Task[Any]]:
            current = asyncio.current_task()
            return [task for task in asyncio.all_tasks() if task is not current]

        return asyncio.run_coroutine_threadsafe(_others(), self.loop).result(timeout=5)


@dataclass
class _NoPoolPath:
    name: str
    policy: _VirtualTimePolicy

    def ran_on_this_path(self, arena: _FakeArena) -> bool:
        return any(arena.loop is loop for loop in self.policy.loops)

    def leftover_tasks(self) -> list[asyncio.Task[Any]]:
        assert self.policy.loops, "run_async never created a temporary loop"
        assert all(loop.is_closed() for loop in self.policy.loops)
        return []


@pytest.fixture(params=["shared_pool", "no_pool"])
def execution_path(request, monkeypatch):
    """Run the controller through either supported ``run_async`` path."""
    if request.param == "shared_pool":
        loop = _VirtualTimeLoop()
        ready = threading.Event()

        def _serve() -> None:
            asyncio.set_event_loop(loop)
            loop.call_soon(ready.set)
            loop.run_forever()

        thread = threading.Thread(target=_serve, name="test-shared-pool-loop", daemon=True)
        thread.start()
        assert ready.wait(timeout=5)
        monkeypatch.setattr(async_utils, "_pool_event_loop_provider", lambda: loop)
        try:
            yield _SharedPoolPath(request.param, loop)
        finally:
            loop.call_soon_threadsafe(loop.stop)
            thread.join(timeout=5)
            loop.close()
    else:
        monkeypatch.setattr(async_utils, "_pool_event_loop_provider", None)
        # nest_asyncio.apply() elsewhere in the worker swaps in an asyncio.run
        # that never closes its loop.
        monkeypatch.setattr(asyncio, "run", asyncio.runners.run)
        policy = _VirtualTimePolicy()
        original_policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(policy)
        try:
            yield _NoPoolPath(request.param, policy)
        finally:
            asyncio.set_event_loop_policy(original_policy)


@pytest.fixture(autouse=True)
def _no_shared_connector_close(monkeypatch):
    monkeypatch.setattr(api_common, "close_shared_connector", AsyncMock())


@dataclass
class _FakeArena:
    """Arena stand-in running the real ``Arena.run`` over ``work_seconds`` of loop time."""

    timeout_seconds: Any
    work_seconds: float
    protocol: Any = field(init=False)
    env: Any = field(init=False)
    loop: asyncio.AbstractEventLoop | None = None
    started_at: float | None = None
    finished_at: float | None = None
    cancelled_at: float | None = None
    cleaned_up: bool = False

    def __post_init__(self) -> None:
        self.protocol = SimpleNamespace(timeout_seconds=self.timeout_seconds, consensus="majority")
        self.env = SimpleNamespace(task="Should our company adopt a four-day work week?")

    run = Arena.run
    _cleanup_debate_persistence = AsyncMock()

    async def _run_inner(self, correlation_id: str = "") -> Any:
        self.loop = asyncio.get_running_loop()
        self.started_at = self.loop.time()
        try:
            await asyncio.sleep(self.work_seconds)
        except asyncio.CancelledError:
            self.cancelled_at = self.loop.time()
            raise
        finally:
            self.cleaned_up = True
        self.finished_at = self.loop.time()
        return SimpleNamespace(
            final_answer="done",
            consensus_reached=True,
            confidence=0.9,
            status="consensus_reached",
            agent_failures={},
            participants=[],
            grounded_verdict=None,
            messages=[],
            explanation=None,
        )

    @property
    def finished_after(self) -> float | None:
        if self.finished_at is None or self.started_at is None:
            return None
        return self.finished_at - self.started_at

    @property
    def cancelled_after(self) -> float | None:
        if self.cancelled_at is None or self.started_at is None:
            return None
        return self.cancelled_at - self.started_at


def _controller(arena: Any, *, storage: Any = None, emitter: Any = None) -> DebateController:
    factory = Mock()
    factory.create_arena.return_value = arena
    factory.reset_circuit_breakers = Mock()
    return DebateController(factory=factory, emitter=emitter or Mock(), storage=storage)


def _config(debate_id: str) -> DebateConfig:
    return DebateConfig(
        question="Should our company adopt a four-day work week?",
        agents_str="openai-api,grok",
        rounds=1,
        debate_id=debate_id,
        org_id="org-a",
    )


@pytest.fixture
def registered_debate():
    manager = get_state_manager()
    created: list[str] = []

    def _register(debate_id: str) -> str:
        manager.register_debate(
            debate_id=debate_id,
            task="Should our company adopt a four-day work week?",
            agents=["openai-api", "grok"],
            total_rounds=1,
        )
        created.append(debate_id)
        return debate_id

    yield _register
    for debate_id in created:
        manager.unregister_debate(debate_id)


class TestDeadlineLongerThanRunAsyncDefault:
    def test_debate_finishes_after_30s_within_configured_deadline(self, execution_path):
        arena = _FakeArena(timeout_seconds=120, work_seconds=45)

        result, _quality, _duration = _controller(arena)._execute_debate_candidate(
            _config("deadline-long"), "deadline-long", {}
        )

        assert execution_path.ran_on_this_path(arena)
        assert result.final_answer == "done"
        assert arena.cancelled_at is None
        assert arena.finished_after == pytest.approx(45.0)
        assert arena.finished_after > RUN_ASYNC_DEFAULT_TIMEOUT

    def test_completed_long_debate_is_persisted_with_creator_org(
        self, execution_path, registered_debate
    ):
        debate_id = registered_debate(f"deadline-persist-{execution_path.name}")
        arena = _FakeArena(timeout_seconds=120, work_seconds=45)
        storage = Mock()
        controller = _controller(arena, storage=storage)
        controller._generate_debate_receipt = Mock()
        controller._emit_leaderboard_update = Mock()

        controller._run_debate(_config(debate_id), debate_id)

        assert execution_path.ran_on_this_path(arena)
        assert get_state_manager().get_debate(debate_id).status == "completed"
        storage.save_dict.assert_called_once()
        saved, kwargs = storage.save_dict.call_args
        assert saved[0]["id"] == debate_id
        assert kwargs == {"org_id": "org-a"}


class TestDeadlineExceeded:
    def test_timeout_fires_at_configured_deadline_not_at_30s(self, execution_path):
        arena = _FakeArena(timeout_seconds=45, work_seconds=10_000)

        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            _controller(arena)._execute_debate_candidate(
                _config("deadline-exceeded"), "deadline-exceeded", {}
            )

        assert execution_path.ran_on_this_path(arena)
        assert arena.finished_at is None
        assert arena.cancelled_after == pytest.approx(45.0)
        assert arena.cleaned_up is True
        assert execution_path.leftover_tasks() == []

    def test_timed_out_debate_is_recorded_and_releases_resources(
        self, execution_path, registered_debate
    ):
        debate_id = registered_debate(f"deadline-cleanup-{execution_path.name}")
        arena = _FakeArena(timeout_seconds=45, work_seconds=10_000)
        storage = Mock()
        emitter = Mock()
        controller = _controller(arena, storage=storage, emitter=emitter)
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-debate-pool")
        try:
            pool.submit(controller._run_debate, _config(debate_id), debate_id).result(timeout=30)
            # The single worker is free again for the next debate.
            assert pool.submit(lambda: "free").result(timeout=5) == "free"
        finally:
            pool.shutdown(wait=True)

        assert execution_path.ran_on_this_path(arena)
        assert arena.cancelled_after == pytest.approx(45.0)
        assert arena.cleaned_up is True

        state = get_state_manager().get_debate(debate_id)
        assert state.status == "timeout"
        assert state.status not in ("starting", "initializing", "running")
        assert state.metadata["error"] == "Debate stopped at its 45s deadline"
        assert "completed_at" in state.metadata

        storage.save_dict.assert_not_called()
        end_events = _debate_end_events(emitter)
        assert len(end_events) == 1
        assert end_events[0].data["debate_id"] == debate_id
        assert end_events[0].data["error"] == "Debate stopped at its 45s deadline"

        assert execution_path.leftover_tasks() == []
        assert not [t for t in threading.enumerate() if t.name == "run_async_worker"]


def _debate_end_events(emitter: Mock) -> list[Any]:
    return [
        call.args[0]
        for call in emitter.emit.call_args_list
        if call.args[0].type == StreamEventType.DEBATE_END
    ]


class TestArenaDeadlineWinsRace:
    def test_arena_timeout_result_at_deadline_is_recorded_as_timeout(
        self, execution_path, registered_debate
    ):
        debate_id = registered_debate(f"deadline-race-{execution_path.name}")
        arena = _FakeArena(timeout_seconds=1800, work_seconds=10_000)
        storage = Mock()
        emitter = Mock()
        controller = _controller(arena, storage=storage, emitter=emitter)
        controller._generate_debate_receipt = Mock()

        controller._run_debate(_config(debate_id), debate_id)

        assert execution_path.ran_on_this_path(arena)
        assert arena.cancelled_after == pytest.approx(1800.0)
        state = get_state_manager().get_debate(debate_id)
        assert state.status == "timeout"
        assert state.metadata["deadline_seconds"] == 1800.0
        assert "result" not in state.metadata
        storage.save_dict.assert_not_called()
        controller._generate_debate_receipt.assert_not_called()
        assert [event.data["status"] for event in _debate_end_events(emitter)] == ["timeout"]
        assert execution_path.leftover_tasks() == []

    def test_backstop_cancels_arena_without_its_own_limit(self, execution_path, monkeypatch):
        monkeypatch.setattr(dc, "DEBATE_TIMEOUT_SECONDS", 45)
        arena = _FakeArena(timeout_seconds=0, work_seconds=10_000)

        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            _controller(arena)._execute_debate_candidate(
                _config("deadline-backstop"), "deadline-backstop", {}
            )

        assert execution_path.ran_on_this_path(arena)
        assert arena.cancelled_after == pytest.approx(45.0 + dc._RUN_ASYNC_CLEANUP_MARGIN_SECONDS)
        assert arena.cleaned_up is True
        assert execution_path.leftover_tasks() == []


class TestRunAsyncTimeoutArgument:
    @pytest.fixture
    def run_async_calls(self, monkeypatch):
        calls: list[float] = []

        def _spy(coro, timeout=RUN_ASYNC_DEFAULT_TIMEOUT):
            calls.append(timeout)
            coro.close()
            return SimpleNamespace(final_answer="done")

        monkeypatch.setattr(dc, "run_async", _spy)
        return calls

    def test_configured_deadline_plus_bounded_margin_is_passed(self, run_async_calls):
        margin = dc._RUN_ASYNC_CLEANUP_MARGIN_SECONDS
        assert 0 < margin <= 60

        _controller(_FakeArena(timeout_seconds=600, work_seconds=0))._execute_debate_candidate(
            _config("deadline-arg"), "deadline-arg", {}
        )

        assert run_async_calls == [600.0 + 2 * margin]

    def test_default_protocol_deadline_is_passed(self, run_async_calls):
        arena = SimpleNamespace(protocol=DebateProtocol())

        _controller(arena)._execute_debate_candidate(_config("deadline-dflt"), "deadline-dflt", {})

        expected = (
            float(DebateProtocol().timeout_seconds) + 2 * dc._RUN_ASYNC_CLEANUP_MARGIN_SECONDS
        )
        assert run_async_calls == [expected]
        assert math.isfinite(run_async_calls[0])

    def test_protocol_without_deadline_uses_debate_timeout_setting(
        self, run_async_calls, monkeypatch
    ):
        monkeypatch.setattr(dc, "DEBATE_TIMEOUT_SECONDS", 240)
        arena = SimpleNamespace(protocol=SimpleNamespace())

        _controller(arena)._execute_debate_candidate(_config("deadline-none"), "deadline-none", {})

        assert run_async_calls == [240.0 + 2 * dc._RUN_ASYNC_CLEANUP_MARGIN_SECONDS]

    def test_invalid_deadline_still_passes_a_finite_timeout(self, run_async_calls, monkeypatch):
        monkeypatch.setattr(dc, "DEBATE_TIMEOUT_SECONDS", 0)
        arena = _FakeArena(timeout_seconds=float("inf"), work_seconds=0)

        _controller(arena)._execute_debate_candidate(_config("deadline-inv"), "deadline-inv", {})

        assert run_async_calls == [
            dc._FALLBACK_DEBATE_DEADLINE_SECONDS + 2 * dc._RUN_ASYNC_CLEANUP_MARGIN_SECONDS
        ]
        assert math.isfinite(run_async_calls[0])


class TestResolveDebateDeadline:
    @pytest.mark.parametrize("value", [45, 120.5, 1800])
    def test_valid_protocol_deadline_is_used(self, value):
        assert dc._resolve_debate_deadline(value) == float(value)

    @pytest.mark.parametrize(
        "value",
        [0, -5, None, "600", float("nan"), float("inf"), float("-inf"), True, Mock()],
        ids=["zero", "negative", "none", "string", "nan", "inf", "-inf", "bool", "mock"],
    )
    def test_invalid_protocol_deadline_falls_back_to_debate_timeout(self, value, monkeypatch):
        monkeypatch.setattr(dc, "DEBATE_TIMEOUT_SECONDS", 240)

        assert dc._resolve_debate_deadline(value) == 240.0

    @pytest.mark.parametrize(
        "setting",
        [0, -1, None, float("nan"), float("inf")],
        ids=["zero", "negative", "none", "nan", "inf"],
    )
    def test_invalid_debate_timeout_setting_falls_back_to_finite_default(
        self, setting, monkeypatch
    ):
        monkeypatch.setattr(dc, "DEBATE_TIMEOUT_SECONDS", setting)

        deadline = dc._resolve_debate_deadline(0)

        assert deadline == dc._FALLBACK_DEBATE_DEADLINE_SECONDS
        assert math.isfinite(deadline) and deadline > 0


def test_run_async_global_default_timeout_is_unchanged():
    default = inspect.signature(async_utils.run_async).parameters["timeout"].default
    assert default == RUN_ASYNC_DEFAULT_TIMEOUT
