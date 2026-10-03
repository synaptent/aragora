"""Tests for the control-plane event registry adapter."""

from __future__ import annotations

import importlib

import pytest

from aragora.control_plane.channels import NotificationEventType
from aragora.events import registry as registry_module


@pytest.fixture(autouse=True)
def _reset_event_registry():
    registry_module.reset_event_registry()
    register = getattr(registry_module, "register_notification_event_contributor", None)
    if register is not None:
        register(None)
    yield
    registry_module.reset_event_registry()
    if register is not None:
        register(None)


def test_adapter_import_is_side_effect_free() -> None:
    """Importing the adapter does not register its contributor."""
    registry_module.register_notification_event_contributor(None)

    adapter = importlib.import_module("aragora.control_plane.event_registry")
    importlib.reload(adapter)

    assert registry_module._notification_event_contributor is None


def test_adapter_supplies_every_notification_event_value() -> None:
    """The adapter exposes all channel-owned notification enum values."""
    adapter = importlib.import_module("aragora.control_plane.event_registry")

    assert adapter.get_notification_event_names() == tuple(
        event_type.value for event_type in NotificationEventType
    )


def test_adapter_registration_is_explicit_and_idempotent() -> None:
    """Explicit repeated composition installs one stable contributor."""
    adapter = importlib.import_module("aragora.control_plane.event_registry")

    assert adapter.register_notification_event_contributor() is True
    contributor = registry_module._notification_event_contributor
    assert adapter.register_notification_event_contributor() is True
    assert registry_module._notification_event_contributor is contributor

    registry = registry_module.EventRegistry()
    registered = {
        event.name
        for event in registry.list_events(source=registry_module.EventSource.CONTROL_PLANE)
    }
    assert registered == {event_type.value for event_type in NotificationEventType}
