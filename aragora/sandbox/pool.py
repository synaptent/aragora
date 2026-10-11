"""
Container Pool Management.

Pre-warmed container pool for fast sandbox execution with:
- Container pre-warming for low latency startup (<100ms)
- Dynamic scaling based on demand
- Health monitoring and automatic recovery
- Resource limit enforcement

Usage:
    from aragora.sandbox.pool import ContainerPool, ContainerPoolConfig

    config = ContainerPoolConfig(min_pool_size=5, max_pool_size=50)
    pool = ContainerPool(config)

    await pool.start()

    # Acquire a container for a session
    container = await pool.acquire("session-123")

    # Release when done
    await pool.release("session-123")
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ContainerState(str, Enum):
    """State of a pooled container."""

    CREATING = "creating"
    READY = "ready"
    ACQUIRED = "acquired"
    UNHEALTHY = "unhealthy"
    DESTROYING = "destroying"


class PoolState(str, Enum):
    """State of the container pool."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    DRAINING = "draining"


@dataclass
class ContainerPoolConfig:
    """Configuration for the container pool."""

    # Pool sizing
    min_pool_size: int = 5
    """Minimum number of containers to keep warm."""

    max_pool_size: int = 50
    """Maximum containers in the pool."""

    warmup_count: int = 10
    """Initial containers to warm up on start."""

    # Timeouts
    idle_timeout_seconds: float = 300.0
    """How long an idle container can live before cleanup."""

    acquire_timeout_seconds: float = 30.0
    """Timeout for acquiring a container."""

    creation_timeout_seconds: float = 60.0
    """Timeout for creating a new container."""

    # Health checks
    health_check_interval_seconds: float = 30.0
    """Interval between health checks."""

    max_container_age_seconds: float = 3600.0
    """Maximum age before container is recycled."""

    # Docker settings
    base_image: str = "python:3.11-slim"
    """Base Docker image for containers."""

    network_mode: str = "none"
    """Docker network mode (none for isolation)."""

    # Resource limits per container
    memory_limit_mb: int = 512
    """Memory limit per container in MB."""

    cpu_limit: float = 1.0
    """CPU limit per container (1.0 = 1 core)."""

    pids_limit: int = 100
    """Process limit per container."""

    # Labels
    container_prefix: str = "aragora-sandbox"
    """Prefix for container names."""

    labels: dict[str, str] = field(default_factory=lambda: {"managed-by": "aragora"})
    """Labels to apply to containers."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "min_pool_size": self.min_pool_size,
            "max_pool_size": self.max_pool_size,
            "warmup_count": self.warmup_count,
            "idle_timeout_seconds": self.idle_timeout_seconds,
            "acquire_timeout_seconds": self.acquire_timeout_seconds,
            "creation_timeout_seconds": self.creation_timeout_seconds,
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "max_container_age_seconds": self.max_container_age_seconds,
            "base_image": self.base_image,
            "network_mode": self.network_mode,
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_limit": self.cpu_limit,
            "pids_limit": self.pids_limit,
            "container_prefix": self.container_prefix,
        }


@dataclass
class PooledContainer:
    """A container managed by the pool."""

    container_id: str
    """Docker container ID."""

    container_name: str
    """Docker container name."""

    state: ContainerState = ContainerState.CREATING
    """Current state of the container."""

    session_id: str | None = None
    """Session currently using this container."""

    created_at: float = field(default_factory=time.time)
    """When the container was created."""

    last_used_at: float = field(default_factory=time.time)
    """When the container was last used."""

    last_health_check: float = field(default_factory=time.time)
    """When health was last checked."""

    health_check_failures: int = 0
    """Consecutive health check failures."""

    execution_count: int = 0
    """Number of executions in this container."""

    def is_expired(self, max_age_seconds: float, idle_timeout_seconds: float) -> bool:
        """Check if container should be recycled."""
        now = time.time()
        age = now - self.created_at
        idle_time = now - self.last_used_at

        return age > max_age_seconds or idle_time > idle_timeout_seconds

    def is_available(self) -> bool:
        """Check if container can be acquired."""
        return self.state == ContainerState.READY and self.session_id is None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "container_id": self.container_id,
            "container_name": self.container_name,
            "state": self.state.value,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "execution_count": self.execution_count,
            "health_check_failures": self.health_check_failures,
        }


@dataclass
class PoolStats:
    """Statistics for the container pool."""

    total_containers: int = 0
    ready_containers: int = 0
    acquired_containers: int = 0
    unhealthy_containers: int = 0
    creating_containers: int = 0

    total_acquisitions: int = 0
    total_releases: int = 0
    total_creations: int = 0
    total_destructions: int = 0

    avg_acquire_time_ms: float = 0.0
    avg_creation_time_ms: float = 0.0

    pool_utilization: float = 0.0
    """Ratio of acquired to total containers."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_containers": self.total_containers,
            "ready_containers": self.ready_containers,
            "acquired_containers": self.acquired_containers,
            "unhealthy_containers": self.unhealthy_containers,
            "creating_containers": self.creating_containers,
            "total_acquisitions": self.total_acquisitions,
            "total_releases": self.total_releases,
            "total_creations": self.total_creations,
            "total_destructions": self.total_destructions,
            "avg_acquire_time_ms": self.avg_acquire_time_ms,
            "avg_creation_time_ms": self.avg_creation_time_ms,
            "pool_utilization": self.pool_utilization,
        }


