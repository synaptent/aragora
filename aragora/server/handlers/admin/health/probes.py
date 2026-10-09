"""
Kubernetes probe implementations for health checks.

Provides lightweight liveness and readiness probes suitable for K8s deployments.
These endpoints are public (no auth required) and designed to be fast.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import time
from typing import Any
from collections.abc import Callable

from ...base import HandlerResult, json_response

logger = logging.getLogger(__name__)


class ProbesMixin:
    """Mixin providing K8s liveness and readiness probes.

    Should be mixed into a handler class that has a `ctx` attribute
    (typically a ServerContext dict) containing storage and elo_system.

    When mixed with BaseHandler or its subclasses, these methods will
    access the storage and ELO system from the server context.
    """

    # Type hint for ctx attribute (provided by BaseHandler or similar)
    ctx: dict[str, Any]

    def get_storage(self) -> Any:
        """Get debate storage instance from server context.

        Returns:
            DebateStorage instance if configured, None otherwise.
        """
        # Use ctx if available (when mixed with BaseHandler)
        if hasattr(self, "ctx") and self.ctx is not None:
            return self.ctx.get("storage")
        return None

    def get_elo_system(self) -> Any:
        """Get ELO system instance from server context.

        Checks class attribute first (set by unified_server for efficiency),
        then falls back to ctx lookup.

        Returns:
            EloSystem instance if configured, None otherwise.
        """
        # Check class attribute first (set by unified_server)
        if hasattr(self.__class__, "elo_system") and self.__class__.elo_system is not None:
            return self.__class__.elo_system
        # Fall back to ctx if available (when mixed with BaseHandler)
        if hasattr(self, "ctx") and self.ctx is not None:
            return self.ctx.get("elo_system")
        return None

    def liveness_probe(self) -> HandlerResult:
        """Kubernetes liveness probe - lightweight check that server is alive.

        Returns 200 if the server process is running and can respond.
        This should be very fast and not check external dependencies.
        Used by k8s to determine if the container should be restarted.

        IMPORTANT: Returns 200 even in degraded mode. The container is alive
        and shouldn't be restarted just because of misconfiguration. Use
        /readyz for routing decisions.

        Returns:
            {"status": "ok"} with 200 status
        """
        try:
            from aragora.server.degraded_mode import is_degraded, get_degraded_reason

            if is_degraded():
                return json_response(
                    {
                        "status": "ok",
                        "degraded": True,
                        "degraded_reason": get_degraded_reason()[:100],
                        "note": "Server alive but degraded. Check /api/health for details.",
                    }
                )
        except ImportError:
            pass

        return json_response({"status": "ok"})

    def readiness_probe(
        self,
        cache_get: Callable[[str], Any],
        cache_set: Callable[[str, Any], None],
    ) -> HandlerResult:
        """Kubernetes readiness probe - check if ready to serve traffic.

        Returns 200 if critical services are initialized and ready.
        Returns 503 if the service is not ready to accept traffic.
        Used by k8s to determine if traffic should be routed to this pod.

        Args:
            cache_get: Function to get cached health result
            cache_set: Function to set cached health result

        Checks:
        - Degraded mode (server misconfiguration)
        - Storage initialized (if configured)
        - ELO system available (if configured)
        - Redis connectivity (if distributed state required)
        - PostgreSQL connectivity (if required)
        """
        # Return cached result if available (1 second cache)
        cached = cache_get("readiness")
        if cached is not None:
            status_code = 200 if cached.get("status") == "ready" else 503
            return json_response(cached, status=status_code)

        start_time = time.time()
        ready = True
        checks: dict[str, Any] = {}

        # Check for degraded mode first - return 503 immediately
        try:
            from aragora.server.degraded_mode import is_degraded, get_degraded_state

            if is_degraded():
                state = get_degraded_state()
                return json_response(
                    {
                        "status": "not_ready",
                        "reason": "Server in degraded mode",
                        "degraded": {
                            "error_code": state.error_code.value,
                            "reason": state.reason,
                            "recovery_hint": state.recovery_hint,
                        },
                        "checks": {"degraded_mode": False},
                    },
                    status=503,
                )
        except ImportError:
            pass

        # Check storage readiness
        try:
            storage = self.get_storage()
            checks["storage"] = storage is not None
            if not storage:
                # Storage not configured is OK for readiness
                checks["storage"] = True
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("Storage readiness check failed: %s: %s", type(e).__name__, e)
            checks["storage"] = False
            ready = False

        # Check ELO system readiness
        try:
            elo = self.get_elo_system()
            checks["elo_system"] = elo is not None
            if not elo:
                # ELO not configured is OK for readiness
                checks["elo_system"] = True
        except (OSError, RuntimeError, ValueError) as e:
            logger.warning("ELO system readiness check failed: %s: %s", type(e).__name__, e)
            checks["elo_system"] = False
            ready = False

        # Check Redis connectivity (if distributed state required)
        ready, checks = self._check_redis_readiness(ready, checks)

        # Check PostgreSQL connectivity (if required)
        ready, checks = self._check_postgresql_readiness(ready, checks)

        status_code = 200 if ready else 503
        latency_ms = (time.time() - start_time) * 1000
        result = {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
            "latency_ms": round(latency_ms, 2),
        }

        # Cache result for subsequent requests
        cache_set("readiness", result)

        return json_response(result, status=status_code)

    def _check_redis_readiness(
        self, ready: bool, checks: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Check Redis connectivity for readiness probe."""
        try:
            from aragora.config.distributed import is_distributed_state_required
            from aragora.server.startup import validate_redis_connectivity

            distributed_required = is_distributed_state_required()
            redis_url = os.environ.get("REDIS_URL") or os.environ.get("ARAGORA_REDIS_URL")

            if distributed_required and redis_url:
                # Run async validation in sync context
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop:
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run, validate_redis_connectivity(timeout_seconds=2.0)
                        )
                        redis_ok, redis_msg = future.result(timeout=3.0)
                else:
                    redis_ok, redis_msg = asyncio.run(
                        validate_redis_connectivity(timeout_seconds=2.0)
                    )

                checks["redis"] = {"connected": redis_ok, "message": redis_msg}
                if not redis_ok:
                    ready = False
            elif redis_url:
                checks["redis"] = {"configured": True, "required": False}
            else:
                checks["redis"] = {"configured": False}

        except ImportError:
            checks["redis"] = {"status": "check_skipped"}
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("Redis connectivity failed: %s: %s", type(e).__name__, e)
            checks["redis"] = {"error": "Redis connectivity failed", "error_type": "connectivity"}
            try:
                from aragora.config.distributed import is_distributed_state_required

                if is_distributed_state_required():
                    ready = False
            except (ImportError, RuntimeError):
                pass
        except (asyncio.TimeoutError, concurrent.futures.TimeoutError) as e:
            logger.warning("Redis check timed out: %s: %s", type(e).__name__, e)
            checks["redis"] = {"error": "timeout", "error_type": "timeout"}
            try:
                from aragora.config.distributed import is_distributed_state_required

                if is_distributed_state_required():
                    ready = False
            except (ImportError, RuntimeError):
                pass
        except (
            RuntimeError,
            ValueError,
            TypeError,
            AttributeError,
        ) as e:  # broad catch: last-resort handler
            logger.warning("Redis readiness check failed: %s: %s", type(e).__name__, e)
            checks["redis"] = {"error": "Redis check failed"}
            try:
                from aragora.config.distributed import is_distributed_state_required

                if is_distributed_state_required():
                    ready = False
            except (ImportError, RuntimeError, AttributeError) as err:
                logger.debug("Error checking distributed state requirement: %s", err)

        return ready, checks

    def _check_postgresql_readiness(
        self, ready: bool, checks: dict[str, Any]
    ) -> tuple[bool, dict[str, Any]]:
        """Check PostgreSQL connectivity for readiness probe."""
        require_database = False
        try:
            from aragora.server.startup import validate_database_connectivity

            database_url = os.environ.get("DATABASE_URL") or os.environ.get("ARAGORA_POSTGRES_DSN")
            require_database = os.environ.get("ARAGORA_REQUIRE_DATABASE", "").lower() in (
                "true",
                "1",
                "yes",
            )

            if require_database and database_url:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop:
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            asyncio.run, validate_database_connectivity(timeout_seconds=2.0)
                        )
                        db_ok, db_msg = future.result(timeout=3.0)
                else:
                    db_ok, db_msg = asyncio.run(validate_database_connectivity(timeout_seconds=2.0))

                checks["postgresql"] = {"connected": db_ok, "message": db_msg}
                if not db_ok:
                    ready = False
            elif database_url:
                checks["postgresql"] = {"configured": True, "required": False}
            else:
                checks["postgresql"] = {"configured": False}

        except ImportError:
            checks["postgresql"] = {"status": "check_skipped"}
        except (ConnectionError, TimeoutError, OSError) as e:
            logger.warning("PostgreSQL connectivity failed: %s: %s", type(e).__name__, e)
            checks["postgresql"] = {
                "error": "PostgreSQL connectivity failed",
                "error_type": "connectivity",
            }
            if require_database:
                ready = False
        except (asyncio.TimeoutError, concurrent.futures.TimeoutError) as e:
            logger.warning("PostgreSQL check timed out: %s: %s", type(e).__name__, e)
            checks["postgresql"] = {"error": "timeout", "error_type": "timeout"}
            if require_database:
                ready = False
        except (
            RuntimeError,
            ValueError,
            TypeError,
            AttributeError,
        ) as e:  # broad catch: last-resort handler
            logger.warning("PostgreSQL readiness check failed: %s: %s", type(e).__name__, e)
            checks["postgresql"] = {"error": "PostgreSQL check failed"}

        return ready, checks
