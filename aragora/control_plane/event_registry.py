"""Control-plane adapter for the events-owned registration contracts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aragora.control_plane.channels import NotificationEventType
from aragora.events.agent_registry_hooks import register_agent_registry_factory
from aragora.events.registry import (
    register_notification_event_contributor as register_events_contributor,
)

if TYPE_CHECKING:
    from aragora.control_plane.registry import AgentRegistry


def get_notification_event_names() -> tuple[str, ...]:
    """Return every control-plane notification event name."""
    return tuple(event_type.value for event_type in NotificationEventType)


def register_notification_event_contributor() -> bool:
    """Compose notification event discovery into the events registry."""
    register_events_contributor(get_notification_event_names)
    return True


# Imports at call time so it resolves the current module attribute: callers and
# tests patch ``aragora.control_plane.registry.AgentRegistry`` after registration.
def new_agent_registry() -> AgentRegistry:
    """Create a control-plane agent registry for event handlers."""
    from aragora.control_plane.registry import AgentRegistry

    return AgentRegistry()


def register_event_agent_registry() -> bool:
    """Let event handlers create the control-plane agent registry.

    Returns:
        True when newly registered, False when it was already registered.
    """
    return register_agent_registry_factory(new_agent_registry)


__all__ = [
    "get_notification_event_names",
    "new_agent_registry",
    "register_event_agent_registry",
    "register_notification_event_contributor",
]
