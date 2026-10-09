"""Pin the ``aragora swarm`` helper split into sibling modules.

The issue validation-contract audit helpers live in
``aragora.cli.commands.swarm_validation_audit`` and the runner payload builders
live in ``aragora.cli.commands.swarm_runner_payloads``.
``aragora.cli.commands.swarm`` keeps exporting every name, so existing imports
and ``mock.patch("aragora.cli.commands.swarm.<name>")`` targets keep working.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aragora.cli.commands import swarm
from aragora.cli.commands import swarm_runner_payloads as runner_payloads
from aragora.cli.commands import swarm_validation_audit as validation_audit

VALIDATION_AUDIT_NAMES = [
    "_trim_command_output",
    "_UNSAFE_VALIDATION_SHELL_FRAGMENTS",
    "_probe_validation_command",
    "_classify_issue_validation_status",
    "_audit_issue_validation_contract",
    "_open_audit_checkout",
]

RUNNER_PAYLOAD_NAMES = [
    "_build_runner_report_payload",
    "_build_multi_runner_payload",
    "_build_runner_probe_payload",
]


@pytest.mark.parametrize("name", VALIDATION_AUDIT_NAMES)
def test_validation_audit_helpers_live_in_sibling_module(name: str) -> None:
    obj = getattr(validation_audit, name)
    if callable(obj):
        assert obj.__module__ == "aragora.cli.commands.swarm_validation_audit"
    assert getattr(swarm, name) is obj


@pytest.mark.parametrize("name", RUNNER_PAYLOAD_NAMES)
def test_runner_payload_builders_live_in_sibling_module(name: str) -> None:
    obj = getattr(runner_payloads, name)
    assert obj.__module__ == "aragora.cli.commands.swarm_runner_payloads"
    assert getattr(swarm, name) is obj


def test_probe_rejects_shell_operators_without_running_anything(tmp_path: Path) -> None:
    with patch.object(validation_audit.subprocess, "run") as run:
        result = swarm._probe_validation_command(
            "pytest tests/ -q | tail -1", repo_root=tmp_path, timeout_seconds=5
        )
    assert result["status"] == "unsafe"
    run.assert_not_called()


def test_audit_reports_passes_now_when_every_probe_passes(tmp_path: Path) -> None:
    issue = SimpleNamespace(
        number=7,
        title="Fix the thing",
        url="https://example.invalid/7",
        labels=["bug"],
        body="## Validation\n- `python3 -m pytest tests/cli -q`\n",
    )
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok", stderr="")
    with patch.object(validation_audit.subprocess, "run", return_value=completed) as run:
        report = swarm._audit_issue_validation_contract(issue, repo_root=tmp_path)
    assert run.call_args.kwargs["cwd"] == str(tmp_path)
    assert report["number"] == 7
    assert report["commands"] == ["python3 -m pytest tests/cli -q"]
    assert report["status"] == "passes_now"


def test_open_audit_checkout_without_ref_yields_repo_root(tmp_path: Path) -> None:
    with swarm._open_audit_checkout(tmp_path, git_ref=None) as root:
        assert root == tmp_path


def test_runner_report_payload_counts_capacity_and_probe_results() -> None:
    payload = swarm._build_runner_report_payload(
        registrations=[
            {
                "runner_id": "r1",
                "runner_type": "codex",
                "freshness_status": "fresh",
                "probe_status": "passed",
                "capabilities": {"max_parallel_lanes": 3, "active_lanes": 1},
                "claimed_lanes": 1,
            },
            {"runner_id": "r2", "runner_type": "claude", "probe_status": "failed"},
        ],
        routing={"selected_runners": [{"runner_id": "r1", "probe_status": "passed"}]},
    )
    assert payload["summary"] == {
        "registered": 2,
        "fresh": 1,
        "execution_verified": 1,
        "probe_failed": 1,
        "discovered": 0,
        "selected_for_routing": 1,
        "selected_verified": 1,
    }
    assert [row["available_capacity"] for row in payload["runners"]] == [1, 1]


def test_runner_probe_payload_reports_heartbeat_readiness_for_maintain() -> None:
    payload = swarm._build_runner_probe_payload(
        subaction="maintain",
        runners=[{"runner_id": "r1", "probe_status": "failed"}],
        discovered=[],
        routing_after={"selected_runners": []},
    )
    assert payload["heartbeat_readiness"] == {
        "ready": False,
        "blocked_reason": "no_execution_verified_runner",
        "execution_verified_count": 0,
    }
