"""Characterization of the code scanner registry used by the codebase understanding agent.

``aragora.agents`` (domain layer) must not import ``aragora.audit`` (application layer),
which implements the security scanner and bug detector. The audit package registers a
factory per scanner kind from its own init, the agent builds scanners through the
registry, and a process that never imports the audit package reaches the registration
declared under the ``aragora.code_scanners`` entry-point group.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.agents import code_scanners as scanners

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = REPO_ROOT / "aragora" / "agents"
AUDIT_REGISTRATION = ("audit", "aragora.audit.code_scanners:register_code_scanners")


@pytest.fixture
def isolated_scanners(monkeypatch):
    """Run a test against an empty registry; the process-wide one is restored afterwards."""
    # Loading the audit package inside the swap would register into the temporary
    # registry only, so load it before swapping.
    import aragora.audit  # noqa: F401

    monkeypatch.setattr(scanners, "_factories", {})
    # Treat the declared registrations as already run, so a miss stays a miss.
    monkeypatch.setattr(scanners, "_declared_registrations_loaded", True)
    return scanners


@pytest.fixture
def undiscovered_scanners(isolated_scanners, monkeypatch, tmp_path):
    """An empty registry on which the declared registrations have not run yet.

    The source-checkout pyproject is pointed at a missing file, so only the entry points a
    test declares run; tests of the source-checkout fallback point it back at the repo.
    """
    monkeypatch.setattr(scanners, "_declared_registrations_loaded", False)
    monkeypatch.setattr(scanners, "_SOURCE_PYPROJECT", tmp_path / "missing.toml")
    return scanners


def _use_the_repo_pyproject(monkeypatch):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    monkeypatch.setattr(scanners, "_SOURCE_PYPROJECT", REPO_ROOT / "pyproject.toml")


def _declare(monkeypatch, *registrations):
    """Make ``registrations`` the only installed entry points of the aragora.code_scanners group.

    Each registration is a callable, or a ``(name, "module:function", callable)`` triple
    that sets its entry point's name and target.
    """
    entry_points = []
    for index, registration in enumerate(registrations):
        if isinstance(registration, tuple):
            name, value, fn = registration
        else:
            name, value, fn = f"d{index}", f"tests.declared:d{index}", registration
        entry_points.append(SimpleNamespace(name=name, value=value, load=lambda fn=fn: fn))
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: entry_points if group == "aragora.code_scanners" else [],
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", [scanners.SECURITY_SCANNER, scanners.BUG_DETECTOR])
def test_an_unregistered_kind_raises(isolated_scanners, kind):
    with pytest.raises(scanners.CodeScannerNotRegisteredError, match=kind):
        scanners.create_code_scanner(kind)


def test_registering_again_replaces_the_factory(isolated_scanners):
    first, second = object(), object()
    scanners.register_code_scanner(scanners.BUG_DETECTOR, lambda: first)
    scanners.register_code_scanner(scanners.BUG_DETECTOR, lambda: second)
    assert scanners.create_code_scanner(scanners.BUG_DETECTOR) is second
    assert list(scanners._factories) == [scanners.BUG_DETECTOR]


def test_each_lookup_builds_a_new_scanner(isolated_scanners):
    scanners.register_code_scanner(scanners.SECURITY_SCANNER, object)
    first = scanners.create_code_scanner(scanners.SECURITY_SCANNER)
    assert scanners.create_code_scanner(scanners.SECURITY_SCANNER) is not first


# ---------------------------------------------------------------------------
# The audit package registers its scanners
# ---------------------------------------------------------------------------


def test_audit_init_registers_both_scanners():
    import aragora.audit  # noqa: F401
    from aragora.audit.bug_detector import BugDetector
    from aragora.audit.security_scanner import SecurityScanner

    assert isinstance(scanners.create_code_scanner(scanners.SECURITY_SCANNER), SecurityScanner)
    assert isinstance(scanners.create_code_scanner(scanners.BUG_DETECTOR), BugDetector)


def test_audit_registration_is_idempotent(isolated_scanners):
    from aragora.audit.code_scanners import register_code_scanners

    register_code_scanners()
    register_code_scanners()
    assert sorted(scanners._factories) == [scanners.BUG_DETECTOR, scanners.SECURITY_SCANNER]


# ---------------------------------------------------------------------------
# Declared registrations run on the first lookup that finds nothing
# ---------------------------------------------------------------------------


def test_a_lookup_miss_runs_the_declared_registrations_once(undiscovered_scanners, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        scanners.register_code_scanner(scanners.SECURITY_SCANNER, object)

    _declare(monkeypatch, register)

    assert scanners.create_code_scanner(scanners.SECURITY_SCANNER) is not None
    assert scanners.create_code_scanner(scanners.SECURITY_SCANNER) is not None
    with pytest.raises(scanners.CodeScannerNotRegisteredError):
        scanners.create_code_scanner(scanners.BUG_DETECTOR)
    assert calls == ["register"]


def test_a_failing_declared_registration_is_logged_and_the_lookup_still_raises(
    undiscovered_scanners, monkeypatch, caplog
):
    def broken():
        raise ImportError("optional dependency missing")

    _declare(monkeypatch, broken)

    with caplog.at_level("WARNING", logger="aragora.agents.code_scanners"):
        with pytest.raises(scanners.CodeScannerNotRegisteredError, match="aragora.code_scanners"):
            scanners.create_code_scanner(scanners.BUG_DETECTOR)
    assert "optional dependency missing" in caplog.text


def test_an_unexpected_registration_error_reaches_the_caller_after_the_later_ones_ran(
    undiscovered_scanners, monkeypatch
):
    class PluginBug(Exception):
        pass

    def broken():
        raise PluginBug("plugin defect")

    _declare(
        monkeypatch, broken, lambda: scanners.register_code_scanner(scanners.BUG_DETECTOR, object)
    )

    with pytest.raises(PluginBug):
        scanners.create_code_scanner(scanners.BUG_DETECTOR)
    assert scanners.create_code_scanner(scanners.BUG_DETECTOR) is not None


def test_a_source_checkout_uses_its_pyproject_declarations_when_metadata_has_none(
    undiscovered_scanners, monkeypatch
):
    from aragora.audit.security_scanner import SecurityScanner

    _use_the_repo_pyproject(monkeypatch)
    _declare(monkeypatch)

    assert isinstance(scanners.create_code_scanner(scanners.SECURITY_SCANNER), SecurityScanner)


def test_an_unrelated_installed_plugin_does_not_hide_the_source_checkout_declarations(
    undiscovered_scanners, monkeypatch
):
    from aragora.audit.security_scanner import SecurityScanner

    _use_the_repo_pyproject(monkeypatch)
    # Named like aragora's own entry point, but with another target.
    _declare(monkeypatch, ("audit", "other.scanners:register", lambda: None))

    assert isinstance(scanners.create_code_scanner(scanners.SECURITY_SCANNER), SecurityScanner)


def test_an_installed_declaration_is_not_run_again_from_the_source_checkout(
    undiscovered_scanners, monkeypatch
):
    calls = []

    def installed_audit():
        calls.append("installed")
        scanners.register_code_scanner(scanners.BUG_DETECTOR, object)

    _use_the_repo_pyproject(monkeypatch)
    _declare(monkeypatch, (*AUDIT_REGISTRATION, installed_audit))

    assert scanners.create_code_scanner(scanners.BUG_DETECTOR) is not None
    assert calls == ["installed"]
    # The source-checkout audit registration would have registered this one too.
    with pytest.raises(scanners.CodeScannerNotRegisteredError):
        scanners.create_code_scanner(scanners.SECURITY_SCANNER)


def test_unreadable_entry_point_metadata_is_logged_and_the_source_checkout_still_registers(
    undiscovered_scanners, monkeypatch, caplog
):
    from aragora.audit.bug_detector import BugDetector

    def unreadable(*, group):
        raise RuntimeError("corrupt dist-info")

    _use_the_repo_pyproject(monkeypatch)
    monkeypatch.setattr(importlib.metadata, "entry_points", unreadable)

    with caplog.at_level("WARNING", logger="aragora.agents.code_scanners"):
        assert isinstance(scanners.create_code_scanner(scanners.BUG_DETECTOR), BugDetector)
    assert "corrupt dist-info" in caplog.text


def test_pyproject_declares_the_audit_registration(monkeypatch, tmp_path):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = [(ep.name, ep.value) for ep in scanners._source_checkout_registrations()]
    assert declared == [AUDIT_REGISTRATION]

    other = tmp_path / "pyproject.toml"
    other.write_text(
        '[project]\nname = "other"\n\n[project.entry-points."aragora.code_scanners"]\n'
        'other = "other.scanners:register"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(scanners, "_SOURCE_PYPROJECT", other)
    assert scanners._source_checkout_registrations() == []
    monkeypatch.setattr(scanners, "_SOURCE_PYPROJECT", tmp_path / "missing.toml")
    assert scanners._source_checkout_registrations() == []


def test_an_agents_only_process_still_builds_both_scanners(tmp_path):
    # Installed metadata that predates the entry point leaves the pyproject fallback,
    # which needs tomli before Python 3.11.
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "from aragora.agents.codebase_agent import CodebaseUnderstandingAgent\n"
        "assert not any(m.startswith('aragora.audit') for m in sys.modules), 'audit preloaded'\n"
        "agent = CodebaseUnderstandingAgent(sys.argv[1], enable_debate=False)\n"
        "print(type(agent.security_scanner).__name__, type(agent.bug_detector).__name__)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["SecurityScanner", "BugDetector"]


# ---------------------------------------------------------------------------
# aragora.agents names no import of aragora.audit
# ---------------------------------------------------------------------------


def _module_name(node: ast.ImportFrom, path: Path) -> str:
    if node.level == 0:
        return node.module or ""
    package = path.relative_to(REPO_ROOT).with_suffix("").parts[: -node.level]
    return ".".join(package + ((node.module,) if node.module else ()))


def _is_audit(name: str) -> bool:
    return name == "aragora.audit" or name.startswith("aragora.audit.")


def test_agents_have_no_import_of_audit_at_any_scope():
    offenders = []
    for path in sorted(AGENTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [_module_name(node, path)]
            elif isinstance(node, ast.Call) and node.args:
                func = node.func
                callee = getattr(func, "attr", None) or getattr(func, "id", None)
                first = node.args[0]
                if callee in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                    names = [str(first.value)]
            offenders += [
                f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {n}" for n in names if _is_audit(n)
            ]
    assert offenders == []


def test_agents_source_text_names_no_audit_import():
    pattern = re.compile(
        r"(from|import) aragora\.audit\b|(import_module|__import__)\(\s*['\"]aragora\.audit\b"
    )
    hits = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}"
        for path in sorted(AGENTS_DIR.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert hits == []
