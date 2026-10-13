"""The email recipient record lives in ``aragora.notifications``.

The knowledge mound builds recipients for its sharing notifications and must not import
``aragora.integrations`` (application layer) to do so. ``aragora.integrations.email``
re-exports the same class.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aragora.integrations import email as old
from aragora.notifications import email_recipient as new

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_the_old_path_holds_the_same_class():
    assert old.EmailRecipient is new.EmailRecipient
    assert new.EmailRecipient.__module__ == "aragora.notifications.email_recipient"


def test_the_formatted_address_is_unchanged():
    assert new.EmailRecipient(email="a@example.com").formatted == "a@example.com"
    assert old.EmailRecipient(email="a@example.com", name="Ann").formatted == "Ann <a@example.com>"
    assert new.EmailRecipient(email="a@example.com").preferences == {}


def test_the_new_home_imports_nothing_from_aragora():
    tree = ast.parse((REPO_ROOT / "aragora/notifications/email_recipient.py").read_text())
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    assert [name for name in imported if name.startswith("aragora")] == []


def test_knowledge_holds_no_import_of_integrations():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno}"
        for path in sorted((REPO_ROOT / "aragora/knowledge").rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.ImportFrom)
        and node.level == 0
        and (node.module or "").startswith("aragora.integrations")
    ]
    assert offenders == []
