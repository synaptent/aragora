"""Tests for ``aragora swarm`` CLI parser and command entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.cli.commands.swarm import cmd_swarm


class _FakeSpec:
    def __init__(self, yaml_text: str = "id: test-spec\n") -> None:
        self._yaml_text = yaml_text

    def to_yaml(self) -> str:
        return self._yaml_text


class TestSwarmParser:
    def test_swarm_registered_in_root_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "improve onboarding"])
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "improve onboarding"
        assert args.swarm_goal is None
        assert args.spec is None
        assert args.dry_run is False

    def test_swarm_parser_accepts_options(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "swarm",
                "reduce latency",
                "--skip-interrogation",
                "--budget-limit",
                "12.5",
                "--require-approval",
                "--dry-run",
                "--save-spec",
                "swarm-spec.yaml",
            ]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "reduce latency"
        assert args.skip_interrogation is True
        assert args.budget_limit == 12.5
        assert args.require_approval is True
        assert args.dry_run is True
        assert args.save_spec == "swarm-spec.yaml"

    def test_swarm_status_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(["swarm", "status", "--run-id", "run-123", "--json"])
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "status"
        assert args.run_id == "run-123"
        assert args.json is True

    def test_swarm_reconcile_parser(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "reconcile", "--run-id", "run-123", "--watch", "--interval-seconds", "1.5"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal == "reconcile"
        assert args.run_id == "run-123"
        assert args.watch is True
        assert args.interval_seconds == 1.5


class TestSwarmCommand:
    def test_cmd_swarm_requires_goal_or_spec(self, capsys):
        args = argparse.Namespace(
            swarm_action_or_goal="run",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=False,
            budget_limit=5.0,
            require_approval=False,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )
        cmd_swarm(args)
        out = capsys.readouterr().out
        assert "provide a goal or --spec file" in out

    def test_cmd_swarm_dry_run_saves_spec(self, tmp_path: Path):
        output_spec = tmp_path / "generated-spec.yaml"
        fake_spec = _FakeSpec("id: generated\n")
        mock_commander = SimpleNamespace(dry_run=AsyncMock(return_value=fake_spec))

        args = argparse.Namespace(
            swarm_action_or_goal="ship swarm",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=True,
            budget_limit=7.0,
            require_approval=False,
            save_spec=str(output_spec),
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        mock_commander.dry_run.assert_awaited_once()
        assert output_spec.exists()
        assert output_spec.read_text() == "id: generated\n"

    def test_cmd_swarm_skip_interrogation_dispatches(self):
        fake_run = MagicMock()
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock(return_value=fake_run))
        args = argparse.Namespace(
            swarm_action_or_goal="harden CI",
            swarm_goal=None,
            spec=None,
            skip_interrogation=True,
            dry_run=False,
            budget_limit=9.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        mock_commander.run_supervised_from_spec.assert_awaited_once()

    def test_cmd_swarm_status_uses_supervisor(self, capsys):
        args = argparse.Namespace(
            swarm_action_or_goal="status",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=False,
            budget_limit=9.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id=None,
            status_limit=20,
            refresh_scaling=False,
        )

        with patch("aragora.swarm.SwarmSupervisor") as supervisor_cls:
            supervisor_cls.return_value.status_summary.return_value = {
                "runs": [],
                "counts": {
                    "runs": 1,
                    "queued_work_orders": 2,
                    "leased_work_orders": 1,
                    "completed_work_orders": 0,
                },
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "runs=1 queued=2 leased=1 completed=0" in out

    def test_cmd_swarm_reconcile_uses_reconciler(self, capsys):
        args = argparse.Namespace(
            swarm_action_or_goal="reconcile",
            swarm_goal=None,
            spec=None,
            skip_interrogation=False,
            dry_run=False,
            budget_limit=9.0,
            require_approval=True,
            save_spec=None,
            from_obsidian=None,
            obsidian_vault=None,
            no_obsidian_receipts=False,
            profile="developer",
            autonomy="propose",
            max_parallel=20,
            no_loop=False,
            target_branch="main",
            concurrency_cap=8,
            managed_dir_pattern=".worktrees/{agent}-auto",
            json=False,
            run_id="run-123",
            status_limit=20,
            refresh_scaling=False,
            no_dispatch=False,
            watch=False,
            interval_seconds=5.0,
            max_ticks=None,
            all_runs=False,
        )

        fake_run = MagicMock()
        fake_run.to_dict.return_value = {
            "run_id": "run-123",
            "status": "active",
            "target_branch": "main",
            "goal": "goal",
            "work_orders": [],
        }

        with patch("aragora.swarm.SwarmReconciler") as reconciler_cls:
            reconciler_cls.return_value.tick_run = AsyncMock(return_value=fake_run)
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "run_id=run-123" in out
