"""The synthetic GitHub market adapter lives in ``aragora.markets.synthetic_github``.

``aragora.markets.emitter`` (application layer) builds the adapter. The adapter
used to live in ``aragora.connectors.prediction_markets`` (interface layer); it
only wraps ``aragora.markets``, so it now sits in that package, and the connector
paths re-export the same objects.
"""

from __future__ import annotations

import ast
import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_HOME = "aragora.markets.synthetic_github"
OLD_HOME = "aragora.connectors.prediction_markets.synthetic_github"
NAMES = (
    "DEFAULT_POSITION_CAP",
    "SYNTHETIC_MARKETS_FLAG",
    "SyntheticGitHubAdapter",
    "SyntheticGitHubError",
    "open_adapter",
    "synthetic_markets_enabled",
)
CREATED_AT = datetime(2026, 1, 5, tzinfo=UTC)


@pytest.fixture
def new():
    return importlib.import_module(NEW_HOME)


@pytest.mark.parametrize("module_name", [OLD_HOME, "aragora.connectors.prediction_markets"])
@pytest.mark.parametrize("name", NAMES)
def test_the_old_paths_are_the_same_objects(new, module_name, name):
    assert getattr(importlib.import_module(module_name), name) is getattr(new, name)


def test_the_adapter_is_defined_in_the_markets_package(new):
    assert new.SyntheticGitHubAdapter.__module__ == NEW_HOME
    assert new.open_adapter.__module__ == NEW_HOME
    assert sorted(new.__all__) == sorted(NAMES)
    assert sorted(importlib.import_module(OLD_HOME).__all__) == sorted(NAMES)


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_the_flag_reads_the_same_through_both_paths(module_name, monkeypatch):
    module = importlib.import_module(module_name)
    assert module.SYNTHETIC_MARKETS_FLAG == "ARAGORA_SYNTHETIC_MARKETS_ENABLED"
    monkeypatch.delenv(module.SYNTHETIC_MARKETS_FLAG, raising=False)
    assert module.synthetic_markets_enabled() is False
    monkeypatch.setenv(module.SYNTHETIC_MARKETS_FLAG, "yes")
    assert module.synthetic_markets_enabled() is True


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_the_disabled_guard_raises_the_shared_error(new, module_name, monkeypatch, tmp_path):
    module = importlib.import_module(module_name)
    monkeypatch.delenv(module.SYNTHETIC_MARKETS_FLAG, raising=False)
    adapter = module.open_adapter(tmp_path / "markets")
    with pytest.raises(new.SyntheticGitHubError, match=module.SYNTHETIC_MARKETS_FLAG):
        adapter.create_pr_merge_market(repo="owner/repo", pr_number=1)


def test_a_market_written_through_the_old_path_is_read_through_the_new_path(
    new, monkeypatch, tmp_path
):
    old = importlib.import_module(OLD_HOME)
    monkeypatch.setenv(old.SYNTHETIC_MARKETS_FLAG, "1")
    market = old.open_adapter(tmp_path / "markets", require_expiry=False).create_pr_merge_market(
        repo="owner/repo", pr_number=7, created_at=CREATED_AT
    )
    reread = new.open_adapter(tmp_path / "markets").store.get_market(market.market_id)
    assert reread == market
    assert reread.description == "Will PR #7 in owner/repo merge within 7d?"


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


def test_markets_holds_no_import_of_connectors_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "markets").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.connectors" or name.startswith("aragora.connectors.")
    ]
    assert offenders == []


def test_the_new_home_imports_only_the_markets_package_from_aragora(new):
    imported = {
        name for _, name in _imported_modules(Path(new.__file__)) if name.startswith("aragora")
    }
    assert imported == {
        "aragora.markets.resolver",
        "aragora.markets.store",
        "aragora.markets.types",
    }
