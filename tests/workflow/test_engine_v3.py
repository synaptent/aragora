"""Comprehensive tests for the WorkflowEngine -- deep coverage of execution
lifecycle, step types, DAG validation, error handling, checkpointing,
transitions, termination, metrics, and event emission.

This supplements the existing test_engine.py with additional scenarios
focused on:
- WorkflowEngine construction and default step type registration
- Workflow execution with sequential, conditional, and loop steps
- DAG validation via WorkflowDefinition.validate()
- Error handling: unknown step type, step failure with stop_on_failure,
  optional step skipping, timeout, retry exhaustion
- Checkpoint creation and retrieval
- Transition evaluation with safe_eval
- Termination control
- get_metrics accuracy
- Event callback invocation
- Resume from checkpoint
- WorkflowContext accessors
- Singleton management (get_workflow_engine / reset_workflow_engine)
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.workflow.engine import (
    WorkflowEngine,
    get_workflow_engine,
    reset_workflow_engine,
    get_workflow_executor,
)
from aragora.workflow.step import (
    BaseStep,
    WorkflowContext,
    AgentStep,
    ParallelStep,
    ConditionalStep,
    LoopStep,
)
from aragora.workflow.types import (
    StepDefinition,
    StepResult,
    StepStatus,
    TransitionRule,
    WorkflowCheckpoint,
    WorkflowConfig,
    WorkflowDefinition,
    WorkflowResult,
)


# ---------------------------------------------------------------------------
# Helper step classes
# ---------------------------------------------------------------------------


class EchoStep(BaseStep):
    """Step that echoes its config message or a default."""

    async def execute(self, context: WorkflowContext) -> Any:
        msg = self._config.get("message", "echo")
        return {"message": msg}


class CounterStep(BaseStep):
    """Step that increments a counter in context state."""

    async def execute(self, context: WorkflowContext) -> Any:
        count = context.get_state("counter", 0)
        context.set_state("counter", count + 1)
        return {"counter": count + 1}


class FailStep(BaseStep):
    """Step that always fails."""

    async def execute(self, context: WorkflowContext) -> Any:
        raise RuntimeError("FailStep always fails")


class SlowStep(BaseStep):
    """Step that sleeps for a configured duration."""

    async def execute(self, context: WorkflowContext) -> Any:
        delay = self._config.get("delay", 5.0)
        await asyncio.sleep(delay)
        return {"completed": True}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def engine() -> WorkflowEngine:
    """Create an engine with test step types registered."""
    config = WorkflowConfig(
        total_timeout_seconds=30.0,
        step_timeout_seconds=10.0,
        stop_on_failure=True,
        enable_checkpointing=False,
    )
    e = WorkflowEngine(
        config=config,
        step_registry={
            "echo": EchoStep,
            "counter": CounterStep,
            "fail": FailStep,
            "slow": SlowStep,
        },
        checkpoint_store=MagicMock(),
    )
    return e


@pytest.fixture
def simple_def() -> WorkflowDefinition:
    """Single-step workflow definition."""
    return WorkflowDefinition(
        id="wf-simple",
        name="Simple",
        steps=[
            StepDefinition(
                id="s1",
                name="Echo Step",
                step_type="echo",
                config={"message": "hello"},
            ),
        ],
        entry_step="s1",
    )


@pytest.fixture
def sequential_def() -> WorkflowDefinition:
    """Three-step sequential workflow."""
    return WorkflowDefinition(
        id="wf-seq",
        name="Sequential",
        steps=[
            StepDefinition(
                id="s1",
                name="Step 1",
                step_type="echo",
                config={"message": "one"},
                next_steps=["s2"],
            ),
            StepDefinition(
                id="s2",
                name="Step 2",
                step_type="echo",
                config={"message": "two"},
                next_steps=["s3"],
            ),
            StepDefinition(
                id="s3",
                name="Step 3",
                step_type="echo",
                config={"message": "three"},
            ),
        ],
        entry_step="s1",
    )


@pytest.fixture
def failing_def() -> WorkflowDefinition:
    """Workflow with a failing step."""
    return WorkflowDefinition(
        id="wf-fail",
        name="Failing",
        steps=[
            StepDefinition(
                id="s1",
                name="Good Step",
                step_type="echo",
                config={"message": "ok"},
                next_steps=["s2"],
            ),
            StepDefinition(
                id="s2",
                name="Bad Step",
                step_type="fail",
            ),
        ],
        entry_step="s1",
    )


@pytest.fixture
def optional_fail_def() -> WorkflowDefinition:
    """Workflow with an optional failing step followed by a good step."""
    return WorkflowDefinition(
        id="wf-opt",
        name="Optional Fail",
        steps=[
            StepDefinition(
                id="s1",
                name="Optional Bad",
                step_type="fail",
                optional=True,
                next_steps=["s2"],
            ),
            StepDefinition(
                id="s2",
                name="Good",
                step_type="echo",
                config={"message": "survived"},
            ),
        ],
        entry_step="s1",
    )


# ---------------------------------------------------------------------------
# Engine construction and step type registration
# ---------------------------------------------------------------------------


class TestEngineConstruction:
    def test_default_step_types_registered(self):
        """Engine should register agent, parallel, conditional, loop by default."""
        eng = WorkflowEngine(checkpoint_store=MagicMock())
        assert "agent" in eng._step_types
        assert "parallel" in eng._step_types
        assert "conditional" in eng._step_types
        assert "loop" in eng._step_types

    def test_custom_step_type_registration(self, engine: WorkflowEngine):
        """register_step_type should add custom types."""
        engine.register_step_type("custom_echo", EchoStep)
        assert "custom_echo" in engine._step_types
        assert engine._step_types["custom_echo"] is EchoStep

    def test_custom_registry_at_construction(self):
        """Step registry passed to constructor should be available."""
        eng = WorkflowEngine(
            step_registry={"my_step": EchoStep},
            checkpoint_store=MagicMock(),
        )
        # Both default and custom should be present
        assert "my_step" in eng._step_types
        assert "agent" in eng._step_types


# ---------------------------------------------------------------------------
# Workflow execution: simple and sequential
# ---------------------------------------------------------------------------


class TestWorkflowExecution:
    @pytest.mark.asyncio
    async def test_single_step_execution(
        self, engine: WorkflowEngine, simple_def: WorkflowDefinition
    ):
        """Single step workflow should succeed with output."""
        result = await engine.execute(simple_def)
        assert result.success is True
        assert len(result.steps) == 1
        assert result.steps[0].status == StepStatus.COMPLETED
        assert result.final_output == {"message": "hello"}

    @pytest.mark.asyncio
    async def test_sequential_execution_order(
        self, engine: WorkflowEngine, sequential_def: WorkflowDefinition
    ):
        """Steps should execute in order s1 -> s2 -> s3."""
        result = await engine.execute(sequential_def)
        assert result.success is True
        assert len(result.steps) == 3
        step_ids = [s.step_id for s in result.steps]
        assert step_ids == ["s1", "s2", "s3"]

    @pytest.mark.asyncio
    async def test_custom_workflow_id(self, engine: WorkflowEngine, simple_def: WorkflowDefinition):
        """Passing workflow_id should use it."""
        result = await engine.execute(simple_def, workflow_id="my-wf-123")
        assert result.workflow_id == "my-wf-123"

    @pytest.mark.asyncio
    async def test_inputs_available_in_context(self, engine: WorkflowEngine):
        """Workflow inputs should be accessible in step execution."""

        class InputReadStep(BaseStep):
            async def execute(self, context: WorkflowContext) -> Any:
                return {"got_name": context.get_input("name", "default")}

        engine.register_step_type("input_read", InputReadStep)
        wf = WorkflowDefinition(
            id="wf-input",
            name="Input Test",
            steps=[
                StepDefinition(id="s1", name="Read", step_type="input_read"),
            ],
            entry_step="s1",
        )

        result = await engine.execute(wf, inputs={"name": "aragora"})
        assert result.success is True
        assert result.final_output["got_name"] == "aragora"


# ---------------------------------------------------------------------------
# DAG validation
# ---------------------------------------------------------------------------


class TestDAGValidation:
    def test_valid_workflow_passes(self, sequential_def: WorkflowDefinition):
        """Well-formed workflow should validate without errors."""
        is_valid, errors = sequential_def.validate()
        assert is_valid is True
        assert errors == []

    def test_no_steps_fails(self):
        """Workflow with no steps should fail validation."""
        wf = WorkflowDefinition(id="wf-empty", name="Empty", steps=[])
        is_valid, errors = wf.validate()
        assert is_valid is False
        assert any("at least one step" in e for e in errors)

    def test_missing_entry_step(self):
        """Entry step referencing nonexistent step should fail."""
        wf = WorkflowDefinition(
            id="wf-bad-entry",
            name="Bad Entry",
            steps=[StepDefinition(id="s1", name="S1", step_type="echo")],
            entry_step="nonexistent",
        )
        is_valid, errors = wf.validate()
        assert is_valid is False
        assert any("not found" in e for e in errors)

    def test_transition_to_unknown_step(self):
        """Transition referencing unknown step should fail validation."""
        wf = WorkflowDefinition(
            id="wf-bad-tr",
            name="Bad Transition",
            steps=[StepDefinition(id="s1", name="S1", step_type="echo")],
            transitions=[
                TransitionRule(
                    id="tr1",
                    from_step="s1",
                    to_step="nonexistent",
                    condition="True",
                )
            ],
            entry_step="s1",
        )
        is_valid, errors = wf.validate()
        assert is_valid is False
        assert any("unknown step" in e.lower() for e in errors)

    def test_next_steps_to_unknown_step(self):
        """next_steps referencing unknown step should fail validation."""
        wf = WorkflowDefinition(
            id="wf-bad-next",
            name="Bad Next",
            steps=[
                StepDefinition(
                    id="s1",
                    name="S1",
                    step_type="echo",
                    next_steps=["missing"],
                )
            ],
            entry_step="s1",
        )
        is_valid, errors = wf.validate()
        assert is_valid is False
        assert any("unknown next step" in e.lower() for e in errors)

    def test_no_id_fails(self):
        """Missing workflow ID should fail validation."""
        wf = WorkflowDefinition(
            id="",
            name="No ID",
            steps=[StepDefinition(id="s1", name="S1", step_type="echo")],
        )
        is_valid, errors = wf.validate()
        assert is_valid is False

    def test_no_name_fails(self):
        """Missing workflow name should fail validation."""
        wf = WorkflowDefinition(
            id="wf-no-name",
            name="",
            steps=[StepDefinition(id="s1", name="S1", step_type="echo")],
        )
        is_valid, errors = wf.validate()
        assert is_valid is False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_unknown_step_type_fails(self, engine: WorkflowEngine):
        """Step with unregistered type should produce a FAILED result."""
        wf = WorkflowDefinition(
            id="wf-unknown",
            name="Unknown Type",
            steps=[
                StepDefinition(id="s1", name="Bad", step_type="nonexistent_type"),
            ],
            entry_step="s1",
        )
        result = await engine.execute(wf)
        assert result.success is False
        assert result.steps[0].status == StepStatus.FAILED
        assert "Unknown step type" in (result.steps[0].error or "")

    @pytest.mark.asyncio
    async def test_step_failure_stops_workflow(
        self, engine: WorkflowEngine, failing_def: WorkflowDefinition
    ):
        """With stop_on_failure=True, failure halts the workflow."""
        result = await engine.execute(failing_def)
        assert result.success is False
        # s1 should succeed, s2 should fail, no s3
        assert len(result.steps) == 2
        assert result.steps[0].status == StepStatus.COMPLETED
        assert result.steps[1].status == StepStatus.FAILED

    @pytest.mark.asyncio
    async def test_optional_step_failure_continues(
        self, engine: WorkflowEngine, optional_fail_def: WorkflowDefinition
    ):
        """Optional step failure should not stop the workflow."""
        result = await engine.execute(optional_fail_def)
        # Optional failures are marked skipped and should not block s2.
        assert len(result.steps) == 2
        assert result.steps[0].status == StepStatus.SKIPPED
        assert result.steps[1].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_step_timeout_with_retry(self, engine: WorkflowEngine):
        """Step that times out should retry and eventually fail."""
        wf = WorkflowDefinition(
            id="wf-timeout",
            name="Timeout",
            steps=[
                StepDefinition(
                    id="s1",
                    name="Slow",
                    step_type="slow",
                    config={"delay": 20.0},
                    timeout_seconds=0.5,
                    retries=1,
                ),
            ],
            entry_step="s1",
        )
        result = await engine.execute(wf)
        assert result.success is False
        assert result.steps[0].status == StepStatus.FAILED
        assert result.steps[0].retry_count == 2  # initial + 1 retry

    @pytest.mark.asyncio
    async def test_no_entry_step_raises(self, engine: WorkflowEngine):
        """Workflow with no entry step should fail with error."""
        wf = WorkflowDefinition(
            id="wf-noentry",
            name="No Entry",
            steps=[StepDefinition(id="s1", name="S1", step_type="echo")],
        )
        # Force entry_step to None
        wf.entry_step = None
        result = await engine.execute(wf)
        assert result.success is False
        assert result.error is not None


# ---------------------------------------------------------------------------
# Conditional transitions
# ---------------------------------------------------------------------------


class TestConditionalTransitions:
    @pytest.mark.asyncio
    async def test_transition_taken_when_condition_true(self, engine: WorkflowEngine):
        """Transition should route to to_step when condition evaluates True."""
        wf = WorkflowDefinition(
            id="wf-cond",
            name="Conditional",
            steps=[
                StepDefinition(
                    id="s1",
                    name="Decision",
                    step_type="echo",
                    config={"message": "go_a"},
                ),
                StepDefinition(
                    id="s_a",
                    name="Path A",
                    step_type="echo",
                    config={"message": "took_a"},
                ),
                StepDefinition(
                    id="s_b",
                    name="Path B",
                    step_type="echo",
                    config={"message": "took_b"},
                ),
            ],
            transitions=[
                TransitionRule(
                    id="tr1",
                    from_step="s1",
                    to_step="s_a",
                    condition="True",
                    priority=10,
                ),
                TransitionRule(
                    id="tr2",
                    from_step="s1",
                    to_step="s_b",
                    condition="False",
                    priority=5,
                ),
            ],
            entry_step="s1",
        )

        result = await engine.execute(wf)
        assert result.success is True
        step_ids = [s.step_id for s in result.steps]
        assert "s_a" in step_ids
        assert "s_b" not in step_ids

    @pytest.mark.asyncio
    async def test_transition_fallback_to_next_steps(self, engine: WorkflowEngine):
        """When no transition condition is met, next_steps is used."""
        wf = WorkflowDefinition(
            id="wf-fallback",
            name="Fallback",
            steps=[
                StepDefinition(
                    id="s1",
                    name="Start",
                    step_type="echo",
                    next_steps=["s2"],
                ),
                StepDefinition(
                    id="s2",
                    name="Default",
                    step_type="echo",
                    config={"message": "default"},
                ),
            ],
            transitions=[
                TransitionRule(
                    id="tr_never",
                    from_step="s1",
                    to_step="s_never",
                    condition="False",
                ),
            ],
            entry_step="s1",
        )
        # Add the never step so validation doesn't fail
        wf.steps.append(StepDefinition(id="s_never", name="Never", step_type="echo"))

        result = await engine.execute(wf)
        step_ids = [s.step_id for s in result.steps]
        assert "s2" in step_ids
        assert "s_never" not in step_ids


# ---------------------------------------------------------------------------
# Termination control
# ---------------------------------------------------------------------------


class TestTerminationControl:
    @pytest.mark.asyncio
    async def test_request_termination_stops_execution(self, engine: WorkflowEngine):
        """request_termination should prevent subsequent steps."""

        class TerminateStep(BaseStep):
            async def execute(self, context: WorkflowContext) -> Any:
                # Reach into the engine to request termination
                engine.request_termination("Test termination")
                return {"terminated": True}

        engine.register_step_type("terminate", TerminateStep)

        wf = WorkflowDefinition(
            id="wf-term",
            name="Terminate",
            steps=[
                StepDefinition(
                    id="s1",
                    name="Terminate",
                    step_type="terminate",
                    next_steps=["s2"],
                ),
                StepDefinition(
                    id="s2",
                    name="Should Not Run",
                    step_type="echo",
                ),
            ],
            entry_step="s1",
        )

        result = await engine.execute(wf)
        # s1 executes, s2 should be skipped due to termination
        step_ids = [s.step_id for s in result.steps]
        assert "s1" in step_ids
        assert "s2" not in step_ids

    def test_check_termination_returns_state(self, engine: WorkflowEngine):
        """check_termination should reflect the current state."""
        terminated, reason = engine.check_termination()
        assert terminated is False
        assert reason is None

        engine.request_termination("done")
        terminated, reason = engine.check_termination()
        assert terminated is True
        assert reason == "done"

    @pytest.mark.asyncio
    async def test_pause_all_stops_all_live_engine_instances(
        self,
        engine: WorkflowEngine,
    ):
        """The emergency brake should stop every currently executing engine."""
        reset_workflow_engine()
        other_engine = WorkflowEngine(
            config=WorkflowConfig(enable_checkpointing=False),
            step_registry={"slow": SlowStep, "echo": EchoStep},
            checkpoint_store=MagicMock(),
        )
        workflow = WorkflowDefinition(
            id="wf-brake",
            name="Brake",
            steps=[
                StepDefinition(
                    id="s1",
                    name="Slow",
                    step_type="slow",
                    config={"delay": 0.05},
                    next_steps=["s2"],
                ),
                StepDefinition(id="s2", name="Should Not Run", step_type="echo"),
            ],
            entry_step="s1",
        )

        try:
            tasks = [
                asyncio.create_task(engine.execute(workflow)),
                asyncio.create_task(other_engine.execute(workflow)),
            ]
            await asyncio.sleep(0.01)
            WorkflowEngine.pause_all("Critical alert")
            results = await asyncio.gather(*tasks)

            assert engine.check_termination() == (True, "Critical alert")
            assert other_engine.check_termination() == (True, "Critical alert")
            assert all([step.step_id for step in result.steps] == ["s1"] for result in results)
            assert WorkflowEngine(checkpoint_store=MagicMock()).check_termination() == (False, None)
        finally:
            reset_workflow_engine()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_after_execution(
        self, engine: WorkflowEngine, sequential_def: WorkflowDefinition
    ):
        """Metrics should reflect execution results."""
        await engine.execute(sequential_def)
        metrics = engine.get_metrics()

        assert metrics["total_steps"] == 3
        assert metrics["completed_steps"] == 3
        assert metrics["failed_steps"] == 0
        assert metrics["skipped_steps"] == 0
        assert metrics["total_duration_ms"] > 0

    @pytest.mark.asyncio
    async def test_metrics_include_step_durations(
        self, engine: WorkflowEngine, sequential_def: WorkflowDefinition
    ):
        """Metrics should include per-step durations."""
        await engine.execute(sequential_def)
        metrics = engine.get_metrics()

        assert "step_durations" in metrics
        assert "s1" in metrics["step_durations"]
        assert "s2" in metrics["step_durations"]
        assert "s3" in metrics["step_durations"]

    @pytest.mark.asyncio
    async def test_metrics_on_failure(
        self, engine: WorkflowEngine, failing_def: WorkflowDefinition
    ):
        """Metrics should count failures."""
        await engine.execute(failing_def)
        metrics = engine.get_metrics()

        assert metrics["failed_steps"] >= 1


# ---------------------------------------------------------------------------
# Event callbacks
# ---------------------------------------------------------------------------


class TestEventCallbacks:
    @pytest.mark.asyncio
    async def test_event_callback_receives_events(
        self, engine: WorkflowEngine, simple_def: WorkflowDefinition
    ):
        """Event callback should be called with workflow lifecycle events."""
        events = []

        def capture_event(event_type: str, payload: dict):
            events.append((event_type, payload))

        await engine.execute(simple_def, event_callback=capture_event)

        event_types = [e[0] for e in events]
        # Should have start, step start/complete, and completion events
        assert any("start" in et.lower() for et in event_types)
        assert any("complete" in et.lower() for et in event_types)

    @pytest.mark.asyncio
    async def test_event_callback_error_does_not_crash(
        self, engine: WorkflowEngine, simple_def: WorkflowDefinition
    ):
        """Failing event callback should not crash the workflow."""

        def bad_callback(event_type: str, payload: dict):
            raise RuntimeError("callback error")

        result = await engine.execute(simple_def, event_callback=bad_callback)
        # Workflow should still succeed despite callback errors
        assert result.success is True

    @pytest.mark.asyncio
    async def test_trace_callback(self, simple_def: WorkflowDefinition):
        """trace_callback in config should receive events."""
        traces = []

        def trace_fn(event_type: str, payload: dict):
            traces.append(event_type)

        config = WorkflowConfig(
            total_timeout_seconds=30.0,
            trace_callback=trace_fn,
            enable_checkpointing=False,
        )
        eng = WorkflowEngine(
            config=config,
            step_registry={"echo": EchoStep},
            checkpoint_store=MagicMock(),
        )

        await eng.execute(simple_def)
        assert len(traces) > 0


# ---------------------------------------------------------------------------
# WorkflowContext accessors
# ---------------------------------------------------------------------------


class TestWorkflowContext:
    def test_get_input_default(self):
        """get_input should return default when key missing."""
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        assert ctx.get_input("missing", "fallback") == "fallback"

    def test_get_step_output(self):
        """get_step_output should retrieve previous step outputs."""
        ctx = WorkflowContext(
            workflow_id="w1",
            definition_id="d1",
            step_outputs={"s1": {"data": 42}},
        )
        assert ctx.get_step_output("s1") == {"data": 42}
        assert ctx.get_step_output("missing") is None

    def test_state_get_set(self):
        """set_state / get_state should round-trip."""
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        ctx.set_state("key", "value")
        assert ctx.get_state("key") == "value"
        assert ctx.get_state("missing", "default") == "default"

    def test_get_config(self):
        """get_config should read from current_step_config."""
        ctx = WorkflowContext(
            workflow_id="w1",
            definition_id="d1",
            current_step_config={"param": "val"},
        )
        assert ctx.get_config("param") == "val"
        assert ctx.get_config("missing", "def") == "def"

    def test_emit_event_calls_callback(self):
        """emit_event should forward to callback."""
        captured = []
        ctx = WorkflowContext(
            workflow_id="w1",
            definition_id="d1",
            event_callback=lambda t, p: captured.append((t, p)),
        )
        ctx.emit_event("test_event", {"key": "val"})
        assert len(captured) == 1
        assert captured[0] == ("test_event", {"key": "val"})

    def test_emit_event_no_callback(self):
        """emit_event with no callback should not raise."""
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        ctx.emit_event("test", {})  # should not raise


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement:
    def test_get_workflow_engine_returns_same_instance(self):
        """get_workflow_engine should return singleton."""
        reset_workflow_engine()
        try:
            e1 = get_workflow_engine()
            e2 = get_workflow_engine()
            assert e1 is e2
        finally:
            reset_workflow_engine()

    def test_reset_clears_singleton(self):
        """reset_workflow_engine should clear the singleton."""
        reset_workflow_engine()
        try:
            e1 = get_workflow_engine()
            reset_workflow_engine()
            e2 = get_workflow_engine()
            assert e1 is not e2
        finally:
            reset_workflow_engine()

    def test_get_workflow_executor_default(self):
        """get_workflow_executor with mode='default' should return engine."""
        reset_workflow_engine()
        try:
            executor = get_workflow_executor(mode="default")
            assert isinstance(executor, WorkflowEngine)
        finally:
            reset_workflow_engine()

    def test_get_workflow_executor_unknown_mode(self):
        """Unknown mode should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown executor mode"):
            get_workflow_executor(mode="nonexistent")


