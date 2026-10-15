"""The source evidence record lives in ``aragora.reasoning.source_evidence``.

``aragora.evidence`` (domain layer) must not import ``aragora.connectors`` (interface layer) at
runtime. ``aragora.connectors.base`` re-exports the same ``Evidence`` class, and the evidence
collector builds its document connector through ``aragora.runtime.connector_factory``.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.evidence
from aragora.connectors import base as old
from aragora.evidence.collector import EvidenceCollector
from aragora.reasoning import source_evidence as new
from aragora.reasoning.provenance import SourceType
from aragora.runtime import connector_factory as hook
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]

FIELDS = {
    "id": "ev-1",
    "source_type": SourceType.WEB_SEARCH,
    "source_id": "https://example.com/a",
    "content": "rate limiters bound request bursts",
    "title": "Rate limiting",
    "confidence": 0.8,
    "freshness": 0.5,
    "authority": 0.6,
}


def test_both_paths_hold_the_same_class():
    assert old.Evidence is new.Evidence
    assert aragora.evidence.Evidence is new.Evidence
    assert new.Evidence.__module__ == "aragora.reasoning.source_evidence"
    assert "Evidence" in old.__all__
    assert new.__all__ == ["Evidence"]


@pytest.mark.parametrize("evidence_cls", [old.Evidence, new.Evidence], ids=["old", "new"])
def test_scores_and_hash_are_unchanged_at_both_paths(evidence_cls):
    evidence = evidence_cls(**FIELDS)
    assert evidence.reliability_score == pytest.approx(0.4 * 0.8 + 0.3 * 0.5 + 0.3 * 0.6)
    assert evidence.content_hash == "0d3de3356cf088a1"
    assert evidence.to_dict()["source_type"] == "web_search"
    assert evidence.to_dict()["reliability_score"] == pytest.approx(0.65)


@pytest.mark.parametrize("evidence_cls", [old.Evidence, new.Evidence], ids=["old", "new"])
def test_a_dict_round_trip_is_unchanged_at_both_paths(evidence_cls):
    evidence = evidence_cls(**FIELDS, metadata={"lang": "en"})
    restored = evidence_cls.from_dict(evidence.to_dict())
    assert restored == evidence
    assert isinstance(restored, new.Evidence)
    fallback = evidence_cls.from_dict(
        {"id": "x", "source_type": "not-a-source", "source_id": "s", "content": "c"}
    )
    assert fallback.source_type is SourceType.WEB_SEARCH
    assert (fallback.title, fallback.confidence, fallback.metadata) == ("", 0.5, {})


def test_the_old_path_builds_the_same_record_as_the_new_one():
    assert old.Evidence(**FIELDS) == new.Evidence(**FIELDS)
    assert old.Evidence(**FIELDS).content_hash == new.Evidence(**FIELDS).content_hash


def test_the_new_home_imports_only_the_reasoning_package():
    tree = ast.parse((REPO_ROOT / "aragora/reasoning/source_evidence.py").read_text())
    imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]
    assert [
        m for m in imported if m.startswith("aragora") and not m.startswith("aragora.reasoning")
    ] == []


def _runtime_imports(path: Path) -> list[tuple[int, str]]:
    """Absolute ``aragora`` imports outside ``if TYPE_CHECKING:`` blocks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    type_checking_nodes = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
        and (
            (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
            or (isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING")
        )
        for stmt in node.body
        for child in ast.walk(stmt)
    }
    found = []
    for node in ast.walk(tree):
        if id(node) in type_checking_nodes:
            continue
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
            and getattr(node.func, "id", getattr(node.func, "attr", ""))
            in {"import_module", "__import__"}
        ):
            found.append((node.lineno, "<dynamic import>"))
    return found


def test_the_evidence_package_holds_no_runtime_import_of_connectors():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line} {module}"
        for path in sorted((REPO_ROOT / "aragora/evidence").rglob("*.py"))
        for line, module in _runtime_imports(path)
        if module.startswith("aragora.connectors") or module == "<dynamic import>"
    ]
    assert offenders == []


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.CONNECTOR_FACTORIES_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def test_the_registration_builds_a_real_document_connector(isolated_hook, monkeypatch):
    from aragora.connectors.documents import DocumentConnector
    from aragora.connectors.factory_registration import register_evidence_connectors

    register_evidence_connectors()
    connector = hook.create_connector("documents", max_pages=3)
    assert type(connector) is DocumentConnector
    assert connector.parser.max_pages == 3

    recording = type("Recording", (), {"__init__": lambda self, **kw: setattr(self, "kw", kw)})
    monkeypatch.setattr("aragora.connectors.documents.DocumentConnector", recording)
    assert type(hook.create_connector("documents")) is recording


def test_the_collector_builds_its_document_connector_through_the_hook(isolated_hook):
    built = []

    def factory(kind, **kwargs):
        built.append((kind, kwargs))
        return object()

    isolated_hook.register_connector_factory(factory)
    collector = EvidenceCollector()
    connector = collector._get_document_connector()
    assert built == [("documents", {})]
    assert collector._get_document_connector() is connector
    assert len(built) == 1


def test_the_collector_without_a_factory_disables_document_parsing(isolated_hook):
    collector = EvidenceCollector()
    assert collector._get_document_connector() is None
    assert collector._document_connector is None


def test_an_evidence_only_process_reads_a_document_through_the_hook(tmp_path):
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    note = tmp_path / "note.csv"
    note.write_text(
        "topic,text\nlimits,Token buckets refill at a fixed rate and bound request bursts.\n",
        encoding="utf-8",
    )
    script = (
        "import asyncio, sys\n"
        "from aragora.evidence.collector import EvidenceCollector\n"
        "collector = EvidenceCollector()\n"
        "print(type(collector._get_document_connector()).__name__)\n"
        "snippets = asyncio.run(collector.parse_document_file(sys.argv[1]))\n"
        "print(any('Token buckets' in s.snippet for s in snippets or []))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(note)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["DocumentConnector", "True"]
