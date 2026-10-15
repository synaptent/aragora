"""Spectator mode lives in ``aragora.events.spectate``; the old paths are the same modules.

``aragora.debate`` (domain layer) must not import ``aragora.spectate`` (application layer).
The spectator stream, its event constants, payload redaction and WebSocket bridge moved down
to ``aragora.events.spectate`` (infrastructure), and the PII redactor they use moved to
``aragora.utils.pii_redactor``.
"""

from __future__ import annotations

import ast
import importlib
import io
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MOVED = [
    ("aragora.spectate.events", "aragora.events.spectate.events"),
    ("aragora.spectate.stream", "aragora.events.spectate.stream"),
    ("aragora.spectate.redaction", "aragora.events.spectate.redaction"),
    ("aragora.spectate.ws_bridge", "aragora.events.spectate.ws_bridge"),
    ("aragora.services.pii_redactor", "aragora.utils.pii_redactor"),
]
INFRASTRUCTURE_MODULES = [
    REPO_ROOT / "aragora" / "events" / "spectate" / "events.py",
    REPO_ROOT / "aragora" / "events" / "spectate" / "stream.py",
    REPO_ROOT / "aragora" / "events" / "spectate" / "redaction.py",
    REPO_ROOT / "aragora" / "events" / "spectate" / "ws_bridge.py",
    REPO_ROOT / "aragora" / "utils" / "pii_redactor.py",
]


def _absolute_imports(path: Path) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


@pytest.mark.parametrize(("old", "new"), MOVED)
def test_the_old_path_is_the_moved_module(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_the_package_exports_the_moved_objects():
    import aragora.spectate as package
    from aragora.events.spectate import events, stream, ws_bridge

    assert package.SpectatorEvents is events.SpectatorEvents
    assert package.SpectatorStream is stream.SpectatorStream
    assert package.SpectateWebSocketBridge is ws_bridge.SpectateWebSocketBridge
    assert package.get_spectate_bridge is ws_bridge.get_spectate_bridge


def test_both_paths_share_one_bridge():
    from aragora.events.spectate import ws_bridge
    from aragora.spectate.ws_bridge import get_spectate_bridge, reset_spectate_bridge

    reset_spectate_bridge()
    try:
        bridge = get_spectate_bridge()
        bridge.start()
        assert ws_bridge.get_spectate_bridge() is bridge
        assert ws_bridge.get_spectate_bridge().running
    finally:
        reset_spectate_bridge()
    assert ws_bridge._bridge_instance is None


def test_a_debate_stream_reaches_the_bridge_with_redacted_details():
    from aragora.events.spectate.stream import SpectatorStream
    from aragora.spectate.ws_bridge import get_spectate_bridge, reset_spectate_bridge

    reset_spectate_bridge()
    try:
        bridge = get_spectate_bridge()
        bridge.start()
        SpectatorStream(enabled=True, output=io.StringIO(), format="json").emit(
            "proposal", agent="a1", details="mail me at someone@example.com", round_number=1
        )
        (event,) = bridge.get_recent_events()
        assert (event.event_type, event.agent_name, event.round_number) == ("proposal", "a1", 1)
        assert "someone@example.com" not in str(event.to_dict())
    finally:
        reset_spectate_bridge()


@pytest.mark.parametrize("path", INFRASTRUCTURE_MODULES, ids=lambda path: path.name)
def test_the_moved_modules_import_only_infrastructure(path):
    allowed = ("aragora.events.", "aragora.utils.")
    upward = [
        f"{line}: {name}"
        for line, name in _absolute_imports(path)
        if name.startswith("aragora") and not name.startswith(allowed)
    ]
    assert upward == []


def test_debate_holds_no_import_of_spectate_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py"))
        for line, name in _absolute_imports(path)
        if name == "aragora.spectate" or name.startswith("aragora.spectate.")
    ]
    assert offenders == []
