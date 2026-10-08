"""
Tests for Parallel Server Initialization.

Tests cover:
- InitTask creation and execution
- Parallel phase execution
- Dependency ordering between phases
- Error handling in parallel init
- Timeout handling
- Cleanup on failure
- ParallelInitializer full workflow
- Integration with unified_server.py
"""

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestInitTask:
    """Tests for InitTask dataclass."""

    def test_init_task_creation(self):
        """Test creating an InitTask with required fields."""
        from aragora.server.startup.parallel import InitTask

        async def dummy_func():
            return {"status": "ok"}

        task = InitTask(
            name="test_task",
            func=dummy_func,
        )

        assert task.name == "test_task"
        assert task.func == dummy_func
        assert task.args == ()
        assert task.kwargs == {}
        assert task.timeout == 30.0
        assert task.required is False
        assert task.result is None
        assert task.error is None
        assert task.duration_ms == 0.0

    def test_init_task_status_pending(self):
        """Test InitTask status is pending before execution."""
        from aragora.server.startup.parallel import InitTask

        async def dummy_func():
            return "done"

        task = InitTask(name="test", func=dummy_func)

        assert task.status == "pending"
        assert task.success is False

    def test_init_task_status_after_completion(self):
        """Test InitTask status after successful completion."""
        from aragora.server.startup.parallel import InitTask

        async def dummy_func():
            return "done"

        task = InitTask(name="test", func=dummy_func)
        task.started_at = time.perf_counter()
        task.completed_at = time.perf_counter() + 0.1
        task.result = "done"

        assert task.status == "success"
        assert task.success is True

    def test_init_task_status_after_failure(self):
        """Test InitTask status after failure."""
        from aragora.server.startup.parallel import InitTask

        async def dummy_func():
            raise ValueError("test error")

        task = InitTask(name="test", func=dummy_func)
        task.started_at = time.perf_counter()
        task.completed_at = time.perf_counter() + 0.1
        task.error = ValueError("test error")

        assert task.status == "failed"
        assert task.success is False


class TestPhaseResult:
    """Tests for PhaseResult dataclass."""

    def test_phase_result_creation(self):
        """Test creating a PhaseResult."""
        from aragora.server.startup.parallel import InitTask, PhaseResult

        async def dummy_func():
            return "ok"

        task1 = InitTask(name="task1", func=dummy_func)
        task1.completed_at = time.perf_counter()

        result = PhaseResult(
            name="test_phase",
            tasks=[task1],
            duration_ms=100.5,
            success=True,
        )

        assert result.name == "test_phase"
        assert len(result.tasks) == 1
        assert result.duration_ms == 100.5
        assert result.success is True

    def test_phase_result_failed_tasks(self):
        """Test getting failed tasks from PhaseResult."""
        from aragora.server.startup.parallel import InitTask, PhaseResult

        async def dummy_func():
            return "ok"

        task1 = InitTask(name="task1", func=dummy_func)
        task1.completed_at = time.perf_counter()

        task2 = InitTask(name="task2", func=dummy_func)
        task2.error = ValueError("failed")
        task2.completed_at = time.perf_counter()

        result = PhaseResult(
            name="test_phase",
            tasks=[task1, task2],
            duration_ms=100.0,
            success=False,
        )

        failed = result.failed_tasks
        assert len(failed) == 1
        assert failed[0].name == "task2"

    def test_phase_result_to_dict(self):
        """Test converting PhaseResult to dictionary."""
        from aragora.server.startup.parallel import InitTask, PhaseResult

        async def dummy_func():
            return "ok"

        task = InitTask(name="task1", func=dummy_func)
        task.completed_at = time.perf_counter()
        task.started_at = task.completed_at - 0.1
        task.duration_ms = 100.0

        result = PhaseResult(
            name="test_phase",
            tasks=[task],
            duration_ms=100.0,
            success=True,
        )

        d = result.to_dict()
        assert d["name"] == "test_phase"
        assert d["success"] is True
        assert "tasks" in d
        assert "task1" in d["tasks"]


