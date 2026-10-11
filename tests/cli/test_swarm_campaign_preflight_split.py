"""Pin ``aragora swarm preflight`` and ``aragora swarm campaign`` text output and their move."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aragora.cli.commands import swarm, swarm_campaign, swarm_preflight


def _args(action: str, subaction: str | None, **overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "swarm_action_or_goal": action,
        "swarm_goal": subaction,
        "json": False,
        "target_branch": "main",
        "skip_publication": False,
        "contract": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_actions_live_in_their_modules() -> None:
    assert swarm._run_preflight_action is swarm_preflight._run_preflight_action
    assert swarm._run_campaign_action is swarm_campaign._run_campaign_action


def test_cmd_swarm_dispatches_preflight_and_campaign() -> None:
    preflight_args = _args("preflight", None, target_branch="dev", skip_publication=True)
    campaign_args = _args("campaign", "status", json=True, target_branch="dev")
    with (
        patch("aragora.cli.commands.swarm._run_preflight_action") as preflight,
        patch("aragora.cli.commands.swarm._run_campaign_action") as campaign,
    ):
        swarm.cmd_swarm(preflight_args)
        swarm.cmd_swarm(campaign_args)
    preflight.assert_called_once_with(
        preflight_args, target_branch="dev", skip_publication=True, as_json=False
    )
    campaign.assert_called_once_with(
        campaign_args, goal="status", target_branch="dev", as_json=True
    )


def _preflight_result(passed: bool) -> SimpleNamespace:
    payload = {
        "passed": passed,
        "repo_root": "/repo",
        "agent": "claude",
        "base_ref": "main",
        "branch": "feature",
        "worker": {"worker_contract_checksum": "abc123"},
    }
    return SimpleNamespace(to_dict=lambda: dict(payload))


def test_preflight_text_output_and_exit_code(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/repo")),
        patch("aragora.swarm.preflight.run_preflight") as run_preflight,
    ):
        run_preflight.return_value = _preflight_result(True)
        swarm.cmd_swarm(_args("preflight", None))
        run_preflight.return_value = _preflight_result(False)
        with pytest.raises(SystemExit) as blocked:
            swarm.cmd_swarm(_args("preflight", None))
    assert blocked.value.code == 2
    expected = [
        "repo_root=/repo",
        "agent=claude",
        "base_ref=main",
        "branch=feature",
        "worker_contract_checksum=abc123",
    ]
    assert capsys.readouterr().out.splitlines() == (
        ["swarm preflight: ok", *expected, "swarm preflight: blocked", *expected]
    )


def test_preflight_contract_text_output_and_exit_code(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    receipt = SimpleNamespace(
        artifacts={"expected_contract_checksum": "sum-1"},
        failure_terminal_class=SimpleNamespace(value="auth_failure"),
        to_dict=lambda: {
            "receipt_id": "rcpt-1",
            "check_type": "scratch",
            "passed": False,
            "expires_at": "2026-10-11T07:00:00Z",
        },
    )
    gate = SimpleNamespace(to_dict=lambda: {"verdict": "blocked"})
    args = _args("preflight", None, contract=str(tmp_path / "c.json"), skip_publication=True)
    with (
        patch("aragora.worktree.fleet.resolve_repo_root", return_value=Path("/repo")),
        patch("aragora.swarm.credential_envelope.CredentialEnvelope"),
        patch("aragora.swarm.preflight.run_contract_preflight_receipt", return_value=receipt),
        patch(
            "aragora.swarm.preflight.evaluate_preflight_receipt_gate", return_value=gate
        ) as gate_fn,
    ):
        with pytest.raises(SystemExit) as blocked:
            swarm.cmd_swarm(args)
    assert blocked.value.code == 2
    assert gate_fn.call_args.kwargs["check_type"] == "scratch"
    assert gate_fn.call_args.kwargs["expected_contract_checksum"] == "sum-1"
    assert capsys.readouterr().out.splitlines() == [
        "swarm preflight: blocked",
        "receipt_id=rcpt-1",
        "check_type=scratch",
        "passed=False",
        "expires_at=2026-10-11T07:00:00Z",
        "failure_terminal_class=auth_failure",
    ]


def test_campaign_status_text_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status = {
        "campaign_id": "camp-1",
        "stop_reason": "budget",
        "counts": {"queued": 2, "done": 1},
        "projects": [
            {"project_id": "p-1", "status": "done", "review_status": "passed", "title": "One"},
            "skipped",
        ],
    }
    args = _args("campaign", "status", manifest=str(tmp_path / "manifest.yaml"))
    with patch("aragora.swarm.campaign.CampaignExecutor") as executor_cls:
        executor_cls.return_value.status.return_value = status
        swarm.cmd_swarm(args)
    assert executor_cls.call_args.kwargs["target_branch"] == "main"
    assert capsys.readouterr().out.splitlines() == [
        "campaign_id=camp-1 stop_reason=budget",
        "counts=done=1, queued=2",
        "p-1 status=done review=passed title=One",
    ]


@pytest.mark.parametrize(
    ("subaction", "message"),
    [
        ("bogus", "campaign action must be one of"),
        ("review", "campaign review requires a project id"),
        ("plan", "campaign plan requires exactly one of"),
    ],
)
def test_campaign_rejects_bad_requests(tmp_path: Path, subaction: str, message: str) -> None:
    args = _args("campaign", subaction, manifest=str(tmp_path / "manifest.yaml"))
    with patch("aragora.swarm.campaign.CampaignExecutor"):
        with pytest.raises(ValueError, match=message):
            swarm.cmd_swarm(args)
