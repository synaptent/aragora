"""Control-plane adapter for the events-owned notification registry contract."""

from __future__ import annotations

from aragora.control_plane.channels import NotificationEventType
from aragora.events.registry import (
    register_notification_event_contributor as register_events_contributor,
)


def get_notification_event_names() -> tuple[str, ...]:
    """Return every control-plane notification event name."""
    return tuple(event_type.value for event_type in NotificationEventType)


def register_notification_event_contributor() -> bool:
    """Compose notification event discovery into the events registry."""
    register_events_contributor(get_notification_event_names)
    return True


__all__ = [
    "get_notification_event_names",
    "register_notification_event_contributor",
]
