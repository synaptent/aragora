"""
Unit tests for Phase 2 Workflow Builder components.

Tests the visual workflow builder infrastructure:
- Extended workflow types with visual metadata
- New step types (HumanCheckpoint, Memory, Debate, Decision, Task)
- YAML serialization
- Workflow validation
"""

import asyncio
import pytest
import tempfile
from datetime import datetime
from pathlib import Path

from aragora.workflow.types import (
    Position,
    NodeSize,
    VisualNodeData,
    VisualEdgeData,
    CanvasSettings,
    NodeCategory,
    EdgeType,
    WorkflowCategory,
    StepDefinition,
    TransitionRule,
    WorkflowDefinition,
    ExecutionPattern,
)
from aragora.workflow.engine import WorkflowEngine
from aragora.workflow.step import WorkflowContext


class TestVisualTypes:
    """Tests for visual metadata types."""

    def test_position_serialization(self):
        """Test Position to_dict and from_dict."""
        pos = Position(x=100.0, y=200.0)
        data = pos.to_dict()
        assert data == {"x": 100.0, "y": 200.0}

        restored = Position.from_dict(data)
        assert restored.x == 100.0
        assert restored.y == 200.0

    def test_node_size_serialization(self):
        """Test NodeSize to_dict and from_dict."""
        size = NodeSize(width=300.0, height=150.0)
        data = size.to_dict()
        assert data == {"width": 300.0, "height": 150.0}

        restored = NodeSize.from_dict(data)
        assert restored.width == 300.0
        assert restored.height == 150.0

    def test_visual_node_data_serialization(self):
        """Test VisualNodeData serialization."""
        visual = VisualNodeData(
            position=Position(50, 100),
            size=NodeSize(250, 120),
            category=NodeCategory.AGENT,
            color="#4299e1",
            icon="user",
            collapsed=False,
        )

        data = visual.to_dict()
        assert data["position"]["x"] == 50
        assert data["category"] == "agent"
        assert data["color"] == "#4299e1"

        restored = VisualNodeData.from_dict(data)
        assert restored.position.x == 50
        assert restored.category == NodeCategory.AGENT

    def test_visual_edge_data_serialization(self):
        """Test VisualEdgeData serialization."""
        edge = VisualEdgeData(
            edge_type=EdgeType.CONDITIONAL,
            label="If approved",
            animated=True,
            color="#48bb78",
        )

        data = edge.to_dict()
        assert data["edge_type"] == "conditional"
        assert data["label"] == "If approved"
        assert data["animated"] is True

        restored = VisualEdgeData.from_dict(data)
        assert restored.edge_type == EdgeType.CONDITIONAL

    def test_canvas_settings_serialization(self):
        """Test CanvasSettings serialization."""
        canvas = CanvasSettings(
            width=5000.0,
            height=4000.0,
            zoom=0.8,
            grid_size=25.0,
            snap_to_grid=True,
        )

        data = canvas.to_dict()
        assert data["width"] == 5000.0
        assert data["grid_size"] == 25.0

        restored = CanvasSettings.from_dict(data)
        assert restored.width == 5000.0
        assert restored.snap_to_grid is True


class TestExtendedStepDefinition:
    """Tests for extended StepDefinition."""

    def test_step_with_visual_metadata(self):
        """Test StepDefinition includes visual metadata."""
        step = StepDefinition(
            id="step_1",
            name="Test Step",
            step_type="agent",
            visual=VisualNodeData(
                position=Position(100, 200),
                category=NodeCategory.AGENT,
            ),
            description="A test step",
            inputs={"query": "string"},
            outputs={"response": "string"},
        )

        data = step.to_dict()
        assert "visual" in data
        assert data["visual"]["position"]["x"] == 100
        assert data["visual"]["category"] == "agent"
        assert data["description"] == "A test step"

    def test_step_from_dict_with_visual(self):
        """Test StepDefinition from_dict preserves visual metadata."""
        data = {
            "id": "step_1",
            "name": "Test Step",
            "step_type": "task",
            "visual": {
                "position": {"x": 300, "y": 400},
                "category": "task",
                "color": "#48bb78",
            },
        }

        step = StepDefinition.from_dict(data)
        assert step.visual.position.x == 300
        assert step.visual.category == NodeCategory.TASK
        assert step.visual.color == "#48bb78"


class TestExtendedTransitionRule:
    """Tests for extended TransitionRule."""

    def test_transition_with_visual_metadata(self):
        """Test TransitionRule includes visual edge data."""
        transition = TransitionRule(
            id="trans_1",
            from_step="step_a",
            to_step="step_b",
            condition="outputs.success == True",
            visual=VisualEdgeData(
                edge_type=EdgeType.CONDITIONAL,
                label="Success",
                animated=True,
            ),
            label="On Success",
        )

        data = transition.to_dict()
        assert "visual" in data
        assert data["visual"]["edge_type"] == "conditional"
        assert data["label"] == "On Success"


