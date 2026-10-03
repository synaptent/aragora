"""Tests for decision pipeline CLI command behavior."""

from __future__ import annotations

import argparse
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.execution_mode import ExecutionMode


def _make_args(**overrides):
    base = {
        "task": "Test task",
        "agents": "codex,claude",
        "rounds": 3,
        "execution_mode": None,
        "computer_use": False,
        "hybrid": False,
        "fabric": False,
        "implementation_profile": None,
        "fabric_models": None,
        "channel_targets": None,
        "thread_id": None,
        "thread_id_by_platform": None,
        "auto_select": False,
        "auto_select_config": None,
        "context": None,
        "context_file": None,
        "spec": None,
        "document": None,
        "documents": None,
        "no_knowledge": False,
        "no_cross_memory": False,
        "enable_supermemory": False,
        "supermemory_container": None,
        "supermemory_max_items": None,
        "enable_belief_guidance": False,
        "auto_approve": False,
        "dry_run": True,
        "budget_limit": None,
        "verbose": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def test_cmd_decide_promotes_execution_mode_into_profile_when_missing():
    """--execution-mode should persist into implementation_profile for later execution."""
    from aragora.cli.commands import decide as decide_cmd

    args = _make_args(execution_mode="hybrid")

    with (
        patch.object(decide_cmd, "run_decide", return_value="coro") as mock_run_decide,
        patch.object(decide_cmd.asyncio, "run", return_value={}),
    ):
        decide_cmd.cmd_decide(args)

    kwargs = mock_run_decide.call_args.kwargs
    assert kwargs["execution_mode"] == "hybrid"
    assert kwargs["implementation_profile"] == {"execution_mode": "hybrid"}


def test_cmd_decide_does_not_override_profile_execution_mode():
    """Existing implementation_profile execution_mode should remain authoritative."""
    from aragora.cli.commands import decide as decide_cmd

    args = _make_args(
        execution_mode="hybrid",
        implementation_profile='{"execution_mode":"fabric","max_parallel":2}',
    )

    with (
        patch.object(decide_cmd, "run_decide", return_value="coro") as mock_run_decide,
        patch.object(decide_cmd.asyncio, "run", return_value={}),
    ):
        decide_cmd.cmd_decide(args)

    kwargs = mock_run_decide.call_args.kwargs
    assert kwargs["execution_mode"] == "hybrid"
    assert kwargs["implementation_profile"]["execution_mode"] == "fabric"
    assert kwargs["implementation_profile"]["max_parallel"] == 2


def test_cmd_decide_normalizes_execution_mode_alias() -> None:
    """Known execution-mode aliases should be normalized before run_decide."""
    from aragora.cli.commands import decide as decide_cmd

    args = _make_args(execution_mode="workflow_execute")

    with (
        patch.object(decide_cmd, "run_decide", return_value="coro") as mock_run_decide,
        patch.object(decide_cmd.asyncio, "run", return_value={}),
    ):
        decide_cmd.cmd_decide(args)

    kwargs = mock_run_decide.call_args.kwargs
    assert kwargs["execution_mode"] == "workflow"
    assert kwargs["implementation_profile"]["execution_mode"] == "workflow"


def test_cmd_decide_uses_structured_spec_path_without_mutating_context(tmp_path) -> None:
    """cmd_decide should pass spec_file through without stuffing spec text into context."""
    from aragora.cli.commands import decide as decide_cmd

    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"specification":{"title":"Spec","problem_statement":"Ship it"}}')
    args = _make_args(
        spec=str(spec_path),
        context="operator notes",
    )

    with (
        patch.object(decide_cmd, "run_decide", return_value="coro") as mock_run_decide,
        patch.object(decide_cmd.asyncio, "run", return_value={}),
    ):
        decide_cmd.cmd_decide(args)

    kwargs = mock_run_decide.call_args.kwargs
    assert kwargs["context"] == "operator notes"
    assert kwargs["spec_file"] == str(spec_path)


def test_cmd_decide_demo_falls_back_without_aragora_debate(capsys) -> None:
    """Demo mode should degrade to the built-in fallback instead of crashing."""
    from aragora.cli.commands import decide as decide_cmd

    args = _make_args(demo=True, dry_run=True)

    with patch.object(decide_cmd, "_import_decide_demo_runtime", return_value=None):
        decide_cmd.cmd_decide(args)

    out = capsys.readouterr().out
    assert "ARAGORA DECIDE (Demo Mode)" in out
    assert "Built-in offline demo agents" in out
    assert "Dry run mode - no receipt saved" in out


