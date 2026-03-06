"""Tests for WorkerLauncher — spawns and monitors CLI worker processes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.swarm.worker_launcher import (
    LaunchConfig,
    WorkerLauncher,
    WorkerProcess,
)


class TestWorkerProcess:
    def test_defaults(self):
        wp = WorkerProcess(
            work_order_id="wo-1",
            agent="claude",
            worktree_path="/tmp/wt",
            branch="main",
        )
        assert wp.is_running is False  # no pid
        assert wp.exit_code is None

    def test_is_running_with_pid(self):
        wp = WorkerProcess(
            work_order_id="wo-1",
            agent="codex",
            worktree_path="/tmp/wt",
            branch="main",
            pid=12345,
        )
        assert wp.is_running is True

    def test_not_running_after_exit(self):
        wp = WorkerProcess(
            work_order_id="wo-1",
            agent="claude",
            worktree_path="/tmp/wt",
            branch="main",
            pid=12345,
            exit_code=0,
        )
        assert wp.is_running is False

    def test_to_dict(self):
        wp = WorkerProcess(
            work_order_id="wo-1",
            agent="claude",
            worktree_path="/tmp/wt",
            branch="feat-x",
            pid=99,
        )
        d = wp.to_dict()
        assert d["work_order_id"] == "wo-1"
        assert d["agent"] == "claude"
        assert d["pid"] == 99
        assert d["branch"] == "feat-x"


class TestLaunchConfig:
    def test_defaults(self):
        cfg = LaunchConfig()
        assert cfg.claude_path == "claude"
        assert cfg.codex_path == "codex"
        assert cfg.timeout_seconds == 600.0
        assert cfg.auto_commit is True
        assert cfg.use_managed_session_script is True


class TestBuildPrompt:
    def test_basic_prompt(self):
        wo = {
            "title": "Fix auth module",
            "description": "The auth module has a race condition",
            "file_scope": ["aragora/auth/oidc.py"],
            "expected_tests": ["python -m pytest tests/auth/ -q"],
        }
        prompt = WorkerLauncher._build_prompt(wo)
        assert "# Task: Fix auth module" in prompt
        assert "race condition" in prompt
        assert "aragora/auth/oidc.py" in prompt
        assert "python -m pytest tests/auth/ -q" in prompt
        assert "Commit your changes" in prompt

    def test_empty_work_order(self):
        prompt = WorkerLauncher._build_prompt({})
        assert "Commit your changes" in prompt

    def test_metadata_acceptance_criteria(self):
        wo = {
            "title": "Add feature",
            "metadata": {
                "acceptance_criteria": ["All tests pass", "No regressions"],
                "constraints": ["Do not modify CLAUDE.md"],
            },
        }
        prompt = WorkerLauncher._build_prompt(wo)
        assert "All tests pass" in prompt
        assert "Do not modify CLAUDE.md" in prompt


class TestBuildCommand:
    def test_claude_command(self):
        launcher = WorkerLauncher(LaunchConfig(claude_model="claude-opus-4-6"))
        cmd = launcher._build_command("claude", "fix bug", "/tmp/wt")
        assert cmd[0] == "bash"
        assert "scripts/codex_session.sh" in cmd[1]
        assert "--session-id" not in cmd
        assert "--" in cmd
        assert "-p" in cmd
        assert "fix bug" in cmd
        assert "--yes" in cmd
        assert "--model" in cmd
        assert "claude-opus-4-6" in cmd

    def test_codex_command(self):
        launcher = WorkerLauncher(LaunchConfig(codex_model="o3"))
        cmd = launcher._build_command("codex", "fix bug", "/tmp/wt")
        assert cmd[0] == "bash"
        assert "exec" in cmd
        assert "fix bug" in cmd
        assert "--full-auto" in cmd
        assert "--model" in cmd
        assert "o3" in cmd

    def test_unknown_agent_falls_back_to_claude(self):
        launcher = WorkerLauncher()
        cmd = launcher._build_command("gpt5", "do thing", "/tmp/wt")
        assert cmd[0] == "bash"
        assert "--yes" in cmd

    def test_no_model_flag_when_none(self):
        launcher = WorkerLauncher()
        cmd = launcher._build_command("claude", "task", "/tmp/wt")
        assert "--model" not in cmd

    def test_direct_cli_command_when_session_wrapper_disabled(self):
        launcher = WorkerLauncher(LaunchConfig(use_managed_session_script=False))
        cmd = launcher._build_command("claude", "task", "/tmp/wt")
        assert cmd[0] == "claude"
        assert "-p" in cmd


class TestLaunch:
    @pytest.mark.asyncio
    async def test_launch_creates_worker(self, tmp_path: Path):
        launcher = WorkerLauncher()
        mock_proc = AsyncMock()
        mock_proc.pid = 42
        worktree = tmp_path / "wt"
        (worktree / "scripts").mkdir(parents=True)
        (worktree / "scripts" / "codex_session.sh").write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )

        wo = {"work_order_id": "wo-abc", "target_agent": "claude", "title": "Test"}

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch.object(WorkerLauncher, "_git_output", return_value=""),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        ):
            worker = await launcher.launch(wo, worktree_path=str(worktree), branch="feat")

        assert worker.work_order_id == "wo-abc"
        assert worker.agent == "claude"
        assert worker.pid == 42
        assert worker.is_running

    @pytest.mark.asyncio
    async def test_launch_raises_on_missing_cli(self):
        launcher = WorkerLauncher()
        wo = {"work_order_id": "wo-1", "target_agent": "claude"}

        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="CLI not found"):
                await launcher.launch(wo, worktree_path="/tmp/wt")


class TestWait:
    @pytest.mark.asyncio
    async def test_wait_collects_results(self):
        launcher = WorkerLauncher(LaunchConfig(auto_commit=False))

        # Set up a mock worker + process
        worker = WorkerProcess(
            work_order_id="wo-1",
            agent="claude",
            worktree_path="/tmp/wt",
            branch="main",
            pid=100,
        )
        launcher._workers["wo-1"] = worker

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output text", b""))
        mock_proc.returncode = 0
        launcher._processes["wo-1"] = mock_proc

        with patch.object(WorkerLauncher, "_collect_diff", return_value="diff --git a/file"):
            result = await launcher.wait("wo-1")

        assert result.exit_code == 0
        assert result.stdout == "output text"
        assert result.diff == "diff --git a/file"
        assert result.completed_at is not None
        assert "wo-1" not in launcher._processes

    @pytest.mark.asyncio
    async def test_wait_handles_timeout(self):
        launcher = WorkerLauncher(LaunchConfig(timeout_seconds=0.01, auto_commit=False))

        worker = WorkerProcess(
            work_order_id="wo-2",
            agent="codex",
            worktree_path="/tmp/wt",
            branch="main",
            pid=200,
        )
        launcher._workers["wo-2"] = worker

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_proc.kill = AsyncMock()
        mock_proc.wait = AsyncMock()
        launcher._processes["wo-2"] = mock_proc

        with patch.object(WorkerLauncher, "_collect_diff", return_value=""):
            result = await launcher.wait("wo-2")

        assert result.exit_code == -1
        assert "Timed out" in result.stderr
        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_wait_unknown_raises(self):
        launcher = WorkerLauncher()
        with pytest.raises(KeyError, match="No running worker"):
            await launcher.wait("nonexistent")


class TestLaunchAndWait:
    @pytest.mark.asyncio
    async def test_launch_and_wait_combined(self, tmp_path: Path):
        launcher = WorkerLauncher(LaunchConfig(auto_commit=False))
        wo = {"work_order_id": "wo-combo", "target_agent": "claude", "title": "Test"}
        worktree = tmp_path / "wt"
        (worktree / "scripts").mkdir(parents=True)
        (worktree / "scripts" / "codex_session.sh").write_text(
            "#!/usr/bin/env bash\n", encoding="utf-8"
        )

        mock_proc = AsyncMock()
        mock_proc.pid = 55
        mock_proc.communicate = AsyncMock(return_value=(b"done", b""))
        mock_proc.returncode = 0

        with (
            patch("shutil.which", return_value="/usr/bin/claude"),
            patch.object(WorkerLauncher, "_git_output", return_value=""),
            patch("asyncio.create_subprocess_exec", return_value=mock_proc),
            patch.object(WorkerLauncher, "_collect_diff", return_value=""),
        ):
            result = await launcher.launch_and_wait(wo, worktree_path=str(worktree))

        assert result.exit_code == 0
        assert result.stdout == "done"


class TestActiveWorkers:
    def test_active_workers_list(self):
        launcher = WorkerLauncher()
        launcher._workers["a"] = WorkerProcess(
            work_order_id="a",
            agent="claude",
            worktree_path="/tmp",
            branch="main",
            pid=1,
        )
        launcher._workers["b"] = WorkerProcess(
            work_order_id="b",
            agent="codex",
            worktree_path="/tmp",
            branch="main",
            pid=2,
            exit_code=0,
        )
        active = launcher.active_workers()
        assert len(active) == 1
        assert active[0].work_order_id == "a"
