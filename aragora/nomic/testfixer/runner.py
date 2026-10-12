"""
TestRunner - Execute tests and capture failures.

Runs test commands and parses output to extract:
- Which tests failed
- The error messages and stack traces
- Which files are involved
- Timing information
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TestFramework(str, Enum):
    """Supported test frameworks."""

    PYTEST = "pytest"
    UNITTEST = "unittest"
    JEST = "jest"
    MOCHA = "mocha"
    GO_TEST = "go_test"
    CARGO_TEST = "cargo_test"
    UNKNOWN = "unknown"


@dataclass
class TestFailure:
    """A single test failure."""

    test_name: str
    test_file: str
    error_type: str
    error_message: str
    stack_trace: str
    line_number: int | None = None
    relevant_code: str = ""
    duration_seconds: float = 0.0

    # Parsed context
    involved_files: list[str] = field(default_factory=list)
    involved_functions: list[str] = field(default_factory=list)

    def to_prompt_context(self) -> str:
        """Format failure for LLM analysis."""
        lines = [
            f"## Test Failure: {self.test_name}",
            f"File: {self.test_file}",
            f"Error Type: {self.error_type}",
            "",
            "### Error Message",
            self.error_message,
            "",
            "### Stack Trace",
            self.stack_trace,
        ]

        if self.relevant_code:
            lines.extend(
                [
                    "",
                    "### Relevant Code",
                    "```python",
                    self.relevant_code,
                    "```",
                ]
            )

        if self.involved_files:
            lines.extend(
                [
                    "",
                    "### Involved Files",
                    *[f"- {f}" for f in self.involved_files],
                ]
            )

        return "\n".join(lines)


@dataclass
class TestResult:
    """Result of a test run."""

    command: str
    exit_code: int
    stdout: str
    stderr: str

    # Parsed results
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0

    failures: list[TestFailure] = field(default_factory=list)

    duration_seconds: float = 0.0
    started_at: datetime = field(default_factory=datetime.now)
    framework: TestFramework = TestFramework.UNKNOWN
    diagnostics: RunDiagnostics | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.errors == 0

    @property
    def first_failure(self) -> TestFailure | None:
        return self.failures[0] if self.failures else None

    def summary(self) -> str:
        """Human-readable summary."""
        if self.success:
            return f"✓ All {self.total_tests} tests passed in {self.duration_seconds:.1f}s"
        else:
            return (
                f"✗ {self.failed} failed, {self.errors} errors, "
                f"{self.passed} passed of {self.total_tests} tests "
                f"in {self.duration_seconds:.1f}s"
            )


@dataclass
class RunDiagnostics:
    """Artifacts and crash classification for a test run."""

    run_dir: Path
    stdout_path: Path
    stderr_path: Path
    exit_code_path: Path
    meta_path: Path
    env_path: Path
    resource_path: Path
    kernel_log_path: Path | None = None
    classification: str | None = None
    exit_signal: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_dir": str(self.run_dir),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "exit_code_path": str(self.exit_code_path),
            "meta_path": str(self.meta_path),
            "env_path": str(self.env_path),
            "resource_path": str(self.resource_path),
            "kernel_log_path": str(self.kernel_log_path) if self.kernel_log_path else None,
            "classification": self.classification,
            "exit_signal": self.exit_signal,
            "notes": self.notes,
        }


def detect_framework(command: str) -> TestFramework:
    """Detect test framework from command."""
    cmd_lower = command.lower()

    if "pytest" in cmd_lower:
        return TestFramework.PYTEST
    elif "jest" in cmd_lower:
        return TestFramework.JEST
    elif "mocha" in cmd_lower:
        return TestFramework.MOCHA
    elif "go test" in cmd_lower:
        return TestFramework.GO_TEST
    elif "cargo test" in cmd_lower:
        return TestFramework.CARGO_TEST
    elif "unittest" in cmd_lower or "python -m unittest" in cmd_lower:
        return TestFramework.UNITTEST

    return TestFramework.UNKNOWN


def _safe_write_text(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("test.run.write_failed path=%s error=%s", path, exc)


def _safe_write_json(path: Path, payload: dict[str, Any]) -> None:
    _safe_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _run_command(command: list[str], cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(  # subprocess with fixed args, no shell
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        logger.debug("Command failed: %s", command, exc_info=True)
        return None


def _get_git_head(repo_path: Path) -> str | None:
    return _run_command(["git", "rev-parse", "HEAD"], cwd=repo_path)


def _collect_env_snapshot(
    *,
    repo_path: Path,
    command: str,
    run_id: str,
    framework: TestFramework,
    env: dict[str, str],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "command": command,
        "repo_path": str(repo_path),
        "framework": framework.value,
        "python": sys.version,
        "platform": platform.platform(),
        "cwd": str(repo_path),
        "git_head": _get_git_head(repo_path),
        "env_keys": sorted(env.keys()),
    }


def _collect_resource_snapshot(repo_path: Path) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    try:
        snapshot["load_avg"] = os.getloadavg()
    except (AttributeError, OSError):
        snapshot["load_avg"] = None

    try:
        disk = shutil.disk_usage(repo_path)
        snapshot["disk"] = {
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
        }
    except OSError:
        snapshot["disk"] = None

    meminfo_path = Path("/proc/meminfo")
    if meminfo_path.exists():
        meminfo: dict[str, int] = {}
        try:
            for line in meminfo_path.read_text(encoding="utf-8").splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    parts = value.strip().split()
                    if parts:
                        try:
                            meminfo[key] = int(parts[0])
                        except ValueError:
                            continue
            snapshot["meminfo_kb"] = meminfo
        except OSError:
            snapshot["meminfo_kb"] = None
    else:
        snapshot["meminfo_kb"] = None

    return snapshot


def _collect_kernel_log() -> str | None:
    if os.name != "posix":
        return None
    for command in (["dmesg", "-T"], ["journalctl", "-k", "-n", "200"]):
        output = _run_command(command)
        if output:
            return "\n".join(output.splitlines()[-200:])
    return None


def _signal_name_from_exit(exit_code: int) -> str | None:
    try:
        if exit_code < 0:
            sig = -exit_code
        elif exit_code >= 128:
            sig = exit_code - 128
        else:
            return None
        return signal.Signals(sig).name
    except (ValueError, AttributeError):
        logger.debug("Failed to map exit code %d to signal name", exit_code)
        return None


def _classify_exit(
    *,
    exit_code: int,
    stdout: str,
    stderr: str,
    kernel_log: str | None,
    timed_out: bool,
) -> tuple[str | None, str | None, list[str]]:
    notes: list[str] = []
    if timed_out:
        return "timeout", None, notes
    if exit_code == 0:
        return "success", None, notes

    combined = f"{stdout}\n{stderr}"
    exit_signal = _signal_name_from_exit(exit_code)

    if exit_signal:
        notes.append(f"exit_signal={exit_signal}")

    if exit_code in (137, -9) or exit_signal == "SIGKILL":
        if kernel_log and re.search(r"Out of memory|Killed process", kernel_log, re.IGNORECASE):
            return "oom_kill", exit_signal, notes
        if "Killed" in combined:
            return "killed", exit_signal, notes

    if exit_code in (139, -11) or "Segmentation fault" in combined:
        return "segfault", exit_signal, notes

    if not stdout.strip() and not stderr.strip():
        return "empty_output", exit_signal, notes

    if re.search(r"\bFAILED\b|\bERROR\b", combined):
        return "test_failures", exit_signal, notes

    return "nonzero_exit", exit_signal, notes


def parse_pytest_output(stdout: str, stderr: str) -> tuple[dict[str, int], list[TestFailure]]:
    """Parse pytest output to extract failures."""
    stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    failures = []

    combined = stdout + "\n" + stderr

    # More comprehensive summary parsing
    for match in re.finditer(
        r"(\d+) (failed|passed|error|skipped|warning)", combined, re.IGNORECASE
    ):
        count = int(match.group(1))
        status = match.group(2).lower()
        if status == "passed":
            stats["passed"] = count
        elif status == "failed":
            stats["failed"] = count
        elif status == "error":
            stats["errors"] = count
        elif status == "skipped":
            stats["skipped"] = count

    stats["total"] = stats["passed"] + stats["failed"] + stats["errors"] + stats["skipped"]

    # Parse FAILED lines like "FAILED tests/foo/test_bar.py::TestClass::test_method"
    failed_pattern = re.compile(r"FAILED\s+([^\s:]+)::([^\s]+)")
    for match in failed_pattern.finditer(combined):
        test_file = match.group(1)
        test_name = match.group(2)

        # Try to extract error details from the failure block
        error_type = "AssertionError"
        error_message = ""
        stack_trace = ""

        # Look for the failure block
        failure_block_pattern = re.compile(
            rf"_{(2,)}\s+{re.escape(test_name)}\s+_{(2,)}(.*?)(?=_{(2,)}|\Z)", re.DOTALL
        )
        block_match = failure_block_pattern.search(combined)
        if block_match:
            block = block_match.group(1)

            # Extract error type and message
            error_line_match = re.search(r"([\w.]+Error|[\w.]+Exception):\s*(.+?)(?:\n|$)", block)
            if error_line_match:
                error_type = error_line_match.group(1)
                error_message = error_line_match.group(2).strip()

            stack_trace = block.strip()

        failures.append(
            TestFailure(
                test_name=test_name,
                test_file=test_file,
                error_type=error_type,
                error_message=error_message,
                stack_trace=stack_trace,
            )
        )

    # Parse collection errors like "ERROR collecting tests/foo/test_bar.py"
    collect_pattern = re.compile(r"_+ ERROR collecting (.*?) _+", re.DOTALL)
    collect_matches = list(collect_pattern.finditer(combined))
    for idx, match in enumerate(collect_matches):
        test_file = match.group(1).strip()
        block_start = match.end()
        block_end = collect_matches[idx + 1].start() if idx + 1 < len(collect_matches) else None
        block = combined[block_start:block_end].strip()

        error_type = "ImportError"
        error_message = ""
        # Pytest collection errors typically have lines prefixed with "E"
        error_line_match = re.search(
            r"^E\s+([\w.]+Error|[\w.]+Exception):\s*(.+)$", block, re.MULTILINE
        )
        if error_line_match:
            error_type = error_line_match.group(1)
            error_message = error_line_match.group(2).strip()
        else:
            # Fallback to the first non-empty line that looks like an error
            alt_match = re.search(r"([\w.]+Error|[\w.]+Exception):\s*(.+)", block)
            if alt_match:
                error_type = alt_match.group(1)
                error_message = alt_match.group(2).strip()

        failures.append(
            TestFailure(
                test_name=f"collection_error::{test_file}",
                test_file=test_file,
                error_type=error_type,
                error_message=error_message or "Test collection failed",
                stack_trace=block,
            )
        )

    # Also check for short test summary info
    short_summary_match = re.search(
        r"=+ short test summary info =+(.*?)(?==+|\Z)", combined, re.DOTALL
    )
    if short_summary_match and not failures:
        summary_block = short_summary_match.group(1)
        for line in summary_block.strip().split("\n"):
            if line.startswith("FAILED"):
                parts = line.replace("FAILED ", "").split("::")
                if len(parts) >= 2:
                    test_file = parts[0]
                    test_name = "::".join(parts[1:]).split(" - ")[0]

                    error_message = ""
                    if " - " in line:
                        error_message = line.split(" - ", 1)[1]

                    failures.append(
                        TestFailure(
                            test_name=test_name,
                            test_file=test_file,
                            error_type="TestFailure",
                            error_message=error_message,
                            stack_trace="",
                        )
                    )

    # Backfill missing error details from combined output
    if failures:
        error_lines = re.findall(r"([\w.]+Error|[\w.]+Exception):\s*(.+)", combined)
        if error_lines:
            last_error_type, last_error_msg = error_lines[-1]
            for failure in failures:
                if not failure.error_message:
                    failure.error_type = last_error_type
                    failure.error_message = last_error_msg.strip()
                if not failure.stack_trace:
                    failure.stack_trace = combined

    return stats, failures


def extract_involved_files(failure: TestFailure, repo_path: Path) -> list[str]:
    """Extract files mentioned in stack trace."""
    files = set()

    # Look for file paths in stack trace
    file_pattern = re.compile(r'File "([^"]+)"')
    for match in file_pattern.finditer(failure.stack_trace):
        filepath = match.group(1)
        # Filter to repo files
        try:
            rel_path = Path(filepath).relative_to(repo_path)
            files.add(str(rel_path))
        except ValueError as e:
            logger.debug("extract involved files encountered an error: %s", e)

    # Also capture pytest-style paths like "pkg/module.py:123: in ..."
    inline_pattern = re.compile(r"^([^\s].*?\.py):\d+:", re.MULTILINE)
    for match in inline_pattern.finditer(failure.stack_trace):
        filepath = match.group(1)
        try:
            rel_path = Path(filepath).relative_to(repo_path)
            files.add(str(rel_path))
        except ValueError:
            # If already relative
            if not Path(filepath).is_absolute():
                files.add(filepath)

    # Add the test file itself
    files.add(failure.test_file)

    return list(files)


class TestRunner:
    """Runs tests and captures failures.

    Example:
        runner = TestRunner(
            repo_path=Path("/path/to/repo"),
            test_command="pytest tests/ -q --maxfail=1",
        )

        result = await runner.run()

        if not result.success:
            for failure in result.failures:
                print(f"Failed: {failure.test_name}")
                print(f"  {failure.error_message}")
    """

    def __init__(
        self,
        repo_path: Path,
        test_command: str,
        timeout_seconds: float = 300.0,
        env: dict[str, str] | None = None,
        run_id: str | None = None,
        artifacts_dir: Path | None = None,
        enable_diagnostics: bool = True,
    ):
        """Initialize the runner.

        Args:
            repo_path: Path to repository root
            test_command: Command to run tests
            timeout_seconds: Timeout for test execution
            env: Environment variables for test process
        """
        self.repo_path = Path(repo_path)
        self.test_command = test_command
        self.timeout = timeout_seconds
        self.env = env
        self.run_id = run_id
        self.artifacts_dir = artifacts_dir
        self.enable_diagnostics = enable_diagnostics
        self.framework = detect_framework(test_command)

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self.env:
            env.update(self.env)
        if self.enable_diagnostics:
            env.setdefault("PYTHONFAULTHANDLER", "1")
            env.setdefault("PYTHONASYNCIODEBUG", "1")
            env.setdefault("PYTHONHASHSEED", "0")
        return env

    def _prepare_run_dir(self, started_at: datetime) -> tuple[str, Path]:
        run_id = self.run_id or uuid.uuid4().hex
        root = self.artifacts_dir or (self.repo_path / ".testfixer" / "runs")
        ts = started_at.strftime("%Y%m%d_%H%M%S")
        head = _get_git_head(self.repo_path)
        suffix = head[:7] if head else "nogit"
        run_dir = root / f"{ts}_{run_id[:8]}_{suffix}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_id, run_dir

    async def run(self) -> TestResult:
        """Run tests and return parsed results.

        Returns:
            TestResult with parsed failures
        """
        start_time = time.time()
        started_at = datetime.now()
        run_id, run_dir = self._prepare_run_dir(started_at)
        env = self._build_env()
        env_snapshot = _collect_env_snapshot(
            repo_path=self.repo_path,
            command=self.test_command,
            run_id=run_id,
            framework=self.framework,
            env=env,
        )
        resource_snapshot = _collect_resource_snapshot(self.repo_path)

        stdout_path = run_dir / "stdout.log"
        stderr_path = run_dir / "stderr.log"
        exit_code_path = run_dir / "exit.code"
        meta_path = run_dir / "run.json"
        env_path = run_dir / "env.json"
        resource_path = run_dir / "resources.json"

        diagnostics = RunDiagnostics(
            run_dir=run_dir,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            exit_code_path=exit_code_path,
            meta_path=meta_path,
            env_path=env_path,
            resource_path=resource_path,
        )

        _safe_write_json(env_path, env_snapshot)
        _safe_write_json(resource_path, resource_snapshot)
        _safe_write_json(
            meta_path,
            {
                "run_id": run_id,
                "command": self.test_command,
                "cwd": str(self.repo_path),
                "framework": self.framework.value,
                "started_at": started_at.isoformat(),
            },
        )

        logger.info(
            "test.run.start run_id=%s command=%s cwd=%s timeout=%s framework=%s run_dir=%s",
            run_id,
            self.test_command,
            self.repo_path,
            self.timeout,
            self.framework.value,
            run_dir,
        )
        logger.debug("test.run.env_keys=%s", sorted(env.keys()))

        stdout = ""
        stderr = ""
        exit_code = -1
        timed_out = False
        execution_error: Exception | None = None
        process_pid: int | None = None

        try:
            # Run the test command
            process = await asyncio.create_subprocess_shell(
                self.test_command,
                cwd=self.repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            process_pid = process.pid
            _safe_write_json(
                meta_path,
                {
                    "run_id": run_id,
                    "command": self.test_command,
                    "cwd": str(self.repo_path),
                    "framework": self.framework.value,
                    "started_at": started_at.isoformat(),
                    "pid": process_pid,
                },
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                process.kill()
                await process.wait()
                logger.error(
                    "test.run.timeout run_id=%s command=%s timeout=%s",
                    run_id,
                    self.test_command,
                    self.timeout,
                )
                stdout_bytes = b""
                stderr_bytes = f"Test execution timed out after {self.timeout}s".encode()
                exit_code = -1
            else:
                exit_code = process.returncode if process.returncode is not None else 0

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            logger.info(
                "test.run.complete run_id=%s exit_code=%s duration=%.2fs stdout_bytes=%s stderr_bytes=%s",
                run_id,
                exit_code,
                time.time() - start_time,
                len(stdout_bytes),
                len(stderr_bytes),
            )
            if exit_code != 0:
                logger.debug("test.run.stdout_tail=%s", stdout[-800:])
                logger.debug("test.run.stderr_tail=%s", stderr[-800:])

        except (OSError, subprocess.SubprocessError) as e:
            execution_error = e
            logger.warning("test.run.execution_error run_id=%s: %s", run_id, e)
            stderr = f"Test execution failed: {type(e).__name__}"
            stdout = ""
            exit_code = -1

        duration = time.time() - start_time

        _safe_write_text(stdout_path, stdout)
        _safe_write_text(stderr_path, stderr)
        _safe_write_text(exit_code_path, str(exit_code))

        kernel_log = _collect_kernel_log()
        if kernel_log:
            kernel_path = run_dir / "kernel.log"
            _safe_write_text(kernel_path, kernel_log)
            diagnostics.kernel_log_path = kernel_path

        classification, exit_signal, notes = _classify_exit(
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            kernel_log=kernel_log,
            timed_out=timed_out,
        )
        diagnostics.classification = classification
        diagnostics.exit_signal = exit_signal
        diagnostics.notes.extend(notes)

        _safe_write_json(
            meta_path,
            {
                "run_id": run_id,
                "command": self.test_command,
                "cwd": str(self.repo_path),
                "framework": self.framework.value,
                "started_at": started_at.isoformat(),
                "finished_at": datetime.now().isoformat(),
                "pid": process_pid,
                "exit_code": exit_code,
                "classification": classification,
                "exit_signal": exit_signal,
            },
        )

        # Parse output based on framework
        if timed_out:
            stats = {"total": 0, "passed": 0, "failed": 1, "skipped": 0, "errors": 0}
            failures = [
                TestFailure(
                    test_name="timeout",
                    test_file="",
                    error_type="TimeoutError",
                    error_message=f"Tests did not complete within {self.timeout}s",
                    stack_trace="",
                )
            ]
        elif execution_error is not None:
            stats = {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 1}
            failures = [
                TestFailure(
                    test_name="execution_error",
                    test_file="",
                    error_type=type(execution_error).__name__,
                    error_message=str(execution_error),
                    stack_trace="",
                )
            ]
        elif self.framework == TestFramework.PYTEST:
            stats, failures = parse_pytest_output(stdout, stderr)
        else:
            # Fallback: just check exit code
            stats = {
                "total": 0,
                "passed": 0 if exit_code != 0 else 1,
                "failed": 1 if exit_code != 0 else 0,
                "skipped": 0,
                "errors": 0,
            }
            failures = []
            if exit_code != 0:
                failures.append(
                    TestFailure(
                        test_name="unknown",
                        test_file="",
                        error_type="TestFailure",
                        error_message=f"Tests exited with code {exit_code}",
                        stack_trace=stdout + "\n" + stderr,
                    )
                )

        # Enrich failures with file information
        for failure in failures:
            failure.involved_files = extract_involved_files(failure, self.repo_path)

        logger.info(
            "test.run.parsed total=%s passed=%s failed=%s errors=%s skipped=%s failures=%s",
            stats["total"],
            stats["passed"],
            stats["failed"],
            stats["errors"],
            stats["skipped"],
            len(failures),
        )
        if failures:
            first = failures[0]
            logger.info(
                "test.run.first_failure test=%s file=%s error_type=%s",
                first.test_name,
                first.test_file,
                first.error_type,
            )

        return TestResult(
            command=self.test_command,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            total_tests=stats["total"],
            passed=stats["passed"],
            failed=stats["failed"],
            skipped=stats["skipped"],
            errors=stats["errors"],
            failures=failures,
            duration_seconds=duration,
            started_at=started_at,
            framework=self.framework,
            diagnostics=diagnostics,
        )

    async def run_full(self, override_command: str | None = None) -> TestResult:
        """Run tests collecting ALL failures (strips --maxfail).

        Args:
            override_command: Optional full-suite test command. If not
                provided, the configured test_command is used with
                --maxfail stripped.

        Returns:
            TestResult with all failures collected.
        """
        command = override_command or self._strip_maxfail(self.test_command)
        runner = TestRunner(
            repo_path=self.repo_path,
            test_command=command,
            timeout_seconds=self.timeout,
            env=self.env,
            run_id=self.run_id,
            artifacts_dir=self.artifacts_dir,
            enable_diagnostics=self.enable_diagnostics,
        )
        return await runner.run()

    @staticmethod
    def _strip_maxfail(command: str) -> str:
        """Remove --maxfail flag from a test command."""
        return re.sub(r"\s*--maxfail=?\s*\d*", "", command).strip()

    async def run_single_test(self, test_id: str) -> TestResult:
        """Run a single specific test.

        Args:
            test_id: Test identifier (e.g., "tests/foo.py::test_bar")

        Returns:
            TestResult for the single test
        """
        if self.framework == TestFramework.PYTEST:
            command = f"pytest {test_id} -v"
        else:
            command = f"{self.test_command} {test_id}"

        runner = TestRunner(
            repo_path=self.repo_path,
            test_command=command,
            timeout_seconds=self.timeout,
            env=self.env,
            run_id=self.run_id,
            artifacts_dir=self.artifacts_dir,
            enable_diagnostics=self.enable_diagnostics,
        )
        return await runner.run()
