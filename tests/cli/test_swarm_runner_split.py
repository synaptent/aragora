"""Pin ``aragora swarm runner`` text output and its move into ``swarm_runner``."""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aragora.cli.commands import swarm, swarm_runner


def _runner_args(subaction: str, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "swarm_action_or_goal": "runner",
        "swarm_goal": subaction,
        "json": False,
        "runner_type": "claude",
        "probe_limit": 1,
        "claude_runner_profiles": None,
        "runner_rotation_interval": 1800.0,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _inspection(runner_id: str) -> SimpleNamespace:
    payload = {"runner_id": runner_id, "runner_type": "claude", "availability": "available"}
    return SimpleNamespace(runner_id=runner_id, to_dict=lambda: dict(payload))


def test_runner_action_lives_in_swarm_runner() -> None:
    assert swarm._run_runner_action is swarm_runner._run_runner_action
    assert swarm_runner._run_runner_action.__module__ == "aragora.cli.commands.swarm_runner"


def test_cmd_swarm_dispatches_runner_with_parsed_options() -> None:
    args = _runner_args(
        "report", json=True, claude_runner_profiles="max-01, max-02", runner_rotation_interval=0
    )
    with patch("aragora.cli.commands.swarm._run_runner_action") as run:
        swarm.cmd_swarm(args)
    run.assert_called_once_with(
        args,
        goal="report",
        allowed_runner_profiles={"max-01", "max-02"},
        runner_rotation_interval=1800.0,
        as_json=True,
    )


def test_unknown_runner_subaction_prints_error(capsys: pytest.CaptureFixture[str]) -> None:
    swarm.cmd_swarm(_runner_args("bogus"))
    assert capsys.readouterr().out == (
        "Error: swarm runner action must be 'inspect', 'register', 'heartbeat', "
        "'report', 'probe', or 'maintain'\n"
    )


def test_runner_inspect_text_lists_each_runner(capsys: pytest.CaptureFixture[str]) -> None:
    with patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover:
        discover.return_value = [_inspection("r-1"), _inspection("r-2")]
        swarm.cmd_swarm(_runner_args("inspect"))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Runner inspect count=2 available=2 registered=0"
    assert out[1] == ""
    assert out.count("runner_id=r-1") == 1
    assert out.count("runner_id=r-2") == 1


def test_runner_probe_text_prints_summary_and_runner(capsys: pytest.CaptureFixture[str]) -> None:
    probe = SimpleNamespace(status="passed")
    with (
        patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
        patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
        patch("aragora.swarm.runner_registry.probe_runner_execution", return_value=probe),
        patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
    ):
        discover.return_value = [_inspection("r-1"), _inspection("r-2")]
        auth_ctx.return_value = None
        registry_cls.return_value.record_probe.return_value = {
            "runner_id": "r-1",
            "probe_status": "passed",
        }
        swarm.cmd_swarm(_runner_args("probe"))
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Runner probe discovered=2 attempted=1 passed=1 failed=0"
    assert out[1] == ""
    assert "runner_id=r-1" in out
    registry_cls.return_value.resolve_boss_routing.assert_not_called()


def test_runner_report_text_uses_the_report_renderer(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch("aragora.swarm.runner_registry.discover_runner_inspections") as discover,
        patch("aragora.swarm.runner_registry.authorization_context_with_defaults") as auth_ctx,
        patch("aragora.swarm.runner_registry.LocalRunnerRegistry") as registry_cls,
        patch("aragora.cli.commands.swarm_runner._render_runner_report") as render,
    ):
        discover.return_value = [_inspection("r-1")]
        auth_ctx.return_value = None
        registry_cls.return_value.list_registrations.return_value = []
        registry_cls.return_value.resolve_boss_routing.return_value = SimpleNamespace(
            to_dict=lambda: {"selected_runners": []}
        )
        swarm.cmd_swarm(_runner_args("report"))
    payload = render.call_args.args[0]
    assert (payload["mode"], payload["action"]) == ("runner", "report")
    assert capsys.readouterr().out == ""