class ContainerPoolError(Exception):
    """Base exception for container pool errors."""

    pass


class PoolExhaustedError(ContainerPoolError):
    """Raised when no containers are available."""

    pass


class ContainerCreationError(ContainerPoolError):
    """Raised when container creation fails."""

    pass


class ContainerPool:
    """
    Pre-warmed container pool for fast sandbox execution.

    Features:
    - Container pre-warming for low latency startup (<100ms)
    - Dynamic scaling based on demand
    - Health monitoring and automatic recovery
    - Session binding for per-session isolation
    """

    def __init__(self, config: ContainerPoolConfig | None = None):
        """Initialize the container pool."""
        self.config = config or ContainerPoolConfig()
        self._state = PoolState.STOPPED
        self._containers: dict[str, PooledContainer] = {}
        self._session_containers: dict[str, str] = {}  # session_id -> container_id
        self._lock = asyncio.Lock()
        self._stats = PoolStats()
        self._background_tasks: list[asyncio.Task] = []
        self._creation_semaphore = asyncio.Semaphore(5)  # Limit concurrent creations

        # Timing tracking
        self._acquire_times: list[float] = []
        self._creation_times: list[float] = []

    @property
    def state(self) -> PoolState:
        """Get current pool state."""
        return self._state

    @property
    def stats(self) -> PoolStats:
        """Get pool statistics."""
        return self._get_stats()

    # ==========================================================================
    # Lifecycle
    # ==========================================================================

    async def start(self) -> None:
        """
        Start the container pool.

        Warms up initial containers and starts background tasks.
        """
        if self._state != PoolState.STOPPED:
            logger.warning("Pool already in state %s", self._state.value)
            return

        logger.info("Starting container pool with config: %s", self.config.to_dict())
        self._state = PoolState.STARTING

        try:
            # Warm up initial containers
            warmup_count = min(self.config.warmup_count, self.config.max_pool_size)
            await self._warmup(warmup_count)

            # Start background tasks
            self._background_tasks = [
                asyncio.create_task(self._health_check_loop()),
                asyncio.create_task(self._cleanup_loop()),
                asyncio.create_task(self._scaling_loop()),
            ]

            self._state = PoolState.RUNNING
            logger.info("Container pool started with %s containers", len(self._containers))

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.error("Failed to start container pool: %s", e)
            self._state = PoolState.STOPPED
            raise

    async def stop(self, graceful: bool = True) -> None:
        """
        Stop the container pool.

        Args:
            graceful: If True, wait for acquired containers to be released
        """
        if self._state == PoolState.STOPPED:
            return

        logger.info("Stopping container pool (graceful=%s)", graceful)
        self._state = PoolState.DRAINING if graceful else PoolState.STOPPING

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        if graceful:
            # Wait for acquired containers
            timeout = 30.0
            start = time.time()
            while time.time() - start < timeout:
                acquired = [
                    c for c in self._containers.values() if c.state == ContainerState.ACQUIRED
                ]
                if not acquired:
                    break
                await asyncio.sleep(0.5)

        # Destroy all containers
        async with self._lock:
            container_ids = list(self._containers.keys())

        for container_id in container_ids:
            await self._destroy_container(container_id)

        self._containers.clear()
        self._session_containers.clear()
        self._state = PoolState.STOPPED
        logger.info("Container pool stopped")

    async def _warmup(self, count: int) -> None:
        """Warm up initial containers."""
        logger.info("Warming up %s containers", count)
        start = time.time()

        tasks = []
        for _ in range(count):
            tasks.append(self._create_container())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful = sum(1 for r in results if not isinstance(r, Exception))
        failed = count - successful

        duration = time.time() - start
        logger.info("Warmup complete: %s created, %s failed in %.2fs", successful, failed, duration)

    # ==========================================================================
    # Container Acquisition
    # ==========================================================================

    async def acquire(
        self,
        session_id: str,
        timeout: float | None = None,
    ) -> PooledContainer:
        """
        Acquire a container for a session.

        Args:
            session_id: Session ID to bind container to
            timeout: Acquisition timeout (uses config default if None)

        Returns:
            PooledContainer bound to the session

        Raises:
            PoolExhaustedError: If no container available within timeout
        """
        if self._state != PoolState.RUNNING:
            raise ContainerPoolError(f"Pool not running (state={self._state.value})")

        timeout = timeout or self.config.acquire_timeout_seconds
        start = time.time()

        # Check if session already has a container
        async with self._lock:
            if session_id in self._session_containers:
                container_id = self._session_containers[session_id]
                container = self._containers.get(container_id)
                if container and container.state == ContainerState.ACQUIRED:
                    return container

        # Try to acquire an available container
        deadline = start + timeout
        while time.time() < deadline:
            container = await self._try_acquire(session_id)
            if container:
                duration_ms = (time.time() - start) * 1000
                self._record_acquire_time(duration_ms)
                logger.debug(
                    "Acquired container %s for %s in %.1fms",
                    container.container_id,
                    session_id,
                    duration_ms,
                )
                return container

            # Check if we can create a new container
            async with self._lock:
                if len(self._containers) < self.config.max_pool_size:
                    try:
                        container = await self._create_and_acquire(session_id)
                        duration_ms = (time.time() - start) * 1000
                        self._record_acquire_time(duration_ms)
                        return container
                    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                        logger.warning("Failed to create container: %s", e)

            # Wait briefly before retrying
            await asyncio.sleep(0.1)

        raise PoolExhaustedError(
            f"No container available for session {session_id} after {timeout:.1f}s timeout"
        )

    async def _try_acquire(self, session_id: str) -> PooledContainer | None:
        """Try to acquire an available container."""
        async with self._lock:
            # Find first available container
            for container in self._containers.values():
                if container.is_available():
                    container.state = ContainerState.ACQUIRED
                    container.session_id = session_id
                    container.last_used_at = time.time()
                    self._session_containers[session_id] = container.container_id
                    self._stats.total_acquisitions += 1
                    return container
        return None

    async def _create_and_acquire(self, session_id: str) -> PooledContainer:
        """Create a new container and acquire it."""
        container = await self._create_container()

        async with self._lock:
            container.state = ContainerState.ACQUIRED
            container.session_id = session_id
            container.last_used_at = time.time()
            self._session_containers[session_id] = container.container_id
            self._stats.total_acquisitions += 1

        return container

    async def release(self, session_id: str) -> None:
        """
        Release a container back to the pool.

        Args:
            session_id: Session ID to release container for
        """
        async with self._lock:
            container_id = self._session_containers.pop(session_id, None)
            if not container_id:
                logger.warning("No container found for session %s", session_id)
                return

            container = self._containers.get(container_id)
            if not container:
                logger.warning("Container %s not in pool", container_id)
                return

            container.state = ContainerState.READY
            container.session_id = None
            container.last_used_at = time.time()
            container.execution_count += 1
            self._stats.total_releases += 1

        logger.debug("Released container %s from session %s", container_id, session_id)

    async def destroy(self, session_id: str) -> None:
        """
        Destroy a session's container (don't return to pool).

        Args:
            session_id: Session ID whose container should be destroyed
        """
        async with self._lock:
            container_id = self._session_containers.pop(session_id, None)

        if container_id:
            await self._destroy_container(container_id)

    # ==========================================================================
    # Container Lifecycle
    # ==========================================================================

    async def _create_container(self) -> PooledContainer:
        """Create a new container."""
        async with self._creation_semaphore:
            start = time.time()
            container_name = f"{self.config.container_prefix}-{uuid.uuid4().hex[:8]}"

            try:
                # Build docker create command
                cmd = self._build_create_command(container_name)

                # Create container
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.config.creation_timeout_seconds,
                )

                if proc.returncode != 0:
                    error_msg = stderr.decode("utf-8", errors="replace")
                    raise ContainerCreationError(f"Docker create failed: {error_msg}")

                container_id = stdout.decode().strip()

                # Start container
                start_proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "start",
                    container_id,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await start_proc.wait()

                container = PooledContainer(
                    container_id=container_id,
                    container_name=container_name,
                    state=ContainerState.READY,
                )

                async with self._lock:
                    self._containers[container_id] = container
                    self._stats.total_creations += 1

                duration_ms = (time.time() - start) * 1000
                self._record_creation_time(duration_ms)

                logger.debug("Created container %s in %.1fms", container_id, duration_ms)
                return container

            except asyncio.TimeoutError:
                # Try to cleanup partial container
                await self._cleanup_partial_container(container_name)
                raise ContainerCreationError("Container creation timed out")

            except FileNotFoundError:
                raise ContainerCreationError(
                    "Docker not found. Ensure Docker is installed and running."
                )

    def _build_create_command(self, container_name: str) -> list[str]:
        """Build docker create command."""
        cmd = [
            "docker",
            "create",
            "--name",
            container_name,
            # Resource limits
            f"--memory={self.config.memory_limit_mb}m",
            f"--cpus={self.config.cpu_limit}",
            "--pids-limit",
            str(self.config.pids_limit),
            # Security
            "--security-opt=no-new-privileges",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=100m",  # noqa: S108 - container-internal tmpfs mount
            "--tmpfs",
            "/workspace:rw,exec,size=50m",
            # Network
            f"--network={self.config.network_mode}",
            # Working directory
            "-w",
            "/workspace",
        ]

        # Add labels
        for key, value in self.config.labels.items():
            cmd.extend(["--label", f"{key}={value}"])

        # Add image and command (keep container running)
        cmd.extend([self.config.base_image, "tail", "-f", "/dev/null"])

        return cmd

    async def _cleanup_partial_container(self, container_name: str) -> None:
        """Cleanup a partially created container."""
        try:
            await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.warning("Failed to cleanup partial container %s: %s", container_name, e)

    async def _destroy_container(self, container_id: str) -> None:
        """Destroy a container."""
        async with self._lock:
            container = self._containers.pop(container_id, None)
            if container:
                container.state = ContainerState.DESTROYING
                self._stats.total_destructions += 1

        if not container:
            return

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10.0)
            logger.debug("Destroyed container %s", container_id)

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.warning("Failed to destroy container %s: %s", container_id, e)

    # ==========================================================================
    # Background Tasks
    # ==========================================================================

    async def _health_check_loop(self) -> None:
        """Background health check loop."""
        while self._state == PoolState.RUNNING:
            try:
                await asyncio.sleep(self.config.health_check_interval_seconds)
                await self._run_health_checks()
            except asyncio.CancelledError:
                break
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                logger.error("Health check error: %s", e)

    async def _run_health_checks(self) -> None:
        """Run health checks on all containers."""
        async with self._lock:
            containers = list(self._containers.values())

        for container in containers:
            if container.state in (
                ContainerState.CREATING,
                ContainerState.DESTROYING,
            ):
                continue

            is_healthy = await self._check_container_health(container)

            async with self._lock:
                if container.container_id in self._containers:
                    container.last_health_check = time.time()
                    if is_healthy:
                        container.health_check_failures = 0
                        if container.state == ContainerState.UNHEALTHY:
                            container.state = ContainerState.READY
                    else:
                        container.health_check_failures += 1
                        if container.health_check_failures >= 3:
                            container.state = ContainerState.UNHEALTHY

    async def _check_container_health(self, container: PooledContainer) -> bool:
        """Check if a container is healthy."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return stdout.decode().strip().lower() == "true"

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.debug("Container health check failed: %s: %s", type(e).__name__, e)
            return False

    async def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        while self._state == PoolState.RUNNING:
            try:
                await asyncio.sleep(60.0)  # Check every minute
                await self._cleanup_expired_containers()
            except asyncio.CancelledError:
                break
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                logger.error("Cleanup error: %s", e)

    async def _cleanup_expired_containers(self) -> None:
        """Cleanup expired or unhealthy containers."""
        to_destroy: list[str] = []

        async with self._lock:
            for container in self._containers.values():
                if container.state == ContainerState.ACQUIRED:
                    continue  # Don't cleanup acquired containers

                if container.state == ContainerState.UNHEALTHY:
                    to_destroy.append(container.container_id)
                elif container.is_expired(
                    self.config.max_container_age_seconds,
                    self.config.idle_timeout_seconds,
                ):
                    # Only cleanup if above minimum
                    ready_count = sum(
                        1 for c in self._containers.values() if c.state == ContainerState.READY
                    )
                    if ready_count > self.config.min_pool_size:
                        to_destroy.append(container.container_id)

        for container_id in to_destroy:
            await self._destroy_container(container_id)

        if to_destroy:
            logger.debug("Cleaned up %s expired containers", len(to_destroy))

    async def _scaling_loop(self) -> None:
        """Background scaling loop."""
        while self._state == PoolState.RUNNING:
            try:
                await asyncio.sleep(10.0)  # Check every 10 seconds
                await self._scale_pool()
            except asyncio.CancelledError:
                break
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                logger.error("Scaling error: %s", e)

    async def _scale_pool(self) -> None:
        """Scale pool based on demand."""
        async with self._lock:
            ready_count = sum(
                1 for c in self._containers.values() if c.state == ContainerState.READY
            )
            total_count = len(self._containers)

        # Scale up if below minimum ready containers
        if ready_count < self.config.min_pool_size:
            needed = self.config.min_pool_size - ready_count
            available_slots = self.config.max_pool_size - total_count
            to_create = min(needed, available_slots)

            if to_create > 0:
                logger.debug("Scaling up: creating %s containers", to_create)
                tasks = [self._create_container() for _ in range(to_create)]
                await asyncio.gather(*tasks, return_exceptions=True)

    # ==========================================================================
    # Scaling API
    # ==========================================================================

    async def scale_up(self, count: int) -> int:
        """
        Scale up the pool by creating additional containers.

        Args:
            count: Number of containers to create

        Returns:
            Number of containers actually created
        """
        async with self._lock:
            available = self.config.max_pool_size - len(self._containers)
            to_create = min(count, available)

        if to_create <= 0:
            return 0

        tasks = [self._create_container() for _ in range(to_create)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        created = sum(1 for r in results if not isinstance(r, Exception))

        logger.info("Scaled up pool by %s containers", created)
        return created

    async def scale_down(self, count: int) -> int:
        """
        Scale down the pool by removing idle containers.

        Args:
            count: Number of containers to remove

        Returns:
            Number of containers actually removed
        """
        to_destroy: list[str] = []

        async with self._lock:
            # Find idle containers to remove
            idle_containers = [
                c for c in self._containers.values() if c.state == ContainerState.READY
            ]
            # Sort by last used (oldest first)
            idle_containers.sort(key=lambda c: c.last_used_at)

            # Keep minimum pool size
            removable = len(idle_containers) - self.config.min_pool_size
            to_remove = min(count, max(0, removable))

            for i in range(to_remove):
                to_destroy.append(idle_containers[i].container_id)

        for container_id in to_destroy:
            await self._destroy_container(container_id)

        logger.info("Scaled down pool by %s containers", len(to_destroy))
        return len(to_destroy)

    # ==========================================================================
    # Statistics
    # ==========================================================================

    def _record_acquire_time(self, duration_ms: float) -> None:
        """Record acquisition time for statistics."""
        self._acquire_times.append(duration_ms)
        # Keep last 100
        if len(self._acquire_times) > 100:
            self._acquire_times.pop(0)

    def _record_creation_time(self, duration_ms: float) -> None:
        """Record creation time for statistics."""
        self._creation_times.append(duration_ms)
        # Keep last 100
        if len(self._creation_times) > 100:
            self._creation_times.pop(0)

    def _get_stats(self) -> PoolStats:
        """Calculate current pool statistics."""
        self._stats.total_containers = len(self._containers)
        self._stats.ready_containers = sum(
            1 for c in self._containers.values() if c.state == ContainerState.READY
        )
        self._stats.acquired_containers = sum(
            1 for c in self._containers.values() if c.state == ContainerState.ACQUIRED
        )
        self._stats.unhealthy_containers = sum(
            1 for c in self._containers.values() if c.state == ContainerState.UNHEALTHY
        )
        self._stats.creating_containers = sum(
            1 for c in self._containers.values() if c.state == ContainerState.CREATING
        )

        if self._acquire_times:
            self._stats.avg_acquire_time_ms = sum(self._acquire_times) / len(self._acquire_times)

        if self._creation_times:
            self._stats.avg_creation_time_ms = sum(self._creation_times) / len(self._creation_times)

        if self._stats.total_containers > 0:
            self._stats.pool_utilization = (
                self._stats.acquired_containers / self._stats.total_containers
            )
        else:
            self._stats.pool_utilization = 0.0

        return self._stats

    def get_container(self, session_id: str) -> PooledContainer | None:
        """Get the container for a session."""
        container_id = self._session_containers.get(session_id)
        if container_id:
            return self._containers.get(container_id)
        return None


# ==========================================================================
# Global Pool Instance
# ==========================================================================

_pool_instance: ContainerPool | None = None


def get_container_pool() -> ContainerPool:
    """Get or create the global container pool."""
    global _pool_instance
    if _pool_instance is None:
        config = ContainerPoolConfig(
            min_pool_size=int(os.getenv("ARAGORA_CONTAINER_POOL_MIN", "5")),
            max_pool_size=int(os.getenv("ARAGORA_CONTAINER_POOL_MAX", "50")),
            warmup_count=int(os.getenv("ARAGORA_CONTAINER_POOL_WARMUP", "10")),
            base_image=os.getenv("ARAGORA_SANDBOX_IMAGE", "python:3.11-slim"),
        )
        _pool_instance = ContainerPool(config)
    return _pool_instance


def set_container_pool(pool: ContainerPool) -> None:
    """Set the global container pool instance."""
    global _pool_instance
    _pool_instance = pool


__all__ = [
    "ContainerCreationError",
    "ContainerPool",
    "ContainerPoolConfig",
    "ContainerPoolError",
    "ContainerState",
    "PoolExhaustedError",
    "PooledContainer",
    "PoolState",
    "PoolStats",
    "get_container_pool",
    "set_container_pool",
]
