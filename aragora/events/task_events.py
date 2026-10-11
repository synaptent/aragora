"""Task lifecycle event emissions for a notification dispatcher.

This module provides helper functions to emit task lifecycle notifications
to a notification dispatcher. These events are emitted when tasks are
submitted, claimed, completed, or failed.

The events layer cannot import the control plane, so the fallback dispatcher
is supplied by registration: ``aragora.control_plane`` registers its default
notification dispatcher through
:func:`register_default_task_event_dispatcher_provider` when it is imported.

Usage:
    from aragora.events.task_events import (
        emit_task_submitted,
        emit_task_completed,
        set_task_event_dispatcher,
    )

    # Set a custom dispatcher (optional - will use default if not set)
    set_task_event_dispatcher(dispatcher)

    # Emit task events
    await emit_task_submitted(task_id, task_type, priority, workspace_id)
    await emit_task_completed(task_id, task_type, agent_id, duration_seconds)
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from aragora.events.notification_types import NotificationEventType, NotificationPriority

logger = logging.getLogger(__name__)


class TaskEventDispatcher(Protocol):
    """The part of a notification dispatcher that task events use."""

    async def dispatch(
        self,
        event_type: NotificationEventType,
        title: str,
        body: str,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        metadata: dict[str, Any] | None = None,
        workspace_id: str | None = None,
    ) -> Any: ...


TaskEventDispatcherProvider = Callable[[], TaskEventDispatcher | None]


class TaskEventDispatcherNotRegisteredError(RuntimeError):
    """No dispatcher was set and no default dispatcher provider is registered."""


@dataclass
class TaskEvent:
    """A task lifecycle notification before it is handed to a dispatcher.

    ``event_type`` holds a :class:`NotificationEventType` value such as
    ``"task_submitted"``.
    """

    event_type: str
    title: str
    body: str
    priority: NotificationPriority = NotificationPriority.NORMAL
    workspace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Plain-data payload of this event."""
        return {
            "event_type": self.event_type,
            "title": self.title,
            "body": self.body,
            "priority": self.priority.value,
            "workspace_id": self.workspace_id,
            "metadata": dict(self.metadata),
        }

    def dispatch_kwargs(self) -> dict[str, Any]:
        """Keyword arguments for :meth:`TaskEventDispatcher.dispatch`."""
        return {
            "event_type": NotificationEventType(self.event_type),
            "title": self.title,
            "body": self.body,
            "priority": self.priority,
            "workspace_id": self.workspace_id,
            "metadata": self.metadata,
        }


_dispatcher: TaskEventDispatcher | None = None
_default_dispatcher_provider: TaskEventDispatcherProvider | None = None


def set_task_event_dispatcher(dispatcher: TaskEventDispatcher) -> None:
    """Set the dispatcher for task events.

    Args:
        dispatcher: Notification dispatcher instance to use for task events
    """
    global _dispatcher
    _dispatcher = dispatcher
    logger.info("task_event_dispatcher_set")


def register_default_task_event_dispatcher_provider(
    provider: TaskEventDispatcherProvider,
) -> bool:
    """Register the fallback used when no dispatcher was set explicitly.

    Registering the same provider again is a no-op; a different provider
    replaces the current one.

    Returns:
        True when the provider was installed, False when it was already registered.
    """
    global _default_dispatcher_provider
    if _default_dispatcher_provider is provider:
        return False
    _default_dispatcher_provider = provider
    return True


def registered_count() -> int:
    """Return how many default dispatcher providers are registered (0 or 1)."""
    return 0 if _default_dispatcher_provider is None else 1


def get_task_event_dispatcher() -> TaskEventDispatcher | None:
    """Get the current task event dispatcher.

    Returns the configured dispatcher, or falls back to the registered
    default dispatcher provider if none was explicitly set.

    Returns:
        Dispatcher instance or None if not available
    """
    if _dispatcher is not None:
        return _dispatcher
    if _default_dispatcher_provider is None:
        return None
    return _default_dispatcher_provider()


