"""Tests for the NomicPipelineBridge."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.nomic.pipeline_bridge import BoundedWorkOrder, NomicPipelineBridge
from aragora.nomic.task_decomposer import SubTask
from aragora.pipeline.execution_mode import ExecutionMode


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
        assert work_orders[0].target_agent in {"codex", "claude"}
        assert work_orders[0].reviewer_agent in {"codex", "claude"}
        assert work_orders[0].target_agent != work_orders[0].reviewer_agent
        assert work_orders[1].dependency_ids == ["task-1"]
        assert work_orders[1].risk_level in {"info", "review", "critical"}

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
        assert metadata["dispatch_handoff"]["target"] == "ralph"
        assert metadata["dispatch_handoff"]["receipt_metadata"]["handoff_status"] == "compiled"
        assert (
            metadata["dispatch_handoff"]["receipt_metadata"]["truth"]["manifest_written"] is False
        )
        assert metadata["dispatch_handoff"]["manifest"]["projects"][0]["project_id"] == "task-1"

    def test_build_plan_metadata_includes_assessment_refresh_scope(self):
        bridge = NomicPipelineBridge()
        subtasks = [
            SubTask(
                id="sub-1",
                title="Harden bridge feedback",
                description="Carry changed files into refresh context",
                file_scope=[
                    "aragora/nomic/pipeline_bridge.py",
                    "tests/nomic/test_pipeline_feedback.py",
                ],
                success_criteria={
                    "tests": ["python -m pytest tests/nomic/test_pipeline_feedback.py -q"]
                },
            ),
            SubTask(
                id="sub-2",
                title="Use refresh scope in planning",
                description="Inject changed files into the next assessment",
                file_scope=["aragora/nomic/pipeline_bridge.py", "aragora/nomic/meta_planner.py"],
                success_criteria={
                    "tests": "python -m pytest tests/nomic/test_pipeline_bridge.py -q"
                },
            ),
        ]

        metadata = bridge.build_plan_metadata("Tighten self-assessment cadence", subtasks)
        refresh = metadata["assessment_refresh"]

        assert refresh["required"] is True
        assert refresh["reason"] == "bounded_work_orders_changed_repo_truth"
        assert refresh["files_to_reassess"] == [
            "aragora/nomic/pipeline_bridge.py",
            "tests/nomic/test_pipeline_feedback.py",
            "aragora/nomic/meta_planner.py",
        ]
        assert refresh["test_commands"] == [
            "python -m pytest tests/nomic/test_pipeline_feedback.py -q",
            "python -m pytest tests/nomic/test_pipeline_bridge.py -q",
        ]
        assert refresh["work_order_ids"] == ["sub-1", "sub-2"]

    def test_build_work_orders_extracts_tests_and_approval_flag(self):
        bridge = NomicPipelineBridge()
        subtasks = [
            SubTask(
                id="sub-1",
                title="Harden CI workflow",
                description="Touch workflow policy files",
                file_scope=[".github/workflows/test.yml"],
                estimated_complexity="high",
                success_criteria={"tests": ["python -m pytest tests/scripts -q"]},
            )
        ]

        work_order = bridge.build_work_orders(subtasks)[0]

        assert work_order.expected_tests == ["python -m pytest tests/scripts -q"]
        assert work_order.risk_level == "critical"
        assert work_order.approval_required is True

    def test_bounded_work_order_serializes_mission_lineage(self):
        work_order = BoundedWorkOrder(
            work_order_id="sub-1",
            pipeline_task_id="task-1",
            title="Contract-aware preflight",
            description="Thread mission lineage into the work order",
            file_scope=["aragora/swarm/preflight.py"],
            mission_id="mission-rs-credential-envelope",
            stage_id="stage-contract-aware-preflight",
            assertion_ids=["RS-04-ASSERT-1"],
            roadmap_refs=["RS-04", "RS-05"],
            evidence_expectations=["validation_command", "worker_contract", "receipt"],
        )

        payload = work_order.to_dict()

        assert payload["mission_id"] == "mission-rs-credential-envelope"
        assert payload["stage_id"] == "stage-contract-aware-preflight"
        assert payload["assertion_ids"] == ["RS-04-ASSERT-1"]
        assert payload["roadmap_refs"] == ["RS-04", "RS-05"]
        assert payload["evidence_expectations"] == [
            "validation_command",
            "worker_contract",
            "receipt",
        ]
        assert set(payload["mission_context_policies"]) == {"worker", "validator"}

    def test_ralph_manifest_projects_inherit_mission_lineage(self):
        bridge = NomicPipelineBridge()
        work_order = BoundedWorkOrder(
            work_order_id="sub-1",
            pipeline_task_id="task-1",
            title="Contract-aware preflight",
            description="Thread mission lineage into the work order",
            file_scope=["aragora/swarm/preflight.py"],
            mission_id="mission-rs-credential-envelope",
            stage_id="stage-contract-aware-preflight",
            assertion_ids=["RS-04-ASSERT-1"],
            roadmap_refs=["RS-04"],
            evidence_expectations=["validation_command", "worker_contract", "receipt"],
        )

        manifest = bridge._build_ralph_manifest_for_work_order(
            "Improve dispatch readiness", work_order
        )
        spec = manifest.projects[0].spec

        assert spec.mission_id == "mission-rs-credential-envelope"
        assert spec.stage_id == "stage-contract-aware-preflight"
        assert spec.assertion_ids == ["RS-04-ASSERT-1"]
        assert spec.roadmap_refs == ["RS-04"]
        assert "worker_contract" in spec.evidence_expectations

    def test_write_ralph_handoff_persists_manifest_with_truthful_receipt_metadata(self, tmp_path):
        bridge = NomicPipelineBridge(repo_path=tmp_path)
        subtasks = [
            SubTask(
                id="sub-1",
                title="Bridge one spec",
                description="Connect a generated pipeline spec to Ralph",
                file_scope=[
                    "aragora/nomic/pipeline_bridge.py",
                    "tests/nomic/test_pipeline_bridge.py",
                ],
                success_criteria={
                    "tests": ["python3 -m pytest tests/nomic/test_pipeline_bridge.py -q"]
                },
            ),
            SubTask(
                id="sub-2",
                title="Dependent follow-up",
                description="Do the second phase after the first",
                dependencies=["sub-1"],
                file_scope=["docs/guides/PIPELINE_GUIDE.md"],
            ),
        ]

        handoff = bridge.write_ralph_handoff(
            "Dogfood the Nomic bridge",
            subtasks,
            output_dir=tmp_path / "ralph-handoff",
        )

        manifest_path = tmp_path / "ralph-handoff" / "campaign_manifest.yaml"
        assert manifest_path.exists()
        assert handoff["selection"]["reason"] == "first_dependency_free_work_order"
        assert handoff["manifest_path"] == str(manifest_path)
        assert handoff["receipt_metadata"]["handoff_status"] == "ready"
        assert handoff["receipt_metadata"]["selected_work_order_id"] == "sub-1"
        assert handoff["receipt_metadata"]["truth"]["handoff_compiled"] is True
        assert handoff["receipt_metadata"]["truth"]["manifest_written"] is True
        assert handoff["receipt_metadata"]["truth"]["dispatch_started"] is False
        assert handoff["receipt_metadata"]["worker_receipt_ids"] == []
        assert handoff["receipt_metadata"]["campaign_receipt_id"] is None
        assert handoff["receipt_metadata"]["expected_project_receipts"] == [
            f"docs/receipts/{handoff['manifest']['campaign_id']}/task-1.yaml"
        ]

        from aragora.swarm.campaign import CampaignManifest

        manifest = CampaignManifest.from_text(manifest_path.read_text(encoding="utf-8"))
        assert manifest.worker_model == "codex"
        assert manifest.review_model == "claude"
        assert manifest.projects[0].project_id == "task-1"
        assert manifest.projects[0].spec.work_orders[0]["work_order_id"] == "sub-1"
        assert manifest.projects[0].spec.acceptance_criteria == [
            "Run and satisfy: python3 -m pytest tests/nomic/test_pipeline_bridge.py -q"
        ]


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


class TestExecuteViaPipeline:
    @pytest.mark.asyncio
    async def test_execute_via_pipeline_routes_through_backbone_helper(self, tmp_path):
        bridge = NomicPipelineBridge(repo_path=tmp_path, execution_mode="workflow")
        plan = MagicMock()
        plan.id = "plan-nomic-1"
        plan.debate_id = "debate-nomic-1"
        plan.metadata = {
            "custom": "value",
            "source_surface": "spoofed",
            "source_id": "spoofed-id",
            "backbone_run_id": "run-spoofed",
            "backbone_entrypoint": "spoofed.entrypoint",
        }
        plan.implement_plan = SimpleNamespace(tasks=[MagicMock(), MagicMock()])
        outcome = MagicMock(
            success=True,
            tasks_completed=2,
            tasks_total=2,
            receipt_id="receipt-nomic-1",
        )
        launch = {
            "run_id": "run-nomic-1",
            "execution_id": "exec-nomic-1",
            "correlation_id": "corr-nomic-1",
        }

        with (
            patch.object(bridge, "build_decision_plan", return_value=plan) as mock_build,
            patch("aragora.pipeline.executor.PlanExecutor") as mock_executor_cls,
            patch(
                "aragora.pipeline.decision_integrity_utils.execute_decision_plan_with_backbone",
                new=AsyncMock(return_value=(launch, outcome)),
            ) as mock_execute,
        ):
            mock_executor = MagicMock()
            mock_executor_cls.return_value = mock_executor

            result = await bridge.execute_via_pipeline(
                goal="Harden pipeline bridge",
                subtasks=[],
                execution_mode="queued",
            )

        assert result is outcome
        mock_build.assert_called_once_with(
            goal="Harden pipeline bridge",
            subtasks=[],
            debate_result=None,
            dissent=None,
        )
        mock_executor_cls.assert_called_once_with(
            execution_mode="queued",
            repo_path=tmp_path,
        )
        mock_execute.assert_awaited_once_with(
            plan,
            executor=mock_executor,
            auth_context=None,
            execution_mode="queued",
            safety_mode=ExecutionMode.AUTONOMOUS,
        )
        assert plan.metadata["custom"] == "value"
        assert plan.metadata["source_surface"] == "nomic_pipeline_bridge"
        assert plan.metadata["source_id"] == "debate-nomic-1"
        assert "backbone_run_id" not in plan.metadata
        assert "backbone_entrypoint" not in plan.metadata

    @pytest.mark.asyncio
    async def test_execute_via_pipeline_uses_plan_id_when_debate_id_missing(self, tmp_path):
        bridge = NomicPipelineBridge(repo_path=tmp_path)
        plan = MagicMock()
        plan.id = "plan-nomic-2"
        plan.debate_id = None
        plan.metadata = {}
        plan.implement_plan = SimpleNamespace(tasks=[])
        outcome = MagicMock(
            success=True,
            tasks_completed=0,
            tasks_total=0,
            receipt_id=None,
        )

        with (
            patch.object(bridge, "build_decision_plan", return_value=plan),
            patch("aragora.pipeline.executor.PlanExecutor") as mock_executor_cls,
            patch(
                "aragora.pipeline.decision_integrity_utils.execute_decision_plan_with_backbone",
                new=AsyncMock(return_value=({"run_id": "run-nomic-2"}, outcome)),
            ),
        ):
            mock_executor_cls.return_value = MagicMock()
            await bridge.execute_via_pipeline(goal="Bridge fallback ids", subtasks=[])

        assert plan.metadata["source_surface"] == "nomic_pipeline_bridge"
        assert plan.metadata["source_id"] == "plan-nomic-2"
