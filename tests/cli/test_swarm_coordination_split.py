"""Pin the ``aragora swarm coord|assign|claim-pr|report|findings`` output and their move
into ``swarm_coordination``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.cli.commands import swarm, swarm_coordination


def _args(action: str, goal: str | None = None, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "swarm_action_or_goal": action,
        "swarm_goal": goal,
        "swarm_campaign_target": None,
        "json": False,
        "session_id": "codex-a",
        "assigned_by": "boss-a",
        "findings_limit": 10,
        "scope": None,
        "constraint": None,
        "directive_status": "active",
        "claim_intent": None,
        "ttl_minutes": 30,
        "kind": None,
        "pr": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


@pytest.fixture
def repo_root(tmp_path: Path):
    with patch("aragora.worktree.fleet.resolve_repo_root", return_value=tmp_path):
        yield tmp_path


def test_coordination_helper_lives_in_swarm_coordination() -> None:
    assert swarm._run_coordination_action is swarm_coordination._run_coordination_action
    assert (
        swarm_coordination._run_coordination_action.__module__
        == "aragora.cli.commands.swarm_coordination"
    )


@pytest.mark.parametrize("action", ["coord", "assign", "claim-pr", "report", "findings"])
def test_cmd_swarm_dispatches_coordination_actions(action: str) -> None:
    args = _args(action, "x", json=True)
    with patch("aragora.cli.commands.swarm._run_coordination_action") as run:
        swarm.cmd_swarm(args)
    run.assert_called_once_with(args, action=action, goal="x", as_json=True)


@pytest.mark.parametrize(
    ("action", "goal", "target", "message"),
    [
        (
            "assign",
            None,
            "task",
            'Error: usage: aragora swarm assign <session-id> "task description"',
        ),
        (
            "assign",
            "codex-b",
            None,
            'Error: usage: aragora swarm assign <session-id> "task description"',
        ),
        ("claim-pr", None, None, "Error: usage: aragora swarm claim-pr <pr-number>"),
        ("claim-pr", "12x", None, "Error: invalid PR number: 12x"),
        ("report", "  ", None, 'Error: usage: aragora swarm report "finding text"'),
    ],
)
def test_usage_errors_print_and_return(
    repo_root: Path, capsys, action: str, goal: str | None, target: str | None, message: str
) -> None:
    swarm.cmd_swarm(_args(action, goal, swarm_campaign_target=target))
    assert capsys.readouterr().out == message + "\n"


def test_coord_text_and_json(repo_root: Path, capsys) -> None:
    view = {
        "summary": {"directive_count": 1, "session_count": 2, "claim_count": 0, "finding_count": 0},
        "directives": [
            {"target": "codex-a", "status": "active", "task": "Own lane", "scope": ["#1"]}
        ],
    }
    with patch("aragora.swarm.session_coordinator.read_directives", return_value=view) as read:
        swarm.cmd_swarm(_args("coord", findings_limit=0))
        text = capsys.readouterr().out
        swarm.cmd_swarm(_args("coord", json=True))
        as_json = json.loads(capsys.readouterr().out)
    assert text == (
        "coordination directives=1 sessions=2 claims=0 findings=0\n"
        "directive codex-a status=active task=Own lane\n"
        "  scope: #1\n"
    )
    assert as_json == view
    assert read.call_args_list[0].args == (repo_root,)
    assert read.call_args_list[0].kwargs == {"findings_limit": 1}
    assert read.call_args_list[1].kwargs == {"findings_limit": 10}


def test_assign_text_and_kwargs(repo_root: Path, capsys) -> None:
    directive = {"target": "codex-b", "task": "Fix parity"}
    with patch(
        "aragora.swarm.session_coordinator.set_assignment", return_value=directive
    ) as assign:
        swarm.cmd_swarm(
            _args(
                "assign",
                "codex-b",
                swarm_campaign_target="Fix parity",
                scope=["#2", " "],
                constraint=["no drain", ""],
                directive_status=None,
            )
        )
        text = capsys.readouterr().out
        swarm.cmd_swarm(_args("assign", "codex-b", swarm_campaign_target="Fix parity", json=True))
        as_json = json.loads(capsys.readouterr().out)
    assert text == "assigned codex-b: Fix parity\n"
    assert as_json == {"mode": "coordination-assign", "directive": directive}
    assert assign.call_args_list[0].args == ("codex-b", "Fix parity")
    assert assign.call_args_list[0].kwargs == {
        "scope": ["#2"],
        "constraints": ["no drain"],
        "status": "active",
        "issued_by": "boss-a",
        "repo_root": repo_root,
    }


def test_claim_pr_granted_contested_and_json(repo_root: Path, capsys) -> None:
    results = [
        {"status": "granted"},
        {"status": "contested", "contested_by": [{"session_id": "codex-z"}, "skip"]},
        {"status": "contested", "contested_by": []},
        {"status": "granted", "lease": "l-1"},
    ]
    with patch("aragora.swarm.session_coordinator.claim_pr", side_effect=results) as claim:
        swarm.cmd_swarm(_args("claim-pr", "42", claim_intent="review", ttl_minutes=0))
        swarm.cmd_swarm(_args("claim-pr", "42"))
        swarm.cmd_swarm(_args("claim-pr", "42"))
        text = capsys.readouterr().out
        swarm.cmd_swarm(_args("claim-pr", "42", json=True))
        as_json = json.loads(capsys.readouterr().out)
    assert text == (
        "claimed PR#42 for codex-a\n"
        "PR#42 claim contested for codex-a (also claimed by codex-z)\n"
        "PR#42 claim contested for codex-a\n"
    )
    assert as_json == {
        "mode": "coordination-claim-pr",
        "pr": 42,
        "status": "granted",
        "lease": "l-1",
    }
    assert claim.call_args_list[0].args == (42, "codex-a")
    assert claim.call_args_list[0].kwargs == {
        "intent": "review",
        "ttl_minutes": 30,
        "repo_root": repo_root,
    }


def test_report_text_json_and_kwargs(repo_root: Path, capsys) -> None:
    finding = {"kind": "blocker", "message": "Route bug"}
    with patch("aragora.swarm.session_coordinator.report_finding", return_value=finding) as report:
        swarm.cmd_swarm(_args("report", "Route bug", kind="blocker", pr=7, scope=["a.py"]))
        text = capsys.readouterr().out
        swarm.cmd_swarm(_args("report", "Route bug", json=True))
        as_json = json.loads(capsys.readouterr().out)
    assert text == "reported blocker from codex-a\n"
    assert as_json == {"mode": "coordination-report", "finding": finding}
    assert report.call_args_list[0].args == ("Route bug", "codex-a")
    assert report.call_args_list[0].kwargs == {
        "kind": "blocker",
        "pr": 7,
        "scope": ["a.py"],
        "repo_root": repo_root,
    }
    assert report.call_args_list[1].kwargs["kind"] == "finding"


def test_findings_text_empty_rows_and_json(repo_root: Path, capsys) -> None:
    rows = [
        {"source_session": "codex-b", "kind": "blocker", "pr": 9, "message": "Broken"},
        {"source_session": "", "message": "No pr", "pr": 0},
    ]
    with patch(
        "aragora.swarm.session_coordinator.list_findings", side_effect=[[], rows, rows]
    ) as listing:
        swarm.cmd_swarm(_args("findings", findings_limit=3, session_id=" s-9 ", kind="blocker"))
        empty = capsys.readouterr().out
        swarm.cmd_swarm(_args("findings"))
        text = capsys.readouterr().out
        swarm.cmd_swarm(_args("findings", json=True))
        as_json = json.loads(capsys.readouterr().out)
    assert empty == "No findings reported yet.\n"
    assert text == "[codex-b] blocker pr=#9 Broken\n[-] finding No pr\n"
    assert as_json == {"mode": "coordination-findings", "findings": rows}
    assert listing.call_args_list[0].kwargs == {
        "limit": 3,
        "session_id": "s-9",
        "kind": "blocker",
        "pr": None,
        "repo_root": repo_root,
    }
