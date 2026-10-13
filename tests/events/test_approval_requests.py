"""Characterization of the approval request hook.

``aragora.workflow``, ``aragora.pipeline`` and ``aragora.computer_use`` (application layer)
must not import ``aragora.approvals`` (interface layer), which sends the interactive chat
approval requests. ``aragora.approvals`` registers its chat notifier with
``aragora.events.approval_requests`` from its own init, the three packages go through the
hook, and a process that never imports ``aragora.approvals`` reaches the registration
declared under the ``aragora.approval_notifiers`` entry-point group.
"""

from __future__ import annotations

import ast
import importlib.metadata
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import aragora.approvals  # noqa: F401  (registers before any test empties the slot)
from aragora.approvals import chat
from aragora.approvals.chat import parse_chat_targets, send_chat_approval_request
from aragora.approvals.notifier_registration import (
    CHAT_APPROVAL_NOTIFIER,
    register_chat_approval_notifier,
)
from aragora.events import approval_requests as hook
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
APPROVALS_REGISTRATION = (
    "approvals",
    "aragora.approvals.notifier_registration:register_chat_approval_notifier",
)
FIXED_PACKAGES = ("workflow", "pipeline", "computer_use")


class RecordingNotifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.parsed: list[Any] = []
        self.sent: list[dict[str, Any]] = []
        self._error = error

    def parse_targets(self, targets: list[str] | None) -> dict[str, list[str]]:
        self.parsed.append(targets)
        return {"slack": ["#recorded"]}

    async def send_request(self, **request: Any) -> list[dict[str, Any]]:
        self.sent.append(request)
        if self._error is not None:
            raise self._error
        return [{"platform": "slack", "channel_id": "#recorded", "success": True}]


@pytest.fixture
def no_notifier(monkeypatch):
    """An empty slot on which the declared registrations count as already run."""
    monkeypatch.setattr(hook, "_notifier", None)
    declared = DeclaredRegistrations(hook.APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP)
    monkeypatch.setattr(declared, "load", lambda: None)
    monkeypatch.setattr(hook, "_declared", declared)
    return hook


@pytest.fixture
def recording(no_notifier):
    notifier = RecordingNotifier()
    hook.register_approval_notifier(notifier)
    return notifier


def _fake_connector(message_id: str = "m-1") -> MagicMock:
    connector = MagicMock()
    connector.is_configured = True
    connector.format_blocks = MagicMock(return_value=None)
    connector.send_message = AsyncMock(
        return_value=SimpleNamespace(success=True, message_id=message_id, error=None)
    )
    return connector


# ---------------------------------------------------------------------------
# Hook
# ---------------------------------------------------------------------------


def test_an_unregistered_hook_raises_an_explicit_error(no_notifier):
    assert hook.registered_count() == 0
    with pytest.raises(hook.ApprovalNotifierNotRegisteredError, match="aragora.approval_notifiers"):
        hook.parse_approval_targets(["slack:#c"])
    assert issubclass(hook.ApprovalNotifierNotRegisteredError, RuntimeError)


async def test_an_unregistered_send_raises_an_explicit_error(no_notifier):
    with pytest.raises(hook.ApprovalNotifierNotRegisteredError):
        await hook.send_approval_request(
            title="t", description="d", fields=None, targets=["slack:#c"], kind="k", target_id="1"
        )


async def test_the_registered_notifier_receives_every_request_field(recording):
    result = await hook.send_approval_request(
        title="Deploy",
        description="Ship it",
        fields=[("Step", "s1")],
        targets=["slack:#ops"],
        kind="workflow",
        target_id="req-1",
    )

    assert result == [{"platform": "slack", "channel_id": "#recorded", "success": True}]
    assert recording.sent == [
        {
            "title": "Deploy",
            "description": "Ship it",
            "fields": [("Step", "s1")],
            "targets": ["slack:#ops"],
            "kind": "workflow",
            "target_id": "req-1",
            "ttl_seconds": 3600,
            "extra_text": None,
            "thread_id": None,
            "thread_id_by_platform": None,
        }
    ]
    assert hook.parse_approval_targets(["slack:#ops"]) == {"slack": ["#recorded"]}
    assert recording.parsed == [["slack:#ops"]]


