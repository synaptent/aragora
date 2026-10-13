"""
Subprocess sandboxing utility.

Provides secure subprocess execution with command allowlisting and timeout enforcement.
All subprocess calls should use this utility to ensure consistent security policies.

Usage:
    from aragora.utils.subprocess_runner import run_sandboxed, SandboxedCommand

    # Run a git command
    result = await run_sandboxed(["git", "status"], cwd="/path/to/repo")

    # Run with custom timeout
    result = await run_sandboxed(["ffprobe", "-v", "error", "file.mp3"], timeout=60)

    # Check if a command would be allowed
    allowed, reason = SandboxedCommand.validate(["rm", "-rf", "/"])  # False, "rm not allowed"
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Sequence

logger = logging.getLogger(__name__)

# Command allowlist with permitted subcommands
# Format: command_name -> list of allowed subcommands (None means all subcommands allowed)
ALLOWED_COMMANDS: dict[str, list[str] | None] = {
    # Version control
    "git": [
        "rev-parse",
        "diff",
        "status",
        "checkout",
        "add",
        "commit",
        "push",
        "pull",
        "branch",
        "log",
        "show",
        "fetch",
        "merge",
        "rebase",
        "stash",
        "reset",
        "clone",
        "init",
        "remote",
        "tag",
        "config",
        "ls-files",
        "describe",
    ],
    "gh": [
        "auth",
        "api",
        "pr",
        "issue",
        "repo",
        "release",
        "gist",
        "workflow",
    ],
    # Build and test tools
    "pytest": None,  # All subcommands allowed
    "python": ["-m", "-c", "--version"],  # Only these flags
    "black": None,
    "isort": None,
    "mypy": None,
    "ruff": None,
    "pip": ["install", "list", "show", "freeze", "--version"],
    "npm": ["install", "run", "test", "build", "ci", "audit", "--version"],
    "node": ["--version"],
    # Media processing (sandboxed to specific flags)
    "ffmpeg": None,  # Complex enough to allow all flags
    "ffprobe": None,
    # Formal verification
    "lean": ["--version", "--run", "--print-prefix"],
    "z3": ["--version"],
    # System info (read-only)
    "which": None,
    "uname": None,
    "whoami": None,
    "hostname": None,
    "date": None,
    "pwd": None,
    "ls": None,  # Allow listing directories
    "cat": None,  # Allow reading files (but prefer Read tool)
    "head": None,
    "tail": None,
    "wc": None,
}

# Commands that should never be allowed regardless of subcommand
BLOCKED_COMMANDS: frozenset[str] = frozenset(
    {
        "rm",
        "rmdir",
        "mv",
        "cp",
        "chmod",
        "chown",
        "chgrp",
        "kill",
        "pkill",
        "killall",
        "sudo",
        "su",
        "doas",
        "curl",
        "wget",  # Use WebFetch tool instead
        "ssh",
        "scp",
        "rsync",
        "docker",
        "podman",
        "systemctl",
        "service",
        "mount",
        "umount",
        "dd",
        "mkfs",
        "fdisk",
        "iptables",
        "ufw",
        "passwd",
        "useradd",
        "userdel",
        "reboot",
        "shutdown",
        "halt",
        "eval",
        "exec",
        "source",
    }
)

# Default timeout in seconds
DEFAULT_TIMEOUT: float = 30.0

# Maximum timeout allowed
MAX_TIMEOUT: float = 600.0


@dataclass
class SandboxedResult:
    """Result from a sandboxed subprocess execution."""

    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    timed_out: bool = False

    @property
    def success(self) -> bool:
        """Check if command succeeded (returncode 0)."""
        return self.returncode == 0


class SandboxError(Exception):
    """Raised when a command fails sandbox validation."""

    pass


class SandboxedCommand:
    """Validates and executes sandboxed commands."""

    @staticmethod
    def validate(cmd: Sequence[str]) -> tuple[bool, str]:
        """
        Validate a command against the allowlist.

        Args:
            cmd: Command and arguments as a sequence

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        if not cmd:
            return False, "Empty command"

        command = cmd[0]

        # Get base command name (handle full paths)
        base_command = Path(command).name

        # Check blocked list first
        if base_command in BLOCKED_COMMANDS:
            return False, f"Command '{base_command}' is blocked for security reasons"

        # Check allowlist
        if base_command not in ALLOWED_COMMANDS:
            return False, f"Command '{base_command}' is not in the allowlist"

        # Check subcommand restrictions
        allowed_subcommands = ALLOWED_COMMANDS[base_command]
        if allowed_subcommands is not None and len(cmd) > 1:
            subcommand = cmd[1]
            # Skip flag validation for flags starting with -
            if not subcommand.startswith("-"):
                if subcommand not in allowed_subcommands:
                    return False, f"Subcommand '{subcommand}' not allowed for '{base_command}'"

        # Check for shell metacharacters that could indicate injection
        for arg in cmd:
            if any(c in arg for c in [";", "|", "&", "`", "$", "(", ")", "<", ">"]):
                # Allow these in certain contexts (e.g., git commit messages in quotes)
                if base_command not in {"git", "gh"} or cmd[1] not in {"commit", "pr"}:
                    return False, f"Shell metacharacter detected in argument: {arg[:50]}"

        return True, "Command allowed"

    @staticmethod
    def sanitize_env() -> dict[str, str]:
        """
        Create a sanitized environment for subprocess execution.

        Preserves necessary environment variables while removing potentially
        dangerous ones.
        """
        # Start with a minimal environment
        safe_env = {}

        # Variables to preserve
        preserve_vars = {
            "PATH",
            "HOME",
            "USER",
            "LANG",
            "LC_ALL",
            "TERM",
            "SHELL",
            "TMPDIR",
            "TMP",
            "TEMP",
            # Python-related
            "PYTHONPATH",
            "VIRTUAL_ENV",
            "CONDA_DEFAULT_ENV",
            # API keys (needed for some tools)
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GITHUB_TOKEN",
            "OPENROUTER_API_KEY",
            "MISTRAL_API_KEY",
            # Git-related
            "GIT_AUTHOR_NAME",
            "GIT_AUTHOR_EMAIL",
            "GIT_COMMITTER_NAME",
            "GIT_COMMITTER_EMAIL",
            # Node-related
            "NODE_PATH",
            "NPM_CONFIG_PREFIX",
        }

        for var in preserve_vars:
            if var in os.environ:
                safe_env[var] = os.environ[var]

        return safe_env


