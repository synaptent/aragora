"""
Tests for OpenClaw sandbox runner.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.gateway.openclaw.sandbox import (
    OpenClawSandbox,
    OpenClawTask,
    SandboxConfig,
    SandboxResult,
    SandboxStatus,
    SandboxViolation,
)


class TestSandboxConfig:
    """Tests for SandboxConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = SandboxConfig()

        assert config.max_memory_mb == 512
        assert config.max_cpu_percent == 50
        assert config.max_execution_seconds == 300
        assert config.allow_external_network is False
        assert config.plugin_allowlist_mode is True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = SandboxConfig(
            max_memory_mb=1024,
            max_cpu_percent=75,
            max_execution_seconds=600,
            allow_external_network=True,
            allowed_plugins=["plugin1", "plugin2"],
        )

        assert config.max_memory_mb == 1024
        assert config.max_cpu_percent == 75
        assert config.max_execution_seconds == 600
        assert config.allow_external_network is True
        assert "plugin1" in config.allowed_plugins

    def test_validate_valid_config(self) -> None:
        """Test validation passes for valid config."""
        config = SandboxConfig()
        errors = config.validate()
        assert len(errors) == 0

    def test_validate_memory_too_low(self) -> None:
        """Test validation fails for low memory."""
        config = SandboxConfig(max_memory_mb=32)
        errors = config.validate()
        assert any("max_memory_mb" in e for e in errors)

    def test_validate_memory_too_high(self) -> None:
        """Test validation fails for high memory."""
        config = SandboxConfig(max_memory_mb=16384)
        errors = config.validate()
        assert any("max_memory_mb" in e for e in errors)

    def test_validate_execution_time_too_low(self) -> None:
        """Test validation fails for low execution time."""
        config = SandboxConfig(max_execution_seconds=0)
        errors = config.validate()
        assert any("max_execution_seconds" in e for e in errors)

    def test_validate_execution_time_too_high(self) -> None:
        """Test validation fails for high execution time."""
        config = SandboxConfig(max_execution_seconds=7200)
        errors = config.validate()
        assert any("max_execution_seconds" in e for e in errors)

    def test_validate_invalid_cpu(self) -> None:
        """Test validation fails for invalid CPU percent."""
        config = SandboxConfig(max_cpu_percent=150)
        errors = config.validate()
        assert any("max_cpu_percent" in e for e in errors)


class TestOpenClawTask:
    """Tests for OpenClawTask dataclass."""

    def test_task_creation(self) -> None:
        """Test task creation with defaults."""
        task = OpenClawTask(
            id="task-123",
            type="text_generation",
            payload={"prompt": "Hello"},
        )

        assert task.id == "task-123"
        assert task.type == "text_generation"
        assert task.payload["prompt"] == "Hello"
        assert task.capabilities == []
        assert task.plugins == []

    def test_task_with_capabilities(self) -> None:
        """Test task creation with capabilities."""
        task = OpenClawTask(
            id="task-456",
            type="file_operation",
            payload={"path": "/tmp/test"},
            capabilities=["file_system_read", "file_system_write"],
            plugins=["file-manager"],
        )

        assert "file_system_read" in task.capabilities
        assert "file-manager" in task.plugins


