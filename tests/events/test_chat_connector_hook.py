"""The execution notifier reaches chat connectors through ``aragora.events.chat_connectors``.

``aragora.pipeline`` (application layer) must not import ``aragora.connectors`` (interface
layer), whose chat registry returns the connector for a platform. The chat connector package
registers its lookup through the ``aragora.chat_connector_lookups`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.events import approval_requests
from aragora.events import chat_connectors as hook
from aragora.pipeline.execution_notifier import ExecutionNotifier
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
CHAT_REGISTRATION = (
    "chat",
    "aragora.connectors.chat.lookup_registration:register_chat_connector_lookup_from_registry",
)
PROGRESS = {"completed_tasks": 1, "failed_tasks": 0, "total_tasks": 2, "progress_pct": 50.0}


class TargetParser:
    def __init__(self):
        self.parsed = []

    def parse_targets(self, targets):
        self.parsed.append(targets)
        return {"slack": ["#eng"]}


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations come only from a test; yields the target parser."""
    monkeypatch.setattr(hook, "_lookup", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP,
            source_pyproject=tmp_path / "missing.toml",
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    parser = TargetParser()
    monkeypatch.setattr(approval_requests, "_notifier", parser)
    return parser


def _notifier() -> ExecutionNotifier:
    return ExecutionNotifier(
        debate_id="debate-1",
        channel_targets=["slack:#eng"],
        notify_channel=False,
        notify_websocket=False,
    )


def _connector() -> MagicMock:
    connector = MagicMock()
    connector.is_configured = True
    connector.send_message = AsyncMock(
        return_value=SimpleNamespace(success=True, message_id="m-1", error=None)
    )
    return connector


def test_an_unregistered_lookup_raises(isolated_hook):
    with pytest.raises(
        hook.ChatConnectorLookupNotRegisteredError, match="aragora.chat_connector_lookups"
    ):
        hook.chat_connector_lookup()


async def test_without_a_lookup_the_notifier_stops_before_parsing_targets(isolated_hook):
    await _notifier()._dispatch_to_targets(PROGRESS, is_complete=False)
    assert isolated_hook.parsed == []


async def test_the_notifier_sends_through_the_registered_lookup(isolated_hook):
    slack = _connector()
    platforms = []

    def lookup(platform):
        platforms.append(platform)
        return slack

    hook.register_chat_connector_lookup(lambda platform: None)
    hook.register_chat_connector_lookup(lookup)
    await _notifier()._dispatch_to_targets(PROGRESS, is_complete=False)
    assert platforms == ["slack"]
    assert isolated_hook.parsed == [["slack:#eng"]]
    slack.send_message.assert_awaited_once_with(
        channel_id="#eng", text="Execution update (50%)\n- Tasks: 1/2 completed", thread_id=None
    )


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_chat_connector_lookup(lambda platform: platform)

    entry_point = SimpleNamespace(name="d0", value="tests.declared:d0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            [entry_point] if group == hook.CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP else []
        ),
    )
    assert hook.chat_connector_lookup()("teams") == "teams"
    assert hook.chat_connector_lookup()("slack") == "slack"
    assert calls == ["register"]


def test_pyproject_declares_the_chat_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(
        hook.CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [CHAT_REGISTRATION]


def test_the_registered_lookup_reads_the_registry_at_call_time(isolated_hook):
    from aragora.connectors.chat.lookup_registration import (
        register_chat_connector_lookup_from_registry,
    )

    register_chat_connector_lookup_from_registry()
    register_chat_connector_lookup_from_registry()
    slack = object()
    with patch("aragora.connectors.chat.registry.get_connector", return_value=slack) as lookup:
        assert hook.chat_connector_lookup()("slack") is slack
    lookup.assert_called_once_with("slack")


def test_a_pipeline_only_process_reaches_the_chat_registry():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "import aragora.pipeline.execution_notifier\n"
        "from aragora.events.chat_connectors import chat_connector_lookup\n"
        "assert not any(m.startswith('aragora.connectors.chat') for m in sys.modules), 'preloaded'\n"
        "lookup = chat_connector_lookup()\n"
        "print(lookup.__module__, lookup('no-such-platform'))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["aragora.connectors.chat.lookup_registration", "None"]


@pytest.mark.parametrize("package", ["pipeline", "events"])
def test_the_package_holds_no_import_of_connectors_at_any_scope(package):
    offenders = []
    for path in sorted((REPO_ROOT / "aragora" / package).rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {name}"
                for name in names
                if name == "aragora.connectors" or name.startswith("aragora.connectors.")
            ]
    assert offenders == []
