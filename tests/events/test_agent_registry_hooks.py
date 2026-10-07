"""Agent-registry factory hook used by event handlers."""

from __future__ import annotations

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
