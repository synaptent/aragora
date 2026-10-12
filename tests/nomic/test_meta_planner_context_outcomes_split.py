"""Pin the MetaPlanner context-enrichment and outcome-tracking mixins.

Context enrichment (metrics and past-cycle history) lives on ``MetaPlannerContextMixin``
in ``aragora.nomic.meta_planner_context``; outcome recording and self-correction
re-ranking live on ``MetaPlannerOutcomesMixin`` in ``aragora.nomic.meta_planner_outcomes``.
``MetaPlanner`` inherits both, so ``aragora.nomic.meta_planner`` callers are unaffected.
"""

from __future__ import annotations

import inspect

import pytest

from aragora.nomic import meta_planner
from aragora.nomic import meta_planner_context as context
from aragora.nomic import meta_planner_outcomes as outcomes
from aragora.nomic.types import Track

CONTEXT_METHODS = ["_enrich_context_with_metrics", "_enrich_context_with_history"]
OUTCOME_METHODS = [
    "_apply_self_correction_adjustments",
    "_get_past_outcomes",
    "record_outcome",
    "_persist_outcome_to_km",
]


@pytest.mark.parametrize(
    ("mixin", "name"),
    [(context.MetaPlannerContextMixin, n) for n in CONTEXT_METHODS]
    + [(outcomes.MetaPlannerOutcomesMixin, n) for n in OUTCOME_METHODS],
)
def test_methods_live_on_their_mixin(mixin: type, name: str) -> None:
    assert issubclass(meta_planner.MetaPlanner, mixin)
    assert name in vars(mixin)
    assert name not in vars(meta_planner.MetaPlanner)
    assert inspect.getattr_static(meta_planner.MetaPlanner, name) is vars(mixin)[name]


@pytest.mark.parametrize("module", [context, outcomes])
def test_mixins_log_under_the_meta_planner_logger(module) -> None:
    assert module.logger is meta_planner.logger


def test_scope_summary_moved_with_history_enrichment() -> None:
    assert meta_planner._scope_summary is context._scope_summary
    assert context._scope_summary(["a.py", "b.py", "c.py", "d.py"], ["t1", "t2", "t3"]) == (
        " (files: a.py, b.py, c.py; tests: t1; t2)"
    )
    assert context._scope_summary([], []) == ""


def test_record_outcome_aggregates_by_track_through_the_facade(monkeypatch) -> None:
    planner = meta_planner.MetaPlanner()
    persisted: list[tuple] = []
    monkeypatch.setattr(planner, "_persist_outcome_to_km", lambda *args: persisted.append(args))

    stats = planner.record_outcome(
        [
            {"track": "qa", "success": True},
            {"track": "qa", "success": False, "error": "flaky"},
            {"track": "core", "success": False, "description": "no tests"},
        ],
        objective="harden planning",
    )

    assert {t: (s["attempted"], s["succeeded"], s["rate"]) for t, s in stats.items()} == {
        "qa": (2, 1, 0.5),
        "core": (1, 0, 0.0),
    }
    assert stats["core"]["failures"] == ["no tests"]
    assert len(persisted) == 1 and persisted[0][1] == "harden planning"


def test_self_correction_keeps_goals_without_past_outcomes(monkeypatch) -> None:
    planner = meta_planner.MetaPlanner()
    monkeypatch.setattr(planner, "_get_past_outcomes", lambda: [])
    goals = [
        meta_planner.PrioritizedGoal(
            id="g1",
            track=Track.QA,
            description="Add tests",
            rationale="coverage",
            estimated_impact="high",
            priority=2,
        )
    ]

    assert planner._apply_self_correction_adjustments(goals) is goals
    assert goals[0].priority == 2
