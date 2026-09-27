"""
Computer-Use Orchestrator.

Manages multi-turn computer-use sessions with:
- Claude API integration for tool calling
- Policy enforcement per action
- Screenshot capture and validation
- Error recovery and retry logic
- Session metrics and audit trails

Pattern: Agentic loop with tool calling
Inspired by: Anthropic Computer Use demo
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, cast
from collections.abc import Callable

from aragora.computer_use.actions import (
    Action,
    ActionResult,
    ScreenshotAction,
)
from aragora.computer_use.policies import (
    ComputerPolicy,
    ComputerPolicyChecker,
    PolicyDecision,
    create_default_computer_policy,
)

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    """Status of a single step in the task."""

    PENDING = "pending"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"  # Policy denied
    TIMEOUT = "timeout"


class TaskStatus(str, Enum):
    """Status of the overall task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


@dataclass
class StepResult:
    """Result of a single step in the task."""

    step_number: int
    action: Action
    result: ActionResult
    status: StepStatus
    model_response: str = ""
    policy_check_passed: bool = True
    policy_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "step_number": self.step_number,
            "action": self.action.to_dict(),
            "result": self.result.to_dict(),
            "status": self.status.value,
            "model_response": self.model_response,
            "policy_check_passed": self.policy_check_passed,
            "policy_reason": self.policy_reason,
        }


@dataclass
class TaskResult:
    """Result of executing a computer-use task."""

    task_id: str
    goal: str
    status: TaskStatus
    steps: list[StepResult] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    final_screenshot_b64: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": (self.end_time - self.start_time) if self.end_time else None,
            "has_final_screenshot": self.final_screenshot_b64 is not None,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class ComputerUseMetrics:
    """Metrics for computer-use sessions."""

    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    total_actions: int = 0
    successful_actions: int = 0
    failed_actions: int = 0
    policy_blocked_actions: int = 0
    total_latency_ms: float = 0.0

    @property
    def task_success_rate(self) -> float:
        """Task success rate as percentage."""
        if self.total_tasks == 0:
            return 100.0
        return (self.successful_tasks / self.total_tasks) * 100

    @property
    def action_success_rate(self) -> float:
        """Action success rate as percentage."""
        if self.total_actions == 0:
            return 100.0
        return (self.successful_actions / self.total_actions) * 100

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_tasks": self.total_tasks,
            "successful_tasks": self.successful_tasks,
            "failed_tasks": self.failed_tasks,
            "task_success_rate": round(self.task_success_rate, 2),
            "total_actions": self.total_actions,
            "successful_actions": self.successful_actions,
            "failed_actions": self.failed_actions,
            "policy_blocked_actions": self.policy_blocked_actions,
            "action_success_rate": round(self.action_success_rate, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
        }


@dataclass
class ComputerUseConfig:
    """Configuration for the orchestrator."""

    # Model settings
    model: str = "claude-opus-5"
    max_tokens: int = 4096
    temperature: float = 0.0

    # Display settings
    display_width: int = 1920
    display_height: int = 1080

    # Timeout settings
    action_timeout_seconds: float = 10.0
    total_timeout_seconds: float = 300.0

    # Retry settings
    max_retries_per_action: int = 2
    retry_delay_seconds: float = 1.0

    # Step limits
    max_steps: int = 50

    # Screenshot settings
    take_screenshot_after_action: bool = True
    screenshot_delay_ms: int = 500

    # Human approval callback
    require_approval_callback: Callable[[Action], bool] | None = None

    # Progress callback (invoked per step result)
    on_step_complete: Callable[[StepResult], None] | None = None

    # Approval workflow settings
    enforce_sensitive_approvals: bool = False
    approval_timeout_seconds: float = 300.0


class ActionExecutor(Protocol):
    """Protocol for executing actions on the computer."""

    async def execute(self, action: Action) -> ActionResult:
        """Execute an action and return the result."""
        ...

    async def take_screenshot(self) -> str:
        """Take a screenshot and return base64-encoded image."""
        ...

    async def get_current_url(self) -> str | None:
        """Get current browser URL if applicable."""
        ...


