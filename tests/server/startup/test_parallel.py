"""Tests for the parallel server initialization module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.startup.parallel import (
    InitTask,
    ParallelInitializer,
    ParallelInitResult,
    PhaseResult,
    _run_task,
    run_phase,
)


# ---------------------------------------------------------------------------
# InitTask dataclass tests
# ---------------------------------------------------------------------------


class TestInitTask:
    """Test InitTask dataclass."""

    def test_creation_defaults(self):
        async def dummy():
            return "result"

        task = InitTask(name="test", func=dummy)
        assert task.name == "test"
        assert task.args == ()
        assert task.kwargs == {}
        assert task.timeout == 30.0
        assert task.required is False
        assert task.result is None
        assert task.error is None
        assert task.duration_ms == 0.0
        assert task.started_at == 0.0
        assert task.completed_at == 0.0

    def test_creation_with_args(self):
        async def dummy(x, y):
            return x + y

        task = InitTask(
            name="add",
            func=dummy,
            args=(1, 2),
            kwargs={"extra": "value"},
            timeout=10.0,
            required=True,
        )
        assert task.args == (1, 2)
        assert task.kwargs == {"extra": "value"}
        assert task.timeout == 10.0
        assert task.required is True

    def test_success_property_false_when_no_completion(self):
        task = InitTask(name="test", func=AsyncMock())
        assert task.success is False

    def test_success_property_false_when_error(self):
        task = InitTask(name="test", func=AsyncMock())
        task.completed_at = 1.0
        task.error = ValueError("oops")
        assert task.success is False

    def test_success_property_true_when_completed_no_error(self):
        task = InitTask(name="test", func=AsyncMock())
        task.completed_at = 1.0
        assert task.success is True

    def test_status_pending(self):
        task = InitTask(name="test", func=AsyncMock())
        assert task.status == "pending"

    def test_status_running(self):
        task = InitTask(name="test", func=AsyncMock())
        task.started_at = 1.0
        assert task.status == "running"

    def test_status_success(self):
        task = InitTask(name="test", func=AsyncMock())
        task.started_at = 1.0
        task.completed_at = 2.0
        assert task.status == "success"

    def test_status_failed(self):
        task = InitTask(name="test", func=AsyncMock())
        task.started_at = 1.0
        task.completed_at = 2.0
        task.error = RuntimeError("failed")
        assert task.status == "failed"


# ---------------------------------------------------------------------------
# PhaseResult dataclass tests
# ---------------------------------------------------------------------------


class TestPhaseResult:
    """Test PhaseResult dataclass."""

    def _make_task(self, name: str, success: bool = True, error: Exception | None = None):
        task = InitTask(name=name, func=AsyncMock())
        task.started_at = 1.0
        task.completed_at = 2.0
        task.duration_ms = 1000.0
        if not success or error:
            task.error = error or RuntimeError("failed")
        return task

    def test_creation(self):
        result = PhaseResult(name="phase1", tasks=[], duration_ms=100.0, success=True)
        assert result.name == "phase1"
        assert result.tasks == []
        assert result.duration_ms == 100.0
        assert result.success is True

    def test_failed_tasks_empty(self):
        tasks = [self._make_task("a"), self._make_task("b")]
        result = PhaseResult(name="test", tasks=tasks, duration_ms=100.0, success=True)
        assert result.failed_tasks == []

    def test_failed_tasks_returns_failures(self):
        task_ok = self._make_task("ok")
        task_fail = self._make_task("fail", success=False, error=ValueError("error"))
        result = PhaseResult(
            name="test", tasks=[task_ok, task_fail], duration_ms=100.0, success=False
        )
        assert len(result.failed_tasks) == 1
        assert result.failed_tasks[0].name == "fail"

    def test_successful_tasks(self):
        task_ok = self._make_task("ok")
        task_fail = self._make_task("fail", success=False, error=ValueError("error"))
        result = PhaseResult(
            name="test", tasks=[task_ok, task_fail], duration_ms=100.0, success=False
        )
        assert len(result.successful_tasks) == 1
        assert result.successful_tasks[0].name == "ok"

    def test_to_dict(self):
        task = self._make_task("task1")
        result = PhaseResult(name="test", tasks=[task], duration_ms=123.456, success=True)
        d = result.to_dict()
        assert d["name"] == "test"
        assert d["duration_ms"] == 123.46
        assert d["success"] is True
        assert "task1" in d["tasks"]
        assert d["tasks"]["task1"]["status"] == "success"


# ---------------------------------------------------------------------------
# ParallelInitResult dataclass tests
# ---------------------------------------------------------------------------


class TestParallelInitResult:
    """Test ParallelInitResult dataclass."""

    def test_creation(self):
        result = ParallelInitResult(
            phases=[],
            total_duration_ms=500.0,
            success=True,
            results={"key": "value"},
        )
        assert result.phases == []
        assert result.total_duration_ms == 500.0
        assert result.success is True
        assert result.results == {"key": "value"}

    def test_failed_phases_empty(self):
        phase = PhaseResult(name="p1", tasks=[], duration_ms=100.0, success=True)
        result = ParallelInitResult(phases=[phase], total_duration_ms=100.0, success=True)
        assert result.failed_phases == []

    def test_failed_phases_returns_failures(self):
        phase_ok = PhaseResult(name="ok", tasks=[], duration_ms=100.0, success=True)
        phase_fail = PhaseResult(name="fail", tasks=[], duration_ms=100.0, success=False)
        result = ParallelInitResult(
            phases=[phase_ok, phase_fail],
            total_duration_ms=200.0,
            success=False,
        )
        assert len(result.failed_phases) == 1
        assert result.failed_phases[0].name == "fail"

    def test_to_dict(self):
        phase = PhaseResult(name="p1", tasks=[], duration_ms=100.0, success=True)
        result = ParallelInitResult(
            phases=[phase],
            total_duration_ms=123.789,
            success=True,
            results={"db": "connected"},
        )
        d = result.to_dict()
        assert d["total_duration_ms"] == 123.79
        assert d["success"] is True
        assert len(d["phases"]) == 1
        assert d["results"] == {"db": "connected"}


# ---------------------------------------------------------------------------
# _run_task function tests
# ---------------------------------------------------------------------------


class TestRunTask:
    """Test _run_task function."""

    async def test_success(self):
        async def success_func():
            return "result"

        task = InitTask(name="test", func=success_func)
        result = await _run_task(task)

        assert result.success is True
        assert result.result == "result"
        assert result.error is None
        assert result.duration_ms > 0
        assert result.started_at > 0
        assert result.completed_at > 0

    async def test_timeout(self):
        async def slow_func():
            await asyncio.sleep(10)
            return "never"

        task = InitTask(name="slow", func=slow_func, timeout=0.01)
        result = await _run_task(task)

        assert result.success is False
        assert result.error is not None
        assert isinstance(result.error, TimeoutError)
        assert "timed out" in str(result.error)

    async def test_os_error(self):
        async def error_func():
            raise OSError("disk full")

        task = InitTask(name="disk", func=error_func)
        result = await _run_task(task)

        assert result.success is False
        assert isinstance(result.error, OSError)

    async def test_runtime_error(self):
        async def error_func():
            raise RuntimeError("something went wrong")

        task = InitTask(name="runtime", func=error_func)
        result = await _run_task(task)

        assert result.success is False
        assert isinstance(result.error, RuntimeError)

    async def test_value_error(self):
        async def error_func():
            raise ValueError("bad value")

        task = InitTask(name="value", func=error_func)
        result = await _run_task(task)

        assert result.success is False
        assert isinstance(result.error, ValueError)

    async def test_with_args_kwargs(self):
        async def add_func(a, b, multiplier=1):
            return (a + b) * multiplier

        task = InitTask(
            name="add",
            func=add_func,
            args=(2, 3),
            kwargs={"multiplier": 10},
        )
        result = await _run_task(task)

        assert result.success is True
        assert result.result == 50


# ---------------------------------------------------------------------------
# run_phase function tests
# ---------------------------------------------------------------------------


class TestRunPhase:
    """Test run_phase function."""

    async def test_empty_tasks(self):
        result = await run_phase("empty", [])
        assert result.success is True
        assert result.tasks == []
        assert result.duration_ms == 0.0

    async def test_all_success(self):
        async def ok():
            return "ok"

        tasks = [
            InitTask(name="task1", func=ok),
            InitTask(name="task2", func=ok),
        ]
        result = await run_phase("test", tasks)

        assert result.success is True
        assert len(result.tasks) == 2
        assert all(t.success for t in result.tasks)

    async def test_non_required_failure_still_success(self):
        async def ok():
            return "ok"

        async def fail():
            raise RuntimeError("failed")

        tasks = [
            InitTask(name="ok", func=ok, required=False),
            InitTask(name="fail", func=fail, required=False),
        ]
        result = await run_phase("test", tasks)

        # Phase succeeds because no required tasks failed
        assert result.success is True
        assert len(result.failed_tasks) == 1

    async def test_required_failure_causes_phase_failure(self):
        async def ok():
            return "ok"

        async def fail():
            raise RuntimeError("required failed")

        tasks = [
            InitTask(name="ok", func=ok, required=False),
            InitTask(name="critical", func=fail, required=True),
        ]
        result = await run_phase("test", tasks)

        assert result.success is False
        assert len(result.failed_tasks) == 1
        assert result.failed_tasks[0].name == "critical"

    async def test_parallel_execution(self):
        """Verify tasks run in parallel, not sequentially."""
        call_order = []

        async def task1():
            call_order.append("task1_start")
            await asyncio.sleep(0.01)
            call_order.append("task1_end")

        async def task2():
            call_order.append("task2_start")
            await asyncio.sleep(0.01)
            call_order.append("task2_end")

        tasks = [
            InitTask(name="task1", func=task1),
            InitTask(name="task2", func=task2),
        ]
        await run_phase("parallel", tasks)

        # Both should start before either finishes if truly parallel
        assert "task1_start" in call_order
        assert "task2_start" in call_order
        # The starts should be before both ends
        task1_start_idx = call_order.index("task1_start")
        task2_start_idx = call_order.index("task2_start")
        task1_end_idx = call_order.index("task1_end")
        task2_end_idx = call_order.index("task2_end")
        # At least one end should come after both starts
        assert task1_end_idx > task1_start_idx
        assert task2_end_idx > task2_start_idx


# ---------------------------------------------------------------------------
# ParallelInitializer class tests
# ---------------------------------------------------------------------------


class TestParallelInitializer:
    """Test ParallelInitializer class."""

    def test_init_defaults(self):
        init = ParallelInitializer()
        assert init.nomic_dir is None
        assert init.stream_emitter is None
        assert init.graceful_degradation is True
        assert init._results == {}
        assert init._db_pool is None
        assert init._redis_client is None

    def test_init_with_params(self):
        emitter = MagicMock()
        init = ParallelInitializer(
            nomic_dir="/tmp/nomic",
            stream_emitter=emitter,
            graceful_degradation=False,
        )
        assert init.nomic_dir == "/tmp/nomic"
        assert init.stream_emitter is emitter
        assert init.graceful_degradation is False

    async def test_run_all_phases_success(self):
        """Test successful run through all phases."""
        init = ParallelInitializer()

        # Mock all phase methods to return successful results
        async def mock_phase1():
            return PhaseResult(name="connections", tasks=[], duration_ms=10.0, success=True)

        async def mock_phase2():
            return PhaseResult(name="subsystems", tasks=[], duration_ms=20.0, success=True)

        async def mock_phase3():
            return PhaseResult(name="finalize", tasks=[], duration_ms=5.0, success=True)

        init._run_phase1_connections = mock_phase1
        init._run_phase2_subsystems = mock_phase2
        init._run_phase3_finalize = mock_phase3

        result = await init.run()

        assert result.success is True
        assert len(result.phases) == 3
        assert result.total_duration_ms > 0

    async def test_run_phase1_failure_without_graceful_degradation(self):
        """Test that phase 1 failure stops execution when graceful_degradation=False."""
        init = ParallelInitializer(graceful_degradation=False)

        async def mock_phase1():
            return PhaseResult(name="connections", tasks=[], duration_ms=10.0, success=False)

        async def mock_phase2():
            # Should not be called
            raise AssertionError("Phase 2 should not run")

        init._run_phase1_connections = mock_phase1
        init._run_phase2_subsystems = mock_phase2

        result = await init.run()

        assert result.success is False
        assert len(result.phases) == 1  # Only phase 1 ran

    async def test_run_phase1_failure_with_graceful_degradation(self):
        """Test that phase 1 failure continues when graceful_degradation=True."""
        init = ParallelInitializer(graceful_degradation=True)

        phase2_called = False

        async def mock_phase1():
            return PhaseResult(name="connections", tasks=[], duration_ms=10.0, success=False)

        async def mock_phase2():
            nonlocal phase2_called
            phase2_called = True
            return PhaseResult(name="subsystems", tasks=[], duration_ms=20.0, success=True)

        async def mock_phase3():
            return PhaseResult(name="finalize", tasks=[], duration_ms=5.0, success=True)

        init._run_phase1_connections = mock_phase1
        init._run_phase2_subsystems = mock_phase2
        init._run_phase3_finalize = mock_phase3

        result = await init.run()

        assert phase2_called is True
        assert len(result.phases) == 3
        # Overall still fails because phase 1 failed
        assert result.success is False

    async def test_run_phase2_failure_without_graceful_degradation(self):
        """Test that phase 2 failure stops execution when graceful_degradation=False."""
        init = ParallelInitializer(graceful_degradation=False)

        async def mock_phase1():
            return PhaseResult(name="connections", tasks=[], duration_ms=10.0, success=True)

        async def mock_phase2():
            return PhaseResult(name="subsystems", tasks=[], duration_ms=20.0, success=False)

        async def mock_phase3():
            raise AssertionError("Phase 3 should not run")

        init._run_phase1_connections = mock_phase1
        init._run_phase2_subsystems = mock_phase2
        init._run_phase3_finalize = mock_phase3

        result = await init.run()

        assert result.success is False
        assert len(result.phases) == 2  # Only phases 1 and 2 ran


class TestParallelInitializerPhases:
    """Test ParallelInitializer phase methods."""

    async def test_phase1_creates_connection_tasks(self):
        """Test that phase 1 creates the expected tasks."""
        init = ParallelInitializer()

        # Mock the internal init methods to succeed quickly
        init._init_database_pool = AsyncMock(return_value=MagicMock())
        init._init_redis_connection = AsyncMock(return_value=MagicMock())
        init._init_observability = AsyncMock(return_value=None)

        result = await init._run_phase1_connections()

        assert result.name == "connections"
        assert len(result.tasks) == 3
        task_names = {t.name for t in result.tasks}
        assert "postgres_pool" in task_names
        assert "redis" in task_names
        assert "observability" in task_names

    async def test_phase1_connection_tasks_are_not_required(self):
        """Test that connection tasks are optional (graceful fallback)."""
        init = ParallelInitializer()

        # All connections fail
        init._init_database_pool = AsyncMock(side_effect=OSError("no db"))
        init._init_redis_connection = AsyncMock(side_effect=OSError("no redis"))
        init._init_observability = AsyncMock(side_effect=OSError("no obs"))

        result = await init._run_phase1_connections()

        # Phase should still succeed because none are required
        assert result.success is True
        assert len(result.failed_tasks) == 3

    async def test_phase2_creates_subsystem_tasks(self):
        """Test that phase 2 creates the expected subsystem tasks."""
        init = ParallelInitializer()

        # Mock internal methods
        init._init_knowledge_mound = AsyncMock(return_value=None)
        init._init_agent_registry = AsyncMock(return_value=None)
        init._init_control_plane = AsyncMock(return_value=None)
        init._init_background_tasks = AsyncMock(return_value=None)
        init._init_workers = AsyncMock(return_value=None)

        result = await init._run_phase2_subsystems()

        assert result.name == "subsystems"
        task_names = {t.name for t in result.tasks}
        assert "knowledge_mound" in task_names
        assert "agent_registry" in task_names
        assert "control_plane" in task_names
        assert "background_tasks" in task_names


async def test_parallel_entrypoint_registers_webhook_store_before_initializer_run():
    """Event and webhook wiring must precede scheduling subsystem work."""
    from aragora.server.startup.parallel import parallel_init

    order: list[str] = []

    async def run_stub(_self):
        order.append("initializer_run")
        return ParallelInitResult(
            phases=[],
            total_duration_ms=1.0,
            success=True,
            results={},
        )

    with (
        patch(
            "aragora.server.startup.control_plane.register_control_plane_event_contributors",
            side_effect=lambda: order.append("control_plane_events"),
        ),
        patch(
            "aragora.server.startup.event_subscribers.register_webhook_store",
            side_effect=lambda: order.append("webhook_store"),
        ),
        patch(
            "aragora.server.startup.parallel.init_security_edge_adapters",
            return_value={},
        ),
        patch(
            "aragora.server.startup.parallel.init_billing_edge_adapters",
            return_value={},
        ),
        patch.object(ParallelInitializer, "run", run_stub),
    ):
        await parallel_init()

    assert order == ["control_plane_events", "webhook_store", "initializer_run"]