class TestExtendedWorkflowDefinition:
    """Tests for extended WorkflowDefinition."""

    def test_workflow_with_canvas_and_category(self):
        """Test WorkflowDefinition includes canvas and category."""
        workflow = WorkflowDefinition(
            id="wf_test",
            name="Test Workflow",
            description="A test workflow",
            category=WorkflowCategory.LEGAL,
            tags=["test", "legal"],
            canvas=CanvasSettings(width=6000, height=4000),
            steps=[
                StepDefinition(id="step_1", name="Step 1", step_type="task"),
            ],
        )

        data = workflow.to_dict()
        assert data["category"] == "legal"
        assert "test" in data["tags"]
        assert data["canvas"]["width"] == 6000

    def test_workflow_yaml_serialization(self):
        """Test workflow YAML serialization roundtrip."""
        workflow = WorkflowDefinition(
            id="wf_yaml_test",
            name="YAML Test",
            category=WorkflowCategory.CODE,
            steps=[
                StepDefinition(
                    id="step_1",
                    name="Code Review",
                    step_type="agent",
                    visual=VisualNodeData(position=Position(100, 100)),
                ),
            ],
        )

        yaml_str = workflow.to_yaml()
        assert "wf_yaml_test" in yaml_str
        assert "Code Review" in yaml_str

        restored = WorkflowDefinition.from_yaml(yaml_str)
        assert restored.id == "wf_yaml_test"
        assert restored.steps[0].name == "Code Review"
        assert restored.steps[0].visual.position.x == 100

    def test_workflow_validation_valid(self):
        """Test workflow validation passes for valid workflow."""
        workflow = WorkflowDefinition(
            id="wf_valid",
            name="Valid Workflow",
            steps=[
                StepDefinition(id="step_1", name="Step 1", step_type="task", next_steps=["step_2"]),
                StepDefinition(id="step_2", name="Step 2", step_type="task"),
            ],
            entry_step="step_1",
        )

        is_valid, errors = workflow.validate()
        assert is_valid
        assert len(errors) == 0

    def test_workflow_validation_invalid(self):
        """Test workflow validation catches errors."""
        workflow = WorkflowDefinition(
            id="",  # Missing ID
            name="",  # Missing name
            steps=[],  # No steps
            entry_step="nonexistent",
        )

        is_valid, errors = workflow.validate()
        assert not is_valid
        assert "Workflow ID is required" in errors
        assert "Workflow name is required" in errors
        assert "Workflow must have at least one step" in errors

    def test_workflow_clone(self):
        """Test workflow cloning."""
        original = WorkflowDefinition(
            id="wf_original",
            name="Original",
            is_template=True,
            steps=[
                StepDefinition(id="step_1", name="Step", step_type="task"),
            ],
        )

        cloned = original.clone(new_name="Cloned Workflow")
        assert cloned.id != original.id
        assert cloned.name == "Cloned Workflow"
        assert cloned.is_template is False
        assert cloned.template_id == "wf_original"
        assert len(cloned.steps) == 1


class TestWorkflowEngineStepTypes:
    """Tests for new step types registered in WorkflowEngine."""

    def test_engine_registers_new_step_types(self):
        """Test WorkflowEngine registers Phase 2 step types."""
        engine = WorkflowEngine()

        # Check original step types
        assert "agent" in engine._step_types
        assert "parallel" in engine._step_types
        assert "conditional" in engine._step_types
        assert "loop" in engine._step_types

        # Check Phase 2 step types
        assert "human_checkpoint" in engine._step_types
        assert "memory_read" in engine._step_types
        assert "memory_write" in engine._step_types
        assert "debate" in engine._step_types
        assert "decision" in engine._step_types
        assert "task" in engine._step_types
        assert "switch" in engine._step_types
        assert "quick_debate" in engine._step_types


class TestDecisionStep:
    """Tests for DecisionStep."""

    @pytest.mark.asyncio
    async def test_decision_step_condition_matching(self):
        """Test DecisionStep evaluates conditions correctly."""
        from aragora.workflow.nodes.decision import DecisionStep

        step = DecisionStep(
            name="Test Decision",
            config={
                "conditions": [
                    {
                        "name": "high_score",
                        "expression": "outputs.get('analysis', {}).get('score', 0) > 80",
                        "next_step": "approve",
                    },
                    {
                        "name": "medium_score",
                        "expression": "outputs.get('analysis', {}).get('score', 0) > 50",
                        "next_step": "review",
                    },
                ],
                "default_branch": "reject",
            },
        )

        # Test high score
        context = WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            step_outputs={"analysis": {"score": 85}},
        )
        result = await step.execute(context)
        assert result["decision"] == "approve"
        assert result["decision_name"] == "high_score"

        # Test medium score
        context.step_outputs = {"analysis": {"score": 60}}
        result = await step.execute(context)
        assert result["decision"] == "review"

        # Test low score (default)
        context.step_outputs = {"analysis": {"score": 30}}
        result = await step.execute(context)
        assert result["decision"] == "reject"
        assert result["decision_name"] == "default"


