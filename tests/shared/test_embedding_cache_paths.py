"""The embedding cache lives in ``aragora.shared``; the debate path re-exports it.

Both import paths must hand out the same objects and the same cache state, the
shared module must not import the debate or persistence packages, and the
persistence database path must come from the resolver the debate cache package
registers.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import logging
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

import aragora.debate.cache as debate_cache  # noqa: E402
import aragora.debate.cache.embeddings_lru as old  # noqa: E402
from aragora.persistence.db_config import DatabaseType, get_db_path_str  # noqa: E402

new = importlib.import_module("aragora.shared.embedding_cache")

PUBLIC_NAMES = (
    "EmbeddingCache",
    "EmbeddingCacheManager",
    "get_embedding_cache",
    "get_scoped_embedding_cache",
    "cleanup_embedding_cache",
    "reset_embedding_cache",
)


@pytest.fixture(autouse=True)
def _fresh_cache_state():
    new.reset_embedding_cache()
    yield
    new.reset_embedding_cache()


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_old_path_reexports_the_shared_object(name: str) -> None:
    assert getattr(old, name) is getattr(new, name)
    assert name in old.__all__


def test_implementation_module_is_shared() -> None:
    assert inspect.getmodule(old.EmbeddingCache) is new
    assert new.__name__ == "aragora.shared.embedding_cache"
    assert new.logger.name == "aragora.shared.embedding_cache"


@pytest.mark.parametrize("module", [old, new], ids=["old", "new"])
def test_fixed_input_lru_behaviour_at_both_paths(module) -> None:
    cache = module.EmbeddingCache(max_size=2)
    assert cache._hash_text("hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e"
    cache.put("a", np.array([1.0], dtype=np.float32))
    cache.put("b", np.array([2.0], dtype=np.float32))
    cache.put("c", np.array([3.0], dtype=np.float32))
    assert cache.get("a") is None
    np.testing.assert_array_equal(cache.get("c"), np.array([3.0], dtype=np.float32))
    assert cache.get_stats() == {
        "hits": 1,
        "misses": 1,
        "hit_rate": 0.5,
        "size": 2,
        "max_size": 2,
    }


def test_global_cache_state_is_shared_between_paths() -> None:
    cache = old.get_embedding_cache()
    assert cache is new.get_embedding_cache()

    cache.put("alpha", np.array([0.1, 0.2], dtype=np.float32))
    np.testing.assert_array_equal(
        new.get_embedding_cache().get("alpha"), np.array([0.1, 0.2], dtype=np.float32)
    )

    old.reset_embedding_cache()
    assert new.get_embedding_cache() is not cache
    assert new.get_embedding_cache().get("alpha") is None


def test_scoped_cache_state_is_shared_between_paths() -> None:
    scoped = old.get_scoped_embedding_cache("d1")
    assert scoped is new.get_scoped_embedding_cache("d1")
    scoped.put("beta", np.array([1.0], dtype=np.float32))

    old.cleanup_embedding_cache("d1")
    fresh = new.get_scoped_embedding_cache("d1")
    assert fresh is not scoped
    assert fresh.get("beta") is None


def test_unregistered_resolver_raises_for_default_persistent_caches(monkeypatch) -> None:
    monkeypatch.setattr(new, "_default_db_path_resolver", None)

    with pytest.raises(RuntimeError, match="database path resolver"):
        new.get_embedding_cache(persist=True)

    manager = new.EmbeddingCacheManager()
    manager.configure(persist=True)
    with pytest.raises(RuntimeError, match="database path resolver"):
        manager.get_cache("d-unregistered")


def test_explicit_db_path_needs_no_resolver(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(new, "_default_db_path_resolver", None)
    db_path = str(tmp_path / "embeddings.db")

    assert new.get_embedding_cache(persist=True, db_path=db_path).db_path == db_path
    manager = new.EmbeddingCacheManager()
    manager.configure(persist=True, db_path=db_path)
    assert manager.get_cache("d-explicit").db_path == db_path


def test_debate_cache_package_registers_persistence_path(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(new, "_default_db_path_resolver", None)

    importlib.reload(debate_cache)
    first = new._default_db_path_resolver
    assert first is debate_cache._embeddings_db_path

    expected = get_db_path_str(DatabaseType.EMBEDDINGS)
    assert expected.startswith(str(tmp_path))
    assert new.get_embedding_cache(persist=True).db_path == expected

    manager = new.EmbeddingCacheManager()
    manager.configure(persist=True)
    assert manager.get_cache("d-registered").db_path == expected

    importlib.reload(debate_cache)
    assert new._default_db_path_resolver is debate_cache._embeddings_db_path
    assert new._default_db_path_resolver() == expected


def _upper_imports(tree: ast.AST) -> list[tuple[int, str]]:
    forbidden = ("aragora.debate", "aragora.persistence")
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        elif isinstance(node, ast.Call) and ast.unparse(node.func) in {
            "importlib.import_module",
            "__import__",
        }:
            modules = [ast.unparse(arg) for arg in node.args[:1]]
        for module in modules:
            if any(pkg in module for pkg in forbidden):
                found.append((node.lineno, module))
    return found


def test_shared_package_never_imports_debate_or_persistence() -> None:
    package_dir = Path(new.__file__).parent
    offenders = []
    for source in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        offenders.extend((str(source), *hit) for hit in _upper_imports(tree))
    assert offenders == []


def test_triage_diagnostics_capture_the_shared_cache_logger(tmp_path: Path) -> None:
    from aragora.inbox.triage_diagnostics import TriageRunDiagnostics

    diagnostics = TriageRunDiagnostics(
        profile="test",
        batch_size=1,
        auto_approve=False,
        dry_run=True,
        verbose=False,
        diagnostics_dir=tmp_path,
    )
    record = logging.LogRecord(
        new.logger.name,
        logging.DEBUG,
        __file__,
        1,
        "Created new embedding cache for debate %s",
        ("d1",),
        None,
    )
    assert diagnostics.should_capture_record(record)
