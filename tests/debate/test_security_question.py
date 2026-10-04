"""The security debate question builder leaf.

``security_debate`` (runner) needs the question builder and ``security_response``
(the events-side trigger) needs the runner; hosting the builder in a leaf lets
the runner stop importing the trigger while the trigger keeps re-exporting the
builder for its existing callers.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aragora.debate import security_debate, security_question, security_response

_DEBATE_DIR = Path(security_debate.__file__).resolve().parent
_PACKAGE = "aragora.debate"


def _imported_modules(path: Path) -> set[str]:
    """Absolute dotted names imported by ``path``, with relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parts = _PACKAGE.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                module = f"{base}.{node.module}" if node.module else base
            else:
                module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_response_module_reexports_the_leaf_builder():
    assert (
        security_response.build_security_debate_question
        is security_question.build_security_debate_question
    )
    assert "build_security_debate_question" in security_response.__all__


def test_runner_does_not_import_the_response_module():
    imports = _imported_modules(_DEBATE_DIR / "security_debate.py")
    assert not any(name.startswith("aragora.debate.security_response") for name in imports), imports
    assert "aragora.debate.security_question.build_security_debate_question" in imports


def test_leaf_imports_nothing_from_debate_package():
    imports = _imported_modules(_DEBATE_DIR / "security_question.py")
    assert not any(name.startswith("aragora.debate") for name in imports), imports


def test_leaf_builds_the_same_question_as_before():
    from aragora.events.security_events import (
        SecurityEvent,
        SecurityEventType,
        SecurityFinding,
        SecuritySeverity,
    )

    event = SecurityEvent(
        event_type=SecurityEventType.CRITICAL_CVE,
        severity=SecuritySeverity.CRITICAL,
        repository="acme/widgets",
        findings=[
            SecurityFinding(
                id="finding-1",
                finding_type="vulnerability",
                severity=SecuritySeverity.CRITICAL,
                title="RCE in parser",
                description="Remote code execution via crafted input",
                cve_id="CVE-2026-0001",
                package_name="widget-parser",
            )
        ],
    )
    question = security_question.build_security_debate_question(event)
    assert "Repository: acme/widgets" in question
    assert "CVE-2026-0001 in widget-parser" in question
    assert question == security_response.build_security_debate_question(event)
