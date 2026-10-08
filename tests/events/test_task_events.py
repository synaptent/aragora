"""Task lifecycle events: payloads, dispatcher registration and emission."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

import aragora.events.task_events as task_events
from aragora.events.notification_types import NotificationEventType, NotificationPriority

REPO_ROOT = Path(__file__).resolve().parents[2]


class RecordingDispatcher:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._error = error

    async def dispatch(self, **kwargs: Any) -> list[Any]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return []


@pytest.fixture(autouse=True)
def _isolate_dispatcher_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(task_events, "_dispatcher", None)
    monkeypatch.setattr(task_events, "_default_dispatcher_provider", None)


def test_task_event_payload_is_plain_data() -> None:
    event = task_events.TaskEvent(
        event_type="task_completed",
        title="Task Completed: debate",
        body="done",
        workspace_id="ws-1",
        metadata={"task_id": "t-1"},
    )
    assert event.to_dict() == {
        "event_type": "task_completed",
        "title": "Task Completed: debate",
        "body": "done",
        "priority": "normal",
        "workspace_id": "ws-1",
        "metadata": {"task_id": "t-1"},
    }
    assert event.dispatch_kwargs()["event_type"] is NotificationEventType.TASK_COMPLETED
    assert event.dispatch_kwargs()["priority"] is NotificationPriority.NORMAL


def test_unregistered_lookup_is_explicit() -> None:
    assert task_events.registered_count() == 0
    assert task_events.get_task_event_dispatcher() is None
    with pytest.raises(task_events.TaskEventDispatcherNotRegisteredError):
        task_events.resolve_task_event_dispatcher("task_submitted")


def test_resolve_rejects_non_task_event_types() -> None:
    task_events.set_task_event_dispatcher(RecordingDispatcher())
    with pytest.raises(ValueError):
        task_events.resolve_task_event_dispatcher("agent_error")
    with pytest.raises(ValueError):
        task_events.resolve_task_event_dispatcher("not-an-event")


def test_provider_registration_is_idempotent() -> None:
    dispatcher = RecordingDispatcher()

    def provider() -> RecordingDispatcher:
        return dispatcher

    assert task_events.register_default_task_event_dispatcher_provider(provider) is True
    assert task_events.register_default_task_event_dispatcher_provider(provider) is False
    assert task_events.registered_count() == 1
    assert task_events.get_task_event_dispatcher() is dispatcher
    assert task_events.resolve_task_event_dispatcher("task_claimed") is dispatcher


def test_explicit_dispatcher_wins_over_provider() -> None:
    explicit = RecordingDispatcher()
    task_events.register_default_task_event_dispatcher_provider(RecordingDispatcher)
    task_events.set_task_event_dispatcher(explicit)
    assert task_events.get_task_event_dispatcher() is explicit


@pytest.mark.asyncio
async def test_emitters_skip_silently_when_nothing_is_registered() -> None:
    await task_events.emit_task_submitted("t-1", "debate", "high")
    await task_events.emit_task_cancelled("t-1", "debate", reason="user")


@pytest.mark.asyncio
async def test_emit_task_failed_dispatches_expected_notification() -> None:
    dispatcher = RecordingDispatcher()
    task_events.register_default_task_event_dispatcher_provider(lambda: dispatcher)

    await task_events.emit_task_failed(
        task_id="0123456789abcdef",
        task_type="debate",
        agent_id="claude",
        error="boom",
        will_retry=False,
        workspace_id="ws-1",
    )

    assert dispatcher.calls == [
        {
            "event_type": NotificationEventType.TASK_FAILED,
            "title": "Task Failed: debate",
            "body": "Task `01234567...` failed by agent `claude` (max retries exceeded): boom",
            "priority": NotificationPriority.URGENT,
            "workspace_id": "ws-1",
            "metadata": {
                "task_id": "0123456789abcdef",
                "task_type": "debate",
                "agent_id": "claude",
                "error": "boom",
                "will_retry": False,
            },
        }
    ]


@pytest.mark.asyncio
async def test_emit_task_submitted_maps_priority_and_merges_metadata() -> None:
    dispatcher = RecordingDispatcher()
    task_events.set_task_event_dispatcher(dispatcher)

    await task_events.emit_task_submitted("t-1", "debate", "HIGH", metadata={"source": "api"})

    (call,) = dispatcher.calls
    assert call["event_type"] is NotificationEventType.TASK_SUBMITTED
    assert call["priority"] is NotificationPriority.HIGH
    assert call["metadata"] == {
        "task_id": "t-1",
        "task_type": "debate",
        "priority": "HIGH",
        "source": "api",
    }


@pytest.mark.asyncio
async def test_dispatch_errors_are_logged_not_raised() -> None:
    dispatcher = RecordingDispatcher(error=ConnectionError("down"))
    task_events.set_task_event_dispatcher(dispatcher)

    await task_events.emit_task_retried("t-1", "debate", attempt=2, max_retries=3)

    assert dispatcher.calls[0]["event_type"] is NotificationEventType.TASK_RETRIED


def test_control_plane_init_registers_the_default_dispatcher_once() -> None:
    script = textwrap.dedent(
        """
        import importlib, sys
        import aragora.events.task_events as te
        assert not any(m.startswith("aragora.control_plane") for m in sys.modules)
        try:
            te.resolve_task_event_dispatcher("task_submitted")
        except te.TaskEventDispatcherNotRegisteredError:
            pass
        else:
            raise SystemExit("resolved without a registered provider")
        importlib.import_module("aragora.control_plane")
        assert te.registered_count() == 1
        assert te.resolve_task_event_dispatcher("task_submitted") is None
        importlib.import_module("aragora.control_plane")
        assert te.registered_count() == 1
        from aragora.control_plane import notifications
        sentinel = object()
        notifications.set_default_notification_dispatcher(sentinel)
        assert te.get_task_event_dispatcher() is sentinel
        print("ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip().endswith("ok")
