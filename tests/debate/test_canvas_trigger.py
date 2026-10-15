"""Tests for canvas pipeline trigger in PostDebateCoordinator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.debate.pipeline_backends import pipeline_backend
from aragora.debate.post_debate_coordinator import (
    PostDebateConfig,
    PostDebateCoordinator,
)


class TestCanvasTriggerConfig:
    """Canvas trigger configuration in PostDebateConfig."""

    def test_canvas_default_on(self):
        config = PostDebateConfig()
        assert config.auto_trigger_canvas is True

    def test_canvas_min_confidence_default(self):
        config = PostDebateConfig()
        assert config.canvas_min_confidence == 0.7

    def test_canvas_disabled(self):
        config = PostDebateConfig(auto_trigger_canvas=False)
        assert config.auto_trigger_canvas is False

    def test_canvas_result_field_exists(self):
        from aragora.debate.post_debate_coordinator import PostDebateResult

        result = PostDebateResult()
        assert result.canvas_result is None


class TestCanvasTriggerStep:
    """Tests for _step_trigger_canvas method."""

    def test_trigger_canvas_with_debate_messages(self):
        config = PostDebateConfig(auto_trigger_canvas=True, canvas_min_confidence=0.5)
        coordinator = PostDebateCoordinator(config=config)

        # Mock debate result with messages
        msg = MagicMock()
        msg.agent = "claude"
        msg.content = "We should refactor the auth module"
        msg.role = "proposal"
        msg.round = 1
        debate_result = MagicMock()
        debate_result.messages = [msg]

        mock_cartographer = MagicMock()
        mock_cartographer.nodes = [{"id": "n1"}]
        mock_cartographer.export.return_value = {"nodes": [{"id": "n1"}]}

        mock_pipeline = MagicMock()
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.pipeline_id = "pipe_123"
        mock_pipeline_result.stage_status = {"ideas": "complete", "goals": "complete"}
        mock_pipeline.from_debate.return_value = mock_pipeline_result

        with (
            patch(
                "aragora.visualization.mapper.ArgumentCartographer",
                return_value=mock_cartographer,
            ),
            patch(
                "aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline",
                return_value=mock_pipeline,
            ),
        ):
            result = coordinator._step_trigger_canvas("d1", debate_result, "test task")

        assert result is not None
        assert result["debate_id"] == "d1"
        assert result["pipeline_id"] == "pipe_123"
        assert "ideas" in result["stages_completed"]
        assert "goals" in result["stages_completed"]

    def test_trigger_canvas_skips_empty_debate(self):
        config = PostDebateConfig(auto_trigger_canvas=True)
        coordinator = PostDebateCoordinator(config=config)

        debate_result = MagicMock()
        debate_result.messages = []
        # Explicitly set consensus to None so _build_cartographer_data
        # doesn't auto-create nodes from MagicMock's auto-attributes
        debate_result.consensus = None

        mock_cartographer = MagicMock()
        mock_cartographer.nodes = []  # No nodes extracted

        with (
            patch(
                "aragora.visualization.mapper.ArgumentCartographer",
                return_value=mock_cartographer,
            ),
            patch(
                "aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline",
            ),
        ):
            result = coordinator._step_trigger_canvas("d1", debate_result, "test")

        assert result is None

    def test_trigger_canvas_graceful_on_import_error(self):
        config = PostDebateConfig(auto_trigger_canvas=True)
        coordinator = PostDebateCoordinator(config=config)
        # The declared registrations run once per process; register before hiding a module.
        pipeline_backend()

        with patch.dict("sys.modules", {"aragora.pipeline.idea_to_execution": None}):
            result = coordinator._step_trigger_canvas("d1", MagicMock(), "test")

        assert result is None

    def test_canvas_not_triggered_when_disabled(self):
        config = PostDebateConfig(
            auto_trigger_canvas=False,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_push_calibration=False,
            auto_execution_bridge=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        debate_result = MagicMock()
        result = coordinator.run("d1", debate_result, confidence=0.9)
        assert result.canvas_result is None

    def test_canvas_not_triggered_below_confidence(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.8,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_push_calibration=False,
            auto_execution_bridge=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        debate_result = MagicMock()
        result = coordinator.run("d1", debate_result, confidence=0.5)
        assert result.canvas_result is None

    def test_canvas_triggered_in_pipeline_at_correct_position(self):
        """Canvas trigger fires after outcome feedback, before execution bridge."""
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.5,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_push_calibration=False,
            auto_execution_bridge=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        mock_cartographer = MagicMock()
        mock_cartographer.nodes = [{"id": "n1"}]
        mock_cartographer.export.return_value = {"nodes": [{"id": "n1"}]}

        mock_pipeline = MagicMock()
        mock_pipeline_result = MagicMock()
        mock_pipeline_result.pipeline_id = "p1"
        mock_pipeline_result.stage_status = {}
        mock_pipeline.from_debate.return_value = mock_pipeline_result

        msg = MagicMock()
        msg.agent = "claude"
        msg.content = "proposal"
        msg.role = "proposal"
        msg.round = 1
        debate_result = MagicMock()
        debate_result.messages = [msg]

        with (
            patch(
                "aragora.visualization.mapper.ArgumentCartographer",
                return_value=mock_cartographer,
            ),
            patch(
                "aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline",
                return_value=mock_pipeline,
            ),
        ):
            result = coordinator.run("d1", debate_result, confidence=0.9)

        assert result.canvas_result is not None
