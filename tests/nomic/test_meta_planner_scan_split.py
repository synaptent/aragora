"""Pin the MetaPlanner split into sibling modules.

The planning dataclasses live in ``aragora.nomic.meta_planner_models`` and the
scan-mode prioritization methods live on ``MetaPlannerScanMixin`` in
``aragora.nomic.meta_planner_scan``. ``aragora.nomic.meta_planner`` keeps
exporting every name, so existing imports keep resolving to the same objects.
"""

from __future__ import annotations

import pickle

import pytest

from aragora.nomic import meta_planner
from aragora.nomic import meta_planner_models as models
from aragora.nomic import meta_planner_scan as scan
from aragora.nomic.types import Track

MODEL_NAMES = [
    "PrioritizedGoal",
    "MetaPlanningResult",
    "HistoricalLearning",
    "PlanningContext",
    "MetaPlannerConfig",
]

SCAN_METHODS = [
    "_scan_prioritize",
    "_file_to_track",
    "_gather_file_excerpts",
]


@pytest.mark.parametrize("name", MODEL_NAMES)
def test_models_are_defined_in_models_module_and_reexported(name: str) -> None:
    cls = getattr(models, name)
    assert cls.__module__ == "aragora.nomic.meta_planner_models"
    assert getattr(meta_planner, name) is cls


@pytest.mark.parametrize("name", SCAN_METHODS)
def test_scan_methods_live_on_the_mixin(name: str) -> None:
    assert name in vars(scan.MetaPlannerScanMixin)
    assert name not in vars(meta_planner.MetaPlanner)
    assert getattr(meta_planner.MetaPlanner, name) is getattr(scan.MetaPlannerScanMixin, name)


def test_meta_planner_inherits_the_scan_mixin() -> None:
    assert issubclass(meta_planner.MetaPlanner, scan.MetaPlannerScanMixin)


def test_scan_mixin_logs_under_the_meta_planner_logger() -> None:
    assert scan.logger is meta_planner.logger
    assert scan.logger.name == "aragora.nomic.meta_planner"


def test_prioritized_goal_round_trips_through_pickle() -> None:
    goal = meta_planner.PrioritizedGoal(
        id="g1",
        track=Track.QA,
        description="Add tests",
        rationale="coverage",
        estimated_impact="high",
        priority=1,
        file_hints=["tests/nomic/test_x.py"],
    )
    restored = pickle.loads(pickle.dumps(goal))
    assert restored == goal
    assert restored.to_dict()["track"] == Track.QA.value


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/nomic/test_meta_planner.py", Track.QA),
        ("aragora/live/src/app/page.tsx", Track.SME),
        ("sdk/python/aragora_sdk/client.py", Track.DEVELOPER),
        ("deploy/docker/Dockerfile", Track.SELF_HOSTED),
        ("aragora/rbac/checker.py", Track.SECURITY),
        ("aragora/debate/orchestrator.py", Track.CORE),
    ],
)
def test_file_to_track_maps_paths_to_tracks(path: str, expected: Track) -> None:
    planner = meta_planner.MetaPlanner()
    assert planner._file_to_track(path, list(Track)) is expected


def test_file_to_track_falls_back_to_the_first_available_track() -> None:
    planner = meta_planner.MetaPlanner()
    assert planner._file_to_track("README.md", [Track.CORE, Track.QA]) is Track.CORE
    assert planner._file_to_track("README.md", []) is None