# ---------------------------------------------------------------------------
# BaseStep and step types
# ---------------------------------------------------------------------------


class TestBaseStep:
    def test_base_step_properties(self):
        step = EchoStep(name="test", config={"a": 1})
        assert step.name == "test"
        assert step.config == {"a": 1}

    def test_validate_config_default(self):
        step = EchoStep(name="test")
        assert step.validate_config() is True

    @pytest.mark.asyncio
    async def test_checkpoint_returns_empty(self):
        step = EchoStep(name="test")
        state = await step.checkpoint()
        assert state == {}

    @pytest.mark.asyncio
    async def test_restore_does_not_raise(self):
        step = EchoStep(name="test")
        await step.restore({"key": "val"})  # should not raise


class TestAgentStep:
    def test_agent_step_defaults(self):
        """AgentStep should default to 'claude' agent type."""
        step = AgentStep(name="test")
        assert step.agent_type == "claude"
        assert step.prompt_template == ""

    def test_agent_step_config_override(self):
        """AgentStep should read agent_type from config."""
        step = AgentStep(
            name="test",
            config={"agent_type": "gpt4", "prompt_template": "Hello {name}"},
        )
        assert step.agent_type == "gpt4"
        assert step.prompt_template == "Hello {name}"

    def test_build_prompt_substitution(self):
        """_build_prompt should substitute input and step output placeholders."""
        step = AgentStep(
            name="test",
            prompt_template="Analyze {topic} based on {step.s1}",
        )
        ctx = WorkflowContext(
            workflow_id="w1",
            definition_id="d1",
            inputs={"topic": "security"},
            step_outputs={"s1": "previous analysis"},
        )
        prompt = step._build_prompt(ctx)
        assert "security" in prompt
        assert "previous analysis" in prompt

    def test_extract_code_from_markdown(self):
        """_extract_code should pull code from fenced blocks."""
        text = "Here is code:\n```python\nprint('hello')\n```\n"
        code = AgentStep._extract_code(text)
        assert code == "print('hello')"

    def test_extract_code_no_block(self):
        """_extract_code with no code block returns empty string."""
        assert AgentStep._extract_code("no code here") == ""


