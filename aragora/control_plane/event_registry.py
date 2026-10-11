"""Control-plane adapter for the events-owned registration contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aragora.control_plane.channels import NotificationEventType
from aragora.events.agent_registry_hooks import register_agent_registry_factory
from aragora.events.registry import (
    register_notification_event_contributor as register_events_contributor,
)
from aragora.events.task_events import register_default_task_event_dispatcher_provider

if TYPE_CHECKING:
    from aragora.control_plane.notifications import NotificationDispatcher
    from aragora.control_plane.registry import AgentRegistry


def get_notification_event_names() -> tuple[str, ...]:
    """Return every control-plane notification event name."""
    return tuple(event_type.value for event_type in NotificationEventType)


def register_notification_event_contributor() -> bool:
    """Compose notification event discovery into the events registry."""
    register_events_contributor(get_notification_event_names)
    return True


# Both factories import at call time so they resolve the current module
# attribute: callers and tests patch ``aragora.control_plane.registry.AgentRegistry``
# and ``notifications.get_default_notification_dispatcher`` after registration.
def default_task_event_dispatcher() -> NotificationDispatcher | None:
    """Return the control plane's default notification dispatcher, if configured."""
    from aragora.control_plane.notifications import get_default_notification_dispatcher

    return get_default_notification_dispatcher()


def new_agent_registry() -> AgentRegistry:
    """Create a control-plane agent registry for event handlers."""
    from aragora.control_plane.registry import AgentRegistry

    return AgentRegistry()


def register_task_event_dispatcher() -> bool:
    """Make the default notification dispatcher the fallback for task events.

    Returns:
        True when newly registered, False when it was already registered.
    """
    return register_default_task_event_dispatcher_provider(default_task_event_dispatcher)


def register_event_agent_registry() -> bool:
    """Let event handlers create the control-plane agent registry.

    Returns:
        True when newly registered, False when it was already registered.
    """
    return register_agent_registry_factory(new_agent_registry)


__all__ = [
    "default_task_event_dispatcher",
    "get_notification_event_names",
    "new_agent_registry",
    "register_event_agent_registry",
    "register_notification_event_contributor",
    "register_task_event_dispatcher",
]
