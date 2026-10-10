"""Pin the move of the reporter's lane and receipt helpers into ``aragora.swarm.reporter_lanes``."""

from __future__ import annotations

import ast
import inspect

import pytest

from aragora.swarm import reporter, reporter_lanes

MOVED_NAMES = [
    "_extract_receipt_id",
    "_run_task_tuple",
    "_item_task_key",
    "_item_run_task",
    "_deliverable",
    "_extract_pr_number",
    "_extract_pr_link",
    "_explicit_missing_receipt",
    "_receipt_backfill_scope_gap",
    "_is_superseded",
    "_has_retired_marker",
    "_merge_queue_status",
    "_receipt_expected",
    "_merge_readiness",
    "_next_action",
    "_item_timestamp",
    "_sort_newest",
    "_lane_health",
    "_available_actions",
]


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_moved_names_are_reexported_from_the_reporter(name: str) -> None:
    moved = getattr(reporter_lanes, name)
    assert getattr(reporter, name) is moved
    assert moved.__module__ == "aragora.swarm.reporter_lanes"


def test_lanes_module_does_not_import_the_reporter() -> None:
    tree = ast.parse(inspect.getsource(reporter_lanes))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    allowed = {"aragora.swarm.reporter_lanes", "aragora.swarm.reporter_fields"}
    assert not any(name.startswith("aragora.swarm.reporter") for name in imported - allowed)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (42, 42),
        ("42", 42),
        ("#17", 17),
        ("https://github.com/org/repo/pull/123/", 123),
        ("org/repo#88", 88),
        ("not a pr", None),
        ("", None),
    ],
)
def test_pr_numbers_are_parsed_from_urls_and_references(
    value: object, expected: int | None
) -> None:
    assert reporter._extract_pr_number(value) == expected


def test_pr_link_prefers_explicit_numbers_over_url_tails() -> None:
    link = reporter._extract_pr_link(
        {"pr_url": "https://github.com/org/repo/pull/5", "metadata": {"pr_number": 9}}
    )
    assert link == {"url": "https://github.com/org/repo/pull/5", "number": 9, "reference": None}
    assert reporter._extract_pr_link({"status": "queued"}, None) is None


def test_receipt_id_falls_back_to_metadata() -> None:
    assert reporter._extract_receipt_id(None, {"metadata": {"decision_receipt_id": "r-1"}}) == "r-1"
    assert reporter._extract_receipt_id({"receipt_id": "r-2"}, {"receipt_id": "r-3"}) == "r-2"


def test_retired_lanes_count_as_superseded() -> None:
    assert reporter._is_superseded({"failure_reason": "Retired after 3 attempts"})
    assert reporter._is_superseded({"metadata": {"superseded_by": "wo-2"}})
    assert not reporter._is_superseded({"status": "queued"})


def test_merge_readiness_and_lane_health_for_a_blocked_lane() -> None:
    flags = {
        "stale_heartbeat": False,
        "missing_receipt": True,
        "scope_violation": False,
        "superseded": False,
        "collisions": [],
    }
    readiness = reporter._merge_readiness(status="completed", queue_status="", **flags)
    assert readiness == "blocked"
    health = reporter._lane_health(
        readiness=readiness,
        status="completed",
        terminal_outcome="",
        lease_status="active",
        blockers=[],
        **flags,
    )
    assert health == "blocked"
    actions = reporter._available_actions(
        canonical_lane=True,
        readiness=readiness,
        lane_health=health,
        missing_receipt=True,
        scope_violation=False,
        superseded=False,
        collisions=[],
        decision="",
    )
    assert actions == ["attach_receipt"]


def test_sort_newest_reads_metadata_timestamps() -> None:
    items = [
        {"id": "old", "updated_at": "2026-03-01T00:00:00Z"},
        {"id": "new", "metadata": {"updated_at": "2026-03-02T00:00:00Z"}},
        {"id": "none"},
    ]
    assert [item["id"] for item in reporter._sort_newest(items, "updated_at")] == [
        "new",
        "old",
        "none",
    ]
