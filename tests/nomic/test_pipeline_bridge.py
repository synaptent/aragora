"""Tests for the NomicPipelineBridge."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aragora.nomic.pipeline_bridge import NomicPipelineBridge
from aragora.nomic.task_decomposer import SubTask


def _make_mock_assignment(title, description, status="completed", file_scope=None, deps=None):
    subtask = MagicMock()
    subtask.id = f"st-{title[:8]}"
    subtask.title = title
    subtask.description = description
    subtask.estimated_complexity = "medium"
    subtask.file_scope = file_scope or []
    subtask.dependencies = deps or []
    assignment = MagicMock()
    assignment.subtask = subtask
    assignment.status = status
    assignment.agent_type = "implementer"
    assignment.track = MagicMock(value="core")
    return assignment


def _make_mock_cycle_result(goal="Improve tests", assignments=None):
    result = MagicMock()
    result.goal = goal
    result.summary = f"Summary: {goal}"
    result.success = True
    result.duration_seconds = 42.0
    result.improvement_score = 0.8
    result.assignments = assignments or [
        _make_mock_assignment("Fix flaky test", "Make test_leader_election reliable"),
        _make_mock_assignment(
            "Add coverage", "Add tests for pipeline bridge", file_scope=["tests/nomic/"]
        ),
    ]
    return result


class TestCycleResultToIdeas:
    def test_extracts_ideas_from_assignments(self):
        bridge = NomicPipelineBridge()
        cycle = _make_mock_cycle_result()
        ideas = bridge.cycle_result_to_ideas(cycle)
        # 1 for the goal + 1 per assignment
        assert len(ideas) == 3

    def test_idea_has_required_fields(self):
        bridge = NomicPipelineBridge()
        cycle = _make_mock_cycle_result()
        ideas = bridge.cycle_result_to_ideas(cycle)
        for idea in ideas:
            assert "id" in idea
            assert "label" in idea
            assert "description" in idea
            assert "idea_type" in idea

    def test_file_scoped_assignments_are_evidence(self):
        bridge = NomicPipelineBridge()
        assignments = [
            _make_mock_assignment("Task with files", "desc", file_scope=["src/foo.py"]),
        ]
        cycle = _make_mock_cycle_result(assignments=assignments)
        ideas = bridge.cycle_result_to_ideas(cycle)
        # The assignment-derived idea should be 'evidence' type
        assignment_ideas = [i for i in ideas if i["idea_type"] == "evidence"]
        assert len(assignment_ideas) >= 1


class TestDesignPhaseToGoals:
    def test_converts_design_to_goals(self):
        bridge = NomicPipelineBridge()
        design = {
            "goal": "Improve error handling",
            "rationale": "Current handlers leak stack traces",
            "subtasks": [
                {
                    "title": "Sanitize str(e)",
                    "description": "Replace with static messages",
                    "estimated_complexity": "low",
                },
                {
                    "title": "Add @handle_errors",
                    "description": "Decorator for all handlers",
                    "estimated_complexity": "medium",
                },
            ],
        }
        goals = bridge.design_phase_to_goals(design)
        assert len(goals) == 3  # 1 primary goal + 2 milestones

    def test_empty_design_returns_empty(self):
        bridge = NomicPipelineBridge()
        goals = bridge.design_phase_to_goals({})
        assert goals == []


class TestBoundedWorkOrders:
    def test_build_work_orders_preserves_scope_and_dependencies(self):
        bridge = NomicPipelineBridge()
        subtasks = [
            SubTask(
                id="sub-1",
                title="Harden auth",
                description="Harden auth checks",
                file_scope=["aragora/server/auth_checks.py"],
                success_criteria={"tests": ["python -m pytest tests/auth -q"]},
            ),
            SubTask(
                id="sub-2",
                title="Add tests",
                description="Add auth tests",
                dependencies=["sub-1"],
                file_scope=["tests/auth/test_auth_checks.py"],
            ),
        ]

        work_orders = bridge.build_work_orders(subtasks)

        assert len(work_orders) == 2
        assert work_orders[0].pipeline_task_id == "task-1"
        assert work_orders[0].file_scope == ["aragora/server/auth_checks.py"]
        assert work_orders[1].dependency_ids == ["task-1"]

    def test_build_plan_metadata_includes_protocol_and_orders(self):
        bridge = NomicPipelineBridge()
        subtasks = [
            SubTask(
                id="sub-1",
                title="Receipt gate",
                description="Add bounded work order metadata",
                file_scope=["aragora/nomic/pipeline_bridge.py"],
            )
        ]

        metadata = bridge.build_plan_metadata("Improve self-improvement execution", subtasks)

        assert metadata["work_order_protocol"] == "bounded-work-order/v1"
        assert metadata["subtask_count"] == 1
        assert metadata["bounded_work_orders"][0]["work_order_id"] == "sub-1"


class TestCreatePipelineFromCycle:
    def test_creates_graph_with_all_stages(self):
        bridge = NomicPipelineBridge()
        cycle = _make_mock_cycle_result()
        graph = bridge.create_pipeline_from_cycle(cycle)

        assert graph is not None
        assert len(graph.nodes) >= 2
        assert len(graph.edges) >= 1
        assert graph.metadata["source"] == "nomic_loop"

    def test_graph_has_cross_stage_edges(self):
        bridge = NomicPipelineBridge()
        cycle = _make_mock_cycle_result()
        graph = bridge.create_pipeline_from_cycle(cycle)

        # Should have at least one cross-stage edge (idea -> goal)
        assert len(graph.edges) >= 1
