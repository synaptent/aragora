"""The Supermemory client lives in ``aragora.memory.supermemory``.

``aragora.memory.backends.supermemory`` (domain layer) builds the client. The client
package used to live in ``aragora.connectors`` (interface layer) and imports nothing
from aragora outside itself, so it now sits in the memory package.
``aragora.connectors.supermemory`` and its ``client``, ``config`` and
``privacy_filter`` submodules re-export the same objects; the shared client lives
only in ``aragora.memory.supermemory.client``.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEW_HOME = "aragora.memory.supermemory"
OLD_HOME = "aragora.connectors.supermemory"
PACKAGE_NAMES = tuple(
    "PrivacyFilter PrivacyFilterConfig SupermemoryClient SupermemoryConfig clear_client "
    "get_client".split()
)
SUBMODULE_NAMES = {
    "client": tuple(
        "MemoryAddResult SearchResponse SearchResult SupermemoryClient SupermemoryConnectionError "
        "SupermemoryError SupermemoryRateLimitError clear_client get_client with_retry".split()
    ),
    "config": ("SupermemoryConfig",),
    "privacy_filter": ("PrivacyFilter", "PrivacyFilterConfig"),
}
SUBMODULE_CASES = [
    (submodule, name) for submodule, names in SUBMODULE_NAMES.items() for name in names
]


@pytest.fixture
def new():
    client = importlib.import_module(f"{NEW_HOME}.client")
    client.clear_client()
    yield importlib.import_module(NEW_HOME)
    client.clear_client()


@pytest.mark.parametrize("name", PACKAGE_NAMES)
def test_the_old_package_is_the_same_objects(new, name):
    assert getattr(importlib.import_module(OLD_HOME), name) is getattr(new, name)


@pytest.mark.parametrize(("submodule", "name"), SUBMODULE_CASES)
def test_the_old_submodules_are_the_same_objects(new, submodule, name):
    old = importlib.import_module(f"{OLD_HOME}.{submodule}")
    assert getattr(old, name) is getattr(importlib.import_module(f"{NEW_HOME}.{submodule}"), name)
    assert name in old.__all__


def test_the_client_is_defined_in_the_memory_package(new):
    assert new.SupermemoryClient.__module__ == f"{NEW_HOME}.client"
    assert new.SupermemoryConfig.__module__ == f"{NEW_HOME}.config"
    assert new.PrivacyFilter.__module__ == f"{NEW_HOME}.privacy_filter"
    assert sorted(new.__all__) == sorted(PACKAGE_NAMES)
    assert sorted(importlib.import_module(OLD_HOME).__all__) == sorted(PACKAGE_NAMES)


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_the_privacy_filter_redacts_the_same_through_both_paths(new, module_name):
    module = importlib.import_module(module_name)
    filtered = module.PrivacyFilter().filter('config = {"password": "supersecret123"}')
    assert "supersecret123" not in filtered
    assert "password=[REDACTED]" in filtered


@pytest.mark.parametrize("module_name", [OLD_HOME, NEW_HOME])
def test_the_config_reads_the_same_through_both_paths(new, module_name, monkeypatch):
    module = importlib.import_module(module_name)
    monkeypatch.delenv("SUPERMEMORY_API_KEY", raising=False)
    assert module.SupermemoryConfig.from_env() is None
    monkeypatch.setenv("SUPERMEMORY_API_KEY", "test-key")
    monkeypatch.setenv("SUPERMEMORY_SYNC_THRESHOLD", "0.5")
    config = module.SupermemoryConfig.from_env()
    assert isinstance(config, new.SupermemoryConfig)
    assert (config.api_key, config.sync_threshold, config.container_tag) == (
        "test-key",
        0.5,
        "aragora",
    )
    assert config.should_sync(0.6) is True
    assert config.should_sync(0.4) is False


def test_the_shared_client_is_shared_with_the_old_paths(new):
    old_client = importlib.import_module(f"{OLD_HOME}.client")
    config = new.SupermemoryConfig(api_key="test-key")
    client = old_client.get_client(config)
    assert isinstance(client, new.SupermemoryClient)
    assert new.get_client() is client
    assert importlib.import_module(OLD_HOME).get_client() is client
    importlib.import_module(OLD_HOME).clear_client()
    assert new.get_client() is None


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


def test_memory_holds_no_import_of_connectors_at_any_scope():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "memory").rglob("*.py"))
        for lineno, name in _imported_modules(path)
        if name == "aragora.connectors" or name.startswith("aragora.connectors.")
    ]
    assert offenders == []


@pytest.mark.parametrize(
    "relative",
    [
        "aragora/debate/knowledge_manager.py",
        "aragora/knowledge/mound/adapters/factory.py",
        "aragora/knowledge/mound/adapters/supermemory_adapter.py",
    ],
)
def test_debate_and_knowledge_build_the_client_from_the_memory_package(relative):
    imported = {name for _, name in _imported_modules(REPO_ROOT / relative)}
    assert OLD_HOME not in imported
    assert NEW_HOME in imported


def test_the_home_imports_only_itself_from_aragora(new):
    package_dir = Path(new.__file__).parent
    imported = {
        name
        for path in sorted(package_dir.glob("*.py"))
        for _, name in _imported_modules(path)
        if name.startswith("aragora")
    }
    assert imported <= {NEW_HOME, f"{NEW_HOME}.client", f"{NEW_HOME}.config"}
