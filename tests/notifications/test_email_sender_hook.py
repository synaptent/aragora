"""Services build email senders through ``aragora.notifications.email_senders``.

``aragora.services`` (application layer) must not import ``aragora.integrations`` (interface
layer) at runtime. The integrations package registers ``EmailIntegration`` through the
``aragora.email_senders`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.notifications import email_senders as hook
from aragora.notifications.email_recipient import EmailRecipient
from aragora.services.ar_automation import ARAutomation
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATIONS_REGISTRATION = (
    "integrations",
    "aragora.integrations.email_sender_registration:register_email_sender",
)


class RecordingSender:
    def __init__(self, config):
        self.config = config
        self.sent = []

    async def _send_email(self, recipient, subject, html_body, text_body=None):
        self.sent.append((recipient, subject))
        return True


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.EMAIL_SENDERS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


async def _invoice(ar):
    return await ar.generate_invoice(
        customer_id="c1",
        line_items=[{"description": "Work", "amount": 100}],
        customer_name="Ada",
        customer_email="ada@example.com",
    )


def test_an_unregistered_sender_raises(isolated_hook):
    with pytest.raises(hook.EmailSenderNotRegisteredError, match="aragora.email_senders"):
        hook.create_email_sender(object())


@pytest.mark.asyncio
async def test_ar_automation_sends_invoices_through_the_registered_sender(isolated_hook):
    config = object()
    senders = []

    def factory(cfg):
        senders.append(RecordingSender(cfg))
        return senders[-1]

    hook.register_email_sender_factory(factory)
    ar = ARAutomation(company_name="Acme", email_config=config)
    invoice = await _invoice(ar)
    assert await ar.send_invoice(invoice.id) is True
    assert await ar.send_invoice(invoice.id) is True
    (sender,) = senders
    assert sender.config is config
    recipient, subject = sender.sent[0]
    assert type(recipient) is EmailRecipient
    assert recipient.formatted == "Ada <ada@example.com>"
    assert subject == f"Invoice {invoice.invoice_number} from Acme"


@pytest.mark.asyncio
async def test_without_an_email_config_no_sender_is_built(isolated_hook):
    hook.register_email_sender_factory(lambda cfg: pytest.fail("no sender should be built"))
    ar = ARAutomation()
    invoice = await _invoice(ar)
    assert await ar.send_invoice(invoice.id) is True
    assert ar._get_email_integration() is None


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_email_sender_factory(RecordingSender)

    entry_point = SimpleNamespace(name="e0", value="tests.declared:e0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.EMAIL_SENDERS_ENTRY_POINT_GROUP else [],
    )
    assert hook.create_email_sender("a").config == "a"
    assert hook.create_email_sender("b").config == "b"
    assert calls == ["register"]


def test_pyproject_declares_the_integrations_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.EMAIL_SENDERS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [
        INTEGRATIONS_REGISTRATION
    ]


def test_the_registration_reads_the_integration_class_at_call_time(isolated_hook, monkeypatch):
    from aragora.integrations import email
    from aragora.integrations.email_sender_registration import register_email_sender

    register_email_sender()
    register_email_sender()
    sender = hook.create_email_sender(email.EmailConfig(smtp_host="smtp.example.com"))
    assert type(sender) is email.EmailIntegration
    monkeypatch.setattr(email, "EmailIntegration", RecordingSender)
    assert type(hook.create_email_sender("cfg")) is RecordingSender


def test_a_services_only_process_reaches_the_email_integration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "from aragora.notifications.email_senders import create_email_sender\n"
        "import aragora.services.ar_automation\n"
        "sender = create_email_sender(None)\n"
        "print(type(sender).__module__, type(sender).__name__)\n"
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
    assert result.stdout.split()[-2:] == ["aragora.integrations.email", "EmailIntegration"]


def _runtime_imports(tree):
    """Absolute imports outside ``if TYPE_CHECKING:`` blocks."""
    type_only = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            type_only.update(id(child) for stmt in node.body for child in ast.walk(stmt))
    for node in ast.walk(tree):
        if id(node) in type_only:
            continue
        if isinstance(node, ast.Import):
            yield from ((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.lineno, node.module


def test_services_hold_no_runtime_import_of_integrations():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "services").rglob("*.py"))
        for line, name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if name == "aragora.integrations" or name.startswith("aragora.integrations.")
    ]
    assert offenders == []