def test_registering_again_replaces_the_notifier_and_counts_one(no_notifier):
    first, second = RecordingNotifier(), RecordingNotifier()
    hook.register_approval_notifier(first)
    hook.register_approval_notifier(first)
    assert hook.registered_count() == 1
    hook.register_approval_notifier(second)
    assert hook.registered_count() == 1
    hook.parse_approval_targets(["x"])
    assert (first.parsed, second.parsed) == ([], [["x"]])


# ---------------------------------------------------------------------------
# aragora.approvals registers its chat notifier
# ---------------------------------------------------------------------------


def test_the_chat_registration_is_idempotent(no_notifier):
    register_chat_approval_notifier()
    register_chat_approval_notifier()
    assert hook.registered_count() == 1
    assert hook._notifier is CHAT_APPROVAL_NOTIFIER


def test_the_chat_notifier_parses_targets_like_the_chat_module(no_notifier):
    register_chat_approval_notifier()
    targets = ["slack:#c", "teams:x", "#general", "ops@example.com", "gchat:space", ""]

    assert hook.parse_approval_targets(targets) == parse_chat_targets(targets)
    assert hook.parse_approval_targets(targets) == {
        "slack": ["#c", "#general"],
        "teams": ["x"],
        "google_chat": ["space"],
    }
    assert hook.parse_approval_targets(None) == {}


async def test_the_chat_notifier_delivers_to_a_recorded_fake_channel(no_notifier):
    register_chat_approval_notifier()
    slack = _fake_connector("m-42")

    with patch("aragora.connectors.chat.registry.get_connector", return_value=slack):
        result = await hook.send_approval_request(
            title="Approve deploy",
            description="Ship release 1.2",
            fields=[("Workflow", "wf-1")],
            targets=["slack:#ops"],
            kind="workflow",
            target_id="req-9",
            ttl_seconds=60,
            thread_id="t-1",
        )

    assert result == [
        {
            "platform": "slack",
            "channel_id": "#ops",
            "success": True,
            "message_id": "m-42",
            "error": None,
        }
    ]
    slack.send_message.assert_awaited_once_with(
        channel_id="#ops", text="Approve deploy\nShip release 1.2", blocks=None, thread_id="t-1"
    )
    assert slack.format_blocks.call_args.kwargs["fields"] == [("Workflow", "wf-1")]


async def test_the_chat_notifier_looks_the_chat_functions_up_at_call_time(no_notifier):
    register_chat_approval_notifier()
    sent = AsyncMock(return_value=[{"success": True}])

    with patch.object(chat, "send_chat_approval_request", sent):
        assert await hook.send_approval_request(
            title="t", description="d", fields=None, targets=["slack:#c"], kind="k", target_id="1"
        ) == [{"success": True}]
    with patch.object(chat, "parse_chat_targets", return_value={"teams": ["x"]}):
        assert hook.parse_approval_targets(["slack:#c"]) == {"teams": ["x"]}

    sent.assert_awaited_once_with(
        title="t",
        description="d",
        fields=None,
        targets=["slack:#c"],
        kind="k",
        target_id="1",
        ttl_seconds=3600,
        extra_text=None,
        thread_id=None,
        thread_id_by_platform=None,
    )


# ---------------------------------------------------------------------------
# Declared registration
# ---------------------------------------------------------------------------


def test_a_miss_runs_the_declared_approvals_registration_once(no_notifier, monkeypatch, tmp_path):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "aragora"\n'
        '[project.entry-points."aragora.approval_notifiers"]\n'
        f'{APPROVALS_REGISTRATION[0]} = "{APPROVALS_REGISTRATION[1]}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    declared = DeclaredRegistrations(
        hook.APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP, source_pyproject=pyproject
    )
    monkeypatch.setattr(hook, "_declared", declared)

    assert hook.parse_approval_targets(["teams:x"]) == {"teams": ["x"]}
    assert declared.loaded
    assert hook._notifier is CHAT_APPROVAL_NOTIFIER


def test_pyproject_declares_the_approvals_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [
        APPROVALS_REGISTRATION
    ]


def _run(script: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=180,
        check=False,
    )