class TestOpenClawSandbox:
    """Tests for OpenClawSandbox."""

    @pytest.fixture
    def sandbox(self) -> OpenClawSandbox:
        """Create sandbox instance."""
        return OpenClawSandbox(
            config=SandboxConfig(max_execution_seconds=10),
            openclaw_endpoint="http://localhost:8081",
        )

    @pytest.fixture
    def simple_task(self) -> OpenClawTask:
        """Create a simple task."""
        return OpenClawTask(
            id="test-task",
            type="text_generation",
            payload={"prompt": "Hello"},
            capabilities=["text_generation"],
        )

    @pytest.mark.asyncio
    async def test_execute_simple_task(
        self, sandbox: OpenClawSandbox, simple_task: OpenClawTask
    ) -> None:
        """Test executing a simple task."""
        # Mock the HTTP call to OpenClaw
        with patch("aiohttp.ClientSession") as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(
                return_value={
                    "result": {"text": "Hello back!"},
                    "stdout": "",
                    "stderr": "",
                    "memory_used_mb": 128,
                }
            )
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)

            mock_session_instance = MagicMock()
            mock_session_instance.post = MagicMock(return_value=mock_response)
            mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
            mock_session_instance.__aexit__ = AsyncMock(return_value=False)
            mock_session.return_value = mock_session_instance

            result = await sandbox.execute(simple_task)

            assert result.status == SandboxStatus.COMPLETED
            assert result.output is not None

    @pytest.mark.asyncio
    async def test_execute_with_invalid_config(
        self, sandbox: OpenClawSandbox, simple_task: OpenClawTask
    ) -> None:
        """Test execution fails with invalid config."""
        invalid_config = SandboxConfig(max_memory_mb=1)  # Too low

        result = await sandbox.execute(simple_task, config_override=invalid_config)

        assert result.status == SandboxStatus.FAILED
        assert "Invalid sandbox config" in result.error

    @pytest.mark.asyncio
    async def test_execute_plugin_not_in_allowlist(self, sandbox: OpenClawSandbox) -> None:
        """Test execution fails when plugin not in allowlist."""
        task = OpenClawTask(
            id="test-task",
            type="text_generation",
            payload={},
            plugins=["unauthorized-plugin"],
        )

        # Create config with specific allowlist
        config = SandboxConfig(
            plugin_allowlist_mode=True,
            allowed_plugins=["allowed-plugin"],
        )

        result = await sandbox.execute(task, config_override=config)

        assert result.status == SandboxStatus.POLICY_VIOLATION
        assert "not in allowlist" in result.error

    @pytest.mark.asyncio
    async def test_execute_timeout(self, sandbox: OpenClawSandbox) -> None:
        """Test execution timeout handling."""
        task = OpenClawTask(
            id="slow-task",
            type="text_generation",
            payload={},
        )

        # Create config with very short timeout
        config = SandboxConfig(max_execution_seconds=1)

        # Mock the execution to take too long
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return SandboxResult(status=SandboxStatus.COMPLETED)

        with patch.object(sandbox, "_execute_task", side_effect=slow_execute):
            result = await sandbox.execute(task, config_override=config)

        assert result.status == SandboxStatus.TIMEOUT
        assert "exceeded" in result.error.lower()

    def test_validate_network_access_blocked(self, sandbox: OpenClawSandbox) -> None:
        """Test network validation blocks when disabled."""
        task = OpenClawTask(
            id="net-task",
            type="api_call",
            payload={},
            capabilities=["network_external"],
        )
        config = SandboxConfig(allow_external_network=False)

        with pytest.raises(SandboxViolation) as exc_info:
            sandbox._validate_network_access(task, config)

        assert "disabled" in str(exc_info.value)

    def test_validate_network_access_domain_not_allowed(self, sandbox: OpenClawSandbox) -> None:
        """Test network validation blocks unauthorized domains."""
        task = OpenClawTask(
            id="net-task",
            type="api_call",
            payload={"domains": ["malicious.com"]},
            capabilities=["network_external"],
        )
        config = SandboxConfig(
            allow_external_network=True,
            allowed_domains=["safe.com"],
        )

        with pytest.raises(SandboxViolation) as exc_info:
            sandbox._validate_network_access(task, config)

        assert "not in allowlist" in str(exc_info.value)

    def test_validate_filesystem_blocked_path(self, sandbox: OpenClawSandbox) -> None:
        """Test filesystem validation blocks sensitive paths."""
        task = OpenClawTask(
            id="file-task",
            type="file_operation",
            payload={"paths": ["/etc/passwd"]},
        )
        config = SandboxConfig()

        with pytest.raises(SandboxViolation) as exc_info:
            sandbox._validate_filesystem_access(task, config)

        assert "blocked" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cancel_task(self, sandbox: OpenClawSandbox) -> None:
        """Test cancelling a task."""
        # No active tasks to cancel
        result = await sandbox.cancel("nonexistent-task")
        assert result is False

        # Get active tasks when empty
        active = sandbox.get_active_tasks()
        assert active == []


class TestSandboxResult:
    """Tests for SandboxResult dataclass."""

    def test_result_completed(self) -> None:
        """Test completed result."""
        result = SandboxResult(
            status=SandboxStatus.COMPLETED,
            output={"text": "Hello"},
            execution_time_ms=150,
        )

        assert result.status == SandboxStatus.COMPLETED
        assert result.output == {"text": "Hello"}
        assert result.execution_time_ms == 150
        assert result.error is None

    def test_result_failed(self) -> None:
        """Test failed result."""
        result = SandboxResult(
            status=SandboxStatus.FAILED,
            error="Something went wrong",
        )

        assert result.status == SandboxStatus.FAILED
        assert result.error == "Something went wrong"
        assert result.output is None

    def test_result_policy_violation(self) -> None:
        """Test policy violation result."""
        result = SandboxResult(
            status=SandboxStatus.POLICY_VIOLATION,
            error="Attempted to access blocked path",
        )

        assert result.status == SandboxStatus.POLICY_VIOLATION


class TestSandboxStatus:
    """Tests for SandboxStatus enum."""

    def test_status_values(self) -> None:
        """Test status enum values."""
        assert SandboxStatus.PENDING.value == "pending"
        assert SandboxStatus.RUNNING.value == "running"
        assert SandboxStatus.COMPLETED.value == "completed"
        assert SandboxStatus.FAILED.value == "failed"
        assert SandboxStatus.TIMEOUT.value == "timeout"
        assert SandboxStatus.RESOURCE_LIMIT.value == "resource_limit"
        assert SandboxStatus.POLICY_VIOLATION.value == "policy_violation"
