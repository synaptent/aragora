"""Tests for Post-Debate Workflow Automation Subscriber.

``PostDebateWorkflowSubscriber`` relocated from infrastructure
``aragora.events.subscribers.workflow_automation`` to its application home
``aragora.workflow.event_subscribers`` (P4a Batch E5 relocate-UP); this test
module was repointed in place rather than moved (same precedent as
``TestBudgetAlertToTeamSelection`` in ``tests/events/test_strategic_handlers.py``
for the P4a Batch E4 relocation). Registration/dispatch coverage for the
``WorkflowEventSubscriber`` home (incl. the exactly-once invocation-count
acceptance test) lives in ``tests/workflow/test_event_subscribers.py``.

Tests cover:
- Outcome classification (high/low confidence, no consensus, timeout)
- Workflow template mapping and triggering
- Custom workflow map overrides
- Stats tracking (events_processed, workflows_triggered, errors)
- Graceful degradation when workflow definition types are unavailable
- Handling of malformed event data without crashing
"""

import pytest
from unittest.mock import MagicMock, patch

from aragora.workflow.event_subscribers import (
    OUTCOME_WORKFLOW_MAP,
    PostDebateWorkflowSubscriber,
    get_post_debate_subscriber,
)
from aragora.events.types import StreamEvent, StreamEventType


def make_debate_end_event(data: dict | None = None) -> StreamEvent:
    """Create a DEBATE_END StreamEvent for testing."""
    return StreamEvent(
        type=StreamEventType.DEBATE_END,
        data=data or {},
    )