@pytest.mark.asyncio
async def test_run_decide_seeds_backbone_run_for_spec_dry_run(tmp_path) -> None:
    """Spec-driven dry runs should still seed a backbone run."""
    from aragora.cli.commands.decide import run_decide

    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"title":"Spec"}')

    plan = MagicMock()
    plan.id = "plan-cli-1"
    plan.status = SimpleNamespace(value="approved")
    plan.risk_register = None
    plan.requires_human_approval = False

    with (
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_specification",
            return_value=plan,
        ),
        patch(
            "aragora.cli.commands.decide._seed_cli_backbone_run",
            return_value="run-cli-1",
        ) as mock_seed,
    ):
        result = await run_decide(
            task="Ship the feature",
            agents_str="claude,gemini",
            dry_run=True,
            spec_file=str(spec_path),
        )

    assert result["plan"] is plan
    assert result["run_id"] == "run-cli-1"
    assert result["dry_run"] is True
    mock_seed.assert_called_once_with(
        plan,
        source_surface="cli_decide_spec",
        source_id=str(spec_path),
    )


@pytest.mark.asyncio
async def test_run_decide_forwards_wrapped_spec_artifacts(tmp_path) -> None:
    """Wrapped spec files should preserve validation and canonical spec artifacts."""
    from aragora.cli.commands.decide import run_decide

    spec_path = tmp_path / "spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "specification": {
                    "title": "Spec",
                    "problem_statement": "Ship it",
                },
                "validation": {
                    "passed": True,
                    "overall_confidence": 0.92,
                },
                "spec_bundle": {
                    "title": "Spec",
                    "problem_statement": "Ship it",
                    "is_execution_grade": False,
                },
            }
        )
    )

    plan = MagicMock()
    plan.id = "plan-cli-wrapped"
    plan.status = SimpleNamespace(value="approved")
    plan.risk_register = None
    plan.requires_human_approval = False

    with (
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_specification",
            return_value=plan,
        ) as mock_from_specification,
        patch(
            "aragora.cli.commands.decide._seed_cli_backbone_run",
            return_value="run-cli-wrapped",
        ),
    ):
        result = await run_decide(
            task="Ship the feature",
            agents_str="claude,gemini",
            dry_run=True,
            spec_file=str(spec_path),
        )

    kwargs = mock_from_specification.call_args.kwargs
    assert kwargs["validation_result"] == {
        "passed": True,
        "overall_confidence": 0.92,
    }
    assert kwargs["metadata"]["prompt_spec_artifacts"]["validation"]["passed"] is True
    assert kwargs["metadata"]["spec_bundle"]["title"] == "Spec"
    assert result["plan"] is plan
    assert result["run_id"] == "run-cli-wrapped"


@pytest.mark.parametrize("mode", ["redteam", "deep_audit", "prober"])
@pytest.mark.asyncio
async def test_run_decide_advertised_advanced_mode_does_not_crash(tmp_path, mode, capsys) -> None:
    """Advertised --mode advanced modes (redteam/deep_audit/prober) are not in the
    operational ModeRegistry, but the parser offers them as valid choices. They must
    degrade gracefully with a clean notice rather than raising a raw KeyError traceback.
    """
    from aragora.cli.commands.decide import run_decide

    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"specification":{"title":"Spec","objective":"test"}}')

    plan = MagicMock()
    plan.id = "plan-mode"
    plan.status = SimpleNamespace(value="approved")
    plan.risk_register = None
    plan.requires_human_approval = False

    with (
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_specification",
            return_value=plan,
        ),
        patch(
            "aragora.cli.commands.decide._seed_cli_backbone_run",
            return_value="run-mode",
        ),
    ):
        # Must not raise KeyError for an advertised-but-unregistered mode.
        result = await run_decide(
            task="Ship the feature",
            agents_str="claude,gemini",
            dry_run=True,
            spec_file=str(spec_path),
            mode=mode,
            verbose=True,
        )

    assert result["plan"] is plan
    # A clean, human-readable notice is printed instead of a traceback.
    out = capsys.readouterr().out
    assert mode in out


