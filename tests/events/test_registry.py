"""Tests for the unified event registry composition contracts."""

from __future__ import annotations

from pathlib import Path

import pytest

from aragora.events import registry as registry_module


@pytest.fixture(autouse=True)
def _reset_registry_state():
    registry_module.reset_event_registry()
    register = getattr(registry_module, "register_notification_event_contributor", None)
    if register is not None:
        register(None)
    yield
    registry_module.reset_event_registry()
    if register is not None:
        register(None)


def test_registry_has_no_control_plane_channel_import() -> None:
    """The events-owned registry must not import the control-plane channel enum."""
    source = Path(registry_module.__file__).read_text(encoding="utf-8")

    assert "aragora.control_plane.channels" not in source


def test_missing_notification_contributor_is_fail_soft() -> None:
    """A cold registry still initializes when startup composition is absent."""
    registry_module.register_notification_event_contributor(None)

    registry = registry_module.EventRegistry()

    assert registry.get_event("task_claimed") is None
    assert registry.get_event("debate_start") is not None


def test_notification_contributor_runs_at_original_precedence_position() -> None:
    """Notifications override stream metadata, then deliberation overrides them."""

    def notification_events() -> tuple[str, ...]:
        return ("debate_start", "deliberation_started")

    registry_module.register_notification_event_contributor(notification_events)

    registry = registry_module.EventRegistry()

    assert registry.get_event("debate_start").source is registry_module.EventSource.CONTROL_PLANE
    assert (
        registry.get_event("deliberation_started").source
        is registry_module.EventSource.DELIBERATION
    )


def test_repeated_contributor_registration_is_idempotent() -> None:
    """Registering the same contributor twice does not duplicate event entries."""
    calls = 0

    def notification_events() -> tuple[str, ...]:
        nonlocal calls
        calls += 1
        return ("task_claimed",)

    registry_module.register_notification_event_contributor(notification_events)
    registry_module.register_notification_event_contributor(notification_events)

    registry = registry_module.EventRegistry()

    assert calls == 1
    assert [event.name for event in registry.list_events()].count("task_claimed") == 1
