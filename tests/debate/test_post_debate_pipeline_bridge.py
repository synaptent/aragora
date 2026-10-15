"""Tests for the debate-to-pipeline bridge in PostDebateCoordinator.

Verifies that:
1. auto_trigger_canvas is disabled by default
2. Confidence threshold is respected
3. Pipeline is created when conditions are met
4. _build_cartographer_data converts debate results correctly
5. Import errors are handled gracefully
6. pipeline_id is set on PostDebateResult
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from aragora.debate.pipeline_backends import pipeline_backend
from aragora.debate.post_debate_coordinator import (
    PostDebateConfig,
    PostDebateCoordinator,
    PostDebateResult,
)


def _make_debate_result(
    messages=None,
    consensus=None,
    confidence=0.9,
):
    """Create a mock debate result for pipeline bridge tests."""
    result = MagicMock()
    result.messages = messages or []
    result.consensus = consensus
    result.confidence = confidence
    result.task = "test task"
    result.domain = "general"
    result.participants = []
    result.final_answer = "test answer"
    return result


def _make_message(content="test", agent="claude", round_num=1, msg_type=None):
    """Create a mock debate message."""
    msg = MagicMock()
    msg.content = content
    msg.agent = agent
    msg.round = round_num
    msg.type = msg_type
    msg.message_type = None
    msg.role = "proposal"
    return msg


class TestAutoTriggerConfig:
    """Test auto_trigger_canvas configuration."""

    def test_enabled_by_default(self):
        config = PostDebateConfig()
        assert config.auto_trigger_canvas is True

    def test_canvas_min_confidence_default(self):
        config = PostDebateConfig()
        assert config.canvas_min_confidence == 0.7

    def test_can_disable(self):
        config = PostDebateConfig(auto_trigger_canvas=False)
        assert config.auto_trigger_canvas is False


class TestPipelineIdField:
    """Test pipeline_id field on PostDebateResult."""

    def test_pipeline_id_defaults_to_none(self):
        result = PostDebateResult()
        assert result.pipeline_id is None

    def test_pipeline_id_can_be_set(self):
        result = PostDebateResult(pipeline_id="pipe-abc123")
        assert result.pipeline_id == "pipe-abc123"


class TestConfidenceThreshold:
    """Test that canvas pipeline respects confidence threshold."""

    def test_low_confidence_does_not_trigger(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.8,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        debate_result = _make_debate_result()

        result = coordinator.run(
            debate_id="test-1",
            debate_result=debate_result,
            agents=[],
            confidence=0.5,
            task="test",
        )
        assert result.pipeline_id is None
        assert result.canvas_result is None

    def test_high_confidence_triggers(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.5,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        msg = _make_message(
            "Build a rate limiter", agent="claude", round_num=1, msg_type="proposal"
        )
        debate_result = _make_debate_result(
            messages=[msg],
            consensus=MagicMock(text="Agreed to build rate limiter"),
        )

        mock_pipeline_result = MagicMock()
        mock_pipeline_result.pipeline_id = "pipe-test-123"
        mock_pipeline_result.stage_status = {"ideas": "complete", "goals": "complete"}

        with patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.from_debate.return_value = mock_pipeline_result
            MockPipeline.return_value = mock_instance

            result = coordinator.run(
                debate_id="test-2",
                debate_result=debate_result,
                agents=[],
                confidence=0.9,
                task="test",
            )

            assert result.pipeline_id == "pipe-test-123"
            assert result.canvas_result is not None
            assert result.canvas_result["pipeline_id"] == "pipe-test-123"


class TestAutoTriggerCreatesPipeline:
    """Test that the pipeline is actually created and invoked."""

    def test_pipeline_from_debate_called_with_cartographer_data(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.0,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        msg = _make_message("We should use Redis", agent="gpt", round_num=1)
        debate_result = _make_debate_result(messages=[msg])

        mock_pipeline_result = MagicMock()
        mock_pipeline_result.pipeline_id = "pipe-xyz"
        mock_pipeline_result.stage_status = {}

        with patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.from_debate.return_value = mock_pipeline_result
            MockPipeline.return_value = mock_instance

            # Also patch out ArgumentCartographer so we use _build_cartographer_data
            with patch.dict(
                "sys.modules",
                {"aragora.visualization.mapper": None},
            ):
                result = coordinator.run(
                    debate_id="test-3",
                    debate_result=debate_result,
                    agents=[],
                    confidence=1.0,
                    task="test",
                )

            mock_instance.from_debate.assert_called_once()
            call_kwargs = mock_instance.from_debate.call_args
            cartographer_data = call_kwargs[1].get("cartographer_data") or call_kwargs[0][0]
            assert "nodes" in cartographer_data
            assert len(cartographer_data["nodes"]) >= 1
            assert result.pipeline_id == "pipe-xyz"

    def test_stages_completed_captured(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.0,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        msg = _make_message("test message")
        debate_result = _make_debate_result(messages=[msg])

        mock_pipeline_result = MagicMock()
        mock_pipeline_result.pipeline_id = "pipe-stages"
        mock_pipeline_result.stage_status = {
            "ideas": "complete",
            "goals": "complete",
            "actions": "pending",
            "orchestration": "pending",
        }

        with patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline:
            mock_instance = MagicMock()
            mock_instance.from_debate.return_value = mock_pipeline_result
            MockPipeline.return_value = mock_instance

            result = coordinator.run(
                debate_id="test-4",
                debate_result=debate_result,
                agents=[],
                confidence=1.0,
                task="test",
            )

            assert "ideas" in result.canvas_result["stages_completed"]
            assert "goals" in result.canvas_result["stages_completed"]
            assert "actions" not in result.canvas_result["stages_completed"]


class TestBuildCartographerData:
    """Test _build_cartographer_data static method."""

    def test_from_messages(self):
        debate_result = _make_debate_result(
            messages=[
                _make_message(
                    "We should build X", agent="claude", round_num=1, msg_type="proposal"
                ),
                _make_message("Evidence supports X", agent="gpt", round_num=1, msg_type="evidence"),
            ],
            consensus=MagicMock(text="Agreed on X"),
        )

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert "nodes" in data
        assert "edges" in data
        # 2 messages + 1 consensus = 3 nodes
        assert len(data["nodes"]) == 3
        assert data["nodes"][0]["type"] == "proposal"
        assert data["nodes"][1]["type"] == "evidence"
        assert data["nodes"][2]["type"] == "consensus"
        assert data["nodes"][2]["id"] == "debate-consensus"

    def test_from_messages_critique_type(self):
        debate_result = _make_debate_result(
            messages=[
                _make_message("critique of X", agent="gpt", msg_type="critique"),
            ],
        )

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["type"] == "critique"

    def test_edges_sequential(self):
        debate_result = _make_debate_result(
            messages=[
                _make_message("msg1", agent="a"),
                _make_message("msg2", agent="b"),
                _make_message("msg3", agent="c"),
            ],
        )

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert len(data["edges"]) == 2
        assert data["edges"][0]["source_id"] == "debate-msg-0"
        assert data["edges"][0]["target_id"] == "debate-msg-1"
        assert data["edges"][1]["source_id"] == "debate-msg-1"
        assert data["edges"][1]["target_id"] == "debate-msg-2"
        assert data["edges"][0]["relation"] == "responds_to"

    def test_empty_messages(self):
        debate_result = _make_debate_result(messages=[], consensus=None)

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert data["nodes"] == []
        assert data["edges"] == []

    def test_consensus_without_text_attr(self):
        """Test consensus that is a plain string."""
        consensus = MagicMock(spec=[])  # No text/summary attrs
        debate_result = _make_debate_result(messages=[], consensus=consensus)

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["type"] == "consensus"
        assert data["nodes"][0]["id"] == "debate-consensus"

    def test_message_content_truncated_in_summary(self):
        long_content = "A" * 200
        debate_result = _make_debate_result(
            messages=[_make_message(long_content)],
        )

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert len(data["nodes"][0]["summary"]) == 100
        assert len(data["nodes"][0]["content"]) == 200

    def test_agent_and_round_preserved(self):
        debate_result = _make_debate_result(
            messages=[_make_message("test", agent="gemini", round_num=3)],
        )

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert data["nodes"][0]["agent"] == "gemini"
        assert data["nodes"][0]["round"] == 3

    def test_none_messages_attribute(self):
        """Handle debate_result with messages=None."""
        debate_result = MagicMock()
        debate_result.messages = None
        debate_result.consensus = None

        data = PostDebateCoordinator._build_cartographer_data(debate_result)

        assert data["nodes"] == []
        assert data["edges"] == []


class TestGracefulErrorHandling:
    """Test that pipeline failures are handled gracefully."""

    def test_import_error_does_not_raise(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.0,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        msg = _make_message("test", agent="a", round_num=1)
        debate_result = _make_debate_result(messages=[msg])
        # The declared registrations run once per process; register before hiding a module.
        pipeline_backend()

        with patch.dict("sys.modules", {"aragora.pipeline.idea_to_execution": None}):
            result = coordinator.run(
                debate_id="test-err",
                debate_result=debate_result,
                agents=[],
                confidence=1.0,
                task="test",
            )
            assert result is not None
            assert result.pipeline_id is None

    def test_pipeline_runtime_error_appends_to_errors(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.0,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        msg = _make_message("test")
        debate_result = _make_debate_result(messages=[msg])

        with patch("aragora.pipeline.idea_to_execution.IdeaToExecutionPipeline") as MockPipeline:
            MockPipeline.side_effect = RuntimeError("pipeline broke")

            result = coordinator.run(
                debate_id="test-runtime",
                debate_result=debate_result,
                agents=[],
                confidence=1.0,
                task="test",
            )

            # RuntimeError caught in _step_trigger_canvas
            assert result.pipeline_id is None
            # canvas_result should be None (error handled internally)
            assert result.canvas_result is None

    def test_no_nodes_returns_none(self):
        config = PostDebateConfig(
            auto_trigger_canvas=True,
            canvas_min_confidence=0.0,
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_persist_receipt=False,
            auto_gauntlet_validate=False,
            auto_queue_improvement=False,
            auto_outcome_feedback=False,
            auto_execution_bridge=False,
            auto_push_calibration=False,
        )
        coordinator = PostDebateCoordinator(config=config)
        debate_result = _make_debate_result(messages=[], consensus=None)

        result = coordinator.run(
            debate_id="test-empty",
            debate_result=debate_result,
            agents=[],
            confidence=1.0,
            task="test",
        )

        assert result.pipeline_id is None
        assert result.canvas_result is None


class TestDisabledExplicitly:
    """Test that the bridge does not fire when auto_trigger_canvas is explicitly off."""

    def test_explicitly_disabled_does_not_trigger(self):
        config = PostDebateConfig(auto_trigger_canvas=False)
        coordinator = PostDebateCoordinator(config=config)
        msg = _make_message("test", agent="claude")
        debate_result = _make_debate_result(messages=[msg])

        result = coordinator.run(
            debate_id="test-default",
            debate_result=debate_result,
            agents=[],
            confidence=0.99,
            task="test",
        )

        assert result.pipeline_id is None
