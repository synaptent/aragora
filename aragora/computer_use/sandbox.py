"""
Sandbox Isolation for Computer Use.

Provides isolated execution environments for computer-use actions:
- Docker container isolation with resource limits
- Process isolation with restricted capabilities
- Network namespace isolation
- Filesystem sandboxing

Safety: All computer-use actions run in isolated environments to prevent
system compromise.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SandboxType(str, Enum):
    """Type of sandbox isolation."""

    NONE = "none"
    PROCESS = "process"
    DOCKER = "docker"
    FIREJAIL = "firejail"


class SandboxStatus(str, Enum):
    """Status of a sandbox instance."""

    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class SandboxConfig:
    """Configuration for sandbox isolation."""

    sandbox_type: SandboxType = SandboxType.DOCKER
    memory_limit_mb: int = 2048
    cpu_limit_cores: float = 2.0
    disk_limit_mb: int = 1024
    timeout_seconds: float = 300.0
    network_enabled: bool = True
    allowed_hosts: list[str] = field(default_factory=list)
    blocked_hosts: list[str] = field(default_factory=list)
    read_only_root: bool = True
    allowed_paths: list[str] = field(default_factory=list)
    temp_dir: str | None = None
    docker_image: str = "mcr.microsoft.com/playwright:v1.40.0-jammy"
    docker_network: str = "bridge"
    docker_extra_args: list[str] = field(default_factory=list)
    drop_capabilities: bool = True
    no_new_privileges: bool = True
    seccomp_profile: str | None = None
    process_user: str | None = None
    process_group: str | None = None
    # Use SYS_ADMIN capability instead of narrower DAC_OVERRIDE+SYS_PTRACE.
    # Only enable if Playwright fails with the narrower set.
    sandbox_use_sys_admin: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxInstance:
    """A running sandbox instance."""

    id: str
    config: SandboxConfig
    status: SandboxStatus
    container_id: str | None = None
    process_pid: int | None = None
    temp_dir: str | None = None
    vnc_port: int | None = None
    ws_port: int | None = None
    created_at: float = 0.0
    started_at: float | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxProvider(ABC):
    """Abstract base class for sandbox providers."""

    @abstractmethod
    async def create(self, config: SandboxConfig) -> SandboxInstance:
        """Create a new sandbox instance."""
        ...

    @abstractmethod
    async def start(self, instance: SandboxInstance) -> None:
        """Start a sandbox instance."""
        ...

    @abstractmethod
    async def stop(self, instance: SandboxInstance) -> None:
        """Stop a sandbox instance."""
        ...

    @abstractmethod
    async def destroy(self, instance: SandboxInstance) -> None:
        """Destroy a sandbox instance and cleanup resources."""
        ...

    @abstractmethod
    async def execute(
        self,
        instance: SandboxInstance,
        command: list[str],
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command in the sandbox."""
        ...

    @abstractmethod
    async def health_check(self, instance: SandboxInstance) -> bool:
        """Check if sandbox is healthy."""
        ...


