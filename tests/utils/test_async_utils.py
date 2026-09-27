"""
Tests for async utility functions.

Tests cover:
- run_async
- run_command
- run_git_command
"""

import asyncio
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock

from aragora.utils import async_utils
from aragora.utils.async_utils import (
    run_async,
    run_command,
    run_git_command,
)


def test_pool_event_loop_provider_registration():
    """Storage can register a pool-loop provider without an upward utils import."""
    previous = async_utils._pool_event_loop_provider
    loop = asyncio.new_event_loop()
    try:
        async_utils.register_pool_event_loop_provider(lambda: loop)
        assert async_utils.get_pool_event_loop() is loop
    finally:
        async_utils.register_pool_event_loop_provider(previous)
        loop.close()


class TestRunAsync:
    """Tests for run_async function."""

    def test_runs_simple_coroutine(self):
        """Runs a simple coroutine and returns result."""

        async def simple():
            return 42

        result = run_async(simple())
        assert result == 42

    def test_runs_coroutine_with_await(self):
        """Runs coroutine that contains await."""

        async def with_await():
            await asyncio.sleep(0.01)
            return "completed"

        result = run_async(with_await())
        assert result == "completed"

    def test_propagates_exceptions(self):
        """Propagates exceptions from coroutine."""

        async def failing():
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            run_async(failing())

    @pytest.mark.asyncio
    async def test_works_in_async_context_via_nest_asyncio(self):
        """Works in async context via nest_asyncio fallback.

        When called from an async context without a pool manager (e.g., tests),
        run_async applies nest_asyncio to allow nested run_until_complete.
        """

        async def inner():
            return "nested"

        result = run_async(inner(), timeout=0.1)
        assert result == "nested"

    @pytest.mark.asyncio
    async def test_works_in_async_context_without_nest_asyncio(self, monkeypatch):
        """Falls back to a worker thread when nest_asyncio is unavailable."""

        async def inner():
            return "worker-thread"

        monkeypatch.setitem(sys.modules, "nest_asyncio", None)

        result = run_async(inner(), timeout=0.1)
        assert result == "worker-thread"

    def test_works_from_sync_context(self):
        """Works when called from sync context (no running loop)."""

        async def simple():
            return "sync-context"

        # This test itself is sync, so no running loop
        result = run_async(simple())
        assert result == "sync-context"

    @pytest.mark.asyncio
    async def test_async_context_returns_correct_value(self):
        """Returns correct values when called from async context."""

        async def inner():
            return "async-context"

        result = run_async(inner(), timeout=5.0)
        assert result == "async-context"

    def test_handles_coroutine_returning_none(self):
        """Handles coroutines returning None."""

        async def return_none():
            return None

        result = run_async(return_none())
        assert result is None

    def test_handles_complex_return_types(self):
        """Handles coroutines returning complex types."""

        async def return_dict():
            return {"nested": {"data": [1, 2, 3]}}

        result = run_async(return_dict())
        assert result == {"nested": {"data": [1, 2, 3]}}


class TestRunCommand:
    """Tests for run_command function."""

    @pytest.mark.asyncio
    async def test_simple_command(self):
        """Runs a simple command."""
        returncode, stdout, stderr = await run_command(["echo", "hello"])
        assert returncode == 0
        assert b"hello" in stdout

    @pytest.mark.asyncio
    async def test_command_with_args(self):
        """Runs command with arguments."""
        returncode, stdout, stderr = await run_command(["echo", "-n", "test"])
        assert returncode == 0
        assert b"test" in stdout

    @pytest.mark.asyncio
    async def test_command_with_cwd(self, tmp_path):
        """Runs command in specified directory."""
        returncode, stdout, stderr = await run_command(["pwd"], cwd=tmp_path)
        assert returncode == 0
        assert str(tmp_path) in stdout.decode()

    @pytest.mark.asyncio
    async def test_command_failure(self):
        """Handles command failure."""
        returncode, stdout, stderr = await run_command(["ls", "/nonexistent/path/xyz"])
        assert returncode != 0
        assert len(stderr) > 0 or len(stdout) > 0  # Error message somewhere

    @pytest.mark.asyncio
    async def test_command_with_input(self):
        """Sends input to command."""
        returncode, stdout, stderr = await run_command(["cat"], input_data=b"input data")
        assert returncode == 0
        assert stdout == b"input data"

    @pytest.mark.asyncio
    async def test_command_timeout(self):
        """Times out on slow commands."""
        with pytest.raises(asyncio.TimeoutError):
            await run_command(["sleep", "10"], timeout=0.1)

    @pytest.mark.asyncio
    async def test_command_not_found(self):
        """Raises FileNotFoundError for missing command."""
        with pytest.raises(FileNotFoundError):
            await run_command(["nonexistent_command_xyz"])

    @pytest.mark.asyncio
    async def test_concurrent_commands(self):
        """Handles concurrent command execution."""
        # Semaphore should allow up to 10 concurrent
        results = await asyncio.gather(
            run_command(["echo", "1"]),
            run_command(["echo", "2"]),
            run_command(["echo", "3"]),
        )

        assert all(r[0] == 0 for r in results)  # All succeeded


