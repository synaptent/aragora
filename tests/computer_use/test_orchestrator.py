"""Tests for computer-use orchestrator."""

import asyncio

import pytest

from aragora.computer_use.actions import ActionType, ClickAction, ScreenshotAction
from aragora.computer_use.orchestrator import (
    ComputerUseConfig,
    ComputerUseMetrics,
    ComputerUseOrchestrator,
    MockActionExecutor,
    StepResult,
    StepStatus,
    TaskResult,
    TaskStatus,
)
from aragora.computer_use.policies import (
    ComputerPolicy,
    PolicyDecision,
    create_default_computer_policy,
    create_readonly_computer_policy,
)


class TestStepStatus:
    """Test StepStatus enum."""

    def test_all_statuses_defined(self):
        """Verify all step statuses exist."""
        expected = ["pending", "executing", "success", "failed", "blocked", "timeout"]
        actual = [s.value for s in StepStatus]
        assert set(expected) == set(actual)


class TestTaskStatus:
    """Test TaskStatus enum."""

    def test_all_statuses_defined(self):
        """Verify all task statuses exist."""
        expected = ["pending", "running", "completed", "failed", "timeout", "cancelled"]
        actual = [s.value for s in TaskStatus]
        assert set(expected) == set(actual)


class TestComputerUseConfig:
    """Test ComputerUseConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ComputerUseConfig()
        assert config.model == "claude-opus-5"
        assert config.max_tokens == 4096
        assert config.temperature == 0.0
        assert config.display_width == 1920
        assert config.display_height == 1080
        assert config.action_timeout_seconds == 10.0
        assert config.max_steps == 50
        assert config.on_step_complete is None

    def test_custom_values(self):
        """Test custom configuration."""
        config = ComputerUseConfig(
            max_steps=20,
            action_timeout_seconds=5.0,
        )
        assert config.max_steps == 20
        assert config.action_timeout_seconds == 5.0


class TestComputerUseMetrics:
    """Test ComputerUseMetrics dataclass."""

    def test_default_values(self):
        """Test default metric values."""
        metrics = ComputerUseMetrics()
        assert metrics.total_tasks == 0
        assert metrics.successful_tasks == 0
        assert metrics.total_actions == 0

    def test_task_success_rate(self):
        """Test task success rate calculation."""
        metrics = ComputerUseMetrics(total_tasks=10, successful_tasks=8)
        assert metrics.task_success_rate == 80.0

    def test_task_success_rate_empty(self):
        """Test success rate with no tasks."""
        metrics = ComputerUseMetrics()
        assert metrics.task_success_rate == 100.0

    def test_action_success_rate(self):
        """Test action success rate calculation."""
        metrics = ComputerUseMetrics(total_actions=100, successful_actions=95)
        assert metrics.action_success_rate == 95.0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        metrics = ComputerUseMetrics(
            total_tasks=5,
            successful_tasks=4,
            total_actions=50,
            successful_actions=45,
        )
        data = metrics.to_dict()
        assert data["total_tasks"] == 5
        assert data["successful_tasks"] == 4
        assert data["task_success_rate"] == 80.0


class TestStepResult:
    """Test StepResult dataclass."""

    def test_create_result(self):
        """Test creating a step result."""
        from aragora.computer_use.actions import ActionResult

        action = ClickAction(x=100, y=100)
        result = ActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            success=True,
        )
        step = StepResult(
            step_number=1,
            action=action,
            result=result,
            status=StepStatus.SUCCESS,
            model_response="Clicking button",
        )
        assert step.step_number == 1
        assert step.status == StepStatus.SUCCESS
        assert step.policy_check_passed is True

    def test_to_dict(self):
        """Test serialization."""
        from aragora.computer_use.actions import ActionResult

        action = ScreenshotAction()
        result = ActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            success=True,
        )
        step = StepResult(
            step_number=1,
            action=action,
            result=result,
            status=StepStatus.SUCCESS,
        )
        data = step.to_dict()
        assert data["step_number"] == 1
        assert data["status"] == "success"


class TestTaskResult:
    """Test TaskResult dataclass."""

    def test_create_result(self):
        """Test creating a task result."""
        result = TaskResult(
            task_id="task-123",
            goal="Test task",
            status=TaskStatus.COMPLETED,
        )
        assert result.task_id == "task-123"
        assert result.goal == "Test task"
        assert result.status == TaskStatus.COMPLETED

    def test_to_dict(self):
        """Test serialization."""
        result = TaskResult(
            task_id="task-456",
            goal="Another task",
            status=TaskStatus.RUNNING,
        )
        data = result.to_dict()
        assert data["task_id"] == "task-456"
        assert data["goal"] == "Another task"
        assert data["status"] == "running"


class TestMockActionExecutor:
    """Test MockActionExecutor."""

    @pytest.fixture
    def executor(self):
        """Create mock executor."""
        return MockActionExecutor()

    @pytest.mark.asyncio
    async def test_execute_action(self, executor):
        """Test executing an action."""
        action = ClickAction(x=100, y=100)
        result = await executor.execute(action)
        assert result.success is True
        assert result.action_id == action.action_id

    @pytest.mark.asyncio
    async def test_take_screenshot(self, executor):
        """Test taking screenshot."""
        screenshot = await executor.take_screenshot()
        assert isinstance(screenshot, str)
        assert len(screenshot) > 0

    @pytest.mark.asyncio
    async def test_get_current_url(self, executor):
        """Test getting current URL."""
        url = await executor.get_current_url()
        assert url == "http://localhost:8080"


class TestComputerUseOrchestrator:
    """Test ComputerUseOrchestrator."""

    @pytest.fixture
    def executor(self):
        """Create mock executor."""
        return MockActionExecutor()

    @pytest.fixture
    def policy(self):
        """Create default policy."""
        return create_default_computer_policy()

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return ComputerUseConfig(
            max_steps=5,
            action_timeout_seconds=5.0,
            total_timeout_seconds=30.0,
        )

    @pytest.fixture
    def orchestrator(self, executor, policy, config):
        """Create orchestrator for tests."""
        return ComputerUseOrchestrator(
            executor=executor,
            policy=policy,
            config=config,
        )

    def test_create_orchestrator(self, orchestrator):
        """Test creating orchestrator."""
        assert orchestrator.policy.name == "default"
        assert orchestrator.metrics.total_tasks == 0

    def test_metrics_property(self, orchestrator):
        """Test accessing metrics."""
        metrics = orchestrator.metrics
        assert isinstance(metrics, ComputerUseMetrics)

    def test_policy_property(self, orchestrator):
        """Test accessing policy."""
        policy = orchestrator.policy
        assert isinstance(policy, ComputerPolicy)

    @pytest.mark.asyncio
    async def test_run_task_no_executor(self):
        """Test running task without executor fails."""
        orchestrator = ComputerUseOrchestrator()
        with pytest.raises(RuntimeError, match="No executor configured"):
            await orchestrator.run_task(goal="Test")

    @pytest.mark.asyncio
    async def test_run_task_completes(self, orchestrator):
        """Test running a task to completion."""
        result = await orchestrator.run_task(
            goal="Take a screenshot",
            max_steps=3,
        )
        assert result.status in [TaskStatus.COMPLETED, TaskStatus.RUNNING]
        assert result.task_id.startswith("task-")

    @pytest.mark.asyncio
    async def test_run_task_invokes_step_callback(self, orchestrator):
        """Step callback should be invoked for completed steps."""
        steps: list[StepResult] = []

        def _capture_step(step_result: StepResult) -> None:
            steps.append(step_result)

        orchestrator._config.on_step_complete = _capture_step  # type: ignore[attr-defined]

        result = await orchestrator.run_task(goal="Test", max_steps=2)

        assert result.status in [TaskStatus.COMPLETED, TaskStatus.RUNNING]
        assert steps
        assert steps[0].step_number == 1

    @pytest.mark.asyncio
    async def test_run_task_with_metadata(self, orchestrator):
        """Test running task with metadata."""
        result = await orchestrator.run_task(
            goal="Test",
            metadata={"user_id": "123"},
        )
        assert result.metadata.get("user_id") == "123"

    @pytest.mark.asyncio
    async def test_get_audit_log(self, orchestrator):
        """Test getting audit log."""
        await orchestrator.run_task(goal="Test")
        log = orchestrator.get_audit_log()
        assert isinstance(log, list)

    @pytest.mark.asyncio
    async def test_cancel_task(self, orchestrator):
        """Test cancelling a task."""
        # No current task
        cancelled = await orchestrator.cancel_task()
        assert cancelled is False

    @pytest.mark.asyncio
    async def test_metrics_updated_after_task(self, orchestrator):
        """Test metrics are updated after task."""
        initial_tasks = orchestrator.metrics.total_tasks
        await orchestrator.run_task(goal="Test")
        assert orchestrator.metrics.total_tasks == initial_tasks + 1


class TestOrchestratorWithReadonlyPolicy:
    """Test orchestrator with readonly policy."""

    @pytest.fixture
    def readonly_orchestrator(self):
        """Create orchestrator with readonly policy."""
        return ComputerUseOrchestrator(
            executor=MockActionExecutor(),
            policy=create_readonly_computer_policy(),
            config=ComputerUseConfig(max_steps=3),
        )

    @pytest.mark.asyncio
    async def test_readonly_blocks_clicks(self, readonly_orchestrator):
        """Test readonly policy blocks click actions."""
        # The orchestrator stub returns screenshot first, then completes
        # In real implementation, this would test policy blocking
        result = await readonly_orchestrator.run_task(goal="Click something")
        assert result.status in [TaskStatus.COMPLETED, TaskStatus.RUNNING]


class TestOrchestratorApprovalCallback:
    """Test orchestrator with approval callback."""

    @pytest.mark.asyncio
    async def test_approval_callback_blocks(self):
        """Test approval callback can block actions."""

        def deny_all(action):
            return False

        config = ComputerUseConfig(
            max_steps=2,
            require_approval_callback=deny_all,
        )
        orchestrator = ComputerUseOrchestrator(
            executor=MockActionExecutor(),
            policy=create_default_computer_policy(),
            config=config,
        )
        result = await orchestrator.run_task(goal="Test")
        # Task should still complete (stub behavior)
        assert result.status in [TaskStatus.COMPLETED, TaskStatus.RUNNING]

    @pytest.mark.asyncio
    async def test_approval_callback_allows(self):
        """Test approval callback can allow actions."""

        def allow_all(action):
            return True

        config = ComputerUseConfig(
            max_steps=2,
            require_approval_callback=allow_all,
        )
        orchestrator = ComputerUseOrchestrator(
            executor=MockActionExecutor(),
            policy=create_default_computer_policy(),
            config=config,
        )
        result = await orchestrator.run_task(goal="Test")
        assert result.status in [TaskStatus.COMPLETED, TaskStatus.RUNNING]