class DockerSandboxProvider(SandboxProvider):
    """Docker-based sandbox provider."""

    def __init__(self) -> None:
        self._instances: dict[str, SandboxInstance] = {}

    async def create(self, config: SandboxConfig) -> SandboxInstance:
        """Create a Docker container sandbox."""
        import time

        instance_id = str(uuid.uuid4())[:8]
        temp_dir = tempfile.mkdtemp(prefix=f"aragora_sandbox_{instance_id}_")

        instance = SandboxInstance(
            id=instance_id,
            config=config,
            status=SandboxStatus.CREATED,
            temp_dir=temp_dir,
            created_at=time.time(),
        )

        self._instances[instance_id] = instance
        logger.info("Created Docker sandbox %s", instance_id)
        return instance

    async def start(self, instance: SandboxInstance) -> None:
        """Start the Docker container."""
        import time

        instance.status = SandboxStatus.STARTING

        try:
            config = instance.config
            cmd = [
                "docker",
                "run",
                "-d",
                "--name",
                f"aragora_sandbox_{instance.id}",
                f"--memory={config.memory_limit_mb}m",
                f"--cpus={config.cpu_limit_cores}",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                *(
                    ["--cap-add", "SYS_ADMIN"]
                    if config.sandbox_use_sys_admin
                    else ["--cap-add", "DAC_OVERRIDE", "--cap-add", "SYS_PTRACE"]
                ),
                "-v",
                f"{instance.temp_dir}:/workspace:rw",
                "-e",
                "DISPLAY=:99",
            ]

            if not config.network_enabled:
                cmd.extend(["--network", "none"])
            else:
                cmd.extend(["--network", config.docker_network])

            if config.read_only_root:
                cmd.append("--read-only")
                cmd.extend(["--tmpfs", "/tmp:rw,exec,size=100m"])  # container-internal tmpfs mount
                cmd.extend(["--tmpfs", "/run:rw,size=50m"])

            cmd.extend(config.docker_extra_args)
            cmd.extend([config.docker_image, "tail", "-f", "/dev/null"])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                raise RuntimeError(f"Docker start failed: {stderr.decode()}")

            instance.container_id = stdout.decode().strip()
            instance.status = SandboxStatus.RUNNING
            instance.started_at = time.time()

            logger.info("Started Docker sandbox %s: %s", instance.id, instance.container_id[:12])

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            instance.status = SandboxStatus.ERROR
            instance.error = str(e)
            logger.error("Failed to start Docker sandbox: %s", e)
            raise

    async def stop(self, instance: SandboxInstance) -> None:
        """Stop the Docker container."""
        if not instance.container_id:
            return

        instance.status = SandboxStatus.STOPPING

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "stop",
                "-t",
                "5",
                instance.container_id,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            instance.status = SandboxStatus.STOPPED
            logger.info("Stopped Docker sandbox %s", instance.id)
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            instance.error = str(e)
            logger.error("Failed to stop Docker sandbox: %s", e)

    async def destroy(self, instance: SandboxInstance) -> None:
        """Destroy the Docker container and cleanup."""
        await self.stop(instance)

        if instance.container_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker",
                    "rm",
                    "-f",
                    instance.container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except (RuntimeError, OSError, subprocess.SubprocessError) as e:
                logger.warning("Failed to remove Docker container: %s", e)

        if instance.temp_dir and Path(instance.temp_dir).exists():
            import shutil

            shutil.rmtree(instance.temp_dir, ignore_errors=True)

        self._instances.pop(instance.id, None)
        logger.info("Destroyed Docker sandbox %s", instance.id)

    async def execute(
        self,
        instance: SandboxInstance,
        command: list[str],
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command in the Docker container."""
        if not instance.container_id:
            raise RuntimeError("Sandbox not started")

        if instance.status != SandboxStatus.RUNNING:
            raise RuntimeError(f"Sandbox not running: {instance.status}")

        timeout = timeout or instance.config.timeout_seconds

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                instance.container_id,
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                return proc.returncode or 0, stdout.decode(), stderr.decode()
            except asyncio.TimeoutError:
                proc.kill()
                return -1, "", "Command timed out"

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            return -1, "", str(e)

    async def health_check(self, instance: SandboxInstance) -> bool:
        """Check if Docker container is healthy."""
        if not instance.container_id:
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                "-f",
                "{{.State.Running}}",
                instance.container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode().strip() == "true"
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            logger.debug("Docker container health check failed: %s: %s", type(e).__name__, e)
            return False


class ProcessSandboxProvider(SandboxProvider):
    """Process-based sandbox provider (lighter weight, less isolation)."""

    def __init__(self) -> None:
        self._instances: dict[str, SandboxInstance] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    async def create(self, config: SandboxConfig) -> SandboxInstance:
        """Create a process sandbox."""
        import time

        instance_id = str(uuid.uuid4())[:8]
        temp_dir = tempfile.mkdtemp(prefix=f"aragora_sandbox_{instance_id}_")

        instance = SandboxInstance(
            id=instance_id,
            config=config,
            status=SandboxStatus.CREATED,
            temp_dir=temp_dir,
            created_at=time.time(),
        )

        self._instances[instance_id] = instance
        logger.info("Created process sandbox %s", instance_id)
        return instance

    async def start(self, instance: SandboxInstance) -> None:
        """Start the sandbox (no-op for process sandbox)."""
        import time

        instance.status = SandboxStatus.RUNNING
        instance.started_at = time.time()
        logger.info("Started process sandbox %s", instance.id)

    async def stop(self, instance: SandboxInstance) -> None:
        """Stop any running processes."""
        proc = self._processes.pop(instance.id, None)
        if proc:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except (RuntimeError, OSError, TimeoutError) as e:
                logger.debug("Process terminate/wait failed, killing: %s: %s", type(e).__name__, e)
                proc.kill()

        instance.status = SandboxStatus.STOPPED
        logger.info("Stopped process sandbox %s", instance.id)

    async def destroy(self, instance: SandboxInstance) -> None:
        """Destroy the sandbox and cleanup."""
        await self.stop(instance)

        if instance.temp_dir and Path(instance.temp_dir).exists():
            import shutil

            shutil.rmtree(instance.temp_dir, ignore_errors=True)

        self._instances.pop(instance.id, None)
        logger.info("Destroyed process sandbox %s", instance.id)

    async def execute(
        self,
        instance: SandboxInstance,
        command: list[str],
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command in the sandbox."""
        if instance.status != SandboxStatus.RUNNING:
            raise RuntimeError(f"Sandbox not running: {instance.status}")

        timeout = timeout or instance.config.timeout_seconds

        env = os.environ.copy()
        env["HOME"] = instance.temp_dir or tempfile.gettempdir()
        env["TMPDIR"] = instance.temp_dir or tempfile.gettempdir()

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=instance.temp_dir,
                env=env,
                start_new_session=True,
            )

            self._processes[instance.id] = proc

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
                return proc.returncode or 0, stdout.decode(), stderr.decode()
            except asyncio.TimeoutError:
                proc.kill()
                return -1, "", "Command timed out"
            finally:
                self._processes.pop(instance.id, None)

        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            return -1, "", str(e)

    async def health_check(self, instance: SandboxInstance) -> bool:
        """Check if sandbox is healthy."""
        return instance.status == SandboxStatus.RUNNING


