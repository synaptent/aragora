"""Tests for micro-task decomposition."""

from __future__ import annotations

from pathlib import Path

import pytest

from aragora.swarm.boss_validation import extract_issue_validation_contract
from aragora.swarm.micro_decomposer import build_micro_work_orders
from aragora.swarm.spec import SwarmSpec
from aragora.swarm.task_sanitizer import TaskSanitizer


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """Create a minimal repo structure for testing."""
    (tmp_path / "aragora" / "routing").mkdir(parents=True)
    (tmp_path / "tests" / "routing").mkdir(parents=True)

    (tmp_path / "aragora" / "routing" / "optimizer.py").write_text(
        "class Optimizer:\n    def route(self): pass\n"
    )
    (tmp_path / "aragora" / "routing" / "config.py").write_text("TIMEOUT = 300\n")
    (tmp_path / "tests" / "routing" / "test_optimizer.py").write_text("def test_route(): pass\n")
    return tmp_path


def test_directory_hint_resolves_to_files(repo_root: Path) -> None:
    orders = build_micro_work_orders(
        goal="Add caching to route()",
        file_scope_hints=["aragora/routing/"],
        repo_root=repo_root,
    )
    assert len(orders) >= 2  # At least impl files + test


def test_specific_file_hint(repo_root: Path) -> None:
    orders = build_micro_work_orders(
        goal="Fix optimizer",
        file_scope_hints=["aragora/routing/optimizer.py"],
        repo_root=repo_root,
    )
    assert len(orders) >= 1
    assert orders[0]["file_scope"] == ["aragora/routing/optimizer.py"]


def test_empty_hints_returns_empty() -> None:
    orders = build_micro_work_orders(
        goal="Do something",
        file_scope_hints=[],
    )
    assert orders == []


def test_nonexistent_path_returns_empty(tmp_path: Path) -> None:
    orders = build_micro_work_orders(
        goal="Fix nonexistent",
        file_scope_hints=["aragora/does_not_exist/"],
        repo_root=tmp_path,
    )
    assert orders == []


def test_nonexistent_file_with_missing_parent_returns_empty(tmp_path: Path) -> None:
    orders = build_micro_work_orders(
        goal="Create a missing test",
        file_scope_hints=["tests/missing/test_new.py"],
        repo_root=tmp_path,
    )
    assert orders == []


@pytest.mark.parametrize(
    ("goal", "missing_path"),
    [
        ("Remove the obsolete module", "aragora/routing/obsolete.py"),
        ("Update references after renaming this module", "aragora/routing/renamed.py"),
    ],
)
def test_missing_non_test_hint_does_not_create_work_order(
    repo_root: Path,
    goal: str,
    missing_path: str,
) -> None:
    orders = build_micro_work_orders(
        goal=goal,
        file_scope_hints=[missing_path],
        repo_root=repo_root,
    )

    assert not (repo_root / missing_path).exists()
    assert orders == []


def test_work_order_has_required_fields(repo_root: Path) -> None:
    orders = build_micro_work_orders(
        goal="Add feature",
        file_scope_hints=["aragora/routing/optimizer.py"],
        repo_root=repo_root,
    )
    assert len(orders) >= 1
    wo = orders[0]
    assert "work_order_id" in wo
    assert "title" in wo
    assert "description" in wo
    assert "file_scope" in wo


def test_test_files_grouped_separately(repo_root: Path) -> None:
    orders = build_micro_work_orders(
        goal="Add tests",
        file_scope_hints=["aragora/routing/", "tests/routing/"],
        repo_root=repo_root,
    )
    # Should have impl work orders + test work order
    test_orders = [o for o in orders if "test" in o.get("title", "").lower()]
    impl_orders = [
        o
        for o in orders
        if "test" not in o.get("title", "").lower()
        and "validation" not in o.get("title", "").lower()
    ]
    assert len(impl_orders) >= 1
    assert len(test_orders) >= 1


def test_acceptance_criteria_creates_validation_order(repo_root: Path) -> None:
    orders = build_micro_work_orders(
        goal="Fix bug",
        file_scope_hints=["aragora/routing/optimizer.py"],
        acceptance_criteria=["pytest tests/routing/ -x -q passes"],
        repo_root=repo_root,
    )
    validation_orders = [o for o in orders if "validation" in o.get("title", "").lower()]
    assert len(validation_orders) == 1


def test_acceptance_criteria_marks_non_validation_lanes_as_deferred(repo_root: Path) -> None:
    orders = build_micro_work_orders(
        goal="Fix optimizer and add regression coverage",
        file_scope_hints=["aragora/routing/optimizer.py", "tests/routing/test_optimizer.py"],
        acceptance_criteria=["pytest tests/routing/test_optimizer.py -x -q passes"],
        repo_root=repo_root,
    )

    validation_orders = [o for o in orders if "validation" in o.get("title", "").lower()]
    assert len(validation_orders) == 1
    validation_task_id = validation_orders[0]["pipeline_task_id"]

    non_validation_orders = [o for o in orders if o is not validation_orders[0]]
    assert non_validation_orders
    for order in non_validation_orders:
        assert order["metadata"]["deferred_verification_to_dependency_ids"] == [validation_task_id]


