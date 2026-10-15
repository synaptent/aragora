"""Pins the waiting-conflict archive and rehabilitation passes to their own module.

They live in ``aragora.nomic.dev_receipts_waiting_conflict``. ``dev_receipts``
re-exports the same function objects, so the store methods in ``core`` that
import them lazily from ``dev_receipts`` keep working.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aragora.nomic import dev_receipts
from aragora.nomic import dev_receipts_waiting_conflict as waiting_conflict
from aragora.nomic.dev_coordination import DevCoordinationStore, core

MOVED_FUNCTIONS = (
    "archive_superseded_waiting_conflict_work_orders",
    "archive_duplicate_waiting_conflict_work_orders",
    "rehabilitate_narrowed_waiting_conflict_work_orders",
)


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_function_is_defined_in_the_waiting_conflict_module(name: str) -> None:
    func = getattr(waiting_conflict, name)
    assert func.__module__ == "aragora.nomic.dev_receipts_waiting_conflict"
    assert getattr(dev_receipts, name) is func


def test_grace_period_default_matches_core() -> None:
    for name in (
        "archive_superseded_waiting_conflict_work_orders",
        "rehabilitate_narrowed_waiting_conflict_work_orders",
    ):
        default = getattr(waiting_conflict, name).__kwdefaults__["grace_period_hours"]
        assert default == core._SUPERSEDED_WAITING_CONFLICT_ARCHIVE_GRACE_HOURS


@pytest.mark.parametrize("name", MOVED_FUNCTIONS)
def test_store_methods_run_the_moved_functions_on_an_empty_store(name: str, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    store = DevCoordinationStore(repo_root=tmp_path)
    assert getattr(store, name)() == 0
