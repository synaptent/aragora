"""Pin the TeamSelector history-signal scorers that live in ``team_selector_history``."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from aragora.debate import team_selector, team_selector_history
from aragora.debate.team_selector import TeamSelectionConfig, TeamSelector
from aragora.debate.team_selector_history import TeamSelectorHistoryMixin

MOVED_METHODS = (
    "_get_km_domain_experts _compute_km_expertise_score _compute_performance_adapter_score "
    "_compute_elo_win_rate_score _compute_pattern_score _track_pattern_classification "
    "get_pattern_telemetry _get_agent_cvs_batch _compute_cv_score get_cv"
).split()


def _selector(**kwargs) -> TeamSelector:
    return TeamSelector(
        calibration_tracker=MagicMock(), control_plane_registry=MagicMock(), **kwargs
    )


def _agent(name: str) -> Any:
    return SimpleNamespace(name=name)


def test_team_selector_inherits_history_mixin() -> None:
    assert issubclass(TeamSelector, TeamSelectorHistoryMixin)


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_moved_method_defined_once_on_mixin(name: str) -> None:
    assert name in vars(TeamSelectorHistoryMixin)
    assert name not in vars(TeamSelector)
    assert getattr(TeamSelector, name) is vars(TeamSelectorHistoryMixin)[name]


def test_scoring_entrypoints_stay_on_team_selector() -> None:
    for name in ("select", "_compute_score", "score_agent", "_compute_domain_score"):
        assert name in vars(TeamSelector)


def test_team_selector_module_under_size_cap() -> None:
    lines = Path(team_selector.__file__).read_text(encoding="utf-8").count("\n")
    assert lines < 2000


def test_mixin_logs_under_team_selector_logger() -> None:
    assert team_selector_history.logger is logging.getLogger("aragora.debate.team_selector")


def test_elo_win_rate_score_through_selector() -> None:
    elo = MagicMock()
    elo.get_top_agents_for_domain.return_value = [
        SimpleNamespace(agent_name="claude", win_rate=0.75)
    ]
    selector = _selector(elo_system=elo, config=TeamSelectionConfig(enable_elo_win_rate=True))

    assert selector._compute_elo_win_rate_score(_agent("claude-opus"), "code") == pytest.approx(0.5)
    assert selector._compute_elo_win_rate_score(_agent("gemini"), "code") == 0.0


def test_pattern_score_caches_affinities_and_records_telemetry() -> None:
    matcher = MagicMock()
    matcher.classify_task.return_value = "refactor"
    matcher.get_agent_affinities.return_value = {"codex": 0.8}
    selector = _selector(pattern_matcher=matcher)

    agent = _agent("codex-mini")
    assert selector._compute_pattern_score(agent, "split the god file") == 0.8
    assert selector._compute_pattern_score(agent, "split another file") == 0.8

    matcher.get_agent_affinities.assert_called_once()
    telemetry = selector.get_pattern_telemetry()
    assert telemetry["classification_counts"] == {"refactor": 2}
    assert telemetry["cached_patterns"] == ["refactor"]


def test_cv_helpers_without_builder() -> None:
    selector = _selector()

    assert selector.get_cv("claude") is None
    assert selector._get_agent_cvs_batch(["claude"]) == {}
