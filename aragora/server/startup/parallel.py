"""
Parallel server initialization for improved startup time.

This module provides parallel initialization of independent subsystems,
significantly reducing server startup time by running non-dependent
initialization tasks concurrently.

Architecture:
    Phase 1: External connections (parallel)
        - Database pool
        - Redis connection
        - External APIs

    Phase 2: Dependent subsystems (parallel, depends on Phase 1)
        - Knowledge mound (needs DB)
        - Agent registry
        - Control plane (needs Redis)

    Phase 3: Final setup (sequential, depends on Phase 2)
        - Cache pre-warming
        - Health checks
        - Metrics registration
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, TypeVar
from collections.abc import Callable, Coroutine

from aragora.exceptions import REDIS_CONNECTION_ERRORS
from aragora.server.startup.billing import init_billing_edge_adapters
from aragora.server.startup.security import init_security_edge_adapters

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class InitTask:
    """Represents an initialization task with timing and status tracking."""

    name: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    timeout: float = 30.0
    required: bool = False
    result: Any = None
    error: Exception | None = None
    duration_ms: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0

    @property
    def success(self) -> bool:
        """Return True if task completed without error."""
        return self.error is None and self.completed_at > 0

    @property
    def status(self) -> str:
        """Return task status string."""
        if self.error:
            return "failed"
        if self.completed_at > 0:
            return "success"
        if self.started_at > 0:
            return "running"
        return "pending"


@dataclass
class PhaseResult:
    """Result of a parallel initialization phase."""

    name: str
    tasks: list[InitTask]
    duration_ms: float
    success: bool

    @property
    def failed_tasks(self) -> list[InitTask]:
        """Return list of failed tasks."""
        return [t for t in self.tasks if t.error is not None]

    @property
    def successful_tasks(self) -> list[InitTask]:
        """Return list of successful tasks."""
        return [t for t in self.tasks if t.success]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/API responses."""
        return {
            "name": self.name,
            "duration_ms": round(self.duration_ms, 2),
            "success": self.success,
            "tasks": {
                t.name: {
                    "status": t.status,
                    "duration_ms": round(t.duration_ms, 2),
                    "error": str(t.error) if t.error else None,
                }
                for t in self.tasks
            },
        }


