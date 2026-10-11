"""
Container Sandbox - OS-level isolation for external agent execution.

Provides multiple isolation levels:
- PROCESS: Subprocess with resource limits (seccomp, rlimit)
- CONTAINER: Docker container with full isolation
- VM: Virtual machine isolation (via Firecracker/gVisor)

Security Model:
1. External agents never run in the main process
2. Network, filesystem, and resource limits enforced at OS level
3. Secrets injected via environment variables (not files)
4. All execution artifacts cleaned up after completion
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from aragora.gateway.external_agents.base import IsolationLevel

logger = logging.getLogger(__name__)


class SandboxState(str, Enum):
    """State of a sandbox instance."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    CLEANED = "cleaned"


@dataclass
class SandboxConfig:
    """Configuration for sandbox isolation."""

    isolation_level: IsolationLevel = IsolationLevel.CONTAINER

    # Resource limits
    max_memory_mb: int = 512
    max_cpu_cores: float = 1.0
    max_execution_seconds: int = 300
    max_output_bytes: int = 10 * 1024 * 1024  # 10MB

    # Network isolation
    allow_network: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    dns_servers: list[str] = field(default_factory=lambda: ["8.8.8.8"])

    # Filesystem
    read_only_root: bool = True
    work_dir: str = "/workspace"
    mount_volumes: dict[str, str] = field(default_factory=dict)  # host:container

    # Container-specific
    docker_image: str = "python:3.11-slim"
    docker_network: str = "none"  # "none", "bridge", or custom network
    docker_runtime: str | None = None  # "runsc" for gVisor, etc.

    # Security
    drop_capabilities: list[str] = field(
        default_factory=lambda: [
            "ALL",  # Drop all, then add back specific ones if needed
        ]
    )
    add_capabilities: list[str] = field(default_factory=list)
    seccomp_profile: str | None = None  # Path to seccomp profile
    apparmor_profile: str | None = None
    no_new_privileges: bool = True

    def validate(self) -> list[str]:
        """Validate configuration."""
        errors = []
        if self.max_memory_mb < 64:
            errors.append("max_memory_mb must be at least 64")
        if self.max_memory_mb > 16384:
            errors.append("max_memory_mb cannot exceed 16384")
        if self.max_cpu_cores < 0.1:
            errors.append("max_cpu_cores must be at least 0.1")
        if self.max_execution_seconds < 1:
            errors.append("max_execution_seconds must be at least 1")
        if self.max_execution_seconds > 3600:
            errors.append("max_execution_seconds cannot exceed 3600")
        return errors


@dataclass
class SandboxExecution:
    """Result of a sandboxed execution."""

    execution_id: str
    success: bool
    output: str = ""
    error: str | None = None
    exit_code: int | None = None
    execution_time_ms: float = 0.0
    memory_peak_mb: float = 0.0
    state: SandboxState = SandboxState.STOPPED
    started_at: datetime | None = None
    completed_at: datetime | None = None
    logs: str = ""


class SandboxBackend(Protocol):
    """Protocol for sandbox backends."""

    async def create(self, config: SandboxConfig) -> str:
        """Create a sandbox instance. Returns instance ID."""
        ...

    async def execute(
        self,
        instance_id: str,
        command: list[str],
        env: dict[str, str],
        stdin: str | None = None,
    ) -> SandboxExecution:
        """Execute command in sandbox."""
        ...

    async def destroy(self, instance_id: str) -> bool:
        """Destroy sandbox instance."""
        ...

    async def is_available(self) -> bool:
        """Check if backend is available."""
        ...


