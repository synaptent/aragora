"""Compatibility re-export of :mod:`aragora.events.task_events`.

Task lifecycle events moved to the events layer. Every name below is the
identical object. The dispatcher state (``_dispatcher`` and the default
provider) lives only in the new module; patch or reset it there.
"""

from __future__ import annotations

from aragora.events.task_events import (
    TaskEvent,
    TaskEventDispatcher,
    TaskEventDispatcherNotRegisteredError,
    TaskEventDispatcherProvider,
    emit_task_cancelled,
    emit_task_claimed,
    emit_task_completed,
    emit_task_failed,
    emit_task_retried,
    emit_task_submitted,
    emit_task_timeout,
    get_task_event_dispatcher,
    register_default_task_event_dispatcher_provider,
    registered_count,
    resolve_task_event_dispatcher,
    set_task_event_dispatcher,
)

__all__ = [
    "TaskEvent",
    "TaskEventDispatcher",
    "TaskEventDispatcherNotRegisteredError",
    "TaskEventDispatcherProvider",
    "emit_task_cancelled",
    "emit_task_claimed",
    "emit_task_completed",
    "emit_task_failed",
    "emit_task_retried",
    "emit_task_submitted",
    "emit_task_timeout",
    "get_task_event_dispatcher",
    "register_default_task_event_dispatcher_provider",
    "registered_count",
    "resolve_task_event_dispatcher",
    "set_task_event_dispatcher",
]
