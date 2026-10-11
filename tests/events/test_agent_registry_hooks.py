"""Agent-registry factory hook used by event handlers."""

from __future__ import annotations

import logging
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import aragora.events.agent_registry_hooks as hooks

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _isolate_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hooks, "_factory", None)


def test_create_without_factory_raises() -> None:
    assert hooks.registered_count() == 0
    with pytest.raises(hooks.AgentRegistryNotRegisteredError):
        hooks.create_agent_registry()


def test_factory_registration_is_idempotent() -> None:
    created: list[object] = []

    def factory() -> object:
        created.append(object())
        return created[-1]

    assert hooks.register_agent_registry_factory(factory) is True
    assert hooks.register_agent_registry_factory(factory) is False
    assert hooks.registered_count() == 1
    assert hooks.create_agent_registry() is created[-1]
    assert hooks.create_agent_registry() is created[-1]
    assert len(created) == 2


def test_replacing_the_factory_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    def first() -> object:
        return object()

    def second() -> object:
        return object()

    with caplog.at_level(logging.DEBUG, logger=hooks.__name__):
        hooks.register_agent_registry_factory(first)
        assert not caplog.records
        assert hooks.register_agent_registry_factory(second) is True

    assert [r.levelno for r in caplog.records] == [logging.DEBUG]
    assert "Replacing" in caplog.records[0].getMessage()


def test_genesis_sync_without_factory_logs_the_skip(caplog: pytest.LogCaptureFixture) -> None:
    from aragora.events.cross_subscribers import manager
    from aragora.events.types import StreamEvent, StreamEventType

    event = StreamEvent(
        type=StreamEventType.AGENT_BIRTH,
        data={"event_type": "birth", "agent_id": "agent_unsynced"},
    )
    with caplog.at_level(logging.DEBUG, logger=manager.__name__):
        manager.CrossSubscriberManager()._handle_genesis_to_control_plane(event)

    skipped = [r.getMessage() for r in caplog.records if "skipped" in r.getMessage()]
    assert skipped and "agent_unsynced" in skipped[0]


def test_control_plane_init_registers_the_factory_once() -> None:
    script = textwrap.dedent(
        """
        import importlib, sys
        from unittest.mock import MagicMock, patch
        import aragora.events.agent_registry_hooks as hooks
        import aragora.events.cross_subscribers.manager
        assert not any(m.startswith("aragora.control_plane") for m in sys.modules)
        try:
            hooks.create_agent_registry()
        except hooks.AgentRegistryNotRegisteredError:
            pass
        else:
            raise SystemExit("created a registry without a factory")
        importlib.import_module("aragora.control_plane")
        assert hooks.registered_count() == 1
        importlib.import_module("aragora.control_plane")
        assert hooks.registered_count() == 1
        fake = MagicMock()
        with patch("aragora.control_plane.registry.AgentRegistry", fake):
            assert hooks.create_agent_registry() is fake.return_value
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
