"""Tests for the task_decomposer facade over its models and debate-mixin modules."""

from __future__ import annotations

import inspect

import pytest

from aragora.nomic import task_decomposer, task_decomposer_debate, task_decomposer_models
from aragora.nomic.task_decomposer import TaskDecomposer
from aragora.nomic.task_decomposer_debate import TaskDecomposerDebateMixin

MODEL_NAMES = (
    "DecompositionQuality",
    "FileConflict",
    "OracleResult",
    "SubTask",
    "TaskDecomposition",
)
DEBATE_METHODS = (
    "analyze_with_debate",
    "_run_debate_with_fallback",
    "_get_openrouter_agents",
    "_build_debate_task",
    "_parse_debate_subtasks",
    "_get_default_agents",
)


@pytest.mark.parametrize(
    "name",
    [
        *MODEL_NAMES,
        "COMPLEXITY_INDICATORS",
        "DECOMPOSITION_CONCEPTS",
        "DecomposerConfig",
        "TaskDecomposer",
        "analyze_task",
        "get_task_decomposer",
    ],
)
def test_facade_keeps_the_pre_split_public_names(name):
    assert getattr(task_decomposer, name) is not None


@pytest.mark.parametrize("name", MODEL_NAMES)
def test_facade_reexports_the_model_classes(name):
    assert getattr(task_decomposer, name) is getattr(task_decomposer_models, name)
    assert name in task_decomposer_models.__all__


@pytest.mark.parametrize("name", DEBATE_METHODS)
def test_decomposer_inherits_each_debate_method_from_the_mixin(name):
    assert issubclass(TaskDecomposer, TaskDecomposerDebateMixin)
    assert name not in vars(TaskDecomposer)
    assert inspect.getattr_static(TaskDecomposer, name) is vars(TaskDecomposerDebateMixin)[name]


def test_debate_mixin_logs_under_the_original_module_logger():
    assert task_decomposer_debate.logger is task_decomposer.logger


def test_parse_debate_subtasks_builds_facade_subtasks():
    consensus = (
        "Plan:\n```json\n"
        '[{"title": "Add cache", "description": "Memoize lookups", "complexity": "low",'
        ' "files": ["aragora/cache.py"], "dependencies": []},'
        ' {"title": "Wire metrics"}]\n```'
    )

    subtasks = TaskDecomposer()._parse_debate_subtasks(consensus)

    assert [type(s) for s in subtasks] == [task_decomposer.SubTask] * 2
    assert [(s.id, s.title, s.estimated_complexity) for s in subtasks] == [
        ("subtask_1", "Add cache", "low"),
        ("subtask_2", "Wire metrics", "medium"),
    ]
    assert subtasks[0].file_scope == ["aragora/cache.py"]
    assert TaskDecomposer()._parse_debate_subtasks("no json at all") == []