def resolve_task_event_dispatcher(event_type: str) -> TaskEventDispatcher | None:
    """Return the dispatcher that receives task events of ``event_type``.

    Unlike :func:`get_task_event_dispatcher`, this distinguishes "nothing is
    wired" from "wired, but no default dispatcher is configured".

    Raises:
        ValueError: ``event_type`` is not a task notification event type.
        TaskEventDispatcherNotRegisteredError: no dispatcher was set and no
            default dispatcher provider is registered.
    """
    if not NotificationEventType(event_type).value.startswith("task_"):
        raise ValueError(f"not a task event type: {event_type!r}")
    if _dispatcher is None and _default_dispatcher_provider is None:
        raise TaskEventDispatcherNotRegisteredError(
            "no task event dispatcher is set and no default provider is registered; "
            "import aragora.control_plane or call set_task_event_dispatcher()"
        )
    return get_task_event_dispatcher()


def _dispatcher_for(event_type: NotificationEventType) -> TaskEventDispatcher | None:
    try:
        return resolve_task_event_dispatcher(event_type.value)
    except TaskEventDispatcherNotRegisteredError:
        logger.debug("task_event_dispatcher_not_registered", extra={"event": event_type.value})
        return None


def _map_priority(task_priority: str) -> NotificationPriority:
    """Map task priority string to notification priority.

    Args:
        task_priority: Task priority as string (urgent, high, normal, low)

    Returns:
        Corresponding NotificationPriority
    """
    mapping = {
        "urgent": NotificationPriority.URGENT,
        "high": NotificationPriority.HIGH,
        "normal": NotificationPriority.NORMAL,
        "low": NotificationPriority.LOW,
    }
    return mapping.get(task_priority.lower(), NotificationPriority.NORMAL)


async def emit_task_submitted(
    task_id: str,
    task_type: str,
    priority: str,
    workspace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit TASK_SUBMITTED notification.

    Called when a new task is submitted to the scheduler.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        priority: Task priority level
        workspace_id: Optional workspace for filtering notifications
        metadata: Additional task metadata
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_SUBMITTED)
    if not dispatcher:
        return

    try:
        event = TaskEvent(
            event_type=NotificationEventType.TASK_SUBMITTED.value,
            title=f"Task Submitted: {task_type}",
            body=f"New {priority} priority task queued for execution",
            priority=_map_priority(priority),
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "priority": priority,
                **(metadata or {}),
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_submitted", "error": str(e)}
        )


async def emit_task_claimed(
    task_id: str,
    task_type: str,
    agent_id: str,
    workspace_id: str | None = None,
) -> None:
    """Emit TASK_CLAIMED notification.

    Called when an agent claims a task for execution.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        agent_id: ID of the agent that claimed the task
        workspace_id: Optional workspace for filtering notifications
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_CLAIMED)
    if not dispatcher:
        return

    try:
        event = TaskEvent(
            event_type=NotificationEventType.TASK_CLAIMED.value,
            title=f"Task Claimed: {task_type}",
            body=f"Agent `{agent_id}` claimed task `{task_id[:8]}...` for execution",
            priority=NotificationPriority.NORMAL,
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "agent_id": agent_id,
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_claimed", "error": str(e)}
        )


async def emit_task_completed(
    task_id: str,
    task_type: str,
    agent_id: str,
    duration_seconds: float,
    workspace_id: str | None = None,
) -> None:
    """Emit TASK_COMPLETED notification.

    Called when a task is successfully completed.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        agent_id: ID of the agent that completed the task
        duration_seconds: Time taken to complete the task
        workspace_id: Optional workspace for filtering notifications
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_COMPLETED)
    if not dispatcher:
        return

    try:
        event = TaskEvent(
            event_type=NotificationEventType.TASK_COMPLETED.value,
            title=f"Task Completed: {task_type}",
            body=f"Task `{task_id[:8]}...` completed by agent `{agent_id}` in {duration_seconds:.1f}s",
            priority=NotificationPriority.NORMAL,
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "agent_id": agent_id,
                "duration_seconds": duration_seconds,
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_completed", "error": str(e)}
        )


