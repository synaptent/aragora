"""Pin the move of the reporter's text renderers into ``aragora.swarm.reporter_render``."""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pytest

from aragora.swarm import reporter, reporter_render

MOVED_NAMES = [
    "render_runner_registration_text",
    "_work_order_status_counts",
    "_render_operator_status_line",
    "render_boss_text",
]


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_moved_names_are_reexported_from_the_reporter(name: str) -> None:
    moved = getattr(reporter_render, name)
    assert getattr(reporter, name) is moved
    assert moved.__module__ == "aragora.swarm.reporter_render"


def test_render_module_does_not_import_the_reporter() -> None:
    tree = ast.parse(inspect.getsource(reporter_render))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0
            assert node.module != "aragora.swarm.reporter"
            if node.module == "aragora.swarm":
                assert all(alias.name != "reporter" for alias in node.names)
        elif isinstance(node, ast.Import):
            assert all(alias.name != "aragora.swarm.reporter" for alias in node.names)


def test_runner_registration_text_lists_the_known_fields() -> None:
    payload = {
        "runner_id": "runner-a",
        "availability": "available",
        "auth_mode": "oauth",
        "runner_type": "claude",
        "profile": "max-03",
        "owner_binding": {"user_id": "u-1"},
        "capabilities": {"supports_exec": True, "max_parallel_lanes": 2},
        "registered": True,
        "registered_at": "2026-03-18T12:00:00Z",
        "freshness_status": "fresh",
        "heartbeat_at": "2026-03-18T12:05:00Z",
        "next_action": "dispatch",
    }
    assert reporter.render_runner_registration_text(payload).splitlines() == [
        "runner_id=runner-a",
        "availability=available auth_mode=oauth",
        "runner_type=claude",
        "profile=max-03",
        "owner=u-1 workspace=none",
        "capabilities=exec=True review=False max_parallel=2",
        "registered_at=2026-03-18T12:00:00Z",
        "freshness=fresh heartbeat_at=2026-03-18T12:05:00Z stale_after=none",
        "next: dispatch",
    ]


def test_work_order_status_counts_skip_non_dicts_and_sort_by_status() -> None:
    work_orders: list[Any] = [{"status": "queued"}, {"status": "done"}, {"status": "done"}, {}, "x"]
    assert reporter._work_order_status_counts(work_orders) == {
        "done": 2,
        "queued": 1,
        "unknown": 1,
    }
    assert reporter._work_order_status_counts(None) == {}


def test_operator_status_line_depends_on_the_source() -> None:
    ledger = {
        "source": "shift_ledger",
        "queue_depth": 3,
        "open_prs": 2,
        "boss_running": True,
        "merge_running": False,
        "benchmark_fresh": True,
        "merged_pr_numbers": [10, 11],
        "green_shift": {"is_green": True},
    }
    assert reporter._render_operator_status_line(ledger) == (
        "proof-first queue=3 open_prs=2 boss=True merge=False benchmark_fresh=True "
        "merged_prs=0 merged=10,11 last_stop=- green_shift=True"
    )
    fallback = {"source": "legacy_reporter_fallback", "queue_depth": 4}
    assert reporter._render_operator_status_line(fallback) == "reporter-fallback queue=4"
    assert reporter._render_operator_status_line({"source": "other"}) == ""


def test_boss_text_renders_lanes_routing_and_needs_human() -> None:
    payload = {
        "run_id": "run-1",
        "status": "running",
        "target_branch": "main",
        "goal": "ship it",
        "work_order_counts": {"queued": 1, "completed": 2},
        "operator_status": {"source": "legacy_reporter_fallback", "queue_depth": 4},
        "lanes": [
            {
                "work_order_id": "wo-1",
                "status": "active",
                "branch": "codex/wo-1",
                "receipt_id": "r-1",
            },
            "skip",
        ],
        "routing": {
            "selected_runner_ids": ["runner-b"],
            "selected_runners": [{"runner_id": "runner-a", "freshness_status": "fresh"}],
            "rejected_runner_ids": ["runner-c"],
            "next_action": "wait",
        },
        "integrator_next_actions": ["merge wo-1"],
        "needs_human": [
            {
                "work_order_id": "wo-2",
                "reasons": ["tests failed"],
                "failure_classes": ["verification"],
                "repair_summary": {
                    "failure_reason": "tests_failed",
                    "verification_command": "pytest -q",
                },
                "next_action": "inspect logs",
            }
        ],
    }
    assert reporter.render_boss_text(payload).splitlines() == [
        "run_id=run-1",
        "status=running target_branch=main",
        "goal=ship it",
        "work_orders=[completed=2, queued=1]",
        "reporter-fallback queue=4",
        "lane: wo-1 active branch=codex/wo-1 receipt=r-1",
        "routing: selected_runners=runner-a(fresh)",
        "routing_rejected: runner-c",
        "routing_next: wait",
        "next: merge wo-1",
        "needs_human: wo-2 -> tests failed",
        "needs_human_classes: wo-2 -> verification",
        "needs_human_repair: wo-2 -> reason=tests_failed; cmd=pytest -q",
        "needs_human_next: wo-2 -> inspect logs",
    ]


def test_boss_text_for_an_empty_payload() -> None:
    assert reporter.render_boss_text({}).splitlines() == [
        "run_id=",
        "status= target_branch=",
        "goal=",
        "work_orders=[none]",
    ]
