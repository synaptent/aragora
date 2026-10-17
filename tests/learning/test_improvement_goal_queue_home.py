"""The SQLite improvement-goal queue lives in ``aragora.learning``.

The introspection evolution bridge pushes goals into this queue and must not import
``aragora.nomic`` (application layer) to do so. ``aragora.nomic.feedback_orchestrator``
re-exports the same objects, so the nomic callers and the tests that patch names on that
module keep working.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from aragora.introspection.evolution_bridge import (
    EvolutionRecommendation,
    IntrospectionEvolutionBridge,
)
from aragora.learning import improvement_goal_queue as new
from aragora.nomic import feedback_orchestrator as old

REPO_ROOT = Path(__file__).resolve().parents[2]
MOVED = ("ImprovementGoal", "FeedbackGoal", "ImprovementQueue")


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
    ]


@pytest.mark.parametrize("name", MOVED)
def test_the_old_path_holds_the_same_object(name):
    assert getattr(old, name) is getattr(new, name)
    assert getattr(new, name).__module__ == "aragora.learning.improvement_goal_queue"


def test_the_legacy_json_path_is_unchanged():
    assert old._DEFAULT_QUEUE_PATH == new._DEFAULT_QUEUE_PATH
    assert new._DEFAULT_QUEUE_PATH == Path(".aragora_beads") / "improvement_queue.json"


def test_goals_pushed_through_one_path_pop_through_the_other(tmp_path):
    db = tmp_path / "queue.db"
    old.ImprovementQueue(db_path=db).push(
        old.ImprovementGoal(goal="low", source="test", priority=0.2, context={"k": 1})
    )
    new.ImprovementQueue(db_path=db).push(
        new.ImprovementGoal(goal="high", source="test", priority=0.9)
    )

    assert [g.goal for g in old.ImprovementQueue(db_path=db).peek()] == ["high", "low"]
    popped = new.ImprovementQueue(db_path=db).pop()
    assert [(g.goal, g.priority, g.context) for g in popped] == [
        ("high", 0.9, {}),
        ("low", 0.2, {"k": 1}),
    ]
    assert old.ImprovementQueue(db_path=db).pop() == []


def test_the_legacy_interface_still_mirrors_into_sqlite(tmp_path):
    db = tmp_path / "queue.db"
    queue = new.ImprovementQueue(db_path=db)
    queue.add(old.FeedbackGoal(description="fix flaky test", source="gauntlet", priority=2))

    [goal] = old.ImprovementQueue(db_path=db).peek()
    assert (goal.goal, goal.source, goal.priority) == ("fix flaky test", "gauntlet", 0.8)

    target = tmp_path / "legacy.json"
    queue.save(target)
    loaded = old.ImprovementQueue.load(target)
    assert [g.description for g in loaded.goals] == ["fix flaky test"]


def test_an_explicit_db_path_is_used_as_given(tmp_path):
    assert new._resolve_queue_db_path(tmp_path / "q.db") == str(tmp_path / "q.db")
    assert new.ImprovementQueue(db_path=tmp_path / "q.db")._db_path == str(tmp_path / "q.db")


def test_the_new_home_imports_only_lower_layers():
    imported = _imported_modules(REPO_ROOT / "aragora/learning/improvement_goal_queue.py")
    assert [name for name in imported if name.startswith("aragora")] == [
        "aragora.persistence.db_config"
    ]


def test_introspection_holds_no_import_of_nomic():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {name}"
        for path in sorted((REPO_ROOT / "aragora/introspection").rglob("*.py"))
        for name in _imported_modules(path)
        if name == "aragora.nomic" or name.startswith("aragora.nomic.")
    ]
    assert offenders == []


def test_the_bridge_routes_recommendations_into_the_default_queue(tmp_path, monkeypatch):
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    bridge = IntrospectionEvolutionBridge()
    rec = EvolutionRecommendation(
        agent_name="a1", recommendation="raise critique quality", severity="high"
    )

    assert bridge.route_to_queue([rec]) == 1

    [goal] = new.ImprovementQueue(db_path=tmp_path / "improvement_queue.db").pop()
    assert isinstance(goal, old.ImprovementGoal)
    assert (goal.goal, goal.source, goal.priority) == (
        "raise critique quality",
        "introspection",
        0.85,
    )
    assert goal.context["agent_name"] == "a1"
