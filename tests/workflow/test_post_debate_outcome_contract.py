"""Emitter-to-subscriber tests for the DEBATE_END -> post-debate workflow contract.

Each case emits a DEBATE_END event through a real ``SyncEventEmitter`` that the
production interface-superset bootstrap's ``CrossSubscriberManager`` is
connected to, then observes the persistent ``PostDebateWorkflowSubscriber``.
Producers are invoked for real where that is cheap (arena hooks, the hook
manager bridge, the spectator bridge and the ``DebateEndPayload`` schema).
The watchdog, cancel-handler and controller error payloads need live server
state to run, so their payloads are mirrored literally from the producer.

Every case also pins the preserved invariants: the subscriber handles the event
exactly once and no ``WorkflowEngine`` is created (construction-only seam).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aragora.debate.hooks import HookType
from aragora.debate.phases.spectator import SpectatorMixin
from aragora.events.cross_subscribers import (
    CrossSubscriberManager,
    reset_cross_subscriber_manager,
    reset_registry,
)
from aragora.events.schema import DebateEndPayload
from aragora.events.types import StreamEvent, StreamEventType
from aragora.server.stream.arena_hooks import (
    create_arena_hooks,
    create_hook_manager_from_emitter,
)
from aragora.server.stream.emitter import SyncEventEmitter
from aragora.workflow.event_subscribers import (
    PostDebateWorkflowSubscriber,
    get_workflow_event_subscriber,
)

LOOP_ID = "debate-contract"


@dataclass
class _Pipeline:
    emitter: SyncEventEmitter
    manager: CrossSubscriberManager
    subscriber: PostDebateWorkflowSubscriber


@dataclass
class _Observation:
    events: list[StreamEvent]
    templates: list[str]
    contexts: list[dict]


class _SpectatorBridge(SpectatorMixin):
    def __init__(self, emitter: SyncEventEmitter) -> None:
        self.spectator = None
        self.event_emitter = emitter
        self.cartographer = None
        self.loop_id = LOOP_ID


@pytest.fixture(autouse=True)
def _clean_registry_and_manager():
    reset_registry()
    reset_cross_subscriber_manager()
    yield
    reset_registry()
    reset_cross_subscriber_manager()


@pytest.fixture
def pipeline() -> _Pipeline:
    from aragora.server.startup.event_subscribers import bootstrap_event_subscribers

    manager = bootstrap_event_subscribers()
    emitter = SyncEventEmitter(loop_id=LOOP_ID)
    manager.connect(emitter)
    return _Pipeline(
        emitter=emitter,
        manager=manager,
        subscriber=get_workflow_event_subscriber().post_debate_workflow,
    )


def _observe(pipeline: _Pipeline, emit: Callable[[SyncEventEmitter], None]) -> _Observation:
    subscriber = pipeline.subscriber
    with (
        patch.object(subscriber, "handle_debate_end", wraps=subscriber.handle_debate_end) as handle,
        patch.object(
            subscriber, "_trigger_workflow", wraps=subscriber._trigger_workflow
        ) as trigger,
        patch("aragora.workflow.engine.WorkflowEngine") as engine,
    ):
        emit(pipeline.emitter)

    engine.assert_not_called()
    return _Observation(
        events=[c.args[0] for c in handle.call_args_list],
        templates=[c.args[0] for c in trigger.call_args_list],
        contexts=[c.args[1] for c in trigger.call_args_list],
    )


def _emit_data(data: dict) -> Callable[[SyncEventEmitter], None]:
    def emit(emitter: SyncEventEmitter) -> None:
        emitter.emit(StreamEvent(type=StreamEventType.DEBATE_END, data=data, loop_id=LOOP_ID))

    return emit


def _assert_single_dispatch(pipeline: _Pipeline, observed: _Observation, outcome: str) -> None:
    assert len(observed.events) == 1
    assert observed.events[0].type == StreamEventType.DEBATE_END
    assert pipeline.subscriber.classify_outcome(observed.events[0].data) == outcome
    assert pipeline.subscriber.stats["events_processed"] == 1
    assert pipeline.subscriber.stats["errors"] == 0
    assert pipeline.manager.get_stats()["debate_end_to_workflow"]["events_processed"] == 1


class TestConsensusOutcomes:
    """Schema-conformant ``DebateEndPayload`` events carry the consensus signal."""

    @pytest.mark.parametrize(
        ("consensus_reached", "confidence", "outcome", "template"),
        [
            pytest.param(
                True, 0.9, "consensus_high_confidence", "post_debate_implement", id="high"
            ),
            pytest.param(True, 0.5, "consensus_low_confidence", "post_debate_review", id="low"),
            pytest.param(False, 0.3, "no_consensus", "post_debate_escalate", id="none"),
        ],
    )
    def test_schema_payload_routes_by_consensus(
        self, pipeline, consensus_reached, confidence, outcome, template
    ):
        payload = DebateEndPayload(
            debate_id=LOOP_ID,
            consensus_reached=consensus_reached,
            confidence=confidence,
            final_answer="Use a token bucket",
            rounds_used=3,
            duration_seconds=12.5,
        ).to_dict()

        observed = _observe(pipeline, _emit_data(payload))

        assert observed.templates == [template]
        _assert_single_dispatch(pipeline, observed, outcome)
        assert observed.contexts[0]["outcome"] == outcome
        assert observed.contexts[0]["debate_id"] == LOOP_ID
        assert pipeline.subscriber.stats["workflows_triggered"] == 1


class TestTimeoutOutcome:
    def test_watchdog_timeout_routes_to_retry(self, pipeline):
        # Mirrors aragora/server/debate_utils.py watchdog_stuck_debates.
        observed = _observe(
            pipeline,
            _emit_data(
                {
                    "debate_id": LOOP_ID,
                    "status": "timeout",
                    "reason": "Debate timed out after 700s",
                    "duration": 700.0,
                }
            ),
        )

        assert observed.templates == ["post_debate_retry"]
        _assert_single_dispatch(pipeline, observed, "timeout")
        assert observed.contexts[0]["debate_id"] == LOOP_ID
        assert pipeline.subscriber.stats["workflows_triggered"] == 1


class TestCancellationOutcome:
    def test_hook_manager_cancellation_is_not_escalated(self, pipeline):
        def emit(emitter: SyncEventEmitter) -> None:
            hooks = create_hook_manager_from_emitter(emitter, loop_id=LOOP_ID)
            hooks.trigger_sync(HookType.ON_CANCELLATION, reason="User requested")

        observed = _observe(pipeline, emit)

        assert observed.templates == []
        _assert_single_dispatch(pipeline, observed, "cancelled")
        assert observed.events[0].data == {"cancelled": True, "reason": "User requested"}
        assert pipeline.subscriber.stats["workflows_triggered"] == 0

    def test_user_cancel_status_is_not_escalated(self, pipeline):
        # Mirrors aragora/server/handlers/debates/create.py _cancel_debate.
        observed = _observe(
            pipeline,
            _emit_data(
                {"debate_id": LOOP_ID, "status": "cancelled", "reason": "Cancelled by user"}
            ),
        )

        assert observed.templates == []
        _assert_single_dispatch(pipeline, observed, "cancelled")
        assert pipeline.subscriber.stats["workflows_triggered"] == 0


class TestErrorOutcome:
    def test_controller_error_is_not_escalated(self, pipeline):
        # Mirrors the aragora/server/debate_controller.py error-path DEBATE_END.
        observed = _observe(
            pipeline,
            _emit_data(
                {
                    "debate_id": LOOP_ID,
                    "duration": 0.4,
                    "rounds": 0,
                    "error": "Debate validation failed. Check agent configuration and parameters.",
                }
            ),
        )

        assert observed.templates == []
        _assert_single_dispatch(pipeline, observed, "error")
        assert pipeline.subscriber.stats["workflows_triggered"] == 0


class TestMinimalCompletionOutcome:
    """Completions without a consensus signal are ordinary, not ``no_consensus``."""

    @staticmethod
    def _arena_hook_debate_end(emitter: SyncEventEmitter) -> None:
        create_arena_hooks(emitter, loop_id=LOOP_ID)["on_debate_end"](12.5, 3)

    @staticmethod
    def _hook_manager_post_debate(emitter: SyncEventEmitter) -> None:
        hooks = create_hook_manager_from_emitter(emitter, loop_id=LOOP_ID)
        hooks.trigger_sync(
            HookType.POST_DEBATE, result=SimpleNamespace(duration=12.5, rounds_completed=3)
        )

    @staticmethod
    def _spectator_debate_end(emitter: SyncEventEmitter) -> None:
        _SpectatorBridge(emitter)._notify_spectator(
            "debate_end", details="Complete in 12.5s", metric=0.92
        )

    @pytest.mark.parametrize(
        ("emit", "expected_data"),
        [
            pytest.param(
                _arena_hook_debate_end.__func__,
                {"duration": 12.5, "rounds": 3},
                id="arena-hooks-on-debate-end",
            ),
            pytest.param(
                _hook_manager_post_debate.__func__,
                {"duration": 12.5, "rounds": 3},
                id="hook-manager-post-debate",
            ),
            pytest.param(
                _spectator_debate_end.__func__,
                {"details": "Complete in 12.5s", "metric": 0.92, "event_source": "spectator"},
                id="spectator-bridge",
            ),
            pytest.param(
                _emit_data({"debate_id": LOOP_ID}),
                {"debate_id": LOOP_ID},
                id="schema-minimal",
            ),
        ],
    )
    def test_minimal_completion_is_not_escalated(self, pipeline, emit, expected_data):
        observed = _observe(pipeline, emit)

        assert observed.templates == []
        _assert_single_dispatch(pipeline, observed, "completed")
        assert observed.events[0].data == expected_data
        assert pipeline.subscriber.stats["workflows_triggered"] == 0