class ComputerUseOrchestrator:
    """
    Orchestrates multi-turn computer-use sessions.

    Manages the agentic loop of:
    1. Take screenshot
    2. Send to Claude with goal
    3. Receive action from Claude
    4. Validate action against policy
    5. Execute action
    6. Repeat until goal achieved or limits reached

    Usage:
        executor = PlaywrightExecutor()  # Or other implementation
        policy = create_default_computer_policy()
        orchestrator = ComputerUseOrchestrator(
            executor=executor,
            policy=policy,
        )

        result = await orchestrator.run_task(
            goal="Open settings and enable dark mode",
            max_steps=10,
        )
    """

    def __init__(
        self,
        executor: ActionExecutor | None = None,
        policy: ComputerPolicy | None = None,
        config: ComputerUseConfig | None = None,
        api_key: str | None = None,
        bridge: Any | None = None,
        approval_workflow: Any | None = None,
        approval_enforcer: Any | None = None,
    ):
        """
        Initialize the orchestrator.

        Args:
            executor: Action executor implementation
            policy: Computer-use policy
            config: Orchestrator configuration
            api_key: Anthropic API key (uses ANTHROPIC_API_KEY env var if not provided)
            bridge: ClaudeComputerUseBridge instance for Claude API integration.
                    If not provided but api_key is given, one is created automatically.
        """
        self._executor = executor
        self._policy = policy or create_default_computer_policy()
        self._config = config or ComputerUseConfig()
        self._api_key = api_key
        self._policy_checker = ComputerPolicyChecker(self._policy)
        self._metrics = ComputerUseMetrics()
        self._current_task: TaskResult | None = None
        self._bridge = bridge
        self._approval_workflow = approval_workflow
        self._approval_enforcer = approval_enforcer

        # Auto-create bridge if api_key provided but no bridge
        if self._bridge is None and self._api_key:
            try:
                from aragora.computer_use.claude_bridge import (
                    BridgeConfig,
                    ClaudeComputerUseBridge,
                )

                self._bridge = ClaudeComputerUseBridge(
                    api_key=self._api_key,
                    config=BridgeConfig(
                        display_width=self._config.display_width,
                        display_height=self._config.display_height,
                    ),
                )
            except ImportError:
                logger.warning("Claude bridge unavailable - using stub for _get_next_action")

    @property
    def metrics(self) -> ComputerUseMetrics:
        """Get session metrics."""
        return self._metrics

    @property
    def policy(self) -> ComputerPolicy:
        """Get the policy."""
        return self._policy

    def _emit_step(self, step_result: StepResult) -> None:
        """Invoke progress callback for a completed step."""
        callback = self._config.on_step_complete
        if not callback:
            return
        try:
            callback(step_result)
        except (RuntimeError, ValueError, AttributeError) as exc:  # user-supplied callback
            logger.debug("Computer-use progress callback failed: %s", exc)

    async def run_task(
        self,
        goal: str,
        max_steps: int | None = None,
        initial_context: str = "",
        metadata: dict[str, Any] | None = None,
        receipt_id: str | None = None,
    ) -> TaskResult:
        """
        Execute a computer-use task.

        Args:
            goal: Natural language description of the goal
            max_steps: Maximum steps (overrides config)
            initial_context: Additional context for Claude
            metadata: Optional metadata to attach
            receipt_id: Optional receipt ID for enforcement gate

        Returns:
            TaskResult with all step details
        """
        if not self._executor:
            raise RuntimeError("No executor configured")

        task_id = f"task-{uuid.uuid4().hex[:8]}"
        max_steps = max_steps or self._config.max_steps

        # Receipt enforcement gate (Phase 2 — Decision Integrity Kernel)
        try:
            from aragora.pipeline.receipt_enforcement import (
                ReceiptEnforcementError,
                is_receipt_enforcement_enabled,
                require_receipt_gate,
            )

            if is_receipt_enforcement_enabled("computer_use"):
                actor_id = (metadata or {}).get("user_id", "system")
                require_receipt_gate(
                    action_domain="computer_use",
                    action_type="run_task",
                    actor_id=actor_id,
                    resource_id=task_id,
                    receipt_id=receipt_id,
                )
        except ReceiptEnforcementError:
            raise
        except ImportError:
            logger.debug("Receipt enforcement module not available, skipping gate")

        result = TaskResult(
            task_id=task_id,
            goal=goal,
            status=TaskStatus.RUNNING,
            metadata=metadata or {},
        )
        self._current_task = result
        self._metrics.total_tasks += 1

        logger.info("Starting computer-use task: %s - %s", task_id, goal)

        try:
            # Initial screenshot
            screenshot_b64 = await self._executor.take_screenshot()

            step_number = 0
            while step_number < max_steps:
                # Check total timeout
                elapsed = time.time() - result.start_time
                if elapsed > self._config.total_timeout_seconds:
                    result.status = TaskStatus.TIMEOUT
                    result.error = f"Total timeout exceeded ({self._config.total_timeout_seconds}s)"
                    break

                # Get current URL for policy checks
                current_url = await self._executor.get_current_url()

                # Call Claude to get next action
                step_number += 1
                action, model_response, is_complete = await self._get_next_action(
                    goal=goal,
                    screenshot_b64=screenshot_b64,
                    previous_steps=result.steps,
                    initial_context=initial_context,
                )

                if is_complete:
                    result.status = TaskStatus.COMPLETED
                    result.final_screenshot_b64 = screenshot_b64
                    logger.info("Task %s completed successfully", task_id)
                    break

                if action is None:
                    # Model indicated completion or confusion
                    result.status = TaskStatus.COMPLETED
                    result.final_screenshot_b64 = screenshot_b64
                    break

                # Policy check
                decision, reason = self._policy_checker.evaluate_action(
                    action,
                    current_url,
                    enforce_sensitive_approvals=self._config.enforce_sensitive_approvals,
                )

                if decision == PolicyDecision.DENY:
                    step_result = StepResult(
                        step_number=step_number,
                        action=action,
                        result=ActionResult(
                            action_id=action.action_id,
                            action_type=action.action_type,
                            success=False,
                            error=f"Policy denied: {reason}",
                        ),
                        status=StepStatus.BLOCKED,
                        model_response=model_response,
                        policy_check_passed=False,
                        policy_reason=reason,
                    )
                    result.steps.append(step_result)
                    self._emit_step(step_result)
                    self._metrics.policy_blocked_actions += 1
                    self._policy_checker.record_error()

                    # Try to continue with screenshot for context
                    await asyncio.sleep(0.5)
                    screenshot_b64 = await self._executor.take_screenshot()
                    continue

                if decision == PolicyDecision.REQUIRE_APPROVAL:
                    approved, approval_reason, approval_id = await self._request_approval(
                        action=action,
                        reason=reason,
                        screenshot_b64=screenshot_b64,
                        current_url=current_url,
                        metadata=metadata or {},
                    )
                    if not approved:
                        step_result = StepResult(
                            step_number=step_number,
                            action=action,
                            result=ActionResult(
                                action_id=action.action_id,
                                action_type=action.action_type,
                                success=False,
                                error=f"Approval denied: {approval_reason}",
                                metadata={"approval_request_id": approval_id}
                                if approval_id
                                else {},
                            ),
                            status=StepStatus.BLOCKED,
                            model_response=model_response,
                            policy_check_passed=False,
                            policy_reason=approval_reason,
                        )
                        result.steps.append(step_result)
                        self._emit_step(step_result)
                        self._metrics.policy_blocked_actions += 1
                        self._policy_checker.record_error()
                        await asyncio.sleep(0.5)
                        screenshot_b64 = await self._executor.take_screenshot()
                        continue

                # Human approval if required
                if self._config.require_approval_callback:
                    if not self._config.require_approval_callback(action):
                        step_result = StepResult(
                            step_number=step_number,
                            action=action,
                            result=ActionResult(
                                action_id=action.action_id,
                                action_type=action.action_type,
                                success=False,
                                error="Human approval denied",
                            ),
                            status=StepStatus.BLOCKED,
                            model_response=model_response,
                            policy_check_passed=True,
                            policy_reason="human approval required",
                        )
                        result.steps.append(step_result)
                        self._emit_step(step_result)
                        continue

                # Execute action
                self._metrics.total_actions += 1
                action_result = await self._execute_with_timeout(action)

                step_status = StepStatus.SUCCESS if action_result.success else StepStatus.FAILED

                step_result = StepResult(
                    step_number=step_number,
                    action=action,
                    result=action_result,
                    status=step_status,
                    model_response=model_response,
                    policy_check_passed=True,
                )
                result.steps.append(step_result)
                self._emit_step(step_result)

                if action_result.success:
                    self._metrics.successful_actions += 1
                    self._policy_checker.record_success()
                else:
                    self._metrics.failed_actions += 1
                    self._policy_checker.record_error()

                # Take screenshot after action
                if self._config.take_screenshot_after_action:
                    await asyncio.sleep(self._config.screenshot_delay_ms / 1000)
                    screenshot_b64 = await self._executor.take_screenshot()
                    action_result.screenshot_b64 = screenshot_b64

            # End of loop
            if result.status == TaskStatus.RUNNING:
                result.status = TaskStatus.COMPLETED
                result.final_screenshot_b64 = screenshot_b64

            self._metrics.successful_tasks += 1

        except asyncio.TimeoutError:
            result.status = TaskStatus.TIMEOUT
            result.error = "Task timeout"
            self._metrics.failed_tasks += 1

        except (RuntimeError, OSError, TimeoutError) as e:
            result.status = TaskStatus.FAILED
            result.error = str(e)
            self._metrics.failed_tasks += 1
            logger.exception("Task %s failed: %s", task_id, e)

        finally:
            result.end_time = time.time()
            self._current_task = None
            self._policy_checker.reset()
            if self._bridge is not None and hasattr(self._bridge, "reset"):
                self._bridge.reset()

        # Transition receipt to EXECUTED after successful task completion
        if receipt_id and result.status == TaskStatus.COMPLETED:
            try:
                from aragora.pipeline.receipt_enforcement import (
                    is_receipt_enforcement_enabled,
                    transition_receipt_executed,
                )

                if is_receipt_enforcement_enabled("computer_use"):
                    transition_receipt_executed(receipt_id)
            except ImportError:
                logger.debug("Receipt enforcement module not available, skipping transition")

        return result

    async def _request_approval(
        self,
        *,
        action: Action,
        reason: str,
        screenshot_b64: str,
        current_url: str | None,
        metadata: dict[str, Any],
    ) -> tuple[bool, str, str | None]:
        """Request approval for a sensitive action."""
        if self._approval_enforcer:
            try:
                from aragora.security.approval_enforcer import EnforcementRequest, EnforcementResult
            except ImportError:
                return False, "Approval enforcer unavailable", None

            action_type = _map_action_type_for_enforcer(action.action_type.value)
            actor_id = metadata.get("user_id", "system")
            request = EnforcementRequest(
                action_type=action_type,
                actor_id=actor_id,
                source="computer_use",
                resource=current_url or action_type,
                details={
                    "force_approval": True,
                    "force_reason": reason,
                    "url": current_url,
                    "action": action.to_tool_input(),
                },
                session_id=self._current_task.task_id if self._current_task else "",
                tenant_id=metadata.get("tenant_id"),
                roles=metadata.get("roles", []),
                approval_id=metadata.get("approval_id"),
            )

            decision = await self._approval_enforcer.enforce(request)
            approval_id = decision.approval_request_id
            if decision.result == EnforcementResult.ALLOWED:
                return True, decision.reason, approval_id
            if decision.result == EnforcementResult.DENIED:
                return False, decision.reason, approval_id
            if approval_id:
                approved = await self._approval_enforcer.wait_for_approval(
                    approval_id,
                    timeout=self._config.approval_timeout_seconds,
                )
                return approved, "approved" if approved else "denied_or_expired", approval_id

            return False, "Approval pending but no request id", None

        if not self._approval_workflow:
            return False, "Approval workflow not configured", None

        try:
            from aragora.computer_use.approval import (
                ApprovalCategory,
                ApprovalContext,
                ApprovalPriority,
                ApprovalStatus,
            )
        except ImportError:
            return False, "Approval module unavailable", None

        action_details = action.to_tool_input()
        context = ApprovalContext(
            task_id=self._current_task.task_id if self._current_task else "unknown",
            action_type=action.action_type.value,
            action_details=action_details,
            category=ApprovalCategory.DESTRUCTIVE_ACTION,
            reason=reason,
            risk_level=metadata.get("risk_level", "medium"),
            screenshot_b64=screenshot_b64,
            current_url=current_url,
            user_id=metadata.get("user_id"),
            tenant_id=metadata.get("tenant_id"),
            metadata=metadata.get("approval_metadata", {}),
        )

        request = await self._approval_workflow.request_approval(
            context=context,
            priority=ApprovalPriority.HIGH,
            timeout_seconds=self._config.approval_timeout_seconds,
        )

        status = await self._approval_workflow.wait_for_decision(
            request.id,
            timeout=self._config.approval_timeout_seconds,
        )
        if status == ApprovalStatus.APPROVED:
            return True, "approved", request.id

        return False, status.value, request.id

    async def _get_next_action(
        self,
        goal: str,
        screenshot_b64: str,
        previous_steps: list[StepResult],
        initial_context: str = "",
    ) -> tuple[Action | None, str, bool]:
        """
        Call Claude to determine the next action.

        Delegates to ClaudeComputerUseBridge when available, otherwise
        falls back to a stub that completes after the first step.

        Returns:
            (action, model_response, is_complete) tuple
        """
        if self._bridge is not None:
            return await self._bridge.get_next_action(
                goal=goal,
                screenshot_b64=screenshot_b64,
                previous_steps=previous_steps,
                initial_context=initial_context,
            )

        # Fallback stub for testing without API key
        logger.debug("No bridge configured, using stub (completes after first step)")
        if previous_steps:
            return None, "Task appears complete", True
        return ScreenshotAction(), "Taking initial screenshot", False

    async def _execute_with_timeout(self, action: Action) -> ActionResult:
        """Execute action with timeout."""
        try:
            start_time = time.time()
            result = await asyncio.wait_for(
                cast(Any, self._executor).execute(action),  # Action subtype dispatch
                timeout=self._config.action_timeout_seconds,
            )
            result.duration_ms = (time.time() - start_time) * 1000
            self._metrics.total_latency_ms += result.duration_ms
            return result

        except asyncio.TimeoutError:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.action_type,
                success=False,
                error=f"Action timeout after {self._config.action_timeout_seconds}s",
            )

    async def cancel_task(self) -> bool:
        """Cancel the current running task."""
        if self._current_task:
            self._current_task.status = TaskStatus.CANCELLED
            self._current_task.end_time = time.time()
            return True
        return False

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Get the policy audit log."""
        return self._policy_checker.get_audit_log()


def _map_action_type_for_enforcer(action_type: str) -> str:
    """Map computer-use action types to approval enforcer action types."""
    if action_type in ("type", "key"):
        return "keyboard"
    if action_type in ("click", "double_click", "right_click", "drag", "move", "scroll"):
        return "mouse"
    if action_type in ("screenshot",):
        return "screenshot"
    return "browser"


class MockActionExecutor:
    """
    Mock executor for testing.

    Simulates action execution without actual computer control.
    """

    def __init__(self, screenshot_b64: str = ""):
        self._screenshot = screenshot_b64 or self._generate_blank_screenshot()
        self._current_url: str | None = "http://localhost:8080"

    def _generate_blank_screenshot(self) -> str:
        """Generate a minimal valid base64 image."""
        # 1x1 white PNG
        return "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="

    async def execute(self, action: Action) -> ActionResult:
        """Simulate action execution."""
        # Simulate some delay
        await asyncio.sleep(0.1)

        return ActionResult(
            action_id=action.action_id,
            action_type=action.action_type,
            success=True,
            screenshot_b64=self._screenshot,
        )

    async def take_screenshot(self) -> str:
        """Return mock screenshot."""
        return self._screenshot

    async def get_current_url(self) -> str | None:
        """Return mock URL."""
        return self._current_url


__all__ = [
    "ActionExecutor",
    "ComputerUseConfig",
    "ComputerUseMetrics",
    "ComputerUseOrchestrator",
    "MockActionExecutor",
    "StepResult",
    "StepStatus",
    "TaskResult",
    "TaskStatus",
]
