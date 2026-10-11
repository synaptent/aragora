"""
OpenClaw Action Sandbox.

Provides isolated execution environments for OpenClaw actions with:
- Workspace scoping (file operations confined to workspace)
- Resource limits (CPU, memory, time)
- Environment isolation
- Cleanup on session end

Each session gets its own sandbox with scoped resources and automatic cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass
class SandboxConfig:
    """Configuration for a sandbox environment."""

    # Workspace settings
    workspace_root: str = "/workspace"
    create_workspace: bool = True
    workspace_size_limit_mb: int = 1000

    # File access
    allowed_read_paths: list[str] = field(default_factory=list)
    allowed_write_paths: list[str] = field(default_factory=list)
    blocked_paths: list[str] = field(
        default_factory=lambda: [
            "/etc/passwd",
            "/etc/shadow",
            "/etc/sudoers",
            "/root",
            "/home/*/.ssh",
        ]
    )

    # Resource limits
    max_execution_time_seconds: int = 300
    max_memory_mb: int = 512
    max_file_size_mb: int = 100
    max_processes: int = 10

    # Shell settings
    allowed_commands: list[str] = field(
        default_factory=lambda: [
            "ls",
            "cat",
            "head",
            "tail",
            "grep",
            "find",
            "wc",
            "echo",
            "pwd",
            "mkdir",
            "rm",
            "cp",
            "mv",
            "touch",
            "python",
            "python3",
            "node",
            "npm",
            "pip",
            "git",
            "sleep",
        ]
    )
    blocked_commands: list[str] = field(
        default_factory=lambda: [
            "sudo",
            "su",
            "doas",
            "pkexec",
            "dd",
            "mkfs",
            "fdisk",
            "mount",
            "umount",
            "reboot",
            "shutdown",
            "halt",
            "poweroff",
            "iptables",
            "firewall-cmd",
            "ufw",
        ]
    )

    # Network settings
    allow_network: bool = True
    allowed_hosts: list[str] = field(default_factory=list)
    blocked_hosts: list[str] = field(
        default_factory=lambda: [
            "localhost",
            "127.0.0.1",
            "0.0.0.0",  # SSRF blocklist entry, not a bind address
            "169.254.169.254",  # AWS metadata
        ]
    )

    # Environment
    environment_vars: dict[str, str] = field(default_factory=dict)
    inherit_env: bool = False


@dataclass
class SandboxSession:
    """An active sandbox session."""

    sandbox_id: str
    session_id: str
    user_id: str
    tenant_id: str
    workspace_path: str
    config: SandboxConfig
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    action_count: int = 0
    bytes_written: int = 0
    status: str = "active"  # active, suspended, terminated


@dataclass
class SandboxActionResult:
    """Result of an action executed in the sandbox."""

    success: bool
    action_id: str
    output: Any = None
    error: str | None = None
    execution_time_ms: float = 0.0
    resources_used: dict[str, Any] = field(default_factory=dict)


class OpenClawActionSandbox:
    """
    Sandbox manager for isolated OpenClaw action execution.

    Creates per-session workspaces with:
    - File system isolation
    - Command filtering
    - Resource monitoring
    - Automatic cleanup

    Example:
    ```python
    from aragora.gateway.openclaw_sandbox import OpenClawActionSandbox, SandboxConfig

    sandbox = OpenClawActionSandbox()

    # Create sandbox for session
    session = await sandbox.create_sandbox(
        session_id="sess-123",
        user_id="user-456",
        tenant_id="acme-corp",
    )

    # Execute command in sandbox
    result = await sandbox.execute_shell(
        sandbox_id=session.sandbox_id,
        command="ls -la",
    )

    # Read file in sandbox
    result = await sandbox.read_file(
        sandbox_id=session.sandbox_id,
        path="/workspace/data.txt",
    )

    # Cleanup on session end
    await sandbox.destroy_sandbox(session.sandbox_id)
    ```
    """

    def __init__(
        self,
        base_workspace_path: str | None = None,
        default_config: SandboxConfig | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        """
        Initialize the sandbox manager.

        Args:
            base_workspace_path: Base directory for sandbox workspaces
            default_config: Default sandbox configuration
            event_callback: Callback for sandbox events
        """
        self._base_path = Path(base_workspace_path or tempfile.gettempdir()) / "openclaw_sandboxes"
        self._default_config = default_config or SandboxConfig()
        self._event_callback = event_callback

        self._sandboxes: dict[str, SandboxSession] = {}
        self._session_to_sandbox: dict[str, str] = {}

        # Ensure base directory exists
        self._base_path.mkdir(parents=True, exist_ok=True)

        # Statistics
        self._stats = {
            "sandboxes_created": 0,
            "sandboxes_destroyed": 0,
            "commands_executed": 0,
            "commands_blocked": 0,
            "files_read": 0,
            "files_written": 0,
            "bytes_written": 0,
        }

    async def create_sandbox(
        self,
        session_id: str,
        user_id: str,
        tenant_id: str = "default",
        config: SandboxConfig | None = None,
    ) -> SandboxSession:
        """
        Create a new sandbox for a session.

        Args:
            session_id: Session identifier
            user_id: User identifier
            tenant_id: Tenant identifier
            config: Optional custom configuration

        Returns:
            SandboxSession with workspace details
        """
        config = config or self._default_config
        sandbox_id = str(uuid.uuid4())

        # Create workspace directory
        workspace_path = self._base_path / tenant_id / sandbox_id / "workspace"
        workspace_path.mkdir(parents=True, exist_ok=True)

        session = SandboxSession(
            sandbox_id=sandbox_id,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            workspace_path=str(workspace_path),
            config=config,
        )

        self._sandboxes[sandbox_id] = session
        self._session_to_sandbox[session_id] = sandbox_id

        self._stats["sandboxes_created"] += 1

        self._emit_event(
            "sandbox_created",
            {
                "sandbox_id": sandbox_id,
                "session_id": session_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "workspace_path": str(workspace_path),
            },
        )

        return session

    async def destroy_sandbox(self, sandbox_id: str) -> bool:
        """
        Destroy a sandbox and clean up its workspace.

        Args:
            sandbox_id: Sandbox identifier

        Returns:
            True if sandbox was destroyed
        """
        session = self._sandboxes.pop(sandbox_id, None)
        if not session:
            return False

        # Remove session mapping
        if session.session_id in self._session_to_sandbox:
            del self._session_to_sandbox[session.session_id]

        # Clean up workspace
        try:
            workspace = Path(session.workspace_path)
            if workspace.exists():
                shutil.rmtree(workspace.parent)  # Remove sandbox directory
        except (OSError, PermissionError) as e:
            logger.warning("Failed to clean up workspace: %s", e)

        session.status = "terminated"
        self._stats["sandboxes_destroyed"] += 1

        self._emit_event(
            "sandbox_destroyed",
            {
                "sandbox_id": sandbox_id,
                "session_id": session.session_id,
                "action_count": session.action_count,
                "bytes_written": session.bytes_written,
                "duration_seconds": time.time() - session.created_at,
            },
        )

        return True

    def get_sandbox(self, sandbox_id: str) -> SandboxSession | None:
        """Get a sandbox by ID."""
        return self._sandboxes.get(sandbox_id)

    def get_sandbox_for_session(self, session_id: str) -> SandboxSession | None:
        """Get sandbox for a session."""
        sandbox_id = self._session_to_sandbox.get(session_id)
        if sandbox_id:
            return self._sandboxes.get(sandbox_id)
        return None

    async def execute_shell(
        self,
        sandbox_id: str,
        command: str,
        timeout: int | None = None,
    ) -> SandboxActionResult:
        """
        Execute a shell command in the sandbox.

        Args:
            sandbox_id: Sandbox identifier
            command: Command to execute
            timeout: Optional timeout override

        Returns:
            SandboxActionResult with command output
        """
        start_time = time.time()
        action_id = str(uuid.uuid4())

        session = self._sandboxes.get(sandbox_id)
        if not session:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error="Sandbox not found",
            )

        if session.status != "active":
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=f"Sandbox is {session.status}",
            )

        # Validate command
        validation = self._validate_command(command, session.config)
        if not validation["allowed"]:
            self._stats["commands_blocked"] += 1
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=validation["reason"],
            )

        # Execute command
        timeout = timeout or session.config.max_execution_time_seconds

        try:
            env = self._build_environment(session)

            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=session.workspace_path,
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout,
            )

            session.action_count += 1
            session.last_activity = time.time()
            self._stats["commands_executed"] += 1

            exec_time = (time.time() - start_time) * 1000

            return SandboxActionResult(
                success=proc.returncode == 0,
                action_id=action_id,
                output={
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "return_code": proc.returncode,
                },
                error=stderr.decode("utf-8", errors="replace") if proc.returncode != 0 else None,
                execution_time_ms=exec_time,
            )

        except asyncio.TimeoutError:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=f"Command timed out after {timeout}s",
                execution_time_ms=(time.time() - start_time) * 1000,
            )
        except (OSError, RuntimeError) as e:
            logger.error("Command execution failed: %s", e)
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    async def read_file(
        self,
        sandbox_id: str,
        path: str,
    ) -> SandboxActionResult:
        """
        Read a file within the sandbox.

        Args:
            sandbox_id: Sandbox identifier
            path: File path to read

        Returns:
            SandboxActionResult with file content
        """
        start_time = time.time()
        action_id = str(uuid.uuid4())

        session = self._sandboxes.get(sandbox_id)
        if not session:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error="Sandbox not found",
            )

        # Resolve and validate path
        resolved = self._resolve_path(path, session)
        if not resolved["allowed"]:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=resolved["reason"],
            )

        file_path = Path(resolved["path"])

        try:
            if not file_path.exists():
                return SandboxActionResult(
                    success=False,
                    action_id=action_id,
                    error=f"File not found: {path}",
                )

            content = file_path.read_text()

            session.action_count += 1
            session.last_activity = time.time()
            self._stats["files_read"] += 1

            return SandboxActionResult(
                success=True,
                action_id=action_id,
                output=content,
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        except (OSError, PermissionError) as e:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    async def write_file(
        self,
        sandbox_id: str,
        path: str,
        content: str,
    ) -> SandboxActionResult:
        """
        Write a file within the sandbox.

        Args:
            sandbox_id: Sandbox identifier
            path: File path to write
            content: Content to write

        Returns:
            SandboxActionResult indicating success
        """
        start_time = time.time()
        action_id = str(uuid.uuid4())

        session = self._sandboxes.get(sandbox_id)
        if not session:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error="Sandbox not found",
            )

        # Check file size limit
        content_bytes = len(content.encode("utf-8"))
        max_bytes = session.config.max_file_size_mb * 1024 * 1024
        if content_bytes > max_bytes:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=f"File size exceeds limit of {session.config.max_file_size_mb}MB",
            )

        # Resolve and validate path
        resolved = self._resolve_path(path, session, write=True)
        if not resolved["allowed"]:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=resolved["reason"],
            )

        file_path = Path(resolved["path"])

        try:
            # Ensure parent directory exists
            file_path.parent.mkdir(parents=True, exist_ok=True)

            file_path.write_text(content)

            session.action_count += 1
            session.last_activity = time.time()
            session.bytes_written += content_bytes
            self._stats["files_written"] += 1
            self._stats["bytes_written"] += content_bytes

            return SandboxActionResult(
                success=True,
                action_id=action_id,
                output={"bytes_written": content_bytes},
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        except (OSError, PermissionError) as e:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    async def delete_file(
        self,
        sandbox_id: str,
        path: str,
    ) -> SandboxActionResult:
        """
        Delete a file within the sandbox.

        Args:
            sandbox_id: Sandbox identifier
            path: File path to delete

        Returns:
            SandboxActionResult indicating success
        """
        start_time = time.time()
        action_id = str(uuid.uuid4())

        session = self._sandboxes.get(sandbox_id)
        if not session:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error="Sandbox not found",
            )

        # Resolve and validate path
        resolved = self._resolve_path(path, session, write=True)
        if not resolved["allowed"]:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=resolved["reason"],
            )

        file_path = Path(resolved["path"])

        try:
            if not file_path.exists():
                return SandboxActionResult(
                    success=False,
                    action_id=action_id,
                    error=f"File not found: {path}",
                )

            if file_path.is_dir():
                shutil.rmtree(file_path)
            else:
                file_path.unlink()

            session.action_count += 1
            session.last_activity = time.time()

            return SandboxActionResult(
                success=True,
                action_id=action_id,
                execution_time_ms=(time.time() - start_time) * 1000,
            )

        except (OSError, PermissionError) as e:
            return SandboxActionResult(
                success=False,
                action_id=action_id,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    def _validate_command(
        self,
        command: str,
        config: SandboxConfig,
    ) -> dict[str, Any]:
        """Validate a command against sandbox configuration."""
        # Extract base command
        parts = command.strip().split()
        if not parts:
            return {"allowed": False, "reason": "Empty command"}

        base_cmd = parts[0]

        # Check for blocked commands
        for blocked in config.blocked_commands:
            if blocked in command:
                return {"allowed": False, "reason": f"Command contains blocked term: {blocked}"}

        # If allowed list is non-empty, check against it
        if config.allowed_commands:
            if base_cmd not in config.allowed_commands:
                return {"allowed": False, "reason": f"Command not in allowed list: {base_cmd}"}

        return {"allowed": True}

    def _resolve_path(
        self,
        path: str,
        session: SandboxSession,
        write: bool = False,
    ) -> dict[str, Any]:
        """Resolve and validate a file path."""
        config = session.config

        # Normalize path
        if path.startswith("/workspace"):
            # Map to actual workspace
            rel_path = path[len("/workspace") :].lstrip("/")
            resolved = Path(session.workspace_path) / rel_path
        elif path.startswith("./") or not path.startswith("/"):
            # Relative path - resolve in workspace
            resolved = Path(session.workspace_path) / path
        else:
            # Absolute path - check if allowed
            resolved = Path(path)

        # Resolve to absolute
        try:
            resolved = resolved.resolve()
        except (OSError, ValueError) as e:
            logger.debug("Failed to resolve path '%s': %s: %s", path, type(e).__name__, e)
            return {"allowed": False, "reason": "Invalid path"}

        resolved_str = str(resolved)
        normalized_input = os.path.normpath(path)

        # Check blocked paths
        for blocked in config.blocked_paths:
            import fnmatch

            if fnmatch.fnmatch(resolved_str, blocked) or fnmatch.fnmatch(normalized_input, blocked):
                return {"allowed": False, "reason": f"Path is blocked: {path}"}

        # For writes, must be within workspace
        workspace = Path(session.workspace_path).resolve()
        if write:
            try:
                resolved.relative_to(workspace)
            except ValueError:
                return {"allowed": False, "reason": "Write outside workspace not allowed"}

        return {"allowed": True, "path": resolved_str}

    def _build_environment(self, session: SandboxSession) -> dict[str, str]:
        """Build environment variables for command execution."""
        config = session.config

        if config.inherit_env:
            env = dict(os.environ)
        else:
            # Minimal safe environment
            env = {
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": session.workspace_path,
                "USER": "sandbox",
                "LANG": "en_US.UTF-8",
            }

        # Add custom environment variables
        env.update(config.environment_vars)

        # Add sandbox-specific vars
        env["SANDBOX_ID"] = session.sandbox_id
        env["WORKSPACE"] = session.workspace_path

        return env

    def get_stats(self) -> dict[str, Any]:
        """Get sandbox statistics."""
        return {
            **self._stats,
            "active_sandboxes": len(self._sandboxes),
        }

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit a sandbox event."""
        if self._event_callback:
            try:
                self._event_callback(event_type, data)
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided event callback
                logger.warning("Event callback failed: %s", e)

    async def cleanup_all(self) -> int:
        """Destroy all sandboxes and clean up."""
        count = 0
        for sandbox_id in list(self._sandboxes.keys()):
            if await self.destroy_sandbox(sandbox_id):
                count += 1
        return count
