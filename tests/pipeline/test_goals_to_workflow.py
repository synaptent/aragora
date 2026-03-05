"""Tests for UnifiedOrchestrator.goals_to_workflow (Task C — Canvas goals→DAG wiring).

Verifies that a list of goal dicts is correctly converted into a
WorkflowDefinition-compatible DAG with steps and transitions.
"""

from __future__ import annotations

import pytest

from aragora.pipeline.unified_orchestrator import UnifiedOrchestrator


@pytest.mark.asyncio
async def test_empty_goals_returns_empty_dag() -> None:
    """Empty input produces an empty but well-formed DAG."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([])

    assert dag["steps"] == []
    assert dag["transitions"] == []
    assert dag["entry_step"] is None
    assert dag["id"].startswith("wf-")
    assert dag["name"] == "Goal Implementation Workflow"


@pytest.mark.asyncio
async def test_single_goal_default_type() -> None:
    """A single goal with default type='goal' decomposes to 4 steps."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Build login page"}])

    steps = dag["steps"]
    assert len(steps) == 4  # research, implement, test, review

    step_types = [s["step_type"] for s in steps]
    assert "task" in step_types
    assert "verification" in step_types
    assert "human_checkpoint" in step_types

    # All steps reference the same goal
    goal_ids = {s["source_goal_id"] for s in steps}
    assert len(goal_ids) == 1

    # entry_step is the first step
    assert dag["entry_step"] == steps[0]["id"]


@pytest.mark.asyncio
async def test_milestone_type_decomposes_to_two_steps() -> None:
    """goal_type='milestone' maps to checkpoint + verify (2 steps)."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Q1 release", "goal_type": "milestone"}])

    assert len(dag["steps"]) == 2
    step_types = [s["step_type"] for s in dag["steps"]]
    assert "human_checkpoint" in step_types
    assert "verification" in step_types


@pytest.mark.asyncio
async def test_strategy_type_decomposes_to_three_steps() -> None:
    """goal_type='strategy' maps to research + design + implement (3 steps)."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Adopt microservices", "goal_type": "strategy"}])

    assert len(dag["steps"]) == 3
    phases = [s["phase"] for s in dag["steps"]]
    assert phases == ["research", "design", "implement"]


@pytest.mark.asyncio
async def test_risk_type_decomposes_to_three_steps() -> None:
    """goal_type='risk' maps to assess + mitigate + verify (3 steps)."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "GDPR compliance risk", "goal_type": "risk"}])

    assert len(dag["steps"]) == 3
    phases = [s["phase"] for s in dag["steps"]]
    assert phases == ["assess", "mitigate", "verify"]


@pytest.mark.asyncio
async def test_unknown_type_falls_back_to_single_execute_step() -> None:
    """Unknown goal_type produces a single execute/task step."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Random thing", "goal_type": "unknown_type"}])

    assert len(dag["steps"]) == 1
    assert dag["steps"][0]["step_type"] == "task"
    assert dag["steps"][0]["phase"] == "execute"


@pytest.mark.asyncio
async def test_two_independent_goals_are_chained_sequentially() -> None:
    """Without explicit dependencies, goals are chained in order."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow(
        [
            {"title": "Set up CI", "goal_type": "milestone"},
            {"title": "Deploy to prod", "goal_type": "milestone"},
        ]
    )

    # 2 milestones × 2 steps each = 4 steps
    assert len(dag["steps"]) == 4

    # Should have a transition linking last step of goal1 → first step of goal2
    transitions = dag["transitions"]
    # Internal sequential transitions (within each milestone: 1 each) = 2
    # Plus the chain between goals = 1 → total 3
    assert len(transitions) >= 1

    # The chain transition should link across the two goals
    cross_chain = [t for t in transitions if t["label"] == "then" and "dep-" not in t["id"]]
    assert len(cross_chain) >= 1


@pytest.mark.asyncio
async def test_dependency_creates_dep_transition() -> None:
    """Explicit dependencies produce 'after' transitions between goals."""
    orch = UnifiedOrchestrator()
    goals = [
        {"id": "g1", "title": "First goal", "goal_type": "milestone"},
        {"id": "g2", "title": "Second goal", "goal_type": "milestone", "dependencies": ["g1"]},
    ]
    dag = await orch.goals_to_workflow(goals)

    dep_transitions = [t for t in dag["transitions"] if t["label"] == "after"]
    assert len(dep_transitions) == 1
    assert "g1" in dep_transitions[0]["id"]
    assert "g2" in dep_transitions[0]["id"]


@pytest.mark.asyncio
async def test_step_ids_are_unique() -> None:
    """Every step has a unique ID."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow(
        [
            {"title": "Goal A"},
            {"title": "Goal B"},
            {"title": "Goal C", "goal_type": "strategy"},
        ]
    )

    step_ids = [s["id"] for s in dag["steps"]]
    assert len(step_ids) == len(set(step_ids))


@pytest.mark.asyncio
async def test_step_names_include_goal_title() -> None:
    """Step names contain the original goal title."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Implement rate limiter"}])

    for step in dag["steps"]:
        assert "rate limiter" in step["name"].lower()


@pytest.mark.asyncio
async def test_priority_low_marks_steps_optional() -> None:
    """Low-priority goals produce optional steps."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Nice to have", "priority": "low"}])

    for step in dag["steps"]:
        assert step["optional"] is True


@pytest.mark.asyncio
async def test_priority_high_not_optional() -> None:
    """High-priority goals produce non-optional steps."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "Critical feature", "priority": "high"}])

    for step in dag["steps"]:
        assert step["optional"] is False


@pytest.mark.asyncio
async def test_workflow_id_is_unique_per_call() -> None:
    """Each call produces a DAG with a unique ID."""
    orch = UnifiedOrchestrator()
    dag1 = await orch.goals_to_workflow([{"title": "Goal"}])
    dag2 = await orch.goals_to_workflow([{"title": "Goal"}])
    assert dag1["id"] != dag2["id"]


@pytest.mark.asyncio
async def test_auto_generated_goal_id() -> None:
    """Goals without an explicit id get one auto-assigned."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "No ID goal"}])

    # All step source_goal_id values should be non-empty strings
    for step in dag["steps"]:
        assert step["source_goal_id"]


@pytest.mark.asyncio
async def test_metric_type_produces_three_steps() -> None:
    """goal_type='metric' maps to instrument + baseline + monitor (3 steps)."""
    orch = UnifiedOrchestrator()
    dag = await orch.goals_to_workflow([{"title": "P99 latency", "goal_type": "metric"}])

    assert len(dag["steps"]) == 3
    phases = [s["phase"] for s in dag["steps"]]
    assert phases == ["instrument", "baseline", "monitor"]
