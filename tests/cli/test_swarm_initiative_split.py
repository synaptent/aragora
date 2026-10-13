"""Pin ``aragora swarm initiative`` output and error paths and its move into ``swarm_initiative``."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aragora.cli.commands import swarm, swarm_initiative
from aragora.swarm.initiative_models import InitiativeRecord, InitiativeSlice
from aragora.swarm.initiative_store import InitiativeStore


def _args(subaction: str | None, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "swarm_action_or_goal": "initiative",
        "swarm_goal": subaction,
        "swarm_campaign_target": None,
        "json": False,
        "target_branch": "main",
        "manifest": None,
        "initiative_dir": None,
        "dry_run": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _record(initiative_id: str, title: str, **overrides: object) -> InitiativeRecord:
    values: dict[str, object] = {
        "initiative_id": initiative_id,
        "title": title,
        "goal": title,
        "rationale": "Pinned by the initiative split tests.",
    }
    values.update(overrides)
    return InitiativeRecord(**values)  # type: ignore[arg-type]


def _slice() -> InitiativeSlice:
    return InitiativeSlice(slice_id="s-1", title="Slice", description="d", status="pending")


@pytest.fixture
def repo_root(tmp_path: Path):
    with patch("aragora.worktree.fleet.resolve_repo_root", return_value=tmp_path):
        yield tmp_path


def test_initiative_helpers_live_in_swarm_initiative() -> None:
    assert swarm._run_initiative_action is swarm_initiative._run_initiative_action
    assert swarm._initiative_rows is swarm_initiative._initiative_rows
    assert (
        swarm_initiative._run_initiative_action.__module__
        == "aragora.cli.commands.swarm_initiative"
    )


def test_cmd_swarm_dispatches_initiative() -> None:
    args = _args("status", json=True, target_branch="dev")
    with patch("aragora.cli.commands.swarm._run_initiative_action") as run:
        swarm.cmd_swarm(args)
    run.assert_called_once_with(args, goal="status", target_branch="dev", as_json=True)


@pytest.mark.parametrize(
    ("subaction", "target", "error", "message"),
    [
        (
            "bogus",
            None,
            ValueError,
            "initiative action must be one of: plan, show, list, run, status, promote",
        ),
        (
            "show",
            None,
            ValueError,
            "initiative show requires an initiative id as the third argument",
        ),
        ("show", "missing-id", FileNotFoundError, "initiative not found: missing-id"),
        ("plan", None, ValueError, "initiative plan requires a goal as the third argument"),
        ("status", "missing-id", FileNotFoundError, "initiative not found: missing-id"),
    ],
)
def test_initiative_rejects_bad_requests(
    repo_root: Path, subaction: str, target: str | None, error: type[Exception], message: str
) -> None:
    args = _args(subaction, swarm_campaign_target=target, initiative_dir=str(repo_root / "state"))
    with pytest.raises(error, match=f"^{re.escape(message)}$"):
        swarm.cmd_swarm(args)


def test_initiative_status_requires_an_existing_manifest(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = repo_root / "missing.yaml"
    with pytest.raises(ValueError, match=re.escape(f"initiative manifest not found: {missing}")):
        swarm.cmd_swarm(_args("status", manifest=str(missing)))
    monkeypatch.chdir(repo_root)
    default = Path(".aragora/campaign_manifest.yaml").resolve()
    with pytest.raises(ValueError, match=re.escape(f"initiative manifest not found: {default}")):
        swarm.cmd_swarm(_args("run"))


def test_initiative_list_text_output(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = InitiativeStore(state_dir=repo_root / "state")
    swarm.cmd_swarm(_args(None, initiative_dir=str(store.state_dir)))
    store.save(
        _record(
            "init-1", "Title One", status="active", feature_flag_name="flag_a", slices=[_slice()]
        )
    )
    store.save(_record("init-2", "Second", status="draft"))
    swarm.cmd_swarm(_args("list", initiative_dir=str(store.state_dir)))
    assert capsys.readouterr().out.splitlines() == [
        f"initiatives=0 state_dir={store.state_dir}",
        "(no items)",
        f"initiatives=2 state_dir={store.state_dir}",
        "Initiative  Status  Feature Flag  Slices  Title    ",
        "----------  ------  ------------  ------  ---------",
        "init-2      draft   -                     Second   ",
        "init-1      active  flag_a        1       Title One",
    ]


def test_initiative_show_text_and_json_output(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = InitiativeStore(state_dir=repo_root / "state")
    store.save(
        _record(
            "init-1",
            "Title One",
            status="active",
            feature_flag_name="flag_a",
            dependencies=["dep-a", "dep-b"],
            validations=["pytest -q"],
            slices=[_slice()],
        )
    )
    show = {"swarm_campaign_target": "init-1", "initiative_dir": str(store.state_dir)}
    swarm.cmd_swarm(_args("show", **show))
    assert capsys.readouterr().out.splitlines() == [
        "initiative_id=init-1",
        "title=Title One",
        "status=active",
        "feature_flag=flag_a",
        "dependencies=dep-a, dep-b",
        "validations=pytest -q",
        "slices=1",
        "  slice s-1 status=pending complexity=medium title=Slice",
    ]
    swarm.cmd_swarm(_args("show", json=True, **show))
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "initiative-show"
    assert payload["action"] == "show"
    assert payload["state_dir"] == str(store.state_dir)
    assert payload["initiative"]["dependencies"] == ["dep-a", "dep-b"]


def test_initiative_plan_text_output(repo_root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    state_dir = repo_root / "state"
    source = repo_root / "notes.md"
    source.write_text("  Why this initiative matters.  \n")
    planned = _record("init-9", "Planned", slices=[_slice(), _slice()])
    args = _args(
        "plan",
        swarm_campaign_target="Build the registry",
        initiative_dir=str(state_dir),
        source_file=str(source),
        dependency=[" dep-a ", " "],
        validation=["pytest -q"],
        feature_flag=" flag_b ",
        milestone=["M1"],
        checkpoint=["C1", ""],
    )
    with patch(
        "aragora.swarm.initiative_planner.InitiativePlanner.plan", return_value=planned
    ) as plan:
        swarm.cmd_swarm(args)
    assert plan.call_args.kwargs == {
        "goal": "Build the registry",
        "rationale": "Why this initiative matters.",
        "dependencies": ["dep-a"],
        "validations": ["pytest -q"],
        "feature_flag_name": "flag_b",
        "milestone_titles": ["M1"],
        "checkpoint_titles": ["C1"],
        "planner_strategy": "heuristic",
        "planner_model": "claude",
    }
    store = InitiativeStore(state_dir=state_dir)
    assert capsys.readouterr().out.splitlines() == [
        "initiative_id=init-9",
        f"path={store.path_for('init-9')}",
        f"manifest={store.campaign_manifest_path_for('init-9')}",
        "slices=2",
    ]
    saved = store.get("init-9")
    assert saved is not None
    assert saved.metadata["source_file"] == str(source.resolve())


def test_initiative_status_and_run_text_output(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = repo_root / "manifest.yaml"
    manifest.write_text("projects: []\n")
    status = {
        "initiative_id": "init-1",
        "completed_slices": 1,
        "total_slices": 2,
        "milestones_complete": 0,
        "milestones_total": 1,
        "milestones": [{"milestone": "M1", "completed": 1, "total": 2, "promotable": True}],
        "slices": [{"project_id": "p-1", "status": "done", "pr_number": 7}, "skipped"],
    }
    with patch("aragora.swarm.initiative_integrator.InitiativeIntegrator") as integrator_cls:
        integrator_cls.return_value.status.return_value = status
        integrator_cls.return_value.run = AsyncMock(return_value={"initiative_id": "init-1"})
        swarm.cmd_swarm(_args("status", manifest=str(manifest), target_branch="dev"))
        swarm.cmd_swarm(_args("run", manifest=str(manifest), boss_repo="org/repo"))
    assert [call.kwargs for call in integrator_cls.call_args_list] == [
        {
            "manifest_path": manifest.resolve(),
            "repo_root": repo_root,
            "target_branch": "dev",
            "repo": "synaptent/aragora",
        },
        {
            "manifest_path": manifest.resolve(),
            "repo_root": repo_root,
            "target_branch": "main",
            "repo": "org/repo",
        },
    ]
    assert capsys.readouterr().out.splitlines() == [
        "initiative_id=init-1 completed=1/2 milestones=0/1",
        "",
        "Milestones",
        "Milestone  Done  Total  WaitPR  WaitMerge  Promotable  Blocked",
        "---------  ----  -----  ------  ---------  ----------  -------",
        "M1         1     2                         True               ",
        "",
        "Slices",
        "Slice  Milestone  Status  Next  PR  Flag",
        "-----  ---------  ------  ----  --  ----",
        "p-1               done          7       ",
        "initiative_id=init-1 completed=0/0 milestones=0/0",
    ]


def test_initiative_promote_prints_json_in_text_mode(
    repo_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = repo_root / "manifest.yaml"
    manifest.write_text("projects: []\n")
    result = {"mode": "initiative-promote", "project_id": "proj-001", "decision": "dry_run"}
    args = _args("promote", swarm_campaign_target="proj-001", manifest=str(manifest), dry_run=True)
    with patch("aragora.swarm.initiative_integrator.InitiativeIntegrator") as integrator_cls:
        integrator_cls.return_value.promote.return_value = result
        swarm.cmd_swarm(args)
    integrator_cls.return_value.promote.assert_called_once_with(project_id="proj-001", dry_run=True)
    assert capsys.readouterr().out == json.dumps(result, indent=2) + "\n"