def test_importing_the_hook_registers_nothing_and_approvals_registers_once():
    script = (
        "import sys\n"
        "from aragora.events import approval_requests as h\n"
        "assert 'aragora.approvals' not in sys.modules, 'approvals preloaded'\n"
        "assert h.registered_count() == 0\n"
        "import aragora.approvals\n"
        "assert h.registered_count() == 1\n"
        "first = h._notifier\n"
        "import aragora.approvals\n"
        "from aragora.approvals.notifier_registration import register_chat_approval_notifier\n"
        "register_chat_approval_notifier()\n"
        "assert h.registered_count() == 1 and h._notifier is first\n"
        "print(h.parse_approval_targets(['slack:#c', 'teams:x']))\n"
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "{'slack': ['#c'], 'teams': ['x']}"


def test_a_process_that_never_imports_approvals_still_reaches_the_chat_notifier():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "from aragora.pipeline.execution_notifier import ExecutionNotifier\n"
        "from aragora.events import approval_requests as h\n"
        "assert 'aragora.approvals' not in sys.modules, 'approvals preloaded'\n"
        "print(h.parse_approval_targets(['slack:#c', 'teams:x']))\n"
        "assert 'aragora.approvals' in sys.modules and h.registered_count() == 1\n"
    )
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "{'slack': ['#c'], 'teams': ['x']}"


# ---------------------------------------------------------------------------
# Call sites: computer_use, workflow, pipeline
# ---------------------------------------------------------------------------


def _computer_use_request(url: str | None = "https://bank.example/login"):
    from aragora.computer_use.approval import (
        ApprovalCategory,
        ApprovalContext,
        ApprovalPriority,
        ApprovalRequest,
        ApprovalStatus,
    )

    now = time.time()
    context = ApprovalContext(
        task_id="task-1",
        action_type="type",
        action_details={},
        category=ApprovalCategory.CREDENTIAL_ACCESS,
        reason="Entering password",
        risk_level="high",
        current_url=url,
    )
    return ApprovalRequest(
        id="cu-1",
        context=context,
        status=ApprovalStatus.PENDING,
        priority=ApprovalPriority.HIGH,
        created_at=now,
        expires_at=now + 300,
    )


async def test_computer_use_chat_notifier_sends_through_the_hook(recording):
    from aragora.computer_use.approval import ChatApprovalNotifier

    await ChatApprovalNotifier(["slack:#sec"]).notify_request(_computer_use_request())

    [sent] = recording.sent
    ttl = sent.pop("ttl_seconds")
    assert 290 <= ttl <= 300
    assert sent == {
        "title": "Computer-Use Approval Required",
        "description": "Entering password",
        "fields": [
            ("Request ID", "cu-1"),
            ("Action", "type"),
            ("Category", "credential_access"),
            ("Risk", "high"),
            ("URL", "https://bank.example/login"),
        ],
        "targets": ["slack:#sec"],
        "kind": "computer_use",
        "target_id": "cu-1",
        "extra_text": None,
        "thread_id": None,
        "thread_id_by_platform": None,
    }


async def test_computer_use_chat_notifier_without_targets_sends_nothing(recording):
    from aragora.computer_use.approval import ChatApprovalNotifier

    await ChatApprovalNotifier().notify_request(_computer_use_request(url=None))
    assert recording.sent == []


async def test_computer_use_chat_notifier_skips_when_nothing_is_registered(no_notifier, caplog):
    from aragora.computer_use.approval import ChatApprovalNotifier

    with caplog.at_level(logging.DEBUG, logger="aragora.computer_use.approval"):
        await ChatApprovalNotifier(["slack:#sec"]).notify_request(_computer_use_request())
    assert "Chat approval integration not available" in caplog.text


async def test_computer_use_delivery_failures_still_reach_the_caller(no_notifier):
    from aragora.computer_use.approval import ChatApprovalNotifier

    hook.register_approval_notifier(RecordingNotifier(error=RuntimeError("chat down")))
    with pytest.raises(RuntimeError, match="chat down"):
        await ChatApprovalNotifier(["slack:#sec"]).notify_request(_computer_use_request())


def _checkpoint_request():
    from aragora.workflow.nodes.human_checkpoint import ApprovalRequest

    return ApprovalRequest(
        id="apr-1",
        workflow_id="wf-1",
        step_id="gate",
        title="Release gate",
        description="Approve the release",
        checklist=[],
        timeout_seconds=60,
    )


def _workflow_context(metadata: dict[str, Any] | None = None):
    from aragora.workflow.step import WorkflowContext

    return WorkflowContext(
        workflow_id="wf-1", definition_id="def-1", metadata=metadata or {}, current_step_id="gate"
    )


