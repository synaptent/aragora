"""The debate-sourced improvement queue lives in ``aragora.learning``.

``aragora.memory`` (domain layer) enqueues suggestions when it detects a contradiction and
must not import ``aragora.nomic`` (application layer) to do so. ``aragora.nomic.improvement_queue``
re-exports the same objects, and both paths share one queue singleton.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aragora.learning import improvement_queue as new
from aragora.nomic import improvement_queue as old

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", new.__all__)
def test_the_old_path_holds_the_same_objects(name):
    assert getattr(old, name) is getattr(new, name)


@pytest.mark.parametrize("name", ["ImprovementQueue", "ImprovementSuggestion"])
def test_the_classes_are_defined_in_the_learning_package(name):
    assert getattr(new, name).__module__ == "aragora.learning.improvement_queue"


def test_both_paths_share_one_queue(monkeypatch):
    monkeypatch.setattr(new, "_global_queue", None)
    queue = old.get_improvement_queue()
    assert new.get_improvement_queue() is queue

    queue.enqueue(
        new.ImprovementSuggestion(
            debate_id="d1", task="t", suggestion="s", category="reliability", confidence=0.5
        )
    )
    assert [s.debate_id for s in new.get_improvement_queue().peek()] == ["d1"]


def test_a_full_queue_evicts_the_oldest_suggestion():
    queue = new.ImprovementQueue(max_size=2)
    for debate_id in ("a", "b", "c"):
        queue.enqueue(
            old.ImprovementSuggestion(
                debate_id=debate_id, task="t", suggestion="s", category="c", confidence=1.0
            )
        )
    assert [s.debate_id for s in queue.dequeue_batch(5)] == ["b", "c"]
    assert len(queue) == 0


def _imported_names(path: Path) -> list[tuple[int, str]]:
    names: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            names.append((node.lineno, node.module or ""))
    return names


def test_the_new_home_imports_nothing_from_aragora():
    imported = _imported_names(REPO_ROOT / "aragora/learning/improvement_queue.py")
    assert [name for _, name in imported if name.startswith("aragora")] == []


def test_memory_holds_no_import_of_nomic():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora/memory").rglob("*.py"))
        for lineno, name in _imported_names(path)
        if name == "aragora.nomic" or name.startswith("aragora.nomic.")
    ]
    assert offenders == []
