"""Tests for sandbox feedback loop in PlanExecutor.

Validates that PlanExecutor correctly integrates with SandboxExecutor:
  1. Initializes _sandbox_executor when sandbox_config is provided
  2. Leaves _sandbox_executor as None when sandbox_config is absent
  3. Includes sandbox_config in execution metadata when present
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.decision_plan import DecisionPlan, PlanStatus
from aragora.pipeline.executor import PlanExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_real_import = __import__


def _make_plan(
    *,
    plan_id: str = "plan-sb-1",
    task: str = "Validate sandbox integration",
    debate_id: str = "debate-sb-1",
    status: PlanStatus = PlanStatus.APPROVED,
) -> MagicMock:
    """Create a minimal DecisionPlan mock for testing."""
    plan = MagicMock(spec=DecisionPlan)
    plan.id = plan_id
    plan.debate_id = debate_id
    plan.task = task
    plan.status = status
    plan.metadata = {}
    plan.requires_human_approval = False
    plan.is_approved = True
    plan.implement_plan = None
    plan.risk_register = None
    plan.verification_plan = None
    plan.implementation_profile = None
    plan.workflow_id = None
    plan.created_at = "2026-03-05T00:00:00"
    plan.execution_started_at = None
    # budget is accessed by _run_workflow for cost tracking
    budget_mock = MagicMock()
    budget_mock.spent_usd = 0.0
    plan.budget = budget_mock
    return plan


def _blocking_import(blocked: str):
    """Return an __import__ replacement that raises ImportError for *blocked*."""

    def _side_effect(name, *args, **kwargs):
        if name == blocked:
            raise ImportError(f"Mocked import failure for {name}")
        return _real_import(name, *args, **kwargs)

    return _side_effect


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestSandboxExecutorInit:
    """PlanExecutor creates or skips _sandbox_executor based on config."""

    def test_sandbox_executor_created_when_config_provided(self):
        """When sandbox_config is set, PlanExecutor imports SandboxExecutor."""
        mock_sandbox_cls = MagicMock()
        mock_sandbox_instance = MagicMock()
        mock_sandbox_cls.return_value = mock_sandbox_instance

        fake_module = MagicMock(SandboxExecutor=mock_sandbox_cls)
        with patch.dict(sys.modules, {"aragora.sandbox.executor": fake_module}):
            config = {"mode": "mock", "network_enabled": False}
            executor = PlanExecutor(
                continuum_memory=MagicMock(),
                knowledge_mound=MagicMock(),
                sandbox_config=config,
            )

        assert executor._sandbox_executor is mock_sandbox_instance
        assert executor._sandbox_config == config
        mock_sandbox_cls.assert_called_once_with(config)

    def test_sandbox_executor_none_when_no_config(self):
        """When sandbox_config is omitted, _sandbox_executor is None."""
        executor = PlanExecutor(
            continuum_memory=MagicMock(),
            knowledge_mound=MagicMock(),
        )
        assert executor._sandbox_executor is None
        assert executor._sandbox_config is None

    def test_sandbox_executor_none_on_import_error(self):
        """When SandboxExecutor import fails, _sandbox_executor falls back to None."""
        with patch(
            "builtins.__import__",
            side_effect=_blocking_import("aragora.sandbox.executor"),
        ):
            executor = PlanExecutor(
                continuum_memory=MagicMock(),
                knowledge_mound=MagicMock(),
                sandbox_config={"mode": "docker"},
            )

        assert executor._sandbox_executor is None
        # Config is still stored even if the executor couldn't be created
        assert executor._sandbox_config == {"mode": "docker"}


# ---------------------------------------------------------------------------
# Execution metadata tests
# ---------------------------------------------------------------------------


class TestSandboxExecutionMetadata:
    """Sandbox config propagates into execution metadata passed to the engine."""

    @pytest.mark.asyncio
    async def test_sandbox_config_included_in_metadata(self):
        """When sandbox_config is set, _run_workflow passes it in engine metadata."""
        config = {"mode": "mock", "timeout": 30}

        # Build executor without triggering real SandboxExecutor init
        executor = PlanExecutor(
            continuum_memory=MagicMock(),
            knowledge_mound=MagicMock(),
        )
        executor._sandbox_config = config
        executor._sandbox_executor = None

        plan = _make_plan()

        # plan.to_workflow_definition() is called inside _run_workflow
        mock_definition = MagicMock()
        mock_definition.name = "test-workflow"
        plan.to_workflow_definition.return_value = mock_definition

        # Mock the WorkflowEngine that _run_workflow imports locally
        mock_engine = AsyncMock()
        mock_result = MagicMock()
        mock_result.step_results = []
        mock_result.success = True
        mock_engine.execute.return_value = mock_result

        mock_engine_cls = MagicMock(return_value=mock_engine)

        with patch.dict(
            sys.modules,
            {"aragora.workflow.engine": MagicMock(WorkflowEngine=mock_engine_cls)},
        ):
            outcome = await executor._run_workflow(plan)

        # Verify the engine.execute call included sandbox_config in metadata
        mock_engine.execute.assert_called_once()
        call_kwargs = mock_engine.execute.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata", {})
        assert metadata["sandbox_config"] == config

    @pytest.mark.asyncio
    async def test_no_sandbox_config_in_metadata_when_absent(self):
        """When sandbox_config is None, metadata omits the sandbox_config key."""
        executor = PlanExecutor(
            continuum_memory=MagicMock(),
            knowledge_mound=MagicMock(),
        )
        plan = _make_plan()

        mock_definition = MagicMock()
        mock_definition.name = "test-workflow"
        plan.to_workflow_definition.return_value = mock_definition

        mock_engine = AsyncMock()
        mock_result = MagicMock()
        mock_result.step_results = []
        mock_result.success = True
        mock_engine.execute.return_value = mock_result

        mock_engine_cls = MagicMock(return_value=mock_engine)

        with patch.dict(
            sys.modules,
            {"aragora.workflow.engine": MagicMock(WorkflowEngine=mock_engine_cls)},
        ):
            outcome = await executor._run_workflow(plan)

        mock_engine.execute.assert_called_once()
        call_kwargs = mock_engine.execute.call_args
        metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata", {})
        assert "sandbox_config" not in metadata
