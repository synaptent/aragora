"""Tests for ``aragora worktree`` CLI command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.cli.commands.worktree import (
    _cmd_worktree_fleet_claim,
    _cmd_worktree_fleet_queue_add,
    _cmd_worktree_fleet_queue_list,
    _cmd_worktree_fleet_queue_process_next,
    _cmd_worktree_fleet_release,
    _cmd_worktree_fleet_status,
    _cmd_worktree_autopilot,
    add_worktree_parser,
    cmd_worktree,
)
from aragora.worktree.integration_worker import FleetIntegrationOutcome


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest="command")
    add_worktree_parser(subs)
    return parser


def _autopilot_args(**overrides: object) -> argparse.Namespace:
    base = {
        "managed_dir": ".worktrees/codex-auto",
        "auto_action": "status",
        "auto_base": None,
        "agent": "codex",
        "session_id": None,
        "force_new": False,
        "strategy": "merge",
        "reconcile": False,
        "all": False,
        "path": None,
        "ttl_hours": 24,
        "force_unmerged": False,
        "delete_branches": None,
        "json": False,
        "print_path": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


def _fleet_args(**overrides: object) -> argparse.Namespace:
    base = {
        "tail": 500,
        "json": False,
    }
    base.update(overrides)
    return argparse.Namespace(**base)


class TestWorktreeParser:
    def test_autopilot_defaults(self):
        args = _parser().parse_args(["worktree", "autopilot"])
        assert args.command == "worktree"
        assert args.wt_action == "autopilot"
        assert args.auto_action == "status"
        assert args.managed_dir == ".worktrees/codex-auto"

    def test_autopilot_ensure_parse(self):
        args = _parser().parse_args(
            [
                "worktree",
                "--base",
                "develop",
                "autopilot",
                "ensure",
                "--managed-dir",
                ".worktrees/codex-auto-ci",
                "--agent",
                "codex-ci",
                "--session-id",
                "ci-123",
                "--force-new",
                "--strategy",
                "rebase",
                "--reconcile",
                "--print-path",
                "--json",
            ]
        )

        assert args.base == "develop"
        assert args.wt_action == "autopilot"
        assert args.auto_action == "ensure"
        assert args.managed_dir == ".worktrees/codex-auto-ci"
        assert args.agent == "codex-ci"
        assert args.session_id == "ci-123"
        assert args.force_new is True
        assert args.strategy == "rebase"
        assert args.reconcile is True
        assert args.print_path is True
        assert args.json is True

    def test_autopilot_base_override_parse(self):
        args = _parser().parse_args(
            [
                "worktree",
                "autopilot",
                "status",
                "--base",
                "release",
            ]
        )
        assert args.base == "main"
        assert args.auto_base == "release"

    def test_fleet_status_parse_defaults(self):
        args = _parser().parse_args(["worktree", "fleet-status"])
        assert args.command == "worktree"
        assert args.wt_action == "fleet-status"
        assert args.tail == 500
        assert args.json is False

    def test_fleet_claim_parse(self):
        args = _parser().parse_args(
            [
                "worktree",
                "fleet-claim",
                "--session-id",
                "s-1",
                "--paths",
                "a.py",
                "b.py",
                "--mode",
                "shared",
            ]
        )
        assert args.wt_action == "fleet-claim"
        assert args.session_id == "s-1"
        assert args.paths == ["a.py", "b.py"]
        assert args.mode == "shared"

    def test_fleet_queue_process_next_parse(self):
        args = _parser().parse_args(
            [
                "worktree",
                "fleet-queue-process-next",
                "--worker-session-id",
                "integrator-1",
                "--target-branch",
                "release",
                "--execute",
                "--test-gate",
                "--json",
            ]
        )
        assert args.wt_action == "fleet-queue-process-next"
        assert args.worker_session_id == "integrator-1"
        assert args.target_branch == "release"
        assert args.execute is True
        assert args.test_gate is True
        assert args.json is True


class TestWorktreeDispatch:
    @patch("aragora.cli.commands.worktree._cmd_worktree_autopilot")
    def test_dispatches_autopilot_before_branch_coordinator_import(self, mock_autopilot):
        args = argparse.Namespace(
            wt_action="autopilot",
            repo="/tmp/repo",
            base="main",
            auto_base=None,
        )
        cmd_worktree(args)
        mock_autopilot.assert_called_once()

        call = mock_autopilot.call_args
        assert call.kwargs["repo_path"] == Path("/tmp/repo").resolve()
        assert call.kwargs["base_branch"] == "main"

    @patch("aragora.cli.commands.worktree._cmd_worktree_autopilot")
    def test_dispatches_autopilot_with_auto_base_override(self, mock_autopilot):
        args = argparse.Namespace(
            wt_action="autopilot",
            repo="/tmp/repo",
            base="main",
            auto_base="release",
        )
        cmd_worktree(args)
        call = mock_autopilot.call_args
        assert call.kwargs["base_branch"] == "release"

    @patch("aragora.cli.commands.worktree._cmd_worktree_fleet_status")
    def test_dispatches_fleet_status_before_branch_coordinator_import(self, mock_fleet):
        args = argparse.Namespace(
            wt_action="fleet-status",
            repo="/tmp/repo",
            base="main",
        )
        cmd_worktree(args)
        mock_fleet.assert_called_once()
        call = mock_fleet.call_args
        assert call.kwargs["repo_path"] == Path("/tmp/repo").resolve()
        assert call.kwargs["base_branch"] == "main"


class TestWorktreeAutopilot:
    @patch("aragora.cli.commands.worktree.run_autopilot", side_effect=FileNotFoundError("/x/y/z"))
    def test_missing_script_prints_error(self, _mock_run, capsys, tmp_path: Path):
        args = _autopilot_args()

        _cmd_worktree_autopilot(args, repo_path=tmp_path, base_branch="main")

        out = capsys.readouterr().out
        assert "autopilot script not found" in out

    @patch("aragora.cli.commands.worktree.run_autopilot")
    def test_runs_ensure_with_expected_flags(self, mock_run, tmp_path: Path):
        mock_run.return_value = argparse.Namespace(stdout="/tmp/wt\n", stderr="", returncode=0)

        args = _autopilot_args(
            auto_action="ensure",
            agent="codex-ci",
            session_id="ci-123",
            force_new=True,
            strategy="rebase",
            reconcile=True,
            print_path=True,
            json=True,
        )

        _cmd_worktree_autopilot(args, repo_path=tmp_path, base_branch="develop")

        call = mock_run.call_args
        request = call.kwargs["request"]
        assert call.kwargs["repo_root"] == tmp_path
        assert call.kwargs["python_executable"]
        assert request.action == "ensure"
        assert request.managed_dir == ".worktrees/codex-auto"
        assert request.agent == "codex-ci"
        assert request.session_id == "ci-123"
        assert request.base_branch == "develop"
        assert request.strategy == "rebase"
        assert request.force_new is True
        assert request.reconcile is True
        assert request.print_path is True
        assert request.json_output is True

    @patch("aragora.cli.commands.worktree.run_autopilot")
    def test_nonzero_exit_reports_failure(self, mock_run, capsys, tmp_path: Path):
        mock_run.return_value = argparse.Namespace(stdout="", stderr="boom", returncode=2)

        args = _autopilot_args(auto_action="status")
        _cmd_worktree_autopilot(args, repo_path=tmp_path, base_branch="main")

        captured = capsys.readouterr()
        assert "boom" in captured.err
        assert "Autopilot command failed with exit code 2" in captured.out


class TestWorktreeFleetStatus:
    @patch("aragora.cli.commands.worktree.FleetCoordinationStore")
    @patch("aragora.cli.commands.worktree.build_fleet_rows")
    @patch("aragora.nomic.dev_coordination.DevCoordinationStore.status_summary")
    def test_fleet_status_prints_tail_and_metadata(
        self, mock_status_summary, mock_rows, mock_store_cls, capsys, tmp_path: Path
    ):
        mock_status_summary.return_value = {"counts": {"active_leases": 1}}
        mock_rows.return_value = [
            {
                "session_id": "session-a",
                "path": str(tmp_path),
                "branch": "codex/test-session",
                "detached": False,
                "has_lock": True,
                "pid": 123,
                "pid_alive": True,
                "agent": "codex",
                "mode": "codex",
                "dirty_files": 2,
                "ahead": 1,
                "behind": 0,
                "last_activity": "2026-02-26T00:00:00+00:00",
                "orchestration_pattern": "crewai",
                "log_path": str(tmp_path / ".codex_session.log"),
                "log_tail": ["line-2", "line-3"],
            }
        ]
        store = MagicMock()
        store.list_claims.return_value = [{"session_id": "session-a", "path": "aragora/a.py"}]
        store.list_merge_queue.return_value = [
            {"session_id": "session-a", "branch": "codex/test-session"}
        ]
        mock_store_cls.return_value = store

        _cmd_worktree_fleet_status(
            _fleet_args(tail=2),
            repo_path=tmp_path,
            base_branch="main",
        )

        out = capsys.readouterr().out
        assert "[active] codex/test-session" in out
        assert (
            "Integrator: ready=0 review=0 blocked=0 stale=0 collisions=0 missing_receipts=0 scope_violations=0 superseded=0"
            in out
        )
        assert "dirty_files: 2 ahead/behind(main): +1/-0" in out
        assert "orchestrator: crewai" in out
        assert "lease_health: healthy merge_readiness: in_progress" in out
        assert "claimed_paths(1): aragora/a.py" in out
        assert "log_tail(last 2 lines):" in out
        assert "line-2" in out
        assert "line-3" in out

    @patch("aragora.cli.commands.worktree.FleetCoordinationStore")
    @patch("aragora.cli.commands.worktree.build_fleet_rows")
    @patch("aragora.nomic.dev_coordination.DevCoordinationStore.status_summary")
    def test_fleet_status_json_output(
        self, mock_status_summary, mock_rows, mock_store_cls, capsys, tmp_path: Path
    ):
        mock_status_summary.return_value = {"counts": {"active_leases": 0}}
        mock_rows.return_value = [
            {
                "session_id": "session-z",
                "path": str(tmp_path / "wt"),
                "branch": None,
                "detached": True,
                "has_lock": False,
                "pid": None,
                "pid_alive": False,
                "agent": "",
                "mode": "",
                "dirty_files": 0,
                "ahead": None,
                "behind": None,
                "last_activity": None,
                "orchestration_pattern": "generic",
                "log_path": None,
                "log_tail": [],
            }
        ]
        store = MagicMock()
        store.list_claims.return_value = []
        store.list_merge_queue.return_value = []
        mock_store_cls.return_value = store

        _cmd_worktree_fleet_status(
            _fleet_args(json=True, tail=0),
            repo_path=tmp_path,
            base_branch="main",
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["repo_root"] == str(tmp_path)
        assert payload["tail"] == 0
        assert len(payload["worktrees"]) == 1
        assert payload["worktrees"][0]["session_id"] == "session-z"
        assert payload["claims"] == []
        assert payload["merge_queue"] == []
        assert payload["integrator_view"]["summary"]["total_lanes"] == 1

    @patch("aragora.cli.commands.worktree.build_integrator_view")
    @patch("aragora.cli.commands.worktree.FleetCoordinationStore")
    @patch("aragora.cli.commands.worktree.build_fleet_rows")
    def test_fleet_status_surfaces_scope_violation(
        self, mock_rows, mock_store_cls, mock_integrator_view, capsys, tmp_path: Path
    ):
        mock_rows.return_value = [
            {
                "session_id": "session-a",
                "path": str(tmp_path),
                "branch": "codex/test-session",
                "detached": False,
                "has_lock": True,
                "pid": 123,
                "pid_alive": True,
                "agent": "codex",
                "mode": "codex",
                "dirty_files": 1,
                "ahead": 1,
                "behind": 0,
                "last_activity": "2026-03-07T00:00:00+00:00",
                "orchestration_pattern": "generic",
                "log_path": None,
                "log_tail": [],
            }
        ]
        mock_integrator_view.return_value = {
            "summary": {
                "ready_lanes": 0,
                "review_lanes": 0,
                "blocked_lanes": 1,
                "stale_heartbeat_lanes": 0,
                "collision_lanes": 0,
                "missing_receipt_lanes": 0,
                "scope_violation_lanes": 1,
                "superseded_lanes": 0,
            },
            "next_actions": [
                "codex/test-session: Narrow the lane scope or split ownership before it can re-enter merge review."
            ],
            "lanes": [
                {
                    "owner_session_id": "session-a",
                    "worktree_path": str(tmp_path),
                    "lease_health": "healthy",
                    "merge_readiness": "blocked",
                    "scope_violation": {
                        "violations": [
                            {
                                "type": "out_of_scope",
                                "path": "aragora/server/handlers/playground.py",
                            }
                        ]
                    },
                }
            ],
        }
        store = MagicMock()
        store.list_claims.return_value = [{"session_id": "session-a", "path": "aragora/server/**"}]
        store.list_merge_queue.return_value = []
        mock_store_cls.return_value = store

        _cmd_worktree_fleet_status(
            _fleet_args(tail=0),
            repo_path=tmp_path,
            base_branch="main",
        )

        out = capsys.readouterr().out
        assert "scope_violations=1" in out
        assert "merge_readiness: blocked" in out
        assert (
            "Narrow the lane scope or split ownership before it can re-enter merge review." in out
        )


class TestWorktreeFleetOwnership:
    @patch("aragora.cli.commands.worktree.FleetCoordinationStore")
    def test_fleet_claim_cli(self, mock_store_cls, capsys, tmp_path: Path):
        store = MagicMock()
        store.claim_paths.return_value = {
            "session_id": "session-a",
            "claimed": ["aragora/a.py"],
            "conflicts": [],
        }
        mock_store_cls.return_value = store

        args = argparse.Namespace(
            session_id="session-a",
            paths=["aragora/a.py"],
            mode="exclusive",
            branch="codex/session-a",
            json=False,
        )
        _cmd_worktree_fleet_claim(args, repo_path=tmp_path)
        out = capsys.readouterr().out
        assert "claimed=1 conflicts=0" in out

    @patch("aragora.cli.commands.worktree.FleetCoordinationStore")
    def test_fleet_release_cli(self, mock_store_cls, capsys, tmp_path: Path):
        store = MagicMock()
        store.release_paths.return_value = {"session_id": "session-a", "released": 2}
        mock_store_cls.return_value = store

        args = argparse.Namespace(session_id="session-a", paths=None, json=False)
        _cmd_worktree_fleet_release(args, repo_path=tmp_path)
        out = capsys.readouterr().out
        assert "released=2" in out

    @patch("aragora.cli.commands.worktree.FleetCoordinationStore")
    def test_fleet_queue_add_and_list_cli(self, mock_store_cls, capsys, tmp_path: Path):
        store = MagicMock()
        store.enqueue_merge.return_value = {
            "duplicate": False,
            "item": {"id": "mq-1", "branch": "codex/x"},
        }
        store.list_merge_queue.return_value = [
            {
                "id": "mq-1",
                "status": "queued",
                "priority": 60,
                "branch": "codex/x",
                "session_id": "session-a",
            }
        ]
        mock_store_cls.return_value = store

        add_args = argparse.Namespace(
            session_id="session-a",
            branch="codex/x",
            title="",
            priority=60,
            json=False,
        )
        _cmd_worktree_fleet_queue_add(add_args, repo_path=tmp_path)
        out = capsys.readouterr().out
        assert "queued: codex/x [mq-1]" in out

        list_args = argparse.Namespace(status="", json=False)
        _cmd_worktree_fleet_queue_list(list_args, repo_path=tmp_path)
        out = capsys.readouterr().out
        assert "Merge queue: 1" in out

    @patch("aragora.cli.commands.worktree.FleetIntegrationWorker")
    def test_fleet_queue_process_next_cli(self, mock_worker_cls, capsys, tmp_path: Path):
        worker = MagicMock()
        worker.process_next = AsyncMock(
            return_value=FleetIntegrationOutcome(
                queue_item_id="mq-1",
                branch="codex/x",
                queue_status="needs_human",
                action="validated",
                dry_run_success=True,
            )
        )
        mock_worker_cls.return_value = worker

        args = argparse.Namespace(
            worker_session_id="integrator-1",
            target_branch="main",
            execute=False,
            test_gate=False,
            json=False,
        )
        _cmd_worktree_fleet_queue_process_next(args, repo_path=tmp_path)
        out = capsys.readouterr().out
        assert "validated: codex/x [mq-1] status=needs_human" in out
