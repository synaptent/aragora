"""Tests for the workflow-domain (application-tier) event-subscriber home
(P4a Batch E5).

Covers ``aragora.workflow.event_subscribers``: the post-debate workflow
automation reaction relocated out of infrastructure
(``aragora.events.subscribers.workflow_automation``) and the alert-escalation
emergency-brake reaction relocated out of
``aragora.events.cross_subscribers.handlers.strategic``, into this
application home, plus the self-registration surface (get-or-create
accessor, ``register()``).

Unit tests for ``PostDebateWorkflowSubscriber``'s own outcome-classification
and workflow-triggering logic live in
``tests/events/test_post_debate_workflow.py`` (repointed in place); the
``_handle_alert_escalated_to_workflow_brake`` handler's direct-execution
tests live in ``TestAlertEscalatedToWorkflowBrake`` in
``tests/events/test_strategic_handlers.py`` (also repointed in place - same
precedent as ``TestBudgetAlertToTeamSelection`` for the P4a Batch E4
relocation). This module covers registration/dispatch integration plus the
E5-specific invocation-count acceptance test.

``WorkflowEventSubscriber.register`` wires one keyed reaction for each handler.
The production interface-superset bootstrap therefore dispatches
``DEBATE_END`` to ``PostDebateWorkflowSubscriber.handle_debate_end`` exactly
once, including after repeated bootstrap calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.events.cross_subscribers import (
    CrossSubscriberManager,
    get_registered_subscribers,
    reset_cross_subscriber_manager,
    reset_registry,
)
from aragora.events.types import StreamEvent, StreamEventType
from aragora.workflow.event_subscribers import (
    WORKFLOW_EVENT_SUBSCRIBER_HANDLER_NAMES,
    PostDebateWorkflowSubscriber,
    WorkflowEventSubscriber,
    get_workflow_event_subscriber,
    register,
)


def make_stream_event(event_type: StreamEventType, data: dict | None = None) -> StreamEvent:
    """Factory for creating test stream events."""
    return StreamEvent(type=event_type, data=data or {}, round=0, agent="test_agent")


@pytest.fixture(autouse=True)
def _clean_registry_and_manager():
    """Isolate each test: empty registry + fresh manager before and after."""
    reset_registry()
    reset_cross_subscriber_manager()
    yield
    reset_registry()
    reset_cross_subscriber_manager()


class TestWorkflowEventSubscriberHandlers:
    """Direct handler-execution tests."""

    def test_debate_end_to_workflow_delegates_to_post_debate_workflow(self):
        subscriber = WorkflowEventSubscriber()
        event = make_stream_event(
            StreamEventType.DEBATE_END,
            data={"debate_id": "d1", "consensus_reached": True, "confidence": 0.9},
        )

        with patch.object(PostDebateWorkflowSubscriber, "_trigger_workflow") as mock_trigger:
            subscriber._handle_debate_end_to_workflow(event)

        mock_trigger.assert_called_once()
        assert subscriber.post_debate_workflow.stats["events_processed"] == 1

    def test_alert_escalated_to_workflow_brake_handler_executes_without_error(self):
        subscriber = WorkflowEventSubscriber()
        event = make_stream_event(
            StreamEventType.ALERT_ESCALATED,
            data={"severity": "warning", "alert_id": "alert_1"},
        )
        subscriber._handle_alert_escalated_to_workflow_brake(event)

    def test_alert_escalated_to_workflow_brake_pauses_on_critical(self):
        subscriber = WorkflowEventSubscriber()
        event = make_stream_event(
            StreamEventType.ALERT_ESCALATED,
            data={"severity": "critical", "alert_id": "alert_2", "reason": "test reason"},
        )
        with patch("aragora.workflow.engine.WorkflowEngine.pause_all") as pause_all:
            subscriber._handle_alert_escalated_to_workflow_brake(event)
        pause_all.assert_called_once()

    def test_alert_escalated_to_workflow_brake_handles_none_reason(self):
        subscriber = WorkflowEventSubscriber()
        event = make_stream_event(
            StreamEventType.ALERT_ESCALATED,
            data={"severity": "critical", "alert_id": "alert_3", "reason": None},
        )
        with patch("aragora.workflow.engine.WorkflowEngine.pause_all") as pause_all:
            delivered = subscriber._handle_alert_escalated_to_workflow_brake(event)

        assert delivered is True
        pause_all.assert_called_once_with(reason="Emergency brake: ")


class TestWorkflowEventSubscriberRegistration:
    """Registration + self-registration surface tests."""

    def test_handler_names_frozenset(self):
        assert WORKFLOW_EVENT_SUBSCRIBER_HANDLER_NAMES == frozenset(
            {
                "alert_escalated_to_workflow_brake",
                "debate_end_to_workflow",
            }
        )

    def test_register_wires_all_handlers_into_manager(self):
        manager = CrossSubscriberManager()
        subscriber = WorkflowEventSubscriber()

        subscriber.register(manager)

        registered = set(manager.get_stats())
        assert WORKFLOW_EVENT_SUBSCRIBER_HANDLER_NAMES <= registered

    def test_register_wires_debate_end_to_workflow(self):
        """The workflow home owns one keyed DEBATE_END reaction."""
        manager = CrossSubscriberManager()
        subscriber = WorkflowEventSubscriber()
        subscriber.register(manager)

        assert "debate_end_to_workflow" in manager.get_stats()
        with patch.object(subscriber.post_debate_workflow, "handle_debate_end") as mock_handle:
            manager._dispatch_event(
                make_stream_event(
                    StreamEventType.DEBATE_END,
                    data={"debate_id": "d1", "consensus_reached": False, "confidence": 0.0},
                )
            )

        mock_handle.assert_called_once()

    def test_register_dispatches_alert_escalated_to_workflow_brake_through_manager(self):
        manager = CrossSubscriberManager()
        WorkflowEventSubscriber().register(manager)

        manager._dispatch_event(
            make_stream_event(
                StreamEventType.ALERT_ESCALATED,
                data={"severity": "warning", "alert_id": "a1"},
            )
        )

        stats = manager.get_stats()
        assert stats["alert_escalated_to_workflow_brake"]["events_processed"] == 1

    def test_get_workflow_event_subscriber_returns_singleton(self):
        first = get_workflow_event_subscriber()
        second = get_workflow_event_subscriber()
        assert first is second
        assert get_registered_subscribers()["workflow"] is first

    def test_register_function_is_idempotent(self):
        register()
        first = get_registered_subscribers()["workflow"]
        register()
        second = get_registered_subscribers()["workflow"]
        assert first is second


class TestPostDebateWorkflowSubscriberInvocationCount:
    """Production composition-root exactly-once acceptance tests.

    Registration-name parity alone cannot detect duplicate delegates. These
    tests patch ``PostDebateWorkflowSubscriber.handle_debate_end`` itself and
    observe the complete production dispatch.
    """

    def test_superset_bootstrap_dispatches_post_debate_exactly_once(self):
        """One production DEBATE_END dispatch invokes the workflow handler once."""
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        manager = bootstrap_event_subscribers()
        event = make_stream_event(
            StreamEventType.DEBATE_END,
            data={"debate_id": "d1", "consensus_reached": True, "confidence": 0.9},
        )

        with patch.object(PostDebateWorkflowSubscriber, "handle_debate_end") as mock_handle:
            manager._dispatch_event(event)

        mock_handle.assert_called_once()
        assert manager.get_stats()["debate_end_to_workflow"]["events_processed"] == 1

    def test_repeated_superset_bootstrap_keeps_post_debate_exactly_once(self):
        """Repeated production bootstrap does not duplicate the DEBATE_END reaction."""
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        first_manager = bootstrap_event_subscribers()
        manager = bootstrap_event_subscribers()
        assert manager is first_manager
        event = make_stream_event(StreamEventType.DEBATE_END, data={"debate_id": "d3"})

        with patch.object(PostDebateWorkflowSubscriber, "handle_debate_end") as mock_handle:
            manager._dispatch_event(event)

        mock_handle.assert_called_once()
        assert manager.get_stats()["debate_end_to_workflow"]["events_processed"] == 1

    def test_superset_dispatch_does_not_probe_workflow_infrastructure(self):
        """The construction stub handles production events without creating an engine."""
        from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

        manager = bootstrap_event_subscribers()
        subscriber = get_workflow_event_subscriber()
        event = make_stream_event(
            StreamEventType.DEBATE_END,
            data={"debate_id": "d4", "consensus_reached": True, "confidence": 0.9},
        )

        with patch("aragora.workflow.engine.WorkflowEngine") as mock_engine:
            manager._dispatch_event(event)

        mock_engine.assert_not_called()
        assert subscriber.post_debate_workflow.stats["events_processed"] == 1
        assert subscriber.post_debate_workflow.stats["workflows_triggered"] == 1
        assert manager.get_stats()["debate_end_to_workflow"]["events_processed"] == 1


class TestLegacyDelegatingSitesRemoved:
    """Structural regression guard: both pre-inversion delegating call sites
    for ``PostDebateWorkflowSubscriber`` are gone entirely, not merely
    unregistered (docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §5.3).

    P4a Batch E7b dissolved ``BasicHandlersMixin``/``StrategicHandlersMixin``
    into ``CrossSubscriberManager`` directly, so the guard now targets the
    manager class itself.
    """

    def test_cross_subscriber_manager_has_no_debate_end_to_workflow_delegate(self):
        from aragora.events.cross_subscribers.manager import CrossSubscriberManager

        assert not hasattr(CrossSubscriberManager, "_handle_debate_end_to_workflow")

    def test_cross_subscriber_manager_has_no_alert_escalated_to_workflow_brake(self):
        from aragora.events.cross_subscribers.manager import CrossSubscriberManager

        assert not hasattr(CrossSubscriberManager, "_handle_alert_escalated_to_workflow_brake")

    def test_workflow_automation_module_removed_no_shim(self):
        """Relocate-UP no-shim exemption: no re-export module survives at the
        old infrastructure path."""
        with pytest.raises(ModuleNotFoundError):
            import aragora.events.subscribers.workflow_automation  # noqa: F401