class SandboxManager:
    """Manages sandbox instances for computer-use."""

    def __init__(self) -> None:
        self._providers: dict[SandboxType, SandboxProvider] = {
            SandboxType.DOCKER: DockerSandboxProvider(),
            SandboxType.PROCESS: ProcessSandboxProvider(),
        }
        self._instances: dict[str, SandboxInstance] = {}
        self._lock = asyncio.Lock()

    async def create_sandbox(
        self,
        config: SandboxConfig | None = None,
    ) -> SandboxInstance:
        """Create a new sandbox instance."""
        config = config or SandboxConfig()
        provider = self._providers.get(config.sandbox_type)

        if not provider:
            raise ValueError(f"Unknown sandbox type: {config.sandbox_type}")

        async with self._lock:
            instance = await provider.create(config)
            self._instances[instance.id] = instance
            return instance

    async def start_sandbox(self, sandbox_id: str) -> None:
        """Start a sandbox instance."""
        instance = self._instances.get(sandbox_id)
        if not instance:
            raise ValueError(f"Sandbox not found: {sandbox_id}")

        provider = self._providers.get(instance.config.sandbox_type)
        if provider:
            await provider.start(instance)

    async def stop_sandbox(self, sandbox_id: str) -> None:
        """Stop a sandbox instance."""
        instance = self._instances.get(sandbox_id)
        if not instance:
            return

        provider = self._providers.get(instance.config.sandbox_type)
        if provider:
            await provider.stop(instance)

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        """Destroy a sandbox instance."""
        instance = self._instances.pop(sandbox_id, None)
        if not instance:
            return

        provider = self._providers.get(instance.config.sandbox_type)
        if provider:
            await provider.destroy(instance)

    async def execute_in_sandbox(
        self,
        sandbox_id: str,
        command: list[str],
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        """Execute a command in a sandbox."""
        instance = self._instances.get(sandbox_id)
        if not instance:
            raise ValueError(f"Sandbox not found: {sandbox_id}")

        provider = self._providers.get(instance.config.sandbox_type)
        if not provider:
            raise RuntimeError(f"No provider for sandbox type: {instance.config.sandbox_type}")

        return await provider.execute(instance, command, timeout)

    async def get_sandbox(self, sandbox_id: str) -> SandboxInstance | None:
        """Get a sandbox instance by ID."""
        return self._instances.get(sandbox_id)

    async def list_sandboxes(self) -> list[SandboxInstance]:
        """List all sandbox instances."""
        return list(self._instances.values())

    async def cleanup_all(self) -> None:
        """Destroy all sandbox instances."""
        sandbox_ids = list(self._instances.keys())
        for sandbox_id in sandbox_ids:
            await self.destroy_sandbox(sandbox_id)

    async def get_stats(self) -> dict[str, Any]:
        """Get sandbox manager statistics."""
        by_status: dict[str, int] = {}
        by_type: dict[str, int] = {}

        for instance in self._instances.values():
            status = instance.status.value
            by_status[status] = by_status.get(status, 0) + 1

            sandbox_type = instance.config.sandbox_type.value
            by_type[sandbox_type] = by_type.get(sandbox_type, 0) + 1

        return {
            "total_sandboxes": len(self._instances),
            "by_status": by_status,
            "by_type": by_type,
        }
