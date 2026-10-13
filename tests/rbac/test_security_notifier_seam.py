"""aragora.rbac reaches the control plane's break-glass notifications without importing it.

``aragora.rbac`` (infrastructure layer) must not import ``aragora.control_plane``
(application layer). The RBAC cache takes ``DistributedStateError`` from its defining
module, ``aragora.resilience.leader``. Break-glass access notifies the security team
through the sender registered in ``aragora.rbac.security_notifier``; the control plane
registers ``send_security_notification`` there from its own init and through the
``aragora.security_notifiers`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED_FILES = ("aragora/rbac/cache.py", "aragora/rbac/emergency.py")
CONTROL_PLANE_NOTIFIER_REGISTRATION = (
    "control_plane",
    "aragora.control_plane.security_registration:register_rbac_security_notifier",
)


def _imported_names(path: Path) -> list[tuple[int, str]]:
    names: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.append((node.lineno, node.module or ""))
        elif isinstance(node, ast.Call) and node.args:
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            first = node.args[0]
            if callee in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                names.append((node.lineno, str(first.value)))
    return names


@pytest.mark.parametrize("relative", CHECKED_FILES)
def test_the_file_holds_no_import_of_the_control_plane(relative):
    offenders = [
        f"{relative}:{lineno}: {name}"
        for lineno, name in _imported_names(REPO_ROOT / relative)
        if name == "aragora.control_plane" or name.startswith("aragora.control_plane.")
    ]
    assert offenders == []


def test_the_cache_raises_the_same_distributed_state_error_as_the_control_plane():
    from aragora.control_plane.leader import DistributedStateError as control_plane_error
    from aragora.rbac import cache
    from aragora.resilience.leader import DistributedStateError

    assert cache.DistributedStateError is DistributedStateError
    assert control_plane_error is DistributedStateError


@pytest.fixture
def isolated_notifier(monkeypatch, tmp_path):
    """The security-notifier slot empty, with declared registrations from a test only."""
    from aragora.rbac import security_notifier

    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    monkeypatch.setattr(security_notifier, "_notifier", None)
    monkeypatch.setattr(
        security_notifier,
        "_declared_registrations",
        DeclaredRegistrations(
            security_notifier.SECURITY_NOTIFIERS_ENTRY_POINT_GROUP,
            source_pyproject=tmp_path / "missing.toml",
        ),
    )
    return security_notifier


@pytest.fixture
def record():
    from aragora.rbac.emergency import EmergencyAccessRecord, EmergencyAccessStatus

    now = datetime.now(timezone.utc)
    return EmergencyAccessRecord(
        id="emerg-seam",
        user_id="user-1",
        reason="Seam characterization",
        status=EmergencyAccessStatus.ACTIVE,
        activated_at=now,
        expires_at=now + timedelta(minutes=30),
        ip_address="10.0.0.1",
    )


@pytest.mark.asyncio
async def test_without_a_notifier_break_glass_logs_that_nothing_was_sent(
    isolated_notifier, record, caplog
):
    from aragora.rbac.emergency import BreakGlassAccess

    with caplog.at_level(logging.INFO, logger="aragora.rbac.emergency"):
        await BreakGlassAccess()._notify_security_team(record, "activated")

    assert isolated_notifier.registered_count() == 0
    assert "Security notification (not sent): break-glass activated for user-1" in caplog.text


@pytest.mark.asyncio
async def test_break_glass_sends_through_the_registered_notifier(isolated_notifier, record):
    from aragora.rbac.emergency import BreakGlassAccess

    notifier = AsyncMock(return_value=True)
    assert isolated_notifier.register_security_notifier(notifier) is True
    assert isolated_notifier.register_security_notifier(notifier) is False

    await BreakGlassAccess()._notify_security_team(record, "activated")

    notifier.assert_awaited_once()
    kwargs = notifier.await_args.kwargs
    assert kwargs["title"] == "Break-Glass Access Activated"
    assert kwargs["severity"] == "high"
    assert kwargs["metadata"] == record.to_dict()
    assert "User: user-1\nAccess ID: emerg-seam\n" in kwargs["message"]
    assert not isolated_notifier._declared_registrations.loaded


def test_loading_the_declared_notifiers_runs_them_once(isolated_notifier, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        isolated_notifier.register_security_notifier(AsyncMock())

    declared = [SimpleNamespace(name="n0", value="tests.declared:n0", load=lambda: register)]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: (
            declared if group == isolated_notifier.SECURITY_NOTIFIERS_ENTRY_POINT_GROUP else []
        ),
    )

    assert isolated_notifier.get_security_notifier() is not None
    assert isolated_notifier.get_security_notifier() is not None
    assert calls == ["register"]


def test_pyproject_declares_the_control_plane_security_notifier():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    from aragora.rbac import security_notifier

    declared = DeclaredRegistrations(
        security_notifier.SECURITY_NOTIFIERS_ENTRY_POINT_GROUP
    )._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [CONTROL_PLANE_NOTIFIER_REGISTRATION]


@pytest.mark.asyncio
async def test_the_control_plane_notifier_calls_the_current_send_security_notification(
    monkeypatch,
):
    from aragora.control_plane import notifications, security_registration
    from aragora.rbac import security_notifier

    sender = AsyncMock(return_value=True)
    monkeypatch.setattr(notifications, "send_security_notification", sender)

    assert security_notifier.get_security_notifier() is security_registration.notify_security_team
    assert security_registration.register_rbac_security_notifier() is False
    assert (
        await security_registration.notify_security_team(
            title="t", message="m", severity="high", metadata={"k": 1}
        )
        is True
    )
    sender.assert_awaited_once_with(title="t", message="m", severity="high", metadata={"k": 1})


def test_an_rbac_only_process_reaches_the_control_plane_notifier():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "from aragora.rbac import security_notifier\n"
        "assert not any(m.startswith('aragora.control_plane') for m in sys.modules), 'preloaded'\n"
        "notifier = security_notifier.get_security_notifier()\n"
        "from aragora.control_plane import security_registration\n"
        "print(security_notifier.registered_count(),\n"
        "      notifier is security_registration.notify_security_team)\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.split()[-2:] == ["1", "True"]
