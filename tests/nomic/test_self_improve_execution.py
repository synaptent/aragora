"""Tests for the self-improve execution mixin and its self_improve facade."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from aragora.nomic import self_improve, self_improve_execution
from aragora.nomic.self_improve import SelfImprovePipeline
from aragora.nomic.self_improve_execution import SelfImproveExecutionMixin

REPO_ROOT = Path(__file__).resolve().parents[2]
SPLIT_FILE = "aragora/nomic/self_improve.py"

MOVED_METHODS = (
    "_execute_single",
    "_execute_with_debug_loop",
    "_infer_test_scope",
    "_read_file_contents",
    "_assess_execution_risk",
    "_dispatch_to_claude_code",
    "_parse_cost_from_output",
    "_run_tests_in_worktree",
    "_write_instruction_to_worktree",
    "_generate_subtask_receipt",
)


@pytest.mark.parametrize(
    "name",
    ["BudgetExceededError", "SelfImproveConfig", "SelfImprovePipeline", "SelfImproveResult"],
)
def test_facade_keeps_the_pre_split_public_names(name):
    assert inspect.isclass(getattr(self_improve, name))


def test_facade_reexports_the_moved_error_class():
    assert self_improve.BudgetExceededError is self_improve_execution.BudgetExceededError
    assert issubclass(self_improve.BudgetExceededError, RuntimeError)


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_pipeline_inherits_each_execution_method_from_the_mixin(name):
    assert issubclass(SelfImprovePipeline, SelfImproveExecutionMixin)
    assert name not in vars(SelfImprovePipeline)
    assert (
        inspect.getattr_static(SelfImprovePipeline, name) is vars(SelfImproveExecutionMixin)[name]
    )


def test_mixin_logs_under_the_original_module_logger():
    assert self_improve_execution.logger is self_improve.logger


def test_parse_cost_from_output_through_the_pipeline():
    pipeline = SelfImprovePipeline()

    assert pipeline._parse_cost_from_output("Total cost: $0.42") == pytest.approx(0.42)
    assert pipeline._parse_cost_from_output("input=1000000, output=0") == pytest.approx(3.0)
    assert pipeline._parse_cost_from_output("nothing to report") == 0.0


def test_split_file_is_under_the_limit_and_out_of_the_baseline():
    lines = (REPO_ROOT / SPLIT_FILE).read_text(encoding="utf-8").count("\n")
    baseline = json.loads(
        (REPO_ROOT / "scripts/baselines/file_size_baseline.json").read_text(encoding="utf-8")
    )

    assert lines <= baseline["limit"]
    assert SPLIT_FILE not in baseline["files"]
