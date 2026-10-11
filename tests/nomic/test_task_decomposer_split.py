"""Tests for the task_decomposer facade over its models and mixin modules."""

from __future__ import annotations

import inspect

import pytest

from aragora.nomic import (
    task_decomposer,
    task_decomposer_debate,
    task_decomposer_grounding,
    task_decomposer_models,
    task_decomposer_validation,
)
from aragora.nomic.task_decomposer import TaskDecomposer
from aragora.nomic.task_decomposer_debate import TaskDecomposerDebateMixin
from aragora.nomic.task_decomposer_grounding import TaskDecomposerGroundingMixin
from aragora.nomic.task_decomposer_validation import TaskDecomposerValidationMixin

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
VALIDATION_METHODS = (
    "validate_file_independence",
    "validate_with_oracle",
    "score_decomposition",
)
GROUNDING_MEMBERS = (
    "_CODEBASE_MODULES",
    "_score_codebase_relevance",
    "_ground_to_codebase",
    "_expand_vague_goal",
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


@pytest.mark.parametrize("name", VALIDATION_METHODS)
def test_decomposer_inherits_each_validation_method_from_the_mixin(name):
    assert issubclass(TaskDecomposer, TaskDecomposerValidationMixin)
    assert name not in vars(TaskDecomposer)
    assert inspect.getattr_static(TaskDecomposer, name) is vars(TaskDecomposerValidationMixin)[name]


@pytest.mark.parametrize("name", GROUNDING_MEMBERS)
def test_decomposer_inherits_each_grounding_member_from_the_mixin(name):
    assert issubclass(TaskDecomposer, TaskDecomposerGroundingMixin)
    assert name not in vars(TaskDecomposer)
    assert inspect.getattr_static(TaskDecomposer, name) is vars(TaskDecomposerGroundingMixin)[name]


@pytest.mark.parametrize(
    "module", [task_decomposer_debate, task_decomposer_validation, task_decomposer_grounding]
)
def test_mixin_modules_log_under_the_original_module_logger(module):
    assert module.logger is task_decomposer.logger


def test_validation_mixin_scores_overlapping_facade_subtasks():
    subtasks = [
        task_decomposer.SubTask(
            id="subtask_1", title="A", description="a", file_scope=["aragora/x.py"]
        ),
        task_decomposer.SubTask(
            id="subtask_2", title="B", description="b", file_scope=["aragora/x.py/"]
        ),
    ]
    decomposer = TaskDecomposer()

    conflicts = decomposer.validate_file_independence(subtasks)
    quality = decomposer.score_decomposition(subtasks, original_file_scope=["aragora/x.py"])

    assert [(c.file_path, c.subtask_ids) for c in conflicts] == [
        ("aragora/x.py", ["subtask_1", "subtask_2"])
    ]
    assert (quality.file_conflicts, quality.coverage_ratio) == (1, 1.0)
    assert quality.score == 0.94


def test_validation_mixin_oracle_reports_missing_and_broken_files(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    (tmp_path / "broken.py").write_text("def (:\n")
    subtask = task_decomposer.SubTask(
        id="subtask_1",
        title="A",
        description="a",
        file_scope=["ok.py", "broken.py", "missing.py", "pkg/"],
    )

    result = TaskDecomposer().validate_with_oracle(subtask, worktree_path=str(tmp_path))

    assert isinstance(result, task_decomposer.OracleResult)
    assert result.valid is False
    assert result.checked_files == ["ok.py", "broken.py", "missing.py"]
    assert [e.split(":")[0] for e in result.errors] == [
        "Syntax error in broken.py",
        "File not found",
    ]


def test_grounding_mixin_maps_goal_keywords_to_codebase_directories(tmp_path):
    (tmp_path / "aragora" / "billing").mkdir(parents=True)
    (tmp_path / "aragora" / "billing" / "meter.py").write_text("")
    decomposer = TaskDecomposer()

    relevant = decomposer._score_codebase_relevance("Harden debate and billing flows")
    grounded = decomposer._ground_to_codebase("Harden billing", repo_root=str(tmp_path))

    assert relevant == ["aragora/debate/", "aragora/billing/"]
    assert "aragora/billing/:\n  - meter.py" in grounded


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