async def test_workflow_checkpoint_sends_through_the_hook(recording):
    from aragora.workflow.nodes.human_checkpoint import HumanCheckpointStep

    step = HumanCheckpointStep("gate")
    config = {"chat_targets": "slack:#release", "thread_id": "th-1"}
    with patch("aragora.notifications.notify_checkpoint_approval_requested", AsyncMock()):
        await step._send_approval_notification(_checkpoint_request(), config, _workflow_context())

    assert recording.sent == [
        {
            "title": "Release gate",
            "description": "Approve the release",
            "fields": [
                ("Workflow", "wf-1"),
                ("Step", "gate"),
                ("Request ID", "apr-1"),
                ("Timeout", "60s"),
            ],
            "targets": ["slack:#release"],
            "kind": "workflow",
            "target_id": "apr-1",
            "ttl_seconds": 60,
            "extra_text": None,
            "thread_id": "th-1",
            "thread_id_by_platform": None,
        }
    ]


async def test_workflow_checkpoint_skips_chat_when_nothing_is_registered(no_notifier, caplog):
    from aragora.workflow.nodes.human_checkpoint import HumanCheckpointStep

    step = HumanCheckpointStep("gate")
    with (
        patch("aragora.notifications.notify_checkpoint_approval_requested", AsyncMock()),
        caplog.at_level(logging.DEBUG, logger="aragora.workflow.nodes.human_checkpoint"),
    ):
        await step._send_approval_notification(
            _checkpoint_request(), {"chat_targets": ["slack:#release"]}, _workflow_context()
        )
    assert "Chat approval notification skipped" in caplog.text


def _execution_notifier():
    from aragora.pipeline.execution_notifier import ExecutionNotifier

    return ExecutionNotifier(
        debate_id="debate-1",
        channel_targets=["slack:#eng"],
        notify_channel=False,
        notify_websocket=False,
    )


PROGRESS = {"completed_tasks": 1, "failed_tasks": 0, "total_tasks": 2, "progress_pct": 50.0}


async def test_pipeline_progress_targets_are_parsed_through_the_hook(recording):
    slack = _fake_connector()
    with patch("aragora.connectors.chat.registry.get_connector", return_value=slack) as lookup:
        await _execution_notifier()._dispatch_to_targets(PROGRESS, is_complete=False)

    assert recording.parsed == [["slack:#eng"]]
    lookup.assert_called_once_with("slack")
    slack.send_message.assert_awaited_once_with(
        channel_id="#recorded",
        text="Execution update (50%)\n- Tasks: 1/2 completed",
        thread_id=None,
    )


async def test_pipeline_progress_skips_targets_when_nothing_is_registered(no_notifier):
    with patch("aragora.connectors.chat.registry.get_connector") as lookup:
        await _execution_notifier()._dispatch_to_targets(PROGRESS, is_complete=True)
    lookup.assert_not_called()


# ---------------------------------------------------------------------------
# The fixed packages name no import of aragora.approvals
# ---------------------------------------------------------------------------


def _module_name(node: ast.ImportFrom, path: Path) -> str:
    if node.level == 0:
        return node.module or ""
    package = path.relative_to(REPO_ROOT).with_suffix("").parts[: -node.level]
    return ".".join(package + ((node.module,) if node.module else ()))


def _is_approvals(name: str) -> bool:
    return name == "aragora.approvals" or name.startswith("aragora.approvals.")


@pytest.mark.parametrize("package", FIXED_PACKAGES)
def test_fixed_packages_have_no_import_of_approvals_at_any_scope(package):
    offenders = []
    for path in sorted((REPO_ROOT / "aragora" / package).rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                module = _module_name(node, path)
                names = [module] + [f"{module}.{alias.name}" for alias in node.names]
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                callee = getattr(func, "attr", None) or getattr(func, "id", None)
                if callee in {"import_module", "__import__"}:
                    names = [ast.unparse(node.args[0]).strip("'\"")]
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {n}"
                for n in names
                if _is_approvals(n)
            ]
    assert offenders == []


def test_the_chat_entry_points_still_import():
    assert callable(send_chat_approval_request)
    assert parse_chat_targets(["slack:#c", "teams:x"]) == {"slack": ["#c"], "teams": ["x"]}