async def emit_task_failed(
    task_id: str,
    task_type: str,
    agent_id: str | None,
    error: str,
    will_retry: bool,
    workspace_id: str | None = None,
) -> None:
    """Emit TASK_FAILED notification.

    Called when a task fails execution. Uses URGENT priority for failures
    that won't be retried.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        agent_id: ID of the agent that was executing (None if unassigned)
        error: Error message describing the failure
        will_retry: Whether the task will be retried
        workspace_id: Optional workspace for filtering notifications
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_FAILED)
    if not dispatcher:
        return

    try:
        agent_info = f" by agent `{agent_id}`" if agent_id else ""
        retry_info = " (will retry)" if will_retry else " (max retries exceeded)"

        event = TaskEvent(
            event_type=NotificationEventType.TASK_FAILED.value,
            title=f"Task Failed: {task_type}",
            body=f"Task `{task_id[:8]}...` failed{agent_info}{retry_info}: {error[:200]}",
            priority=NotificationPriority.URGENT if not will_retry else NotificationPriority.HIGH,
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "agent_id": agent_id,
                "error": error,
                "will_retry": will_retry,
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_failed", "error": str(e)}
        )


async def emit_task_timeout(
    task_id: str,
    task_type: str,
    agent_id: str | None,
    elapsed_seconds: float,
    timeout_seconds: float,
    workspace_id: str | None = None,
) -> None:
    """Emit TASK_TIMEOUT notification.

    Called when a task exceeds its execution timeout.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        agent_id: ID of the agent that was executing (None if unassigned)
        elapsed_seconds: Time elapsed before timeout
        timeout_seconds: Configured timeout threshold
        workspace_id: Optional workspace for filtering notifications
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_TIMEOUT)
    if not dispatcher:
        return

    try:
        agent_info = f" (agent: {agent_id})" if agent_id else ""

        event = TaskEvent(
            event_type=NotificationEventType.TASK_TIMEOUT.value,
            title=f"Task Timeout: {task_type}",
            body=f"Task `{task_id[:8]}...` timed out after {elapsed_seconds:.0f}s{agent_info} (limit: {timeout_seconds:.0f}s)",
            priority=NotificationPriority.HIGH,
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "agent_id": agent_id,
                "elapsed_seconds": elapsed_seconds,
                "timeout_seconds": timeout_seconds,
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_timeout", "error": str(e)}
        )


async def emit_task_retried(
    task_id: str,
    task_type: str,
    attempt: int,
    max_retries: int,
    workspace_id: str | None = None,
) -> None:
    """Emit TASK_RETRIED notification.

    Called when a task is requeued for retry after a failure.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        attempt: Current retry attempt number
        max_retries: Maximum allowed retries
        workspace_id: Optional workspace for filtering notifications
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_RETRIED)
    if not dispatcher:
        return

    try:
        event = TaskEvent(
            event_type=NotificationEventType.TASK_RETRIED.value,
            title=f"Task Retried: {task_type}",
            body=f"Task `{task_id[:8]}...` requeued for retry (attempt {attempt}/{max_retries})",
            priority=NotificationPriority.NORMAL,
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "attempt": attempt,
                "max_retries": max_retries,
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_retried", "error": str(e)}
        )


async def emit_task_cancelled(
    task_id: str,
    task_type: str,
    reason: str | None = None,
    workspace_id: str | None = None,
) -> None:
    """Emit TASK_CANCELLED notification.

    Called when a task is cancelled before completion.

    Args:
        task_id: Unique task identifier
        task_type: Type of the task
        reason: Optional reason for cancellation
        workspace_id: Optional workspace for filtering notifications
    """
    dispatcher = _dispatcher_for(NotificationEventType.TASK_CANCELLED)
    if not dispatcher:
        return

    try:
        reason_info = f": {reason}" if reason else ""

        event = TaskEvent(
            event_type=NotificationEventType.TASK_CANCELLED.value,
            title=f"Task Cancelled: {task_type}",
            body=f"Task `{task_id[:8]}...` was cancelled{reason_info}",
            priority=NotificationPriority.NORMAL,
            workspace_id=workspace_id,
            metadata={
                "task_id": task_id,
                "task_type": task_type,
                "reason": reason,
            },
        )
        await dispatcher.dispatch(**event.dispatch_kwargs())
    except (RuntimeError, ValueError, TypeError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning(
            "task_event_emission_failed", extra={"event": "task_cancelled", "error": str(e)}
        )


__all__ = [
    # Event payload
    "TaskEvent",
    # Dispatcher management
    "TaskEventDispatcher",
    "TaskEventDispatcherNotRegisteredError",
    "TaskEventDispatcherProvider",
    "register_default_task_event_dispatcher_provider",
    "registered_count",
    "resolve_task_event_dispatcher",
    "set_task_event_dispatcher",
    "get_task_event_dispatcher",
    # Event emissions
    "emit_task_submitted",
    "emit_task_claimed",
    "emit_task_completed",
    "emit_task_failed",
    "emit_task_timeout",
    "emit_task_retried",
    "emit_task_cancelled",
]