class TestSwitchStep:
    """Tests for SwitchStep."""

    @pytest.mark.asyncio
    async def test_switch_step_routing(self):
        """Test SwitchStep routes based on value."""
        from aragora.workflow.nodes.decision import SwitchStep

        step = SwitchStep(
            name="Category Router",
            config={
                "value": "inputs.category",
                "cases": {
                    "legal": "legal_review",
                    "technical": "tech_review",
                    "financial": "finance_review",
                },
                "default": "general_review",
            },
        )

        # Test legal category
        context = WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs={"category": "legal"},
        )
        result = await step.execute(context)
        assert result["next_step"] == "legal_review"

        # Test unknown category
        context.inputs = {"category": "unknown"}
        result = await step.execute(context)
        assert result["next_step"] == "general_review"


class TestTaskStep:
    """Tests for TaskStep."""

    @pytest.mark.asyncio
    async def test_task_step_transform(self):
        """Test TaskStep transform operation."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Transform Data",
            config={
                "task_type": "transform",
                "transform": "[x.upper() for x in inputs.get('items', [])]",
                "output_format": "list",
            },
        )

        context = WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs={"items": ["hello", "world"]},
        )

        result = await step.execute(context)
        assert result["success"] is True
        assert result["result"] == ["HELLO", "WORLD"]

    @pytest.mark.asyncio
    async def test_task_step_validate(self):
        """Test TaskStep validation operation."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Validate Input",
            config={
                "task_type": "validate",
                "data": "inputs",
                "validation": {
                    "name": {"required": True, "type": "string", "min_length": 2},
                    "age": {"required": True, "type": "int", "min": 0, "max": 150},
                },
            },
        )

        # Valid input
        context = WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs={"name": "John", "age": 30},
        )
        result = await step.execute(context)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

        # Invalid input
        context.inputs = {"name": "J", "age": 200}
        result = await step.execute(context)
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    @pytest.mark.asyncio
    async def test_task_step_aggregate(self):
        """Test TaskStep aggregate operation."""
        from aragora.workflow.nodes.task import TaskStep

        step = TaskStep(
            name="Aggregate Results",
            config={
                "task_type": "aggregate",
                "inputs": ["step_a", "step_b"],
                "mode": "merge",
            },
        )

        context = WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            step_outputs={
                "step_a": {"result_a": 1},
                "step_b": {"result_b": 2},
            },
        )

        result = await step.execute(context)
        assert result["success"] is True
        assert result["result"]["result_a"] == 1
        assert result["result"]["result_b"] == 2


class TestHumanCheckpointStep:
    """Tests for HumanCheckpointStep."""

    @pytest.mark.asyncio
    async def test_human_checkpoint_auto_approve(self):
        """Test HumanCheckpointStep auto-approval condition."""
        from aragora.workflow.nodes.human_checkpoint import HumanCheckpointStep

        step = HumanCheckpointStep(
            name="Auto-Approve Test",
            config={
                "title": "Test Approval",
                "auto_approve_if": "inputs.get('risk_level', 1) < 0.5",
            },
        )

        # Low risk - should auto-approve
        context = WorkflowContext(
            workflow_id="wf_test",
            definition_id="def_test",
            inputs={"risk_level": 0.2},
        )
        context.current_step_id = "approval_step"
        context.current_step_config = {}

        result = await step.execute(context)
        assert result["status"] == "approved"
        assert result["auto_approved"] is True


class TestWebSocketEvents:
    """Tests for workflow WebSocket events."""

    def test_workflow_events_defined(self):
        """Test workflow events are defined in StreamEventType."""
        from aragora.events.types import StreamEventType

        # Core workflow events
        assert hasattr(StreamEventType, "WORKFLOW_START")
        assert hasattr(StreamEventType, "WORKFLOW_STEP_START")
        assert hasattr(StreamEventType, "WORKFLOW_STEP_COMPLETE")
        assert hasattr(StreamEventType, "WORKFLOW_COMPLETE")

        # Human approval events
        assert hasattr(StreamEventType, "WORKFLOW_HUMAN_APPROVAL_REQUIRED")
        assert hasattr(StreamEventType, "WORKFLOW_HUMAN_APPROVAL_RECEIVED")

        # Debate events
        assert hasattr(StreamEventType, "WORKFLOW_DEBATE_START")
        assert hasattr(StreamEventType, "WORKFLOW_DEBATE_COMPLETE")

        # Memory events
        assert hasattr(StreamEventType, "WORKFLOW_MEMORY_READ")
        assert hasattr(StreamEventType, "WORKFLOW_MEMORY_WRITE")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