@pytest.mark.asyncio
async def test_run_decide_unknown_mode_does_not_crash(tmp_path, capsys) -> None:
    """A genuinely unknown mode should still degrade gracefully (no raw traceback)."""
    from aragora.cli.commands.decide import run_decide

    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"specification":{"title":"Spec","objective":"test"}}')

    plan = MagicMock()
    plan.id = "plan-unknown-mode"
    plan.status = SimpleNamespace(value="approved")
    plan.risk_register = None
    plan.requires_human_approval = False

    with (
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_specification",
            return_value=plan,
        ),
        patch(
            "aragora.cli.commands.decide._seed_cli_backbone_run",
            return_value="run-unknown-mode",
        ),
    ):
        result = await run_decide(
            task="Ship the feature",
            agents_str="claude,gemini",
            dry_run=True,
            spec_file=str(spec_path),
            mode="totally_unknown_mode",
            verbose=True,
        )

    assert result["plan"] is plan


@pytest.mark.asyncio
async def test_run_decide_executes_via_backbone_helper(tmp_path) -> None:
    """run_decide should execute plans through the backbone helper and surface IDs."""
    from aragora.cli.commands.decide import run_decide

    spec_path = tmp_path / "spec.json"
    spec_path.write_text('{"title":"Spec"}')

    plan = MagicMock()
    plan.id = "plan-cli-2"
    plan.status = SimpleNamespace(value="approved")
    plan.risk_register = None
    plan.requires_human_approval = False

    outcome = MagicMock()
    outcome.success = True
    outcome.tasks_completed = 2
    outcome.tasks_total = 2
    outcome.receipt_id = "receipt-1"
    outcome.lessons = []
    launch = {
        "run_id": "run-cli-2",
        "execution_id": "exec-cli-2",
        "correlation_id": "corr-cli-2",
    }
    executor = MagicMock()

    with (
        patch(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_specification",
            return_value=plan,
        ),
        patch(
            "aragora.cli.commands.decide._seed_cli_backbone_run",
            return_value="run-cli-2",
        ),
        patch("aragora.pipeline.executor.PlanExecutor", return_value=executor),
        patch(
            "aragora.cli.commands.decide.execute_decision_plan_with_backbone",
            new=AsyncMock(return_value=(launch, outcome)),
        ) as mock_execute,
    ):
        result = await run_decide(
            task="Ship the feature",
            agents_str="claude,gemini",
            dry_run=False,
            spec_file=str(spec_path),
            execution_mode="hybrid",
        )

    assert result["plan"] is plan
    assert result["outcome"] is outcome
    assert result["run_id"] == "run-cli-2"
    assert result["execution_id"] == "exec-cli-2"
    assert result["correlation_id"] == "corr-cli-2"
    mock_execute.assert_awaited_once_with(
        plan,
        executor=executor,
        auth_context=None,
        execution_mode="hybrid",
        safety_mode=ExecutionMode.INTERACTIVE,
    )


def test_cmd_plans_execute_routes_through_backbone_helper() -> None:
    """plans execute should use the backbone helper rather than direct executor execution."""
    from aragora.cli.commands import decide as decide_cmd

    args = argparse.Namespace(
        plan_id="plan-cli-3",
        execution_mode=None,
        computer_use=False,
        hybrid=True,
    )
    plan = MagicMock()
    plan.id = "plan-cli-3"
    outcome = MagicMock()
    outcome.success = True
    outcome.tasks_completed = 3
    outcome.tasks_total = 3
    outcome.duration_seconds = 1.5
    outcome.receipt_id = None
    outcome.error = None
    launch = {
        "run_id": "run-cli-3",
        "execution_id": "exec-cli-3",
        "correlation_id": "corr-cli-3",
    }
    executor = MagicMock()

    with (
        patch("aragora.pipeline.executor.get_plan", return_value=plan),
        patch("aragora.pipeline.executor.PlanExecutor", return_value=executor),
        patch.object(
            decide_cmd,
            "execute_decision_plan_with_backbone",
            return_value="coro",
        ) as mock_execute,
        patch.object(decide_cmd.asyncio, "run", return_value=(launch, outcome)),
        patch("builtins.print"),
    ):
        decide_cmd.cmd_plans_execute(args)

    mock_execute.assert_called_once_with(
        plan,
        executor=executor,
        auth_context=None,
        execution_mode="hybrid",
        safety_mode=ExecutionMode.INTERACTIVE,
    )