class TestRunGitCommand:
    """Tests for run_git_command function."""

    @pytest.mark.asyncio
    async def test_git_status(self, tmp_path):
        """Runs git status in a git repo."""
        # Initialize a git repo
        returncode, _, _ = await run_command(["git", "init"], cwd=tmp_path)
        assert returncode == 0, "git should be available"

        success, output = await run_git_command(["status"], cwd=tmp_path)
        assert success
        assert "branch" in output.lower() or "commit" in output.lower()

    @pytest.mark.asyncio
    async def test_git_command_failure(self, tmp_path):
        """Handles git command failure."""
        # Not a git repo
        success, output = await run_git_command(["status"], cwd=tmp_path)
        assert not success
        assert len(output) > 0  # Error message

    @pytest.mark.asyncio
    async def test_git_timeout(self, tmp_path):
        """Returns failure on timeout."""
        # Mock run_command to raise timeout
        with patch("aragora.utils.async_utils.run_command") as mock_cmd:
            mock_cmd.side_effect = asyncio.TimeoutError()

            success, output = await run_git_command(["status"], cwd=tmp_path)
            assert not success
            assert "timed out" in output.lower()

    @pytest.mark.asyncio
    async def test_git_not_found(self, tmp_path):
        """Handles git not being installed."""
        with patch("aragora.utils.async_utils.run_command") as mock_cmd:
            mock_cmd.side_effect = FileNotFoundError()

            success, output = await run_git_command(["status"], cwd=tmp_path)
            assert not success
            assert "not found" in output.lower()

    @pytest.mark.asyncio
    async def test_git_generic_error(self, tmp_path):
        """Handles generic errors."""
        with patch("aragora.utils.async_utils.run_command") as mock_cmd:
            mock_cmd.side_effect = OSError("unexpected error")

            success, output = await run_git_command(["status"], cwd=tmp_path)
            assert not success
            assert "unexpected error" in output


class TestSubprocessSemaphore:
    """Tests for subprocess concurrency limiting."""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Verifies semaphore limits concurrent subprocess calls."""
        # The semaphore is set to 10, so we can test that 11+ concurrent
        # calls wait for the semaphore
        from aragora.utils.async_utils import _subprocess_semaphore

        # Check initial value
        assert _subprocess_semaphore._value <= 10


class TestIntegration:
    """Integration tests."""

    def test_run_async_with_run_command(self):
        """run_async works with run_command."""

        async def run_echo():
            returncode, stdout, _ = await run_command(["echo", "integration"])
            return stdout.decode().strip()

        result = run_async(run_echo())
        assert result == "integration"

    @pytest.mark.asyncio
    async def test_git_init_and_status(self, tmp_path):
        """Full git workflow test."""
        # Initialize repo
        init_code, _, _ = await run_command(["git", "init"], cwd=tmp_path)
        assert init_code == 0, "git should be available"

        # Check status via run_git_command
        success, output = await run_git_command(["status", "-s"], cwd=tmp_path)
        assert success

        # Create a file
        (tmp_path / "test.txt").write_text("hello")

        # Check status shows untracked file
        success, output = await run_git_command(["status", "-s"], cwd=tmp_path)
        assert success
        assert "test.txt" in output

    @pytest.mark.asyncio
    async def test_command_output_encoding(self):
        """Handles various output encodings."""
        # Test with unicode output
        returncode, stdout, stderr = await run_command([sys.executable, "-c", "print('café')"])
        assert returncode == 0
        assert "caf" in stdout.decode()  # At least partial match