class TestConditionalStepUnit:
    @pytest.mark.asyncio
    async def test_condition_true_executes_wrapped(self):
        """When condition is True, wrapped step should execute."""
        wrapped = EchoStep(name="inner", config={"message": "inner_msg"})
        cond = ConditionalStep(name="cond", wrapped_step=wrapped, condition="True")
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await cond.execute(ctx)
        assert result == {"message": "inner_msg"}

    @pytest.mark.asyncio
    async def test_condition_false_skips_wrapped(self):
        """When condition is False, step should return skipped dict."""
        wrapped = EchoStep(name="inner")
        cond = ConditionalStep(name="cond", wrapped_step=wrapped, condition="False")
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await cond.execute(ctx)
        assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_invalid_condition_defaults_to_false(self):
        """Invalid condition expression should default to skip (False)."""
        wrapped = EchoStep(name="inner")
        cond = ConditionalStep(name="cond", wrapped_step=wrapped, condition="__import__('os')")
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await cond.execute(ctx)
        assert result["skipped"] is True


class TestLoopStepUnit:
    @pytest.mark.asyncio
    async def test_loop_executes_until_condition(self):
        """Loop should execute until exit condition is met."""
        inner = CounterStep(name="counter")
        loop = LoopStep(
            name="loop",
            wrapped_step=inner,
            condition="state.get('counter', 0) >= 3",
            max_iterations=10,
        )
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await loop.execute(ctx)

        assert result["iterations"] == 3
        assert len(result["outputs"]) == 3

    @pytest.mark.asyncio
    async def test_loop_respects_max_iterations(self):
        """Loop should stop at max_iterations even if condition never true."""
        inner = EchoStep(name="echo")
        loop = LoopStep(
            name="loop",
            wrapped_step=inner,
            condition="False",  # never exit
            max_iterations=5,
        )
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await loop.execute(ctx)

        assert result["iterations"] == 5


class TestParallelStepUnit:
    @pytest.mark.asyncio
    async def test_parallel_executes_all_substeps(self):
        """ParallelStep should execute all sub-steps concurrently."""
        sub1 = EchoStep(name="sub1", config={"message": "one"})
        sub2 = EchoStep(name="sub2", config={"message": "two"})
        parallel = ParallelStep(name="par", sub_steps=[sub1, sub2])
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await parallel.execute(ctx)

        assert "sub1" in result
        assert result["sub1"]["message"] == "one"
        assert "sub2" in result
        assert result["sub2"]["message"] == "two"

    @pytest.mark.asyncio
    async def test_parallel_captures_sub_step_errors(self):
        """ParallelStep should capture exceptions as error dicts."""
        sub1 = EchoStep(name="ok", config={"message": "fine"})
        sub2 = FailStep(name="bad")
        parallel = ParallelStep(name="par", sub_steps=[sub1, sub2])
        ctx = WorkflowContext(workflow_id="w1", definition_id="d1")
        result = await parallel.execute(ctx)

        assert result["ok"]["message"] == "fine"
        assert "error" in result["bad"]
