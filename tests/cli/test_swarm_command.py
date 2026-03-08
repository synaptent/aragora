"""Tests for ``aragora swarm`` CLI parser and command entrypoint."""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.cli.commands.swarm import cmd_swarm
from aragora.swarm.spec import SwarmSpec


class _FakeSpec:
    def __init__(self, yaml_text: str = "id: test-spec\n") -> None:
        self._yaml_text = yaml_text

    def to_yaml(self) -> str:
        return self._yaml_text


def _swarm_args(**overrides: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "swarm_action_or_goal": "run",
        "swarm_goal": None,
        "spec": None,
        "skip_interrogation": False,
        "dry_run": False,
        "budget_limit": 9.0,
        "require_approval": False,
        "save_spec": None,
        "from_obsidian": None,
        "obsidian_vault": None,
        "no_obsidian_receipts": False,
        "profile": "developer",
        "autonomy": "propose",
        "max_parallel": 20,
        "no_loop": False,
        "target_branch": "main",
        "concurrency_cap": 8,
        "managed_dir_pattern": ".worktrees/{agent}-auto",
        "json": False,
        "run_id": None,
        "status_limit": 20,
        "refresh_scaling": False,
        "no_dispatch": False,
        "watch": False,
        "interval_seconds": 5.0,
        "max_ticks": None,
        "all_runs": False,
        "dispatch_only": False,
        "no_wait": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _fake_supervisor_run(
    *,
    run_id: str = "run-123",
    status: str = "active",
    work_orders: list[dict[str, object]] | None = None,
) -> MagicMock:
    fake_run = MagicMock()
    fake_run.to_dict.return_value = {
        "run_id": run_id,
        "status": status,
        "target_branch": "main",
        "goal": "goal",
        "work_orders": work_orders or [],
    }
    return fake_run


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

    def test_swarm_parser_accepts_spec_dispatch_options(self):
        from aragora.cli.parser import build_parser

        parser = build_parser()
        args = parser.parse_args(
            ["swarm", "--spec", "swarm-spec.yaml", "--dispatch-only", "--no-wait", "--json"]
        )
        assert args.command == "swarm"
        assert args.swarm_action_or_goal is None
        assert args.spec == "swarm-spec.yaml"
        assert args.dispatch_only is True
        assert args.no_wait is True
        assert args.json is True


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

    def test_cmd_swarm_dry_run_skip_interrogation_builds_direct_spec(self, capsys):
        args = argparse.Namespace(
            swarm_action_or_goal="verify dry run",
            swarm_goal=None,
            spec=None,
            skip_interrogation=True,
            dry_run=True,
            budget_limit=11.0,
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

        with patch("aragora.swarm.SwarmCommander"):
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "[DRY RUN] Skipping interrogation" in out
        assert '"raw_goal": "verify dry run"' in out

    def test_cmd_swarm_skip_interrogation_dispatches_when_goal_is_already_bounded(self):
        fake_run = MagicMock()
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock(return_value=fake_run))
        args = argparse.Namespace(
            swarm_action_or_goal="Only touch aragora/swarm/spec.py",
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

    def test_cmd_swarm_skip_interrogation_fails_closed_for_vague_goal(self, capsys):
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock())
        args = argparse.Namespace(
            swarm_action_or_goal="make it better",
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

        out = capsys.readouterr().out
        assert "under-specified for dispatch" in out
        mock_commander.run_supervised_from_spec.assert_not_called()

    @patch("aragora.worktree.fleet.FleetCoordinationStore")
    @patch("aragora.worktree.fleet.build_fleet_rows")
    @patch("aragora.worktree.fleet.resolve_repo_root")
    def test_cmd_swarm_status_uses_supervisor(
        self, mock_resolve_root, mock_build_rows, mock_store_cls, capsys
    ):
        mock_resolve_root.return_value = Path("/tmp/repo")
        mock_build_rows.return_value = [
            {
                "session_id": "sess-a",
                "path": "/tmp/repo/.worktrees/a",
                "branch": "codex/docs-lane",
                "has_lock": True,
                "pid_alive": True,
                "agent": "codex",
                "last_activity": "2026-03-07T00:00:00+00:00",
            }
        ]
        store = MagicMock()
        store.list_claims.return_value = [
            {"session_id": "sess-a", "path": "aragora/swarm/reporter.py"}
        ]
        store.list_merge_queue.return_value = [
            {
                "id": "mq-1",
                "branch": "codex/docs-lane",
                "session_id": "sess-a",
                "status": "needs_human",
                "metadata": {"receipt_id": "rcpt-123"},
            }
        ]
        mock_store_cls.return_value = store
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
                "runs": [
                    {
                        "run_id": "run-1",
                        "status": "active",
                        "target_branch": "main",
                        "goal": "dogfood",
                        "work_orders": [
                            {
                                "work_order_id": "docs-lane",
                                "title": "Write operator guide",
                                "status": "completed",
                                "branch": "codex/docs-lane",
                                "worktree_path": "/tmp/repo/.worktrees/a",
                                "target_agent": "codex",
                                "last_progress_at": "2026-03-07T00:00:00+00:00",
                            }
                        ],
                    }
                ],
                "counts": {
                    "runs": 1,
                    "queued_work_orders": 0,
                    "leased_work_orders": 0,
                    "completed_work_orders": 1,
                },
                "coordination": {"counts": {"active_leases": 1}},
            }
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "runs=1 queued=0 leased=0 completed=1" in out
        assert "integrator ready=0 review=1 blocked=0" in out
        assert (
            "next: Write operator guide: Review the validated lane and decide whether it should merge."
            in out
        )

    def test_cmd_swarm_reconcile_uses_reconciler(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="reconcile",
            run_id="run-123",
        )

        fake_run = _fake_supervisor_run()

        with patch("aragora.swarm.SwarmReconciler") as reconciler_cls:
            reconciler_cls.return_value.tick_run = AsyncMock(return_value=fake_run)
            cmd_swarm(args)

        out = capsys.readouterr().out
        assert "run_id=run-123" in out

    def test_cmd_swarm_spec_no_dispatch_preserves_explicit_work_orders(self, tmp_path: Path):
        spec_path = tmp_path / "swarm-spec.yaml"
        spec = SwarmSpec(
            raw_goal="Dogfood the supervised swarm",
            refined_goal="Dogfood the supervised swarm",
            work_orders=[
                {
                    "work_order_id": "docs-lane",
                    "title": "Add operator guide",
                    "file_scope": ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"],
                    "expected_tests": [],
                    "target_agent": "codex",
                    "reviewer_agent": "claude",
                }
            ],
        )
        spec_path.write_text(spec.to_yaml())
        mock_commander = SimpleNamespace(
            run_supervised_from_spec=AsyncMock(return_value=_fake_supervisor_run())
        )
        args = _swarm_args(spec=str(spec_path), no_dispatch=True)

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        mock_commander.run_supervised_from_spec.assert_awaited_once()
        call = mock_commander.run_supervised_from_spec.await_args
        passed_spec = call.args[0]
        assert passed_spec.work_orders[0]["work_order_id"] == "docs-lane"
        assert passed_spec.work_orders[0]["file_scope"] == ["docs/guides/SWARM_DOGFOOD_OPERATOR.md"]
        assert call.kwargs["dispatch"] is False
        assert call.kwargs["wait"] is True

    def test_cmd_swarm_spec_dispatch_only_runs_fire_and_forget(
        self, tmp_path: Path, capsys
    ) -> None:
        spec_path = tmp_path / "swarm-spec.yaml"
        spec = SwarmSpec(
            raw_goal="Dogfood the supervised swarm",
            refined_goal="Dogfood the supervised swarm",
            work_orders=[
                {
                    "work_order_id": "tests-lane",
                    "title": "Add regressions",
                    "file_scope": ["tests/swarm/test_commander.py"],
                    "expected_tests": ["python -m pytest tests/swarm/test_commander.py -q"],
                    "target_agent": "claude",
                    "reviewer_agent": "codex",
                }
            ],
        )
        spec_path.write_text(spec.to_yaml())
        fake_run = _fake_supervisor_run(
            work_orders=[{"work_order_id": "tests-lane", "status": "dispatched"}]
        )
        mock_commander = SimpleNamespace(run_supervised_from_spec=AsyncMock(return_value=fake_run))
        args = _swarm_args(spec=str(spec_path), dispatch_only=True, json=True)

        with patch("aragora.swarm.SwarmCommander", return_value=mock_commander):
            cmd_swarm(args)

        call = mock_commander.run_supervised_from_spec.await_args
        assert call.kwargs["dispatch"] is True
        assert call.kwargs["wait"] is False
        out = capsys.readouterr().out
        assert '"run_id": "run-123"' in out
        assert '"status": "active"' in out

    def test_cmd_swarm_reconcile_watch_uses_watch_run(self, capsys):
        args = _swarm_args(
            swarm_action_or_goal="reconcile",
            run_id="run-123",
            watch=True,
            interval_seconds=1.5,
            max_ticks=4,
        )
        fake_run = _fake_supervisor_run(
            work_orders=[{"work_order_id": "tests-lane", "status": "completed"}]
        )

        with patch("aragora.swarm.SwarmReconciler") as reconciler_cls:
            reconciler = reconciler_cls.return_value
            reconciler.watch_run = AsyncMock(return_value=fake_run)
            reconciler.tick_run = AsyncMock()
            cmd_swarm(args)

        reconciler.watch_run.assert_awaited_once_with(
            "run-123",
            interval_seconds=1.5,
            max_ticks=4,
        )
        reconciler.tick_run.assert_not_called()
        out = capsys.readouterr().out
        assert "work_orders=1 [completed=1]" in out
