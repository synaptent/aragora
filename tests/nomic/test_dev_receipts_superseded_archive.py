"""Pins the superseded and duplicate work-order archive passes to their own module.

They live in ``aragora.nomic.dev_receipts_superseded_archive``. ``dev_receipts``
re-exports the same function objects, so the store methods in ``core`` that
import them lazily from ``dev_receipts`` keep working.
"""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.nomic.dev_coordination as facade
from aragora.nomic import dev_receipts
from aragora.nomic import dev_receipts_superseded_archive as superseded_archive
from aragora.nomic.dev_coordination import DevCoordinationStore, core

MOVED_FUNCTIONS = (
    "archive_superseded_clean_exit_no_deliverable_work_orders",
    "archive_superseded_stale_lease_reaped_work_orders",
    "archive_duplicate_work_order_leasing_failed_work_orders",
    "archive_duplicate_branch_deliverable_work_orders",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_function_is_defined_in_the_superseded_archive_module(name: str) -> None:
    func = getattr(superseded_archive, name)
    assert func.__module__ == "aragora.nomic.dev_receipts_superseded_archive"
    assert getattr(dev_receipts, name) is func


def test_grace_period_default_matches_core() -> None:
    func = superseded_archive.archive_duplicate_branch_deliverable_work_orders
    default = inspect.signature(func).parameters["grace_period_hours"].default
    assert default == core._DUPLICATE_BRANCH_DELIVERABLE_ARCHIVE_GRACE_HOURS


def _runtime_imported_names(tree: ast.Module) -> set[str]:
    """Dotted names imported at module level outside ``TYPE_CHECKING`` blocks."""
    names: set[str] = set()
    pending: list[ast.stmt] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.If):
            if getattr(node.test, "id", None) == "TYPE_CHECKING":
                pending.extend(node.orelse)
            else:
                pending.extend(node.body + node.orelse)
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_module_reaches_core_only_through_the_package_facade() -> None:
    tree = ast.parse(Path(superseded_archive.__file__).read_text(encoding="utf-8"))
    names = _runtime_imported_names(tree)
    assert not any("core" in name.split(".") for name in names), names
    assert superseded_archive._dev is facade


def test_consumed_helpers_are_the_core_objects() -> None:
    source = Path(superseded_archive.__file__).read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"\b_dev\.([A-Za-z_][A-Za-z0-9_]*)", source)))
    assert names
    assert [n for n in names if getattr(superseded_archive, n) is not getattr(core, n)] == []


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("aragora.nomic.dev_receipts_superseded_archive", "aragora.nomic.dev_coordination.core"),
        ("aragora.nomic.dev_coordination.core", "aragora.nomic.dev_receipts_superseded_archive"),
    ],
)
def test_modules_import_in_either_order(first: str, second: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {first}, {second}; print('ok')"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_store_methods_run_the_moved_functions_on_an_empty_store(name: str, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = DevCoordinationStore(repo_root=tmp_path)
    assert getattr(store, name)() == 0