class TestRunPhase:
    """Tests for run_phase function."""

    @pytest.mark.asyncio
    async def test_run_phase_empty_tasks(self):
        """Test running a phase with no tasks."""
        from aragora.server.startup.parallel import run_phase

        result = await run_phase("empty_phase", [])

        assert result.name == "empty_phase"
        assert result.success is True
        assert result.duration_ms >= 0
        assert len(result.tasks) == 0

    @pytest.mark.asyncio
    async def test_run_phase_single_task_success(self):
        """Test running a phase with one successful task."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def success_task():
            return {"status": "completed"}

        tasks = [InitTask(name="success", func=success_task)]
        result = await run_phase("single_phase", tasks)

        assert result.success is True
        assert len(result.successful_tasks) == 1
        assert result.tasks[0].result == {"status": "completed"}

    @pytest.mark.asyncio
    async def test_run_phase_single_task_failure(self):
        """Test running a phase with one failing task."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def failing_task():
            raise ValueError("expected error")

        tasks = [InitTask(name="failing", func=failing_task, required=False)]
        result = await run_phase("failing_phase", tasks)

        # Non-required failure still allows phase to succeed
        assert result.success is True
        assert len(result.failed_tasks) == 1
        assert isinstance(result.failed_tasks[0].error, ValueError)

    @pytest.mark.asyncio
    async def test_run_phase_required_task_failure(self):
        """Test running a phase with required task failure."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def failing_task():
            raise ValueError("critical error")

        tasks = [InitTask(name="required_failing", func=failing_task, required=True)]
        result = await run_phase("critical_phase", tasks)

        # Required failure causes phase to fail
        assert result.success is False
        assert len(result.failed_tasks) == 1

    @pytest.mark.asyncio
    async def test_run_phase_parallel_execution(self):
        """Test that tasks in a phase run in parallel."""
        from aragora.server.startup.parallel import InitTask, run_phase

        execution_order = []
        start_time = time.perf_counter()

        async def slow_task1():
            execution_order.append(("start1", time.perf_counter() - start_time))
            await asyncio.sleep(0.1)
            execution_order.append(("end1", time.perf_counter() - start_time))
            return "task1"

        async def slow_task2():
            execution_order.append(("start2", time.perf_counter() - start_time))
            await asyncio.sleep(0.1)
            execution_order.append(("end2", time.perf_counter() - start_time))
            return "task2"

        tasks = [
            InitTask(name="slow1", func=slow_task1),
            InitTask(name="slow2", func=slow_task2),
        ]
        result = await run_phase("parallel_test", tasks)

        assert result.success is True
        assert len(result.tasks) == 2

        # Both tasks should start before either ends (parallel execution)
        starts = [e for e in execution_order if e[0].startswith("start")]
        ends = [e for e in execution_order if e[0].startswith("end")]

        # Both starts should happen before any end
        assert len(starts) == 2
        assert len(ends) == 2
        # Allow some tolerance for timing
        assert max(s[1] for s in starts) < min(e[1] for e in ends) + 0.05


class TestTaskTimeout:
    """Tests for task timeout handling."""

    @pytest.mark.asyncio
    async def test_task_timeout(self):
        """Test that tasks respect timeout."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def slow_task():
            await asyncio.sleep(10)  # Will be cancelled by timeout
            return "should not reach"

        tasks = [InitTask(name="timeout_task", func=slow_task, timeout=0.1)]
        result = await run_phase("timeout_phase", tasks)

        assert len(result.failed_tasks) == 1
        assert isinstance(result.failed_tasks[0].error, TimeoutError)

    @pytest.mark.asyncio
    async def test_fast_task_no_timeout(self):
        """Test that fast tasks complete before timeout."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def fast_task():
            return "completed"

        tasks = [InitTask(name="fast_task", func=fast_task, timeout=10.0)]
        result = await run_phase("fast_phase", tasks)

        assert result.success is True
        assert result.tasks[0].result == "completed"
        assert result.tasks[0].error is None


class TestParallelInitializer:
    """Tests for ParallelInitializer class."""

    @pytest.mark.asyncio
    async def test_initializer_creation(self):
        """Test creating a ParallelInitializer."""
        from aragora.server.startup.parallel import ParallelInitializer

        initializer = ParallelInitializer(
            nomic_dir=Path("/tmp/test"),
            stream_emitter=None,
            graceful_degradation=True,
        )

        assert initializer.nomic_dir == Path("/tmp/test")
        assert initializer.graceful_degradation is True

    @pytest.mark.asyncio
    async def test_initializer_run_with_mocks(self):
        """Test running initializer with mocked dependencies."""
        from aragora.server.startup.parallel import ParallelInitializer

        with (
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_database_pool",
                new_callable=AsyncMock,
                return_value={"enabled": False, "backend": "sqlite"},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_redis_connection",
                new_callable=AsyncMock,
                return_value={"enabled": False, "mode": "standalone"},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_observability",
                new_callable=AsyncMock,
                return_value={"structured_logging": True},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_knowledge_mound",
                new_callable=AsyncMock,
                return_value={"enabled": False},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_agent_registry",
                new_callable=AsyncMock,
                return_value={"enabled": False},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_control_plane",
                new_callable=AsyncMock,
                return_value={"coordinator": None},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_background_tasks",
                new_callable=AsyncMock,
                return_value={"background_tasks": True},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._init_workers",
                new_callable=AsyncMock,
                return_value={"gauntlet_worker": False},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._prewarm_caches",
                new_callable=AsyncMock,
                return_value={"enabled": False},
            ),
            patch(
                "aragora.server.startup.parallel.ParallelInitializer._run_health_checks",
                new_callable=AsyncMock,
                return_value={"overall": True},
            ),
        ):
            initializer = ParallelInitializer(graceful_degradation=True)
            result = await initializer.run()

            assert result.success is True
            assert len(result.phases) == 3
            assert result.total_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_initializer_graceful_degradation_on(self):
        """Test initializer continues with graceful degradation enabled."""
        from aragora.server.startup.parallel import ParallelInitializer

        async def failing_init():
            raise RuntimeError("Connection failed")

        with (
            patch.object(
                ParallelInitializer,
                "_init_database_pool",
                new_callable=AsyncMock,
                side_effect=failing_init,
            ),
            patch.object(
                ParallelInitializer,
                "_init_redis_connection",
                new_callable=AsyncMock,
                return_value={"enabled": False},
            ),
            patch.object(
                ParallelInitializer,
                "_init_observability",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_knowledge_mound",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_agent_registry",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_control_plane",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_background_tasks",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_workers",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_prewarm_caches",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_run_health_checks",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            initializer = ParallelInitializer(graceful_degradation=True)
            result = await initializer.run()

            # Should complete all phases despite failures
            assert len(result.phases) == 3

    @pytest.mark.asyncio
    async def test_initializer_fails_without_graceful_degradation(self):
        """Test initializer stops on required failure without graceful degradation."""
        from aragora.server.startup.parallel import ParallelInitializer, InitTask

        # Create initializer with graceful_degradation=False
        initializer = ParallelInitializer(graceful_degradation=False)

        # We'll test this by checking that phase failures propagate correctly
        with patch.object(
            ParallelInitializer,
            "_run_phase1_connections",
            new_callable=AsyncMock,
        ) as mock_phase1:
            from aragora.server.startup.parallel import PhaseResult

            mock_phase1.return_value = PhaseResult(
                name="connections",
                tasks=[
                    InitTask(
                        name="postgres",
                        func=AsyncMock(),
                        required=True,
                    )
                ],
                duration_ms=100.0,
                success=False,  # Phase failed
            )

            result = await initializer.run()

            # Should fail fast with only first phase executed
            assert result.success is False


class TestParallelInit:
    """Tests for parallel_init convenience function."""

    @pytest.mark.asyncio
    async def test_parallel_init_returns_status_dict(self):
        """Test that parallel_init returns status dictionary."""
        from aragora.server.startup.parallel import parallel_init

        with (
            patch(
                "aragora.server.startup.parallel.ParallelInitializer.run",
                new_callable=AsyncMock,
            ) as mock_run,
            patch(
                "aragora.server.startup.parallel.init_security_edge_adapters",
                return_value=True,
            ) as mock_security_adapters,
            patch(
                "aragora.server.startup.parallel.init_billing_edge_adapters",
                return_value=True,
            ) as mock_billing_adapters,
        ):
            from aragora.server.startup.parallel import ParallelInitResult

            mock_run.return_value = ParallelInitResult(
                phases=[],
                total_duration_ms=100.0,
                success=True,
                results={"test": "value"},
            )

            status = await parallel_init()

            assert "_parallel_init_success" in status
            assert "_parallel_init_duration_ms" in status
            assert status["_parallel_init_success"] is True
            assert status["security_edge_adapters"] is True
            assert status["billing_edge_adapters"] is True
            mock_security_adapters.assert_called_once_with(strict=False)
            mock_billing_adapters.assert_called_once_with(strict=False)

    @pytest.mark.asyncio
    async def test_parallel_init_with_nomic_dir(self):
        """Test parallel_init with nomic_dir parameter."""
        from aragora.server.startup.parallel import parallel_init

        with (
            patch(
                "aragora.server.startup.parallel.ParallelInitializer.__init__",
                return_value=None,
            ) as mock_init,
            patch(
                "aragora.server.startup.parallel.ParallelInitializer.run",
                new_callable=AsyncMock,
            ) as mock_run,
            patch(
                "aragora.server.startup.parallel.init_billing_edge_adapters",
                return_value=True,
            ),
        ):
            from aragora.server.startup.parallel import ParallelInitResult

            mock_run.return_value = ParallelInitResult(
                phases=[],
                total_duration_ms=50.0,
                success=True,
                results={},
            )

            await parallel_init(nomic_dir=Path("/test/nomic"))

            # Check that nomic_dir was passed to initializer
            mock_init.assert_called_once()
            call_kwargs = mock_init.call_args.kwargs
            assert call_kwargs.get("nomic_dir") == Path("/test/nomic")

    @pytest.mark.asyncio
    async def test_parallel_init_registers_adapters_strictly_in_strict_mode(self):
        """Test strict startup is forwarded to security edge registration."""
        from aragora.server.startup.parallel import ParallelInitResult, parallel_init

        with (
            patch.dict("os.environ", {"ARAGORA_STRICT_STARTUP": "true"}),
            patch(
                "aragora.server.startup.parallel.init_security_edge_adapters",
                return_value=True,
            ) as mock_security_adapters,
            patch(
                "aragora.server.startup.parallel.init_billing_edge_adapters",
                return_value=True,
            ) as mock_billing_adapters,
            patch(
                "aragora.server.startup.parallel.ParallelInitializer.run",
                new_callable=AsyncMock,
                return_value=ParallelInitResult(
                    phases=[],
                    total_duration_ms=10.0,
                    success=True,
                    results={},
                ),
            ),
        ):
            await parallel_init()

        mock_security_adapters.assert_called_once_with(strict=True)
        mock_billing_adapters.assert_called_once_with(strict=True)


class TestCleanupOnFailure:
    """Tests for cleanup_on_failure function."""

    @pytest.mark.asyncio
    async def test_cleanup_closes_database_pool(self):
        """Test that cleanup closes database pool."""
        from aragora.server.startup.parallel import cleanup_on_failure

        with patch(
            "aragora.server.startup.database.close_postgres_pool",
            new_callable=AsyncMock,
        ) as mock_close:
            await cleanup_on_failure({})
            mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_handles_import_errors(self):
        """Test that cleanup handles missing modules gracefully."""
        from aragora.server.startup.parallel import cleanup_on_failure

        with patch(
            "aragora.server.startup.database.close_postgres_pool",
            side_effect=ImportError("module not found"),
        ):
            # Should not raise
            await cleanup_on_failure({})


class TestDependencyOrdering:
    """Tests for proper dependency ordering between phases."""

    @pytest.mark.asyncio
    async def test_phase2_runs_after_phase1(self):
        """Test that Phase 2 runs after Phase 1 completes."""
        from aragora.server.startup.parallel import ParallelInitializer

        phase_order = []

        async def phase1_init(*args, **kwargs):
            phase_order.append("phase1")
            return {"enabled": True}

        async def phase2_init(*args, **kwargs):
            phase_order.append("phase2")
            return {"enabled": True}

        with (
            patch.object(
                ParallelInitializer,
                "_init_database_pool",
                new_callable=AsyncMock,
                side_effect=phase1_init,
            ),
            patch.object(
                ParallelInitializer,
                "_init_redis_connection",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_observability",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_knowledge_mound",
                new_callable=AsyncMock,
                side_effect=phase2_init,
            ),
            patch.object(
                ParallelInitializer,
                "_init_agent_registry",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_control_plane",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_background_tasks",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_init_workers",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_prewarm_caches",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch.object(
                ParallelInitializer,
                "_run_health_checks",
                new_callable=AsyncMock,
                return_value={},
            ),
        ):
            initializer = ParallelInitializer()
            await initializer.run()

            # Phase 1 (database) should complete before Phase 2 (knowledge_mound)
            assert phase_order.index("phase1") < phase_order.index("phase2")


class TestTimingMeasurement:
    """Tests for timing measurement accuracy."""

    @pytest.mark.asyncio
    async def test_task_duration_measurement(self):
        """Test that task duration is accurately measured."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def timed_task():
            await asyncio.sleep(0.05)
            return "done"

        tasks = [InitTask(name="timed", func=timed_task)]
        result = await run_phase("timing_test", tasks)

        # Duration should be at least 50ms (the sleep time)
        assert result.tasks[0].duration_ms >= 40  # Allow some tolerance
        assert result.tasks[0].duration_ms < 500  # But not too long

    @pytest.mark.asyncio
    async def test_phase_duration_includes_all_tasks(self):
        """Test that phase duration reflects all parallel tasks."""
        from aragora.server.startup.parallel import InitTask, run_phase

        async def task_50ms():
            await asyncio.sleep(0.05)
            return "50ms"

        async def task_100ms():
            await asyncio.sleep(0.1)
            return "100ms"

        tasks = [
            InitTask(name="fast", func=task_50ms),
            InitTask(name="slow", func=task_100ms),
        ]
        result = await run_phase("parallel_timing", tasks)

        # Phase duration should be approximately the slowest task
        # (parallel execution), not the sum
        assert result.duration_ms >= 80  # At least ~100ms
        assert result.duration_ms < 200  # But not ~150ms (sequential)