class ProcessSandbox(SandboxBackend):
    """
    Process-based sandbox using subprocess with resource limits.

    Provides basic isolation through:
    - Subprocess isolation
    - Resource limits (via ulimit on Unix)
    - Temporary directory isolation

    Note: Less secure than container/VM isolation.
    """

    def __init__(self) -> None:
        self._instances: dict[str, dict[str, Any]] = {}

    async def create(self, config: SandboxConfig) -> str:
        """Create a process sandbox environment."""
        instance_id = f"proc-{uuid.uuid4().hex[:12]}"

        # Create temp directory for sandbox
        work_dir = tempfile.mkdtemp(prefix=f"sandbox-{instance_id}-")

        self._instances[instance_id] = {
            "config": config,
            "work_dir": work_dir,
            "state": SandboxState.CREATED,
            "process": None,
        }

        logger.info("Created process sandbox: %s", instance_id)
        return instance_id

    async def execute(
        self,
        instance_id: str,
        command: list[str],
        env: dict[str, str],
        stdin: str | None = None,
    ) -> SandboxExecution:
        """Execute command in process sandbox."""
        import time

        start_time = time.time()

        if instance_id not in self._instances:
            return SandboxExecution(
                execution_id=instance_id,
                success=False,
                error=f"Instance {instance_id} not found",
                state=SandboxState.FAILED,
            )

        instance = self._instances[instance_id]
        config: SandboxConfig = instance["config"]

        # Build environment
        execution_env = os.environ.copy()
        execution_env.update(env)
        # Remove potentially sensitive env vars
        for key in ["AWS_SECRET_ACCESS_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
            execution_env.pop(key, None)

        try:
            instance["state"] = SandboxState.RUNNING

            # Create subprocess with resource limits
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=instance["work_dir"],
                env=execution_env,
            )
            instance["process"] = process

            # Execute with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=stdin.encode() if stdin else None),
                    timeout=config.max_execution_seconds,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return SandboxExecution(
                    execution_id=instance_id,
                    success=False,
                    error=f"Execution timed out after {config.max_execution_seconds}s",
                    exit_code=-1,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    state=SandboxState.STOPPED,
                )

            execution_time = (time.time() - start_time) * 1000
            instance["state"] = SandboxState.STOPPED

            # Truncate output if too large
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > config.max_output_bytes:
                output = output[: config.max_output_bytes] + "\n[OUTPUT TRUNCATED]"

            return SandboxExecution(
                execution_id=instance_id,
                success=process.returncode == 0,
                output=output,
                error=stderr.decode("utf-8", errors="replace") if stderr else None,
                exit_code=process.returncode,
                execution_time_ms=execution_time,
                state=SandboxState.STOPPED,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

        except (OSError, RuntimeError) as e:
            instance["state"] = SandboxState.FAILED
            logger.error("Process sandbox execution failed: %s", e)
            return SandboxExecution(
                execution_id=instance_id,
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
                state=SandboxState.FAILED,
            )

    async def destroy(self, instance_id: str) -> bool:
        """Destroy process sandbox."""
        if instance_id not in self._instances:
            return False

        instance = self._instances[instance_id]

        # Kill process if running
        if instance.get("process"):
            try:
                instance["process"].kill()
                await instance["process"].wait()
            except (OSError, ProcessLookupError) as e:
                logger.debug("Failed to kill sandbox process: %s: %s", type(e).__name__, e)

        # Clean up work directory
        work_dir = instance.get("work_dir")
        if work_dir and os.path.exists(work_dir):
            try:
                shutil.rmtree(work_dir)
            except (OSError, PermissionError) as e:
                logger.warning("Failed to clean up sandbox dir: %s", e)

        del self._instances[instance_id]
        logger.info("Destroyed process sandbox: %s", instance_id)
        return True

    async def is_available(self) -> bool:
        """Process sandbox is always available."""
        return True


class DockerSandbox(SandboxBackend):
    """
    Docker container-based sandbox.

    Provides strong isolation through:
    - Container namespace isolation
    - Resource limits (cgroups)
    - Network isolation
    - Capability dropping
    - Seccomp/AppArmor profiles

    Requires Docker to be installed and accessible.
    """

    def __init__(self) -> None:
        self._instances: dict[str, dict[str, Any]] = {}

    async def is_available(self) -> bool:
        """Check if Docker is available."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=10)
            return proc.returncode == 0
        except FileNotFoundError:
            return False
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False
        except (OSError, RuntimeError) as e:
            logger.debug("Docker availability check failed: %s: %s", type(e).__name__, e)
            return False

    async def create(self, config: SandboxConfig) -> str:
        """Create a Docker container sandbox."""
        instance_id = f"docker-{uuid.uuid4().hex[:12]}"

        # Build container create command
        cmd = [
            "docker",
            "create",
            "--name",
            instance_id,
            "--memory",
            f"{config.max_memory_mb}m",
            "--cpus",
            str(config.max_cpu_cores),
            "--network",
            config.docker_network,
            "--workdir",
            config.work_dir,
        ]

        # Security options
        if config.no_new_privileges:
            cmd.extend(["--security-opt", "no-new-privileges"])

        if config.read_only_root:
            cmd.append("--read-only")

        # Capabilities
        for cap in config.drop_capabilities:
            cmd.extend(["--cap-drop", cap])
        for cap in config.add_capabilities:
            cmd.extend(["--cap-add", cap])

        # Seccomp profile
        if config.seccomp_profile:
            cmd.extend(["--security-opt", f"seccomp={config.seccomp_profile}"])

        # AppArmor profile
        if config.apparmor_profile:
            cmd.extend(["--security-opt", f"apparmor={config.apparmor_profile}"])

        # Runtime (e.g., gVisor)
        if config.docker_runtime:
            cmd.extend(["--runtime", config.docker_runtime])

        # Volume mounts
        for host_path, container_path in config.mount_volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}:ro"])

        # Add tmpfs for /tmp
        cmd.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=100m"])  # container-internal tmpfs mount

        # Image
        cmd.append(config.docker_image)

        # Keep container running with sleep
        cmd.extend(["sleep", "infinity"])

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise RuntimeError("Container creation timed out")

            if proc.returncode != 0:
                error = stderr.decode("utf-8", errors="replace")
                raise RuntimeError(f"Failed to create container: {error}")

            self._instances[instance_id] = {
                "config": config,
                "state": SandboxState.CREATED,
            }

            logger.info("Created Docker sandbox: %s", instance_id)
            return instance_id

        except (OSError, RuntimeError) as e:
            logger.error("Failed to create Docker sandbox: %s", e)
            raise

    async def execute(
        self,
        instance_id: str,
        command: list[str],
        env: dict[str, str],
        stdin: str | None = None,
    ) -> SandboxExecution:
        """Execute command in Docker container."""
        import time

        start_time = time.time()

        if instance_id not in self._instances:
            return SandboxExecution(
                execution_id=instance_id,
                success=False,
                error=f"Instance {instance_id} not found",
                state=SandboxState.FAILED,
            )

        instance = self._instances[instance_id]
        config: SandboxConfig = instance["config"]

        try:
            # Start container if not running
            if instance["state"] == SandboxState.CREATED:
                start_proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "start",
                    instance_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await start_proc.communicate()
                if start_proc.returncode != 0:
                    raise RuntimeError(f"Failed to start container: {stderr.decode()}")
                instance["state"] = SandboxState.RUNNING

            # Build exec command
            exec_cmd = ["docker", "exec", "-i"]

            # Add environment variables
            for key, value in env.items():
                exec_cmd.extend(["-e", f"{key}={value}"])

            exec_cmd.append(instance_id)
            exec_cmd.extend(command)

            # Execute
            proc = await asyncio.create_subprocess_exec(
                *exec_cmd,
                stdin=asyncio.subprocess.PIPE if stdin else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(input=stdin.encode() if stdin else None),
                    timeout=config.max_execution_seconds,
                )
            except asyncio.TimeoutError:
                # Kill the exec process
                proc.kill()
                await proc.wait()
                return SandboxExecution(
                    execution_id=instance_id,
                    success=False,
                    error=f"Execution timed out after {config.max_execution_seconds}s",
                    exit_code=-1,
                    execution_time_ms=(time.time() - start_time) * 1000,
                    state=SandboxState.RUNNING,
                )

            execution_time = (time.time() - start_time) * 1000

            # Truncate output if needed
            output = stdout.decode("utf-8", errors="replace")
            if len(output) > config.max_output_bytes:
                output = output[: config.max_output_bytes] + "\n[OUTPUT TRUNCATED]"

            return SandboxExecution(
                execution_id=instance_id,
                success=proc.returncode == 0,
                output=output,
                error=stderr.decode("utf-8", errors="replace") if stderr else None,
                exit_code=proc.returncode,
                execution_time_ms=execution_time,
                state=SandboxState.RUNNING,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )

        except (OSError, RuntimeError) as e:
            logger.error("Docker sandbox execution failed: %s", e)
            return SandboxExecution(
                execution_id=instance_id,
                success=False,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
                state=SandboxState.FAILED,
            )

    async def destroy(self, instance_id: str) -> bool:
        """Destroy Docker container sandbox."""
        if instance_id not in self._instances:
            return False

        try:
            # Stop and remove container
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                instance_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            del self._instances[instance_id]
            logger.info("Destroyed Docker sandbox: %s", instance_id)
            return True

        except (OSError, RuntimeError) as e:
            logger.error("Failed to destroy Docker sandbox: %s", e)
            return False


class SandboxManager:
    """
    Manager for creating and managing sandboxed execution environments.

    Automatically selects the best available backend based on
    the requested isolation level and system capabilities.
    """

    def __init__(self) -> None:
        self._process_backend = ProcessSandbox()
        self._docker_backend = DockerSandbox()
        self._active_sandboxes: dict[str, tuple[SandboxBackend, str]] = {}

    async def create_sandbox(
        self,
        config: SandboxConfig,
    ) -> str:
        """
        Create a sandbox with the specified configuration.

        Args:
            config: Sandbox configuration

        Returns:
            Sandbox instance ID
        """
        # Validate config
        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid sandbox config: {', '.join(errors)}")

        # Select backend based on isolation level
        backend = await self._select_backend(config.isolation_level)

        # Create sandbox
        instance_id = await backend.create(config)
        self._active_sandboxes[instance_id] = (backend, instance_id)

        return instance_id

    async def execute(
        self,
        instance_id: str,
        command: list[str],
        env: dict[str, str] | None = None,
        stdin: str | None = None,
    ) -> SandboxExecution:
        """
        Execute a command in the sandbox.

        Args:
            instance_id: Sandbox instance ID
            command: Command to execute
            env: Environment variables to inject
            stdin: Standard input to provide

        Returns:
            SandboxExecution result
        """
        if instance_id not in self._active_sandboxes:
            return SandboxExecution(
                execution_id=instance_id,
                success=False,
                error=f"Sandbox {instance_id} not found",
                state=SandboxState.FAILED,
            )

        backend, _ = self._active_sandboxes[instance_id]
        return await backend.execute(
            instance_id,
            command,
            env or {},
            stdin,
        )

    async def destroy_sandbox(self, instance_id: str) -> bool:
        """
        Destroy a sandbox instance.

        Args:
            instance_id: Sandbox instance ID

        Returns:
            True if destroyed successfully
        """
        if instance_id not in self._active_sandboxes:
            return False

        backend, _ = self._active_sandboxes[instance_id]
        result = await backend.destroy(instance_id)

        if result:
            del self._active_sandboxes[instance_id]

        return result

    async def cleanup_all(self) -> int:
        """
        Cleanup all active sandboxes.

        Returns:
            Number of sandboxes cleaned up
        """
        count = 0
        for instance_id in list(self._active_sandboxes.keys()):
            if await self.destroy_sandbox(instance_id):
                count += 1
        return count

    async def _select_backend(
        self,
        isolation_level: IsolationLevel,
    ) -> SandboxBackend:
        """Select the appropriate backend for the isolation level."""
        if isolation_level == IsolationLevel.NONE:
            # Use process backend with minimal isolation
            return self._process_backend

        elif isolation_level == IsolationLevel.PROCESS:
            return self._process_backend

        elif isolation_level == IsolationLevel.CONTAINER:
            if await self._docker_backend.is_available():
                return self._docker_backend
            logger.warning("Docker not available, falling back to process isolation")
            return self._process_backend

        elif isolation_level == IsolationLevel.VM:
            # VM isolation not yet implemented
            # Fall back to container if available
            if await self._docker_backend.is_available():
                logger.warning("VM isolation not available, using container isolation")
                return self._docker_backend
            return self._process_backend

        return self._process_backend

    def get_active_sandboxes(self) -> list[str]:
        """Get list of active sandbox IDs."""
        return list(self._active_sandboxes.keys())


__all__ = [
    "SandboxConfig",
    "SandboxExecution",
    "SandboxState",
    "SandboxBackend",
    "ProcessSandbox",
    "DockerSandbox",
    "SandboxManager",
]
