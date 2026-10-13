"""Compatibility re-export of :mod:`aragora.events.deliberation_events`.

Deliberation event types moved to the events layer so the event registry can
describe them without importing the control plane. Every name below is the
identical object.
"""

from __future__ import annotations

from aragora.events.deliberation_events import (
    CATEGORIES,
    EVENT_TYPES_BY_CATEGORY,
    TERMINAL_EVENT_TYPES,
    DeliberationEventType,
)

__all__ = [
    "CATEGORIES",
    "DeliberationEventType",
    "EVENT_TYPES_BY_CATEGORY",
    "TERMINAL_EVENT_TYPES",
]