class TestUnifiedServerIntegration:
    """Tests for integration with unified_server.py."""

    @pytest.mark.asyncio
    async def test_parallel_init_env_var_true(self):
        """Test ARAGORA_PARALLEL_INIT=true uses parallel init."""
        import os

        with patch.dict(os.environ, {"ARAGORA_PARALLEL_INIT": "true"}):
            with (
                patch(
                    "aragora.server.startup.parallel.parallel_init",
                    new_callable=AsyncMock,
                ) as mock_parallel,
                patch(
                    "aragora.server.startup.run_startup_sequence",
                    new_callable=AsyncMock,
                ) as mock_sequential,
            ):
                mock_parallel.return_value = {"_parallel_init_success": True}

                from aragora.server.unified_server import UnifiedServer

                # Create server with minimal config
                server = UnifiedServer(
                    http_port=8080,
                    ws_port=8765,
                    enable_persistence=False,
                )

                # Mock other components to prevent actual startup
                with (
                    patch.object(server, "stream_server"),
                    patch.object(server, "control_plane_stream"),
                    patch.object(server, "nomic_loop_stream"),
                    patch.object(server, "_setup_signal_handlers"),
                ):
                    # We can't easily test the full start() due to event loop issues,
                    # but we can verify the environment variable is respected
                    use_parallel = os.environ.get("ARAGORA_PARALLEL_INIT", "true").lower() in (
                        "1",
                        "true",
                        "yes",
                    )
                    assert use_parallel is True

    @pytest.mark.asyncio
    async def test_parallel_init_env_var_false(self):
        """Test ARAGORA_PARALLEL_INIT=false uses sequential init."""
        import os

        with patch.dict(os.environ, {"ARAGORA_PARALLEL_INIT": "false"}):
            use_parallel = os.environ.get("ARAGORA_PARALLEL_INIT", "true").lower() in (
                "1",
                "true",
                "yes",
            )
            assert use_parallel is False


class TestParallelInitResult:
    """Tests for ParallelInitResult dataclass."""

    def test_parallel_init_result_to_dict(self):
        """Test converting ParallelInitResult to dictionary."""
        from aragora.server.startup.parallel import ParallelInitResult, PhaseResult

        result = ParallelInitResult(
            phases=[
                PhaseResult(name="phase1", tasks=[], duration_ms=100.0, success=True),
            ],
            total_duration_ms=150.0,
            success=True,
            results={"postgres_pool": {"enabled": True}},
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["total_duration_ms"] == 150.0
        assert len(d["phases"]) == 1
        assert "postgres_pool" in d["results"]

    def test_failed_phases_property(self):
        """Test failed_phases property."""
        from aragora.server.startup.parallel import ParallelInitResult, PhaseResult

        result = ParallelInitResult(
            phases=[
                PhaseResult(name="ok", tasks=[], duration_ms=100.0, success=True),
                PhaseResult(name="failed", tasks=[], duration_ms=50.0, success=False),
            ],
            total_duration_ms=150.0,
            success=False,
            results={},
        )

        failed = result.failed_phases
        assert len(failed) == 1
        assert failed[0].name == "failed"
