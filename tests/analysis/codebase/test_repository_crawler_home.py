"""The repository crawler lives in ``aragora.analysis.codebase.repository_crawler``.

``aragora.nomic.rlm_codebase`` (application layer) and ``aragora.knowledge``
(domain layer) crawl local repositories. The crawler used to live in
``aragora.connectors`` (interface layer); it imports nothing from aragora, so it
now sits with the other codebase analysis tools, and the connector path
re-exports the same objects.
"""

from __future__ import annotations

import ast
import asyncio
import importlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
NEW_HOME = "aragora.analysis.codebase.repository_crawler"
OLD_HOME = "aragora.connectors.repository_crawler"
ALL_NAMES = (
    "CrawlConfig",
    "CrawlResult",
    "CrawlState",
    "CrawledFile",
    "FileDependency",
    "FileSymbol",
    "FileType",
    "RepositoryCrawler",
    "crawl_repository",
)
EXPECTED_CRAWL = {
    "total_files": 3,
    "total_lines": 16,
    "file_type_counts": {"javascript": 1, "python": 2},
    "symbol_counts": {"function": 4, "class": 1},
    "files": [
        ("index.js", "javascript", [("add", "function")], []),
        (
            "pkg/app.py",
            "python",
            [("Greeter", "class"), ("main", "function"), ("hello", "function")],
            ["os", "pkg"],
        ),
        ("pkg/util.py", "python", [("helper", "function")], []),
    ],
    "dependency_graph": {"pkg/app.py": ["os", "pkg"]},
    "errors": [],
}


@pytest.fixture
def new():
    return importlib.import_module(NEW_HOME)


@pytest.mark.parametrize("name", (*ALL_NAMES, "EXTENSION_MAP"))
def test_the_old_path_holds_the_same_objects(new, name):
    assert getattr(importlib.import_module(OLD_HOME), name) is getattr(new, name)


@pytest.mark.parametrize("name", ALL_NAMES)
def test_the_connectors_package_lazy_exports_are_the_same_objects(new, name):
    assert getattr(importlib.import_module("aragora.connectors"), name) is getattr(new, name)


def test_the_crawler_is_defined_in_the_analysis_package(new):
    assert new.RepositoryCrawler.__module__ == NEW_HOME
    assert new.crawl_repository.__module__ == NEW_HOME
    assert sorted(new.__all__) == sorted(ALL_NAMES)
    assert sorted(importlib.import_module(OLD_HOME).__all__) == sorted(ALL_NAMES)


def _write_repo(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "app.py").write_text(
        "import os\nfrom pkg import util\n\nclass Greeter:\n    def hello(self, name):\n"
        '        return f"hi {name}"\n\n\ndef main():\n    return Greeter().hello("x")\n',
        encoding="utf-8",
    )
    (root / "pkg" / "util.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    (root / "index.js").write_text(
        "export function add(a, b) { return a + b; }\n", encoding="utf-8"
    )
    return root


def _summary(result: Any) -> dict[str, Any]:
    return {
        "total_files": result.total_files,
        "total_lines": result.total_lines,
        "file_type_counts": result.file_type_counts,
        "symbol_counts": result.symbol_counts,
        "files": sorted(
            (
                crawled.relative_path,
                crawled.file_type.value,
                [(symbol.name, symbol.kind) for symbol in crawled.symbols],
                [dependency.target for dependency in crawled.dependencies],
            )
            for crawled in result.files
        ),
        "dependency_graph": result.dependency_graph,
        "errors": result.errors,
    }


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_the_crawl_gives_the_same_result_through_both_paths(module_name, tmp_path):
    module = importlib.import_module(module_name)
    result = asyncio.run(module.crawl_repository(str(_write_repo(tmp_path / "repo"))))
    assert _summary(result) == EXPECTED_CRAWL


def test_state_saved_through_the_old_path_restores_through_the_new_path(new):
    old = importlib.import_module(OLD_HOME)
    state = old.CrawlState(
        repository_path="/repo",
        last_crawl=datetime(2026, 1, 5, tzinfo=UTC),
        last_commit="abc123",
        file_hashes={"a.py": "h1"},
        total_crawls=2,
    )
    crawler = new.RepositoryCrawler(config=old.CrawlConfig())
    crawler.set_state(new.CrawlState.from_dict(state.to_dict()))
    assert crawler.get_state() == state


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
        elif isinstance(node, ast.Call) and node.args:
            callee = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if callee in {"import_module", "__import__"}:
                found.append((node.lineno, ast.unparse(node.args[0]).strip("'\"")))
    return found


def test_nomic_holds_no_import_of_connectors_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "nomic").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.connectors" or name.startswith("aragora.connectors.")
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "relative",
    [
        "aragora/knowledge/relationship_builder.py",
        "aragora/knowledge/repository_orchestrator.py",
        "aragora/knowledge/mound/adapters/codebase_adapter.py",
    ],
)
def test_knowledge_crawls_through_the_analysis_home(relative):
    names = {name for _, name in _imported_modules(REPO_ROOT / relative)}
    assert NEW_HOME in names
    assert OLD_HOME not in names


def test_the_new_home_imports_nothing_from_aragora(new):
    assert [name for _, name in _imported_modules(Path(new.__file__)) if "aragora" in name] == []
