"""Threat intelligence enrichment builds its CVE client through ``aragora.security.cve_clients``.

``aragora.security`` (infrastructure layer) must not import ``aragora.analysis`` (domain layer)
at runtime. The analysis package registers its CVE client factory through the
``aragora.security_cve_clients`` entry point.
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

from aragora.security import cve_clients as hook
from aragora.security.threat_intel_enrichment import ThreatIntelEnrichment
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
CVE_REGISTRATION = (
    "analysis",
    "aragora.analysis.codebase.cve_registration:register_security_cve_client",
)


class FakeCVEClient:
    async def get_cve(self, cve_id):
        return None


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.CVE_CLIENTS_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def _enrichment(**kwargs):
    # A stand-in threat client keeps the constructor from building the real service.
    return ThreatIntelEnrichment(threat_intel_client=object(), enabled=True, **kwargs)


def test_an_unregistered_factory_raises(isolated_hook):
    with pytest.raises(hook.CVEClientNotRegisteredError, match="aragora.security_cve_clients"):
        hook.create_cve_client()


def test_without_a_factory_enrichment_has_no_cve_client(isolated_hook):
    assert _enrichment()._cve_client is None


def test_enrichment_builds_its_cve_client_with_the_factory(isolated_hook):
    hook.register_cve_client_factory(FakeCVEClient)
    assert isinstance(_enrichment()._cve_client, FakeCVEClient)


def test_a_given_cve_client_skips_the_factory(isolated_hook):
    calls = []
    hook.register_cve_client_factory(lambda: calls.append("built"))
    client = FakeCVEClient()
    assert _enrichment(cve_client=client)._cve_client is client
    assert ThreatIntelEnrichment(threat_intel_client=object(), enabled=False)._cve_client is None
    assert calls == []


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_cve_client_factory(FakeCVEClient)

    entry_point = SimpleNamespace(name="c0", value="tests.declared:c0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.CVE_CLIENTS_ENTRY_POINT_GROUP else [],
    )
    assert isinstance(hook.create_cve_client(), FakeCVEClient)
    assert isinstance(hook.create_cve_client(), FakeCVEClient)
    assert calls == ["register"]


def test_pyproject_declares_the_analysis_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.CVE_CLIENTS_ENTRY_POINT_GROUP)
    assert [(ep.name, ep.value) for ep in declared._source_declarations()] == [CVE_REGISTRATION]


def test_the_registered_factory_builds_the_codebase_cve_client(isolated_hook, monkeypatch):
    from aragora.analysis.codebase.cve_client import CVEClient
    from aragora.analysis.codebase.cve_registration import register_security_cve_client

    monkeypatch.delenv("NVD_API_KEY", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    register_security_cve_client()
    assert type(hook.create_cve_client()) is CVEClient
    assert type(_enrichment()._cve_client) is CVEClient


def test_the_registered_factory_reads_the_client_at_call_time(isolated_hook, monkeypatch):
    from aragora.analysis.codebase import cve_client
    from aragora.analysis.codebase.cve_registration import register_security_cve_client

    register_security_cve_client()
    monkeypatch.setattr(cve_client, "CVEClient", FakeCVEClient)
    assert isinstance(hook.create_cve_client(), FakeCVEClient)

    monkeypatch.setitem(sys.modules, "aragora.analysis.codebase.cve_client", None)
    with pytest.raises(ImportError):
        hook.create_cve_client()
    assert _enrichment()._cve_client is None


def test_a_security_only_process_reaches_the_cve_client_factory():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    script = (
        "import sys\n"
        "import aragora.security.threat_intel_enrichment\n"
        "loaded_before = 'aragora.analysis' in sys.modules\n"
        "from aragora.security.cve_clients import create_cve_client\n"
        "client = create_cve_client()\n"
        "print(loaded_before, type(client).__module__, type(client).__name__)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    env.pop("NVD_API_KEY", None)
    env.pop("GITHUB_TOKEN", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-3:] == [
        "False",
        "aragora.analysis.codebase.cve_client",
        "CVEClient",
    ]


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


def _is_module(name):
    path = REPO_ROOT.joinpath(*name.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def test_security_holds_no_runtime_import_of_analysis():
    # Like the import contract, count only modules that exist: an import of a missing
    # analysis module always raises ImportError and creates no dependency.
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "security").rglob("*.py"))
        for line, name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if (name == "aragora.analysis" or name.startswith("aragora.analysis.")) and _is_module(name)
    ]
    assert offenders == []