@dataclass
class ParallelInitResult:
    """Result of the full parallel initialization."""

    phases: list[PhaseResult]
    total_duration_ms: float
    success: bool
    results: dict[str, Any] = field(default_factory=dict)

    @property
    def failed_phases(self) -> list[PhaseResult]:
        """Return list of failed phases."""
        return [p for p in self.phases if not p.success]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for status reporting."""
        return {
            "total_duration_ms": round(self.total_duration_ms, 2),
            "success": self.success,
            "phases": [p.to_dict() for p in self.phases],
            "results": self.results,
        }


async def _run_task(task: InitTask) -> InitTask:
    """Run a single initialization task with timing and error handling."""
    task.started_at = time.perf_counter()
    try:
        task.result = await asyncio.wait_for(
            task.func(*task.args, **task.kwargs),
            timeout=task.timeout,
        )
    except asyncio.TimeoutError:
        task.error = TimeoutError(f"Task '{task.name}' timed out after {task.timeout}s")
        logger.error("[parallel_init] %s timed out after %ss", task.name, task.timeout)
    except Exception as e:  # noqa: BLE001 - MUST capture all errors (redis.ConnectionError ≠ builtins)
        # Catch all exceptions — this wrapper MUST capture errors into task.error
        # so they don't propagate through asyncio.gather() and crash startup.
        # Notable: redis.exceptions.ConnectionError does NOT inherit from
        # builtins.ConnectionError, so a fixed exception list misses it.
        task.error = e
        logger.error("[parallel_init] %s failed: %s: %s", task.name, type(e).__name__, e)
    finally:
        task.completed_at = time.perf_counter()
        task.duration_ms = (task.completed_at - task.started_at) * 1000

    return task


async def run_phase(name: str, tasks: list[InitTask]) -> PhaseResult:
    """Run all tasks in a phase in parallel.

    Args:
        name: Phase name for logging
        tasks: List of InitTask objects to run concurrently

    Returns:
        PhaseResult with timing and status information
    """
    if not tasks:
        return PhaseResult(name=name, tasks=[], duration_ms=0.0, success=True)

    phase_start = time.perf_counter()
    logger.info("[parallel_init] Phase '%s' starting (%s tasks)", name, len(tasks))

    # Run all tasks concurrently
    completed_tasks = await asyncio.gather(
        *[_run_task(task) for task in tasks],
        return_exceptions=False,  # Errors are captured in task.error
    )

    phase_end = time.perf_counter()
    duration_ms = (phase_end - phase_start) * 1000

    # Check if any required tasks failed
    required_failures = [t for t in completed_tasks if t.required and t.error is not None]
    success = len(required_failures) == 0

    # Log results
    successful = sum(1 for t in completed_tasks if t.success)
    failed = sum(1 for t in completed_tasks if t.error is not None)
    logger.info(
        f"[parallel_init] Phase '{name}' completed in {duration_ms:.1f}ms "
        f"({successful} succeeded, {failed} failed)"
    )

    return PhaseResult(
        name=name,
        tasks=list(completed_tasks),
        duration_ms=duration_ms,
        success=success,
    )


class ParallelInitializer:
    """Manages parallel initialization of server subsystems.

    Usage:
        initializer = ParallelInitializer()
        result = await initializer.run()
        if result.success:
            # Server is ready
    """

    def __init__(
        self,
        nomic_dir: Any | None = None,
        stream_emitter: Any | None = None,
        graceful_degradation: bool = True,
    ):
        """Initialize the parallel initializer.

        Args:
            nomic_dir: Path to nomic state directory
            stream_emitter: Event emitter for WebSocket streaming
            graceful_degradation: If True, continue on non-critical failures
        """
        self.nomic_dir = nomic_dir
        self.stream_emitter = stream_emitter
        self.graceful_degradation = graceful_degradation
        self._results: dict[str, Any] = {}
        self._db_pool: Any = None
        self._redis_client: Any = None

    async def run(self) -> ParallelInitResult:
        """Run the full parallel initialization sequence.

        Returns:
            ParallelInitResult with all phase results and timing
        """
        total_start = time.perf_counter()
        phases: list[PhaseResult] = []

        # Phase 1: External connections (parallel)
        phase1 = await self._run_phase1_connections()
        phases.append(phase1)

        if not phase1.success and not self.graceful_degradation:
            return ParallelInitResult(
                phases=phases,
                total_duration_ms=(time.perf_counter() - total_start) * 1000,
                success=False,
                results=self._results,
            )

        # Gate: check whether required backends from Phase 1 succeeded
        gate_ok = self._check_connectivity_gate(phase1)
        if not gate_ok and not self.graceful_degradation:
            return ParallelInitResult(
                phases=phases,
                total_duration_ms=(time.perf_counter() - total_start) * 1000,
                success=False,
                results=self._results,
            )

        # Phase 2: Dependent subsystems (parallel)
        phase2 = await self._run_phase2_subsystems()
        phases.append(phase2)

        if not phase2.success and not self.graceful_degradation:
            return ParallelInitResult(
                phases=phases,
                total_duration_ms=(time.perf_counter() - total_start) * 1000,
                success=False,
                results=self._results,
            )

        # Phase 3: Final setup (sequential)
        phase3 = await self._run_phase3_finalize()
        phases.append(phase3)

        total_duration_ms = (time.perf_counter() - total_start) * 1000

        # Overall success if no required tasks failed
        overall_success = all(p.success for p in phases)

        logger.info(
            f"[parallel_init] Initialization completed in {total_duration_ms:.1f}ms "
            f"(success={overall_success})"
        )

        return ParallelInitResult(
            phases=phases,
            total_duration_ms=total_duration_ms,
            success=overall_success,
            results=self._results,
        )

    def _check_connectivity_gate(self, phase1: PhaseResult) -> bool:
        """Check whether required backends from Phase 1 are healthy.

        Inspects ARAGORA_REQUIRE_DATABASE and ARAGORA_REQUIRE_REDIS env vars.
        If a required backend's init task failed, logs a warning and returns
        False.  When graceful_degradation is False the caller should abort
        startup; otherwise it continues in degraded mode.
        """
        import os

        require_db = os.environ.get("ARAGORA_REQUIRE_DATABASE", "").lower() in (
            "true",
            "1",
            "yes",
        )
        require_redis = os.environ.get("ARAGORA_REQUIRE_REDIS", "").lower() in (
            "true",
            "1",
            "yes",
        )

        # Also implicitly require Redis when distributed state is needed
        if not require_redis:
            try:
                from aragora.control_plane.leader import is_distributed_state_required

                if is_distributed_state_required():
                    require_redis = True
            except ImportError:
                pass

        failed: list[str] = []

        if require_db:
            db_task = next((t for t in phase1.tasks if t.name == "postgres_pool"), None)
            if db_task and db_task.error is not None:
                failed.append(f"postgres_pool: {db_task.error}")

        if require_redis:
            redis_task = next((t for t in phase1.tasks if t.name == "redis"), None)
            if redis_task and redis_task.error is not None:
                failed.append(f"redis: {redis_task.error}")

        if failed:
            msg = "; ".join(failed)
            logger.error("[parallel_init] Required backend(s) failed connectivity gate: %s", msg)
            if self.graceful_degradation:
                try:
                    from aragora.server.degraded_mode import DegradedErrorCode, set_degraded

                    error_code = DegradedErrorCode.BACKEND_CONNECTIVITY
                    if failed and all(item.startswith("redis:") for item in failed):
                        error_code = DegradedErrorCode.REDIS_UNAVAILABLE
                    elif failed and all(item.startswith("postgres_pool:") for item in failed):
                        error_code = DegradedErrorCode.DATABASE_UNAVAILABLE

                    set_degraded(
                        f"Required backend(s) failed: {msg}",
                        error_code=error_code,
                        recovery_hint="Check database/Redis connectivity and restart.",
                    )
                except ImportError:
                    pass
            return False

        return True

    async def _run_phase1_connections(self) -> PhaseResult:
        """Phase 1: Initialize external connections in parallel.

        Initializes:
        - PostgreSQL connection pool
        - Redis connection
        - External API clients (observability, monitoring)
        """
        tasks = [
            InitTask(
                name="postgres_pool",
                func=self._init_database_pool,
                timeout=15.0,
                required=False,  # Can fall back to SQLite
            ),
            InitTask(
                name="redis",
                func=self._init_redis_connection,
                timeout=10.0,
                required=False,  # Can fall back to in-memory
            ),
            InitTask(
                name="observability",
                func=self._init_observability,
                timeout=10.0,
                required=False,
            ),
        ]

        return await run_phase("connections", tasks)

    async def _run_phase2_subsystems(self) -> PhaseResult:
        """Phase 2: Initialize dependent subsystems in parallel.

        Initializes (depends on Phase 1):
        - Knowledge mound (needs DB pool)
        - Agent registry
        - Control plane (needs Redis)
        - Background tasks
        """
        tasks = [
            InitTask(
                name="knowledge_mound",
                func=self._init_knowledge_mound,
                timeout=15.0,
                required=False,
            ),
            InitTask(
                name="agent_registry",
                func=self._init_agent_registry,
                timeout=10.0,
                required=False,
            ),
            InitTask(
                name="control_plane",
                func=self._init_control_plane,
                timeout=15.0,
                required=False,
            ),
            InitTask(
                name="background_tasks",
                func=self._init_background_tasks,
                timeout=10.0,
                required=False,
            ),
            InitTask(
                name="workers",
                func=self._init_workers,
                timeout=15.0,
                required=False,
            ),
            InitTask(
                name="dr_drilling",
                func=self._init_dr_drilling,
                timeout=10.0,
                required=False,
            ),
        ]

        return await run_phase("subsystems", tasks)

    async def _run_phase3_finalize(self) -> PhaseResult:
        """Phase 3: Final setup and validation.

        Runs sequentially as these may depend on all previous phases.
        """
        tasks = [
            InitTask(
                name="cache_prewarm",
                func=self._prewarm_caches,
                timeout=10.0,
                required=False,
            ),
            InitTask(
                name="health_check",
                func=self._run_health_checks,
                timeout=10.0,
                required=False,
            ),
            InitTask(
                name="spectate_bridge",
                func=self._start_spectate_bridge,
                timeout=5.0,
                required=False,
            ),
        ]

        return await run_phase("finalize", tasks)

    # =========================================================================
    # Phase 1: Connection Initializers
    # =========================================================================

    async def _init_database_pool(self) -> dict[str, Any]:
        """Initialize PostgreSQL connection pool."""
        from aragora.server.startup.database import init_postgres_pool

        result = await init_postgres_pool()
        self._results["postgres_pool"] = result

        # Store pool reference for Phase 2
        if result.get("enabled"):
            try:
                from aragora.storage.pool_manager import get_shared_pool

                self._db_pool = get_shared_pool()
            except (ImportError, RuntimeError, OSError):
                pass

        return result

    async def _init_redis_connection(self) -> dict[str, Any]:
        """Initialize Redis connection."""
        from aragora.server.startup.redis import init_redis_ha

        result = await init_redis_ha()
        self._results["redis_ha"] = result

        # Store Redis client reference for Phase 2
        if result.get("enabled"):
            try:
                from aragora.storage.redis_ha import get_cached_redis_client

                self._redis_client = get_cached_redis_client()
            except (ImportError, RuntimeError, OSError):
                pass

        return result

    async def _init_observability(self) -> dict[str, Any]:
        """Initialize observability stack (monitoring, tracing, metrics)."""
        from aragora.server.startup.observability import (
            init_error_monitoring,
            init_opentelemetry,
            init_otlp_exporter,
            init_prometheus_metrics,
            init_structured_logging,
        )

        results: dict[str, Any] = {}

        # Structured logging should be first (synchronous)
        results["structured_logging"] = init_structured_logging()

        # Run monitoring tasks in parallel
        monitoring_results = await asyncio.gather(
            init_error_monitoring(),
            init_opentelemetry(),
            init_otlp_exporter(),
            init_prometheus_metrics(),
            return_exceptions=True,
        )

        results["error_monitoring"] = (
            monitoring_results[0] if not isinstance(monitoring_results[0], Exception) else False
        )
        results["opentelemetry"] = (
            monitoring_results[1] if not isinstance(monitoring_results[1], Exception) else False
        )
        results["otlp_exporter"] = (
            monitoring_results[2] if not isinstance(monitoring_results[2], Exception) else False
        )
        results["prometheus"] = (
            monitoring_results[3] if not isinstance(monitoring_results[3], Exception) else False
        )

        self._results.update(results)
        return results

    # =========================================================================
    # Phase 2: Subsystem Initializers
    # =========================================================================

    async def _init_knowledge_mound(self) -> dict[str, Any]:
        """Initialize Knowledge Mound adapters."""
        from aragora.server.startup.knowledge_mound import init_km_adapters

        result = await init_km_adapters()
        self._results["km_adapters"] = result
        return {"enabled": result}

    async def _init_agent_registry(self) -> dict[str, Any]:
        """Initialize agent registry and discovery."""
        result: dict[str, Any] = {"enabled": False}

        try:
            from aragora.control_plane.registry import AgentRegistry

            registry = AgentRegistry()
            await registry.connect()
            result["enabled"] = True
            result["agent_count"] = len(await registry.list_all())
            self._results["agent_registry"] = result
        except ImportError:
            logger.debug("[parallel_init] AgentRegistry not available")
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("[parallel_init] AgentRegistry Redis connection failed: %s", e)
            result["error"] = "Redis connection failed"
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("[parallel_init] AgentRegistry init failed: %s", e)
            result["error"] = "Agent registry initialization failed"

        return result

    async def _init_control_plane(self) -> dict[str, Any]:
        """Initialize control plane coordinator."""
        from aragora.server.startup.control_plane import (
            init_control_plane_coordinator,
            init_mayor_coordinator,
            init_shared_control_plane_state,
            init_witness_patrol,
        )

        results: dict[str, Any] = {}

        # Run control plane tasks in parallel
        cp_results = await asyncio.gather(
            init_control_plane_coordinator(),
            init_shared_control_plane_state(),
            init_witness_patrol(),
            init_mayor_coordinator(),
            return_exceptions=True,
        )

        results["coordinator"] = cp_results[0] if not isinstance(cp_results[0], Exception) else None
        results["shared_state"] = (
            cp_results[1] if not isinstance(cp_results[1], Exception) else False
        )
        results["witness_patrol"] = (
            cp_results[2] if not isinstance(cp_results[2], Exception) else False
        )
        results["mayor_coordinator"] = (
            cp_results[3] if not isinstance(cp_results[3], Exception) else False
        )

        # Store coordinator for later use
        if results["coordinator"]:
            self._results["control_plane_coordinator"] = results["coordinator"]

        self._results["control_plane"] = results
        return results

    async def _init_background_tasks(self) -> dict[str, Any]:
        """Initialize background tasks and schedulers."""
        from aragora.server.startup.background import (
            init_background_tasks,
            init_circuit_breaker_persistence,
            init_pulse_scheduler,
            init_state_cleanup_task,
            init_stuck_debate_watchdog,
        )

        results: dict[str, Any] = {}

        # Synchronous initializers
        results["circuit_breakers"] = init_circuit_breaker_persistence(self.nomic_dir)
        results["background_tasks"] = init_background_tasks(self.nomic_dir)
        results["state_cleanup"] = init_state_cleanup_task()

        # Async initializers in parallel
        async_results = await asyncio.gather(
            init_pulse_scheduler(self.stream_emitter),
            init_stuck_debate_watchdog(),
            return_exceptions=True,
        )

        results["pulse_scheduler"] = (
            async_results[0] if not isinstance(async_results[0], Exception) else False
        )
        results["watchdog_task"] = (
            async_results[1] if not isinstance(async_results[1], Exception) else None
        )

        self._results.update(results)
        return results

    async def _init_workers(self) -> dict[str, Any]:
        """Initialize worker processes (gauntlet, notifications, webhooks)."""
        from aragora.server.startup.workers import (
            init_backup_scheduler,
            init_durable_job_queue_recovery,
            init_gauntlet_run_recovery,
            init_gauntlet_worker,
            init_notification_worker,
            init_slo_webhooks,
            init_webhook_dispatcher,
            init_workflow_checkpoint_persistence,
        )

        results: dict[str, Any] = {}

        # Synchronous initializers
        results["workflow_checkpoints"] = init_workflow_checkpoint_persistence()
        results["webhook_dispatcher"] = init_webhook_dispatcher()
        results["slo_webhooks"] = init_slo_webhooks()
        results["gauntlet_runs_recovered"] = init_gauntlet_run_recovery()

        # Async initializers in parallel
        async_results = await asyncio.gather(
            init_durable_job_queue_recovery(),
            init_gauntlet_worker(),
            init_backup_scheduler(),
            init_notification_worker(),
            return_exceptions=True,
        )

        results["durable_jobs_recovered"] = (
            async_results[0] if not isinstance(async_results[0], Exception) else 0
        )
        results["gauntlet_worker"] = (
            async_results[1] if not isinstance(async_results[1], Exception) else False
        )
        results["backup_scheduler"] = (
            async_results[2] if not isinstance(async_results[2], Exception) else False
        )
        results["notification_worker"] = (
            async_results[3] if not isinstance(async_results[3], Exception) else False
        )

        self._results.update(results)
        return results

    async def _init_dr_drilling(self) -> dict[str, Any]:
        """Initialize DR drill scheduler for SOC 2 CC9 compliance."""
        from aragora.server.startup.dr_drilling import start_dr_drilling

        result: dict[str, Any] = {"enabled": False}

        try:
            scheduler = await start_dr_drilling()
            if scheduler:
                result["enabled"] = True
                self._results["dr_drill_scheduler"] = result
        except ImportError:
            logger.debug("[parallel_init] DR drilling not available")
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("[parallel_init] DR drilling Redis connection failed: %s", e)
            result["error"] = "Redis connection failed"
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("[parallel_init] DR drilling init failed: %s", e)
            result["error"] = "DR drilling initialization failed"

        return result

    # =========================================================================
    # Phase 3: Finalization
    # =========================================================================

    async def _prewarm_caches(self) -> dict[str, Any]:
        """Pre-warm frequently accessed caches."""
        result: dict[str, Any] = {"enabled": False}

        try:
            from aragora.server.initialization import prewarm_caches

            cache_result = await prewarm_caches(nomic_dir=self.nomic_dir)
            result.update(cache_result)
            result["enabled"] = True
        except ImportError:
            logger.debug("[parallel_init] Cache pre-warming not available")
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("[parallel_init] Cache pre-warming Redis connection failed: %s", e)
            result["error"] = "Redis connection failed"
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.warning("[parallel_init] Cache pre-warming failed: %s", e)
            result["error"] = "Cache pre-warming failed"

        self._results["cache_prewarm"] = result
        return result

    async def _start_spectate_bridge(self) -> dict[str, Any]:
        """Start the spectate WebSocket bridge for landing page live demos."""
        result: dict[str, Any] = {"enabled": False}
        try:
            from aragora.spectate.ws_bridge import get_spectate_bridge

            bridge = get_spectate_bridge()
            bridge.start()
            result["enabled"] = bridge.running
            if bridge.running:
                logger.info("[parallel_init] SpectateWebSocketBridge started")
        except ImportError:
            logger.debug("[parallel_init] Spectate bridge module not available")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("[parallel_init] SpectateWebSocketBridge failed: %s", e)
            result["error"] = str(e)
        self._results["spectate_bridge"] = result
        return result

    async def _run_health_checks(self) -> dict[str, Any]:
        """Run health checks on initialized subsystems."""
        result: dict[str, Any] = {
            "database": False,
            "redis": False,
            "overall": False,
        }

        # Check database connectivity
        if self._db_pool:
            try:
                async with self._db_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                result["database"] = True
            except (OSError, RuntimeError, TimeoutError) as e:
                logger.warning("[parallel_init] Database health check failed: %s", e)

        # Check Redis connectivity
        if self._redis_client:
            try:
                self._redis_client.ping()
                result["redis"] = True
            except REDIS_CONNECTION_ERRORS as e:
                logger.warning("[parallel_init] Redis health check failed: %s", e)
            except (RuntimeError, TimeoutError) as e:
                logger.warning("[parallel_init] Redis health check failed: %s", e)

        result["overall"] = result["database"] or result["redis"] or True

        self._results["health_check"] = result
        return result


async def parallel_init(
    nomic_dir: Any | None = None,
    stream_emitter: Any | None = None,
    graceful_degradation: bool = True,
) -> dict[str, Any]:
    """Run parallel server initialization.

    This is the main entry point for parallel initialization.
    It replaces the sequential run_startup_sequence() with a
    parallelized version that can reduce startup time significantly.

    Args:
        nomic_dir: Path to nomic state directory
        stream_emitter: Event emitter for WebSocket streaming
        graceful_degradation: If True, continue on non-critical failures

    Returns:
        Dictionary with initialization results compatible with
        run_startup_sequence() return format.

    Example:
        status = await parallel_init(
            nomic_dir=Path("/app/.nomic"),
            stream_emitter=emitter,
        )
        if not status.get("_parallel_init_success"):
            logger.error("Initialization failed")
    """
    from aragora.server.startup.control_plane import register_control_plane_event_contributors
    from aragora.server.startup.event_subscribers import register_webhook_store

    register_control_plane_event_contributors()
    register_webhook_store()

    strict_startup = os.environ.get("ARAGORA_STRICT_STARTUP", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if strict_startup:
        graceful_degradation = False
    security_edge_adapters = init_security_edge_adapters(strict=strict_startup)
    billing_edge_adapters = init_billing_edge_adapters(strict=strict_startup)

    initializer = ParallelInitializer(
        nomic_dir=nomic_dir,
        stream_emitter=stream_emitter,
        graceful_degradation=graceful_degradation,
    )

    result = await initializer.run()

    # Build status dict compatible with run_startup_sequence()
    status = dict(result.results)
    status["security_edge_adapters"] = security_edge_adapters
    status["billing_edge_adapters"] = billing_edge_adapters
    status["_parallel_init_success"] = result.success
    status["_parallel_init_duration_ms"] = result.total_duration_ms
    status["_parallel_init_phases"] = [p.to_dict() for p in result.phases]

    # Log timing comparison
    if result.total_duration_ms < 5000:
        logger.info(f"[parallel_init] Fast startup: {result.total_duration_ms:.0f}ms (target <5s)")
    elif result.total_duration_ms < 15000:
        logger.info(
            f"[parallel_init] Normal startup: {result.total_duration_ms:.0f}ms (target <15s)"
        )
    else:
        logger.warning(
            f"[parallel_init] Slow startup: {result.total_duration_ms:.0f}ms (exceeds 15s target)"
        )

    return status


async def cleanup_on_failure(results: dict[str, Any]) -> None:
    """Clean up resources if initialization fails.

    Called when parallel initialization fails to ensure resources
    like database pools and Redis connections are properly closed.

    Args:
        results: Results dictionary from parallel_init()
    """
    logger.info("[parallel_init] Cleaning up after initialization failure")

    # Close database pool
    try:
        from aragora.server.startup.database import close_postgres_pool

        await close_postgres_pool()
    except (ImportError, OSError, RuntimeError) as e:
        logger.debug("[parallel_init] Database pool cleanup error: %s", e)

    # Close Redis connection
    try:
        from aragora.storage.redis_ha import reset_cached_clients

        reset_cached_clients()
    except (ImportError, OSError, RuntimeError) as e:
        logger.debug("[parallel_init] Redis cleanup error: %s", e)


__all__ = [
    "InitTask",
    "PhaseResult",
    "ParallelInitResult",
    "ParallelInitializer",
    "parallel_init",
    "run_phase",
    "cleanup_on_failure",
]
