"""
Graceful shutdown orchestration for the unified server.

Provides a structured, phase-based approach to server shutdown with:
- Individual phase isolation (errors in one phase don't affect others)
- Consistent logging and error handling
- Configurable timeouts per phase
- Easy extension for new shutdown requirements
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass
class ShutdownPhase:
    """A single phase in the shutdown sequence.

    Attributes:
        name: Human-readable name for logging
        execute: Async function to execute (or sync wrapped in coroutine)
        timeout: Maximum seconds for this phase
        critical: If True, log as warning on failure; else debug
    """

    name: str
    execute: Callable[[], Coroutine[Any, Any, None]]
    timeout: float = 5.0
    critical: bool = False


class ShutdownSequence:
    """Orchestrates multi-phase graceful shutdown.

    Executes shutdown phases in order, isolating failures and
    providing consistent logging throughout.

    Usage:
        sequence = ShutdownSequence()
        sequence.add_phase(ShutdownPhase(
            name="Stop background tasks",
            execute=stop_background_tasks,
            timeout=5.0,
        ))
        await sequence.execute_all()
    """

    def __init__(self):
        """Initialize an empty shutdown sequence."""
        self._phases: list[ShutdownPhase] = []
        self._completed: list[str] = []
        self._failed: list[str] = []

    def add_phase(self, phase: ShutdownPhase) -> ShutdownSequence:
        """Add a phase to the shutdown sequence.

        Args:
            phase: The shutdown phase to add

        Returns:
            Self for method chaining
        """
        self._phases.append(phase)
        return self

    async def execute_all(self, overall_timeout: float = 30.0) -> dict:
        """Execute all shutdown phases in order.

        Args:
            overall_timeout: Maximum total time for all phases

        Returns:
            Dict with 'completed', 'failed', and 'elapsed' keys
        """
        start_time = time.time()
        logger.info("Starting graceful shutdown (%s phases)...", len(self._phases))

        for phase in self._phases:
            elapsed = time.time() - start_time
            if elapsed >= overall_timeout:
                logger.warning("Overall shutdown timeout reached, skipping remaining phases")
                break

            remaining = overall_timeout - elapsed
            phase_timeout = min(phase.timeout, remaining)

            await self._execute_phase(phase, phase_timeout)

        elapsed = time.time() - start_time
        logger.info(
            f"Graceful shutdown completed in {elapsed:.1f}s "
            f"({len(self._completed)} succeeded, {len(self._failed)} failed)"
        )

        return {
            "completed": self._completed.copy(),
            "failed": self._failed.copy(),
            "elapsed": elapsed,
        }

    async def _execute_phase(self, phase: ShutdownPhase, timeout: float) -> bool:
        """Execute a single shutdown phase with error isolation.

        Args:
            phase: The phase to execute
            timeout: Maximum seconds for this phase

        Returns:
            True if phase completed successfully
        """
        try:
            await asyncio.wait_for(phase.execute(), timeout=timeout)
            self._completed.append(phase.name)
            logger.debug("Shutdown phase completed: %s", phase.name)
            return True

        except asyncio.TimeoutError:
            self._failed.append(phase.name)
            if phase.critical:
                logger.warning("Shutdown phase timed out: %s", phase.name)
            else:
                logger.debug("Shutdown phase timed out: %s", phase.name)
            return False

        except asyncio.CancelledError:
            self._failed.append(phase.name)
            logger.debug("Shutdown phase cancelled: %s", phase.name)
            return False

        except Exception as e:  # noqa: BLE001 - Shutdown must continue despite individual phase failures
            # Broad catch intentional: shutdown must continue despite individual phase failures
            self._failed.append(phase.name)
            if phase.critical:
                logger.warning("Shutdown phase failed: %s: %s", phase.name, e)
            else:
                logger.debug("Shutdown phase failed: %s: %s", phase.name, e)
            return False


class ShutdownPhaseBuilder:
    """Helper class to build shutdown phases for UnifiedServer.

    Encapsulates the logic for each shutdown phase into separate methods,
    keeping the phase creation organized and maintainable.
    """

    def __init__(self, server: Any):
        """Initialize the phase builder.

        Args:
            server: The UnifiedServer instance
        """
        self._server = server

    def _phase_set_shutdown_flag(self, sequence: ShutdownSequence) -> None:
        """Add phase to mark server as shutting down.

        Args:
            sequence: The shutdown sequence to add phase to
        """
        server = self._server

        async def set_shutting_down():
            server._shutting_down = True

        sequence.add_phase(
            ShutdownPhase(
                name="Set shutdown flag",
                execute=set_shutting_down,
                timeout=1.0,
            )
        )

    def _phase_drain_connections(self, sequence: ShutdownSequence) -> None:
        """Add phases to drain in-flight requests and debates.

        Timeout budget: drain_requests (15s) + wait_for_debates (12s) = 27s critical
        Leaves ~3s for remaining phases within 30s overall timeout.

        Args:
            sequence: The shutdown sequence to add phases to
        """

        async def drain_requests():
            from aragora.server.request_tracker import get_request_tracker

            tracker = get_request_tracker()
            active = tracker.active_count
            if active > 0:
                logger.info("Draining %s in-flight HTTP request(s)", active)
            success = await tracker.start_drain(timeout=14.0)
            if not success:
                logger.warning("Some HTTP requests still active after drain timeout")

        sequence.add_phase(
            ShutdownPhase(
                name="Drain in-flight requests",
                execute=drain_requests,
                timeout=15.0,
                critical=True,
            )
        )

        async def wait_for_debates():
            from aragora.server.debate_utils import get_active_debates

            active_debates = get_active_debates()
            if not active_debates:
                return

            in_progress = [
                d_id for d_id, d in active_debates.items() if d.get("status") == "in_progress"
            ]
            if not in_progress:
                return

            logger.info("Waiting for %s in-flight debate(s)", len(in_progress))
            wait_start = time.time()
            while time.time() - wait_start < 11.0:  # Leave buffer for other phases
                still_running = sum(
                    1
                    for d_id in in_progress
                    if d_id in active_debates
                    and active_debates.get(d_id, {}).get("status") == "in_progress"
                )
                if still_running == 0:
                    logger.info("All in-flight debates completed")
                    return
                await asyncio.sleep(1)

            logger.warning("Some debates still running after timeout")

        sequence.add_phase(
            ShutdownPhase(
                name="Wait for in-flight debates",
                execute=wait_for_debates,
                timeout=12.0,
                critical=True,
            )
        )

    def _phase_persist_state(self, sequence: ShutdownSequence) -> None:
        """Add phase to persist circuit breaker states.

        Args:
            sequence: The shutdown sequence to add phase to
        """

        async def persist_circuit_breakers():
            from aragora.resilience import persist_all_circuit_breakers

            count = persist_all_circuit_breakers()
            if count > 0:
                logger.info("Persisted %s circuit breaker state(s)", count)

        sequence.add_phase(
            ShutdownPhase(
                name="Persist circuit breakers",
                execute=persist_circuit_breakers,
                timeout=5.0,
            )
        )

    def _phase_flush_queues(self, sequence: ShutdownSequence) -> None:
        """Add phase to flush KM adapters and event batches.

        Args:
            sequence: The shutdown sequence to add phase to
        """

        async def flush_km_adapters():
            try:
                from aragora.events.cross_subscribers import get_cross_subscriber_manager

                manager = get_cross_subscriber_manager()

                # Flush event batches first
                flushed = manager.flush_all_batches()
                if flushed > 0:
                    logger.info("Flushed %s batched events", flushed)

                # Sync RankingAdapter state
                try:
                    ranking_adapter = getattr(manager, "_ranking_adapter", None)
                    if ranking_adapter is not None:
                        stats = ranking_adapter.get_stats()
                        if stats.get("total_expertise_records", 0) > 0:
                            logger.debug(
                                "RankingAdapter has %s expertise records",
                                stats["total_expertise_records"],
                            )
                except ImportError:
                    pass

                # Sync RlmAdapter state
                try:
                    from aragora.knowledge.mound.adapters.rlm_adapter import RlmAdapter  # noqa: F401

                    rlm_adapter = getattr(manager, "_rlm_adapter", None)
                    if rlm_adapter is not None:
                        stats = rlm_adapter.get_stats()
                        if stats.get("total_patterns", 0) > 0:
                            logger.debug(
                                "RlmAdapter has %s compression patterns", stats["total_patterns"]
                            )
                except ImportError:
                    pass

                logger.info("KM adapters and event batches flushed")

            except ImportError:
                pass  # Cross-subscriber module not available
            except (RuntimeError, OSError, AttributeError) as e:
                # Shutdown handler - log and continue
                logger.warning("KM adapter flush failed: %s", e)

        sequence.add_phase(
            ShutdownPhase(
                name="Flush KM adapters",
                execute=flush_km_adapters,
                timeout=5.0,
            )
        )

    def _phase_stop_services(self, sequence: ShutdownSequence) -> None:
        """Add phases to stop background services.

        Includes: OpenTelemetry, background tasks, pulse scheduler,
        state cleanup, and stuck debate watchdog.

        Args:
            sequence: The shutdown sequence to add phases to
        """
        server = self._server

        # OpenTelemetry tracer
        async def shutdown_tracing():
            from aragora.observability.tracing import shutdown as shutdown_otel

            shutdown_otel()
            logger.info("OpenTelemetry tracer shutdown complete")

        sequence.add_phase(
            ShutdownPhase(
                name="Shutdown OpenTelemetry",
                execute=shutdown_tracing,
                timeout=5.0,
            )
        )

        # Background tasks
        async def stop_background_tasks():
            from aragora.server.background import get_background_manager

            background_mgr = get_background_manager()
            background_mgr.stop()
            logger.info("Background tasks stopped")

        sequence.add_phase(
            ShutdownPhase(
                name="Stop background tasks",
                execute=stop_background_tasks,
                timeout=5.0,
            )
        )

        # Pulse scheduler
        async def stop_pulse_scheduler():
            from aragora.server.handlers.pulse import get_pulse_scheduler

            scheduler = get_pulse_scheduler()
            if scheduler and scheduler.state.value != "stopped":
                await scheduler.stop(graceful=True)
                logger.info("Pulse scheduler stopped")

        sequence.add_phase(
            ShutdownPhase(
                name="Stop pulse scheduler",
                execute=stop_pulse_scheduler,
                timeout=5.0,
            )
        )

        # State cleanup task
        async def stop_state_cleanup():
            from aragora.server.stream.state_manager import stop_cleanup_task

            stop_cleanup_task()
            logger.debug("State cleanup task stopped")

        sequence.add_phase(
            ShutdownPhase(
                name="Stop state cleanup",
                execute=stop_state_cleanup,
                timeout=2.0,
            )
        )

        # Stuck debate watchdog
        async def stop_watchdog():
            if hasattr(server, "_watchdog_task") and server._watchdog_task:
                server._watchdog_task.cancel()
                try:
                    await asyncio.wait_for(server._watchdog_task, timeout=2.0)
                except asyncio.TimeoutError:
                    pass
                logger.debug("Stuck debate watchdog stopped")

        sequence.add_phase(
            ShutdownPhase(
                name="Stop watchdog",
                execute=stop_watchdog,
                timeout=3.0,
            )
        )

        # Spectate WebSocket bridge
        async def stop_spectate_bridge():
            try:
                from aragora.spectate.ws_bridge import get_spectate_bridge

                bridge = get_spectate_bridge()
                if bridge.running:
                    bridge.stop()
                    logger.info("SpectateWebSocketBridge stopped")
            except ImportError:
                pass

        sequence.add_phase(
            ShutdownPhase(
                name="Stop spectate bridge",
                execute=stop_spectate_bridge,
                timeout=2.0,
            )
        )

    def _phase_shutdown_control_plane(self, sequence: ShutdownSequence) -> None:
        """Add phase to shutdown Control Plane coordinator.

        Args:
            sequence: The shutdown sequence to add phase to
        """
        server = self._server

        async def shutdown_control_plane():
            if hasattr(server, "_control_plane_coordinator") and server._control_plane_coordinator:
                await server._control_plane_coordinator.shutdown()
                logger.info("Control Plane coordinator shutdown complete")

        sequence.add_phase(
            ShutdownPhase(
                name="Shutdown Control Plane",
                execute=shutdown_control_plane,
                timeout=5.0,
            )
        )

    def _phase_close_websockets(self, sequence: ShutdownSequence) -> None:
        """Add phases to close WebSocket connections.

        Includes: debate stream, control plane, and nomic loop WebSockets.

        Args:
            sequence: The shutdown sequence to add phases to
        """
        server = self._server

        # Debate stream WebSockets
        async def close_debate_websockets():
            if hasattr(server, "stream_server") and server.stream_server:
                await server.stream_server.graceful_shutdown()
                logger.info("Debate stream WebSocket connections closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close debate WebSockets",
                execute=close_debate_websockets,
                timeout=5.0,
                critical=True,
            )
        )

        # Control plane WebSockets
        async def close_control_plane_websockets():
            if hasattr(server, "control_plane_stream") and server.control_plane_stream:
                await server.control_plane_stream.stop()
                logger.info("Control plane WebSocket connections closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close control plane WebSockets",
                execute=close_control_plane_websockets,
                timeout=5.0,
            )
        )

        # Nomic loop WebSockets
        async def close_nomic_websockets():
            if hasattr(server, "nomic_loop_stream") and server.nomic_loop_stream:
                await server.nomic_loop_stream.stop()
                logger.info("Nomic loop WebSocket connections closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close nomic loop WebSockets",
                execute=close_nomic_websockets,
                timeout=5.0,
            )
        )

    def _phase_close_http_connections(self, sequence: ShutdownSequence) -> None:
        """Add phases to close HTTP connections.

        Includes: shared HTTP connector and HTTP client pool.

        Args:
            sequence: The shutdown sequence to add phases to
        """

        # Shared HTTP connector
        async def close_http_connector():
            from aragora.agents.api_agents.common import close_shared_connector

            await close_shared_connector()
            logger.info("Shared HTTP connector closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close HTTP connector",
                execute=close_http_connector,
                timeout=5.0,
            )
        )

        # HTTP client pool
        async def close_http_client_pool():
            try:
                from aragora.observability.http_client_pool import HTTPClientPool

                pool = HTTPClientPool.get_instance()
                if pool and not pool._closed:
                    await pool.aclose()
                    logger.info("HTTP client pool closed")
            except ImportError:
                pass  # HTTP client pool module not available
            except RuntimeError as e:
                # Pool already closed or not initialized
                logger.debug("HTTP client pool close skipped: %s", e)

        sequence.add_phase(
            ShutdownPhase(
                name="Close HTTP client pool",
                execute=close_http_client_pool,
                timeout=5.0,
                critical=False,
            )
        )

    def _phase_stop_caches(self, sequence: ShutdownSequence) -> None:
        """Add phase to stop distributed caches.

        Includes: RBAC distributed cache.

        Args:
            sequence: The shutdown sequence to add phase to
        """

        async def stop_rbac_cache():
            try:
                from aragora.rbac.cache import get_rbac_cache, reset_rbac_cache

                cache = get_rbac_cache()
                if cache:
                    cache.stop()
                    reset_rbac_cache(clear_distributed=False)  # Clear singleton for clean restart
                    logger.debug("RBAC distributed cache stopped")
            except ImportError:
                pass  # RBAC module not available
            except (RuntimeError, OSError, ConnectionError) as e:
                # Shutdown handler - log and continue
                logger.debug("RBAC cache stop skipped: %s", e)

        sequence.add_phase(
            ShutdownPhase(
                name="Stop RBAC cache",
                execute=stop_rbac_cache,
                timeout=2.0,
            )
        )

    def _phase_stop_workers(self, sequence: ShutdownSequence) -> None:
        """Add phase to stop background workers.

        Includes: gauntlet worker (must happen before pool closure).

        Args:
            sequence: The shutdown sequence to add phase to
        """

        async def stop_gauntlet_worker():
            try:
                from aragora.server.startup.workers import get_gauntlet_worker

                worker = get_gauntlet_worker()
                if worker:
                    await worker.stop()
                    # Allow one poll cycle for the worker loop to exit
                    await asyncio.sleep(0.5)
                    logger.info("Gauntlet worker stopped")
            except ImportError:
                pass
            except (RuntimeError, OSError, asyncio.CancelledError) as e:
                # Shutdown handler - log and continue
                logger.debug("Gauntlet worker stop skipped: %s", e)

        sequence.add_phase(
            ShutdownPhase(
                name="Stop gauntlet worker",
                execute=stop_gauntlet_worker,
                timeout=5.0,
            )
        )

    def _phase_close_connection_pools(self, sequence: ShutdownSequence) -> None:
        """Add phases to close connection pools.

        Includes: Redis and PostgreSQL connection pools.

        Args:
            sequence: The shutdown sequence to add phases to
        """

        # Redis connection pool
        async def close_redis():
            from aragora.utils.redis_config import close_redis_pool

            close_redis_pool()
            logger.debug("Redis connection pool closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close Redis pool",
                execute=close_redis,
                timeout=2.0,
            )
        )

        # Auth cleanup thread
        async def stop_auth_cleanup():
            from aragora.server.auth import auth_config

            auth_config.stop_cleanup_thread()
            logger.debug("Auth cleanup thread stopped")

        sequence.add_phase(
            ShutdownPhase(
                name="Stop auth cleanup",
                execute=stop_auth_cleanup,
                timeout=2.0,
            )
        )

        # PostgreSQL connection pools
        async def close_postgres_pools():
            try:
                from aragora.storage.pool_manager import close_shared_pool

                await close_shared_pool()
            except ImportError:
                pass  # pool_manager not available
            except (RuntimeError, OSError, ConnectionError) as e:
                # Shutdown handler - log and continue
                logger.warning("Error closing shared pool: %s", e)

            try:
                from aragora.storage.connection_factory import close_all_pools

                await close_all_pools()
            except ImportError:
                pass
            except (RuntimeError, OSError, ConnectionError) as e:
                # Shutdown handler - log and continue
                logger.warning("Error closing connection factory pools: %s", e)

            logger.info("PostgreSQL connection pools closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close PostgreSQL pools",
                execute=close_postgres_pools,
                timeout=5.0,
                critical=False,
            )
        )

    def _phase_close_databases(self, sequence: ShutdownSequence) -> None:
        """Add phase to close database connections.

        Args:
            sequence: The shutdown sequence to add phase to
        """

        async def close_databases():
            from aragora.storage.schema import DatabaseManager

            DatabaseManager.clear_instances()
            logger.info("Database connections closed")

        sequence.add_phase(
            ShutdownPhase(
                name="Close databases",
                execute=close_databases,
                timeout=5.0,
                critical=True,
            )
        )

    def _phase_shutdown_servers(self, sequence: ShutdownSequence) -> None:
        """Add phases to shutdown HTTP servers.

        Includes: ThreadingHTTPServer and uvicorn server.

        Args:
            sequence: The shutdown sequence to add phases to
        """
        server = self._server

        # HTTP server (ThreadingHTTPServer)
        async def shutdown_http_server():
            if hasattr(server, "_http_server") and server._http_server:
                try:
                    server._http_server.shutdown()
                    logger.info("HTTP server shutdown complete")
                except (OSError, RuntimeError) as e:
                    logger.debug("HTTP server shutdown error (expected if not running): %s", e)

        sequence.add_phase(
            ShutdownPhase(
                name="Shutdown HTTP server",
                execute=shutdown_http_server,
                timeout=5.0,
                critical=True,
            )
        )

        # FastAPI/uvicorn server
        async def shutdown_uvicorn():
            if hasattr(server, "_uvicorn_server") and server._uvicorn_server:
                try:
                    server._uvicorn_server.should_exit = True
                    logger.info("Uvicorn server signaled for shutdown")
                except (OSError, RuntimeError, AttributeError) as e:
                    logger.debug("Uvicorn shutdown error: %s", e)

        sequence.add_phase(
            ShutdownPhase(
                name="Shutdown uvicorn server",
                execute=shutdown_uvicorn,
                timeout=5.0,
                critical=False,
            )
        )

    def _phase_cleanup(self, sequence: ShutdownSequence) -> None:
        """Add final cleanup phases.

        Includes: metrics server and logging flush.

        Args:
            sequence: The shutdown sequence to add phases to
        """

        # Prometheus metrics server
        async def stop_metrics():
            try:
                from aragora.observability.metrics import stop_metrics_server

                stop_metrics_server()
                logger.debug("Metrics server stopped")
            except ImportError:
                pass

        sequence.add_phase(
            ShutdownPhase(
                name="Stop metrics server",
                execute=stop_metrics,
                timeout=2.0,
                critical=False,
            )
        )

        # Logging flush
        async def flush_logging():
            import logging as stdlib_logging

            stdlib_logging.shutdown()
            logger.info("Logging shutdown complete")

        sequence.add_phase(
            ShutdownPhase(
                name="Flush logging",
                execute=flush_logging,
                timeout=2.0,
                critical=True,
            )
        )

    def build(self) -> ShutdownSequence:
        """Build the complete shutdown sequence.

        Assembles all phases in the correct order:
        1. Set shutdown flag
        2. Drain connections (requests, debates)
        3. Persist state (circuit breakers)
        4. Flush queues (KM adapters)
        5. Stop services (tracing, background tasks, scheduler, etc.)
        6. Shutdown control plane
        7. Close WebSockets
        8. Close HTTP connections
        9. Stop caches
        10. Stop workers
        11. Close connection pools (Redis, auth, PostgreSQL)
        12. Close databases
        13. Shutdown servers (HTTP, uvicorn)
        14. Cleanup (metrics, logging)

        Returns:
            Configured ShutdownSequence ready to execute
        """
        sequence = ShutdownSequence()

        # Phase 1: Mark server as shutting down
        self._phase_set_shutdown_flag(sequence)

        # Phase 2: Drain in-flight requests and debates
        self._phase_drain_connections(sequence)

        # Phase 3: Persist circuit breaker states
        self._phase_persist_state(sequence)

        # Phase 4: Flush KM adapters and event batches
        self._phase_flush_queues(sequence)

        # Phase 5: Stop background services
        self._phase_stop_services(sequence)

        # Phase 6: Shutdown Control Plane coordinator
        self._phase_shutdown_control_plane(sequence)

        # Phase 7: Close WebSocket connections
        self._phase_close_websockets(sequence)

        # Phase 8: Close HTTP connections
        self._phase_close_http_connections(sequence)

        # Phase 9: Stop distributed caches
        self._phase_stop_caches(sequence)

        # Phase 10: Stop background workers
        self._phase_stop_workers(sequence)

        # Phase 11: Close connection pools
        self._phase_close_connection_pools(sequence)

        # Phase 12: Close database connections
        self._phase_close_databases(sequence)

        # Phase 13: Shutdown HTTP servers
        self._phase_shutdown_servers(sequence)

        # Phase 14: Shutdown registered daemon threads
        self._phase_shutdown_thread_registry(sequence)

        # Phase 15: Final cleanup
        self._phase_cleanup(sequence)

        return sequence

    def _phase_shutdown_thread_registry(self, sequence: ShutdownSequence) -> None:
        """Add phase to shut down all ThreadRegistry-managed threads."""

        async def shutdown_thread_registry():
            try:
                from aragora.server.lifecycle import get_thread_registry

                registry = get_thread_registry()
                results = registry.shutdown_all(timeout=8.0)
                stopped = sum(1 for v in results.values() if v)
                logger.info("ThreadRegistry shutdown: %s/%s threads stopped", stopped, len(results))
            except ImportError:
                pass

        sequence.add_phase(
            ShutdownPhase(
                name="Shutdown thread registry",
                execute=shutdown_thread_registry,
                timeout=10.0,
            )
        )


def create_server_shutdown_sequence(server: Any) -> ShutdownSequence:
    """Create the standard shutdown sequence for UnifiedServer.

    This factory function uses ShutdownPhaseBuilder to construct
    a complete shutdown sequence with all necessary phases.

    Args:
        server: The UnifiedServer instance

    Returns:
        Configured ShutdownSequence ready to execute
    """
    builder = ShutdownPhaseBuilder(server)
    return builder.build()