class TestPostDebateWorkflowSubscriber:
    """Test PostDebateWorkflowSubscriber."""

    def test_high_confidence_consensus_triggers_implement(self):
        """High-confidence consensus should trigger post_debate_implement workflow."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event(
            {
                "debate_id": "debate-123",
                "consensus_reached": True,
                "confidence": 0.9,
                "task": "Design a rate limiter",
                "winning_position": "Token bucket algorithm",
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        mock_trigger.assert_called_once()
        args = mock_trigger.call_args
        assert args[0][0] == "post_debate_implement"
        context = args[0][1]
        assert context["outcome"] == "consensus_high_confidence"
        assert context["debate_id"] == "debate-123"
        assert context["confidence"] == 0.9

    def test_low_confidence_consensus_triggers_review(self):
        """Low-confidence consensus should trigger post_debate_review workflow."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event(
            {
                "debate_id": "debate-456",
                "consensus_reached": True,
                "confidence": 0.5,
                "task": "Choose database",
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        mock_trigger.assert_called_once()
        assert mock_trigger.call_args[0][0] == "post_debate_review"
        assert mock_trigger.call_args[0][1]["outcome"] == "consensus_low_confidence"

    def test_no_consensus_triggers_escalate(self):
        """No consensus should trigger post_debate_escalate workflow."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event(
            {
                "debate_id": "debate-789",
                "consensus_reached": False,
                "confidence": 0.3,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        mock_trigger.assert_called_once()
        assert mock_trigger.call_args[0][0] == "post_debate_escalate"
        assert mock_trigger.call_args[0][1]["outcome"] == "no_consensus"

    def test_timeout_triggers_retry(self):
        """Timed out debate should trigger post_debate_retry workflow."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event(
            {
                "debate_id": "debate-timeout",
                "consensus_reached": False,
                "confidence": 0.0,
                "timed_out": True,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        mock_trigger.assert_called_once()
        assert mock_trigger.call_args[0][0] == "post_debate_retry"
        assert mock_trigger.call_args[0][1]["outcome"] == "timeout"

    def test_timeout_takes_priority_over_consensus(self):
        """Timeout should be classified as timeout even with consensus."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event(
            {
                "debate_id": "debate-to",
                "consensus_reached": True,
                "confidence": 0.95,
                "timed_out": True,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        assert mock_trigger.call_args[0][1]["outcome"] == "timeout"

    def test_custom_workflow_map(self):
        """Custom workflow map should override defaults."""
        custom_map = {
            "consensus_high_confidence": "custom_action_a",
            "no_consensus": "custom_action_b",
        }
        sub = PostDebateWorkflowSubscriber(workflow_map=custom_map)
        event = make_debate_end_event(
            {
                "debate_id": "d1",
                "consensus_reached": True,
                "confidence": 0.95,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        assert mock_trigger.call_args[0][0] == "custom_action_a"

    def test_custom_min_confidence_threshold(self):
        """Custom min_confidence_for_auto should change the high/low boundary."""
        sub = PostDebateWorkflowSubscriber(min_confidence_for_auto=0.95)
        event = make_debate_end_event(
            {
                "debate_id": "d2",
                "consensus_reached": True,
                "confidence": 0.8,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        # 0.8 < 0.95 threshold, so should be low confidence
        assert mock_trigger.call_args[0][1]["outcome"] == "consensus_low_confidence"

    def test_stats_events_processed_increments(self):
        """events_processed should increment for every call."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event({"debate_id": "d3"})

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ):
            sub.handle_debate_end(event)
            sub.handle_debate_end(event)
            sub.handle_debate_end(event)

        assert sub.stats["events_processed"] == 3

    def test_stats_workflows_triggered_increments(self):
        """workflows_triggered should increment when a workflow is triggered."""
        sub = PostDebateWorkflowSubscriber()
        sub._trigger_workflow("test_template", {"debate_id": "d4", "outcome": "test"})

        assert sub.stats["workflows_triggered"] == 1

    def test_construction_stub_does_not_create_workflow_engine(self):
        """Production dispatch must not probe workflow infrastructure in the stub."""
        sub = PostDebateWorkflowSubscriber()

        with patch("aragora.workflow.engine.WorkflowEngine") as mock_engine:
            sub._trigger_workflow("test_template", {"debate_id": "d4", "outcome": "test"})

        mock_engine.assert_not_called()
        assert sub.stats["workflows_triggered"] == 1

    def test_stats_errors_on_malformed_data(self):
        """errors should increment when event data causes an exception."""
        sub = PostDebateWorkflowSubscriber()
        # Create an event whose .data attribute raises on access
        event = MagicMock()
        event.data = None  # Not a dict, will hit the else branch

        sub.handle_debate_end(event)

        # None is not a dict, so it logs debug but doesn't error
        assert sub.stats["events_processed"] == 1
        assert sub.stats["errors"] == 0

    def test_handles_event_without_data_attribute(self):
        """Should handle event objects that are plain dicts (no .data attr)."""
        sub = PostDebateWorkflowSubscriber()
        plain_dict = {"debate_id": "d5", "consensus_reached": False, "confidence": 0.2}

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(plain_dict)

        # Should treat the dict itself as data since it lacks .data
        mock_trigger.assert_called_once()
        assert mock_trigger.call_args[0][1]["outcome"] == "no_consensus"

    def test_graceful_degradation_workflow_types_unavailable(self):
        """Should not crash when workflow definition types are not importable."""
        sub = PostDebateWorkflowSubscriber()

        with patch.dict("sys.modules", {"aragora.workflow.types": None}):
            # This will cause ImportError inside _trigger_workflow
            sub._trigger_workflow("test_template", {"debate_id": "x", "outcome": "test"})

        # Should not have incremented workflows_triggered
        assert sub.stats["workflows_triggered"] == 0
        # Should not have incremented errors (ImportError is silently handled)
        assert sub.stats["errors"] == 0

    def test_context_truncation(self):
        """Long task/position/synthesis strings should be truncated."""
        sub = PostDebateWorkflowSubscriber()
        long_text = "x" * 2000
        event = make_debate_end_event(
            {
                "debate_id": "d6",
                "consensus_reached": True,
                "confidence": 0.9,
                "task": long_text,
                "winning_position": long_text,
                "synthesis": long_text,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        context = mock_trigger.call_args[0][1]
        assert len(context["task"]) == 500
        assert len(context["winning_position"]) == 1000
        assert len(context["synthesis"]) == 1000

    def test_domain_defaults_to_general(self):
        """Domain should default to 'general' when not provided."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event(
            {
                "debate_id": "d7",
                "consensus_reached": True,
                "confidence": 0.85,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        assert mock_trigger.call_args[0][1]["domain"] == "general"

    def test_empty_event_data(self):
        """Should handle empty event data without crashing."""
        sub = PostDebateWorkflowSubscriber()
        event = make_debate_end_event({})

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        # Empty data defaults: consensus_reached=False, timed_out=False -> no_consensus
        mock_trigger.assert_called_once()
        assert mock_trigger.call_args[0][1]["outcome"] == "no_consensus"

    def test_no_workflow_template_for_unmapped_outcome(self):
        """No workflow should trigger when outcome key has no mapping."""
        sub = PostDebateWorkflowSubscriber(workflow_map={})
        event = make_debate_end_event(
            {
                "debate_id": "d8",
                "consensus_reached": True,
                "confidence": 0.9,
            }
        )

        sub.handle_debate_end(event)

        assert sub.stats["workflows_triggered"] == 0
        assert sub.stats["events_processed"] == 1

    def test_outcome_workflow_map_defaults(self):
        """OUTCOME_WORKFLOW_MAP should have expected default mappings."""
        assert OUTCOME_WORKFLOW_MAP["consensus_high_confidence"] == "post_debate_implement"
        assert OUTCOME_WORKFLOW_MAP["consensus_low_confidence"] == "post_debate_review"
        assert OUTCOME_WORKFLOW_MAP["no_consensus"] == "post_debate_escalate"
        assert OUTCOME_WORKFLOW_MAP["timeout"] == "post_debate_retry"

    def test_confidence_boundary_exactly_at_threshold(self):
        """Confidence exactly at min_confidence_for_auto should be high confidence."""
        sub = PostDebateWorkflowSubscriber(min_confidence_for_auto=0.7)
        event = make_debate_end_event(
            {
                "debate_id": "d9",
                "consensus_reached": True,
                "confidence": 0.7,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        assert mock_trigger.call_args[0][1]["outcome"] == "consensus_high_confidence"

    def test_confidence_just_below_threshold(self):
        """Confidence just below threshold should be low confidence."""
        sub = PostDebateWorkflowSubscriber(min_confidence_for_auto=0.7)
        event = make_debate_end_event(
            {
                "debate_id": "d10",
                "consensus_reached": True,
                "confidence": 0.69,
            }
        )

        with patch(
            "aragora.workflow.event_subscribers.PostDebateWorkflowSubscriber._trigger_workflow"
        ) as mock_trigger:
            sub.handle_debate_end(event)

        assert mock_trigger.call_args[0][1]["outcome"] == "consensus_low_confidence"


class TestGetPostDebateSubscriber:
    """Test the factory function."""

    def test_returns_subscriber_instance(self):
        """get_post_debate_subscriber should return a PostDebateWorkflowSubscriber."""
        sub = get_post_debate_subscriber()
        assert isinstance(sub, PostDebateWorkflowSubscriber)

    def test_accepts_custom_workflow_map(self):
        """Factory should pass custom workflow_map to subscriber."""
        custom = {"consensus_high_confidence": "my_workflow"}
        sub = get_post_debate_subscriber(workflow_map=custom)
        assert sub.workflow_map == custom

    def test_default_workflow_map_is_copy(self):
        """Default workflow map should be a copy, not the global dict."""
        sub = get_post_debate_subscriber()
        sub.workflow_map["new_key"] = "new_value"
        assert "new_key" not in OUTCOME_WORKFLOW_MAP