def test_caps_at_five_impl_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    for i in range(10):
        (tmp_path / "src" / f"module_{i}.py").write_text(f"x = {i}\n")

    orders = build_micro_work_orders(
        goal="Update all modules",
        file_scope_hints=["src/"],
        repo_root=tmp_path,
    )
    impl_orders = [
        o
        for o in orders
        if "validation" not in o.get("title", "").lower()
        and "test" not in o.get("title", "").lower()
    ]
    assert len(impl_orders) <= 5


def test_prefers_test_first_for_conditional_test_only_issue(tmp_path: Path) -> None:
    (tmp_path / "aragora" / "cli").mkdir(parents=True)
    (tmp_path / "tests" / "cli").mkdir(parents=True)
    (tmp_path / "aragora" / "cli" / "parser.py").write_text("def build_parser():\n    pass\n")
    (tmp_path / "tests" / "cli" / "test_swarm_command.py").write_text(
        "def test_swarm_runner_parser():\n    pass\n"
    )

    goal = """
    Add explicit CLI parser coverage for `swarm runner probe --runner-type codex`.

    ## Scope
    - `tests/cli/test_swarm_command.py`
    - `aragora/cli/parser.py` only if the current parser does not already accept the codex probe shape

    ## Constraints
    - Do not broaden into runner execution, freshness, or Boss-loop behavior.
    - Prefer a test-only fix if the parser already supports the codex probe arguments.
    """.strip()

    orders = build_micro_work_orders(
        goal=goal,
        file_scope_hints=["tests/cli/test_swarm_command.py", "aragora/cli/parser.py"],
        acceptance_criteria=[
            "`tests/cli/test_swarm_command.py` includes codex runner probe coverage.",
            "`python3 -m pytest -q tests/cli/test_swarm_command.py -k codex`",
        ],
        repo_root=tmp_path,
    )

    non_validation_orders = [
        order for order in orders if "validation" not in str(order.get("title", "")).lower()
    ]
    assert len(non_validation_orders) == 1
    assert non_validation_orders[0]["title"] == "Write tests for parser.py"
    assert non_validation_orders[0]["file_scope"] == ["tests/cli/test_swarm_command.py"]

    validation_orders = [
        order for order in orders if "validation" in str(order.get("title", "")).lower()
    ]
    assert len(validation_orders) == 1
    assert validation_orders[0]["dependency_ids"] == ["micro-task-1"]
    assert validation_orders[0]["file_scope"] == [
        "tests/cli/test_swarm_command.py",
        "aragora/cli/parser.py",
    ]


def test_new_test_target_and_no_source_edits_emit_test_only_orders(tmp_path: Path) -> None:
    (tmp_path / "aragora" / "swarm").mkdir(parents=True)
    (tmp_path / "tests" / "swarm").mkdir(parents=True)
    (tmp_path / "aragora" / "swarm" / "supervisor_workers.py").write_text(
        "def dispatch_worker():\n    pass\n"
    )

    title = "Add unit tests for swarm/supervisor_workers.py"
    body = """## Scope
Add comprehensive unit tests for `aragora/swarm/supervisor_workers.py`.

## Why
This module handles worker lifecycle in the supervisor. No tests exist today.

## Acceptance criteria
- Test file at `tests/swarm/test_supervisor_workers.py` (new file)
- Cover worker dispatch, lease management, and failure handling
- All tests pass with `pytest tests/swarm/test_supervisor_workers.py -v`
- No modifications to the source module
"""
    sanitization = TaskSanitizer(repo_root=tmp_path).sanitize(title, body)
    sanitized_body = sanitization.sanitized_text.removeprefix(title).strip()
    file_scope_hints = SwarmSpec.infer_file_scope_hints(sanitized_body)
    acceptance_criteria = extract_issue_validation_contract(sanitized_body)

    source_path = "aragora/swarm/supervisor_workers.py"
    test_path = "tests/swarm/test_supervisor_workers.py"
    orders = build_micro_work_orders(
        goal=f"{title}\n\n{sanitized_body}",
        file_scope_hints=file_scope_hints,
        acceptance_criteria=acceptance_criteria,
        repo_root=tmp_path,
    )

    assert file_scope_hints == [source_path, test_path]
    assert not (tmp_path / test_path).exists()
    assert [order["title"] for order in orders] == [
        "Write tests for supervisor_workers.py",
        "Run validation and fix failures",
    ]
    assert orders[0]["file_scope"] == [test_path]
    assert orders[1]["file_scope"] == [test_path]
    assert all(source_path not in order["file_scope"] for order in orders)