async def run_sandboxed(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    capture_output: bool = True,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_data: str | None = None,
) -> SandboxedResult:
    """
    Run a subprocess with sandboxing and validation.

    Args:
        cmd: Command and arguments
        cwd: Working directory
        timeout: Timeout in seconds (max 600)
        capture_output: Capture stdout/stderr
        check: Raise exception on non-zero return
        env: Environment variables (merged with sanitized env)
        input_data: Data to pass to stdin

    Returns:
        SandboxedResult with command output

    Raises:
        SandboxError: If command fails validation
        subprocess.CalledProcessError: If check=True and command fails
        asyncio.TimeoutError: If command times out
    """
    # Validate command
    allowed, reason = SandboxedCommand.validate(cmd)
    if not allowed:
        logger.warning("Blocked command: %s - %s", shlex.join(cmd), reason)
        raise SandboxError(reason)

    # Clamp timeout
    timeout = min(timeout, MAX_TIMEOUT)

    # Build environment
    exec_env = SandboxedCommand.sanitize_env()
    if env:
        exec_env.update(env)

    # Log command execution
    logger.debug("Running sandboxed: %s", shlex.join(cmd))

    # Run the command
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: subprocess.run(  # subprocess with fixed args, no shell
                    list(cmd),
                    cwd=cwd,
                    capture_output=capture_output,
                    text=True,
                    timeout=timeout,
                    shell=False,  # Never use shell=True
                    env=exec_env,
                    input=input_data,
                ),
            ),
            timeout=timeout + 5,  # Extra buffer for executor overhead
        )

        sandboxed_result = SandboxedResult(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            command=list(cmd),
        )

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return sandboxed_result

    except subprocess.TimeoutExpired as e:
        logger.warning("Command timed out after %ss: %s", timeout, shlex.join(cmd))
        stdout_val = e.stdout if hasattr(e, "stdout") else None
        stderr_val = e.stderr if hasattr(e, "stderr") else None
        return SandboxedResult(
            returncode=-1,
            stdout=stdout_val.decode() if isinstance(stdout_val, bytes) else (stdout_val or ""),
            stderr=stderr_val.decode() if isinstance(stderr_val, bytes) else (stderr_val or ""),
            command=list(cmd),
            timed_out=True,
        )
    except asyncio.TimeoutError:
        logger.warning("Async timeout for command: %s", shlex.join(cmd))
        return SandboxedResult(
            returncode=-1,
            stdout="",
            stderr="Async timeout",
            command=list(cmd),
            timed_out=True,
        )


def run_sandboxed_sync(
    cmd: Sequence[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    capture_output: bool = True,
    check: bool = False,
    env: dict[str, str] | None = None,
    input_data: str | None = None,
) -> SandboxedResult:
    """
    Synchronous version of run_sandboxed for non-async contexts.

    Args:
        cmd: Command and arguments
        cwd: Working directory
        timeout: Timeout in seconds (max 600)
        capture_output: Capture stdout/stderr
        check: Raise exception on non-zero return
        env: Environment variables (merged with sanitized env)
        input_data: Data to pass to stdin

    Returns:
        SandboxedResult with command output

    Raises:
        SandboxError: If command fails validation
        subprocess.CalledProcessError: If check=True and command fails
    """
    # Validate command
    allowed, reason = SandboxedCommand.validate(cmd)
    if not allowed:
        logger.warning("Blocked command: %s - %s", shlex.join(cmd), reason)
        raise SandboxError(reason)

    # Clamp timeout
    timeout = min(timeout, MAX_TIMEOUT)

    # Build environment
    exec_env = SandboxedCommand.sanitize_env()
    if env:
        exec_env.update(env)

    # Log command execution
    logger.debug("Running sandboxed (sync): %s", shlex.join(cmd))

    try:
        result = subprocess.run(  # subprocess with fixed args, no shell
            list(cmd),
            cwd=cwd,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            shell=False,
            env=exec_env,
            input=input_data,
        )

        sandboxed_result = SandboxedResult(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            command=list(cmd),
        )

        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )

        return sandboxed_result

    except subprocess.TimeoutExpired as e:
        logger.warning("Command timed out after %ss: %s", timeout, shlex.join(cmd))
        stdout_val = e.stdout if hasattr(e, "stdout") else None
        stderr_val = e.stderr if hasattr(e, "stderr") else None
        return SandboxedResult(
            returncode=-1,
            stdout=stdout_val.decode() if isinstance(stdout_val, bytes) else (stdout_val or ""),
            stderr=stderr_val.decode() if isinstance(stderr_val, bytes) else (stderr_val or ""),
            command=list(cmd),
            timed_out=True,
        )


__all__ = [
    "ALLOWED_COMMANDS",
    "BLOCKED_COMMANDS",
    "DEFAULT_TIMEOUT",
    "MAX_TIMEOUT",
    "SandboxedResult",
    "SandboxError",
    "SandboxedCommand",
    "run_sandboxed",
    "run_sandboxed_sync",
]
