"""Tests for the AI-assisted promotion helpers and their stage_transitions facade."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aragora.goals.extractor as goal_extractor
from aragora.pipeline import stage_transitions, stage_transitions_ai
from aragora.pipeline.stage_transitions import (
    ai_promote_goals_to_actions,
    ai_promote_ideas_to_goals,
)


@pytest.mark.parametrize("name", ["ai_promote_ideas_to_goals", "ai_promote_goals_to_actions"])
def test_facade_reexports_the_split_module_objects(name):
    assert getattr(stage_transitions, name) is getattr(stage_transitions_ai, name)
    assert name in stage_transitions.__all__
    assert name in stage_transitions_ai.__all__


def test_cluster_groups_ideas_sharing_two_keywords():
    ideas = [
        {"id": "i1", "label": "Rate limiter for public API", "description": "token bucket"},
        {"id": "i2", "label": "Public API rate limiter metrics"},
        {"id": "i3", "label": "Dark mode toggle"},
    ]

    clusters = stage_transitions_ai._cluster_ideas_by_similarity(ideas)

    assert [[idea["id"] for idea in cluster] for cluster in clusters] == [["i1", "i2"], ["i3"]]


def test_cluster_respects_max_cluster_size():
    ideas = [{"id": f"i{n}", "label": "shared alpha beta"} for n in range(3)]

    clusters = stage_transitions_ai._cluster_ideas_by_similarity(ideas, max_cluster_size=2)

    assert [len(cluster) for cluster in clusters] == [2, 1]


def test_simple_goal_from_cluster_shape():
    goal = stage_transitions_ai._simple_goal_from_cluster(
        [
            {"id": "i1", "label": "Cache results", "description": "memoize"},
            {"id": "i2", "label": "Cache keys"},
        ]
    )

    assert goal["id"].startswith("goal-")
    assert goal["label"] == "Achieve: Cache results"
    assert goal["description"] == "memoize; Cache keys"
    assert goal["parent_idea_ids"] == ["i1", "i2"]
    assert goal["priority"] == "medium"
    assert goal["confidence"] == pytest.approx(0.5)


def test_simple_goal_from_empty_cluster():
    goal = stage_transitions_ai._simple_goal_from_cluster([])

    assert goal["label"] == "Empty goal"
    assert goal["parent_idea_ids"] == []
    assert goal["priority"] == "low"


async def test_ai_promote_ideas_without_agent_uses_simple_goals():
    assert await ai_promote_ideas_to_goals([]) == []

    goals = await ai_promote_ideas_to_goals(
        [
            {"id": "i1", "label": "Rate limiter for public API"},
            {"id": "i2", "label": "Public API rate limiter metrics"},
        ]
    )

    assert len(goals) == 1
    assert goals[0]["parent_idea_ids"] == ["i1", "i2"]
    assert goals[0]["label"] == "Achieve: Rate limiter for public API"


async def test_ai_promote_ideas_uses_goal_extractor_when_agent_given(monkeypatch):
    captured: dict[str, object] = {}

    class FakeExtractor:
        def __init__(self, agent=None):
            captured["agent"] = agent

        def extract_from_ideas(self, canvas_data):
            captured["canvas_data"] = canvas_data
            return SimpleNamespace(
                goals=[
                    SimpleNamespace(
                        id="goal-x",
                        title="Ship it",
                        description="desc",
                        source_idea_ids=["i1"],
                        confidence=0.9,
                        priority="high",
                    )
                ]
            )

    monkeypatch.setattr(goal_extractor, "GoalExtractor", FakeExtractor)

    agent = object()
    goals = await ai_promote_ideas_to_goals([{"id": "i1", "label": "Ship"}], agent=agent)

    assert captured["agent"] is agent
    assert captured["canvas_data"]["nodes"][0]["id"] == "i1"
    assert goals == [
        {
            "id": "goal-x",
            "label": "Ship it",
            "description": "desc",
            "parent_idea_ids": ["i1"],
            "confidence": 0.9,
            "priority": "high",
        }
    ]


async def test_ai_promote_ideas_falls_back_when_extractor_fails(monkeypatch):
    class FailingExtractor:
        def __init__(self, agent=None):
            pass

        def extract_from_ideas(self, canvas_data):
            raise RuntimeError("model unavailable")

    monkeypatch.setattr(goal_extractor, "GoalExtractor", FailingExtractor)

    goals = await ai_promote_ideas_to_goals([{"id": "i1", "label": "Ship"}], agent=object())

    assert len(goals) == 1
    assert goals[0]["label"] == "Achieve: Ship"
    assert goals[0]["parent_idea_ids"] == ["i1"]


async def test_ai_promote_goals_to_actions_strips_prefix_and_sizes_effort():
    assert await ai_promote_goals_to_actions([]) == []

    actions = await ai_promote_goals_to_actions(
        [
            {"id": "g1", "label": "Achieve: Faster builds", "priority": "critical"},
            {"id": "g2", "label": "Maintain: Docs", "priority": "high"},
            {"id": "g3", "label": "Tidy", "description": "x" * 201},
            {"id": "g4", "label": "Small fix"},
        ]
    )

    assert [action["description"] for action in actions] == [
        "Faster builds",
        "Docs",
        "Tidy",
        "Small fix",
    ]
    assert [action["estimated_effort"] for action in actions] == [
        "large",
        "medium",
        "medium",
        "small",
    ]
    assert [action["parent_goal"] for action in actions] == ["g1", "g2", "g3", "g4"]
    assert [action["priority"] for action in actions] == ["critical", "high", "medium", "medium"]
    assert all(action["id"].startswith("action-") for action in actions)
