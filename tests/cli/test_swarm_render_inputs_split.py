"""Pin the move of the swarm command's renderers and input helpers into sibling modules."""

from __future__ import annotations

import argparse
import ast
import inspect
from pathlib import Path

import pytest

from aragora.cli.commands import swarm, swarm_inputs, swarm_render

RENDER_NAMES = [
    "_format_elapsed_seconds",
    "_print_table",
    "_render_initiative",
    "_render_initiative_status",
    "_render_coordination_view",
    "_render_runner_report",
    "_render_tranche_queue_status",
    "_print_supervisor_run",
    "_render_tranche_queue_harvest_table",
    "_render_integrator_table",
]
INPUT_NAMES = [
    "_resolve_swarm_action_goal",
    "_optional_text",
    "_parse_csv_set",
    "_coordination_session_id",
    "_coordination_assigned_by",
    "_probe_limit_arg",
    "_load_structured_object",
]


@pytest.mark.parametrize(
    ("module", "name"),
    [(swarm_render, name) for name in RENDER_NAMES]
    + [(swarm_inputs, name) for name in INPUT_NAMES],
)
def test_moved_names_are_reexported_from_swarm(module: object, name: str) -> None:
    moved = getattr(module, name)
    assert getattr(swarm, name) is moved
    assert moved.__module__ == module.__name__  # type: ignore[attr-defined]


@pytest.mark.parametrize("module", [swarm_render, swarm_inputs])
def test_split_modules_do_not_import_swarm(module: object) -> None:
    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "aragora.cli.commands.swarm"
            if node.module == "aragora.cli.commands":
                assert all(alias.name != "swarm" for alias in node.names)
        elif isinstance(node, ast.Import):
            assert all(alias.name != "aragora.cli.commands.swarm" for alias in node.names)


def test_print_table_pads_columns_and_reports_empty(capsys: pytest.CaptureFixture[str]) -> None:
    swarm._print_table([("a", "A"), ("b", "Bee")], [{"a": "long-value", "b": 1}, {"a": "x"}])
    swarm._print_table([("a", "A")], [])
    assert capsys.readouterr().out.splitlines() == [
        "A           Bee",
        "----------  ---",
        "long-value  1  ",
        "x              ",
        "(no items)",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "-"), ("bad", "-"), (-3, "0.0s"), (12.34, "12.3s"), (125, "2m 5s"), (7322, "2h 2m")],
)
def test_format_elapsed_seconds(value: object, expected: str) -> None:
    assert swarm._format_elapsed_seconds(value) == expected


def test_supervisor_run_and_harvest_table_output(capsys: pytest.CaptureFixture[str]) -> None:
    swarm._print_supervisor_run(
        {
            "run_id": "run-1",
            "status": "active",
            "target_branch": "main",
            "goal": "ship it",
            "work_orders": [{"status": "queued"}, {"status": "done"}, {"status": "queued"}, "x"],
        }
    )
    swarm._render_tranche_queue_harvest_table(
        {
            "queue_id": "q-1",
            "status": "done",
            "dry_run": True,
            "requested_execute_merge": True,
            "summary": {"total_items": 3, "prs_created": 2, "completed": 1},
        }
    )
    assert capsys.readouterr().out.splitlines() == [
        "run_id=run-1",
        "status=active target_branch=main",
        "goal=ship it",
        "work_orders=4 [done=1, queued=2]",
        "Tranche Queue Harvest (q-1)",
        "status=done",
        "dry_run=true",
        "requested_execute_merge=true",
        "",
        "metric       count",
        "-----------  -----",
        "total items      3",
        "PRs created      2",
        "completed        1",
        "needs_human      0",
        "failed           0",
    ]


def test_integrator_table_output(capsys: pytest.CaptureFixture[str]) -> None:
    swarm._render_integrator_table(
        {
            "summary": {"total_lanes": 1, "ready_lanes": 1},
            "lanes": [
                {
                    "title": "Lane A",
                    "lane_id": "l-1",
                    "branch": "b-1",
                    "merge_readiness": "ready",
                    "status": "open",
                    "canonical_lane": True,
                    "receipt_id": "r-1",
                    "blockers": ["ci"],
                    "next_action": "merge",
                }
            ],
            "next_actions": ["merge l-1", " "],
        }
    )
    assert capsys.readouterr().out.splitlines() == [
        "Swarm Integrator View (1 lanes)",
        "  ready=1 blocked=0 review=0 stale=0 superseded=0",
        "",
        "*[+] Lane A",
        "    lane_id=l-1 branch=b-1 readiness=ready status=open",
        "    receipt=r-1 lease=none",
        "    blockers: ci",
        "    next: merge",
        "",
        "next: merge l-1",
    ]


def test_action_goal_and_csv_inputs() -> None:
    namespace = argparse.Namespace
    assert swarm._resolve_swarm_action_goal(
        namespace(swarm_action_or_goal="tranche", swarm_goal="g")
    ) == ("tranche", "g")
    assert swarm._resolve_swarm_action_goal(
        namespace(swarm_action_or_goal="improve tests", swarm_goal=None)
    ) == ("run", "improve tests")
    assert swarm._optional_text("  ") is None
    assert swarm._parse_csv_set(" a, b,,a ") == {"a", "b"}
    assert swarm._parse_csv_set(" , ") is None
    assert swarm._probe_limit_arg(namespace(probe_limit="x"), default=3) == 3
    assert swarm._probe_limit_arg(namespace(probe_limit=0)) == 1


def test_coordination_identity_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("ARAGORA_SESSION_ID", "ARAGORA_AGENT_SESSION_ID", "ARAGORA_SWARM_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ARAGORA_AGENT", "droid")
    monkeypatch.setenv("ARAGORA_BOSS_SESSION_ID", "boss-env")
    args = argparse.Namespace(session_id=None, assigned_by=None)
    assert swarm._coordination_session_id(args).startswith("droid-")
    assert swarm._coordination_assigned_by(args) == "boss-env"
    monkeypatch.setenv("ARAGORA_SWARM_SESSION_ID", "swarm-env")
    assert swarm._coordination_session_id(args) == "swarm-env"
    assert swarm._coordination_session_id(argparse.Namespace(session_id=" s-1 ")) == "s-1"


def test_load_structured_object(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text('{"queue_id": "q-1"}', encoding="utf-8")
    assert swarm._load_structured_object(str(good)) == {"queue_id": "q-1"}
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="must deserialize to an object"):
        swarm._load_structured_object(str(bad))
