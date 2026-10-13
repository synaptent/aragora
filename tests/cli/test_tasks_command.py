"""Tests for the public ``aragora tasks`` command."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aragora.cli.parser import build_parser


def _lease_payload(lease_id: str = "lease-1") -> dict[str, object]:
    return {
        "lease_id": lease_id,
        "task_id": "task:demo",
        "owner_agent": "codex",
        "owner_session_id": "session-1",
        "branch": "codex/demo",
        "worktree_path": "/tmp/wt",
        "status": "active",
        "expires_at": "2026-03-18T12:00:00+00:00",
    }


class TestTasksParser:
    def test_tasks_registered_in_root_parser(self):
        parser = build_parser()
        args = parser.parse_args(["tasks", "claim", "task:demo", "--ttl-hours", "4"])
        assert args.command == "tasks"
        assert args.tasks_command == "claim"
        assert args.task_id == "task:demo"
        assert args.ttl_hours == 4.0

    def test_tasks_release_uses_lease_id(self):
        parser = build_parser()
        args = parser.parse_args(["tasks", "release", "lease-123"])
        assert args.command == "tasks"
        assert args.tasks_command == "release"
        assert args.lease_id == "lease-123"


class TestTasksCommand:
    def test_list_json_output(self, capsys):
        parser = build_parser()
        args = parser.parse_args(["tasks", "list", "--status", "pending", "--format", "json"])
        queue = MagicMock()
        item = MagicMock()
        item.to_dict.return_value = {
            "id": "task:demo",
            "status": "pending",
            "work_type": "custom",
            "computed_priority": 88,
            "title": "Demo task",
        }
        queue.list_items.return_value = [item]

        with patch("aragora.cli.commands.tasks._load_queue", return_value=queue):
            args.func(args)

        payload = json.loads(capsys.readouterr().out)
        assert payload[0]["id"] == "task:demo"
        queue.list_items.assert_called_once()

    def test_claim_uses_queue_defaults(self, capsys):
        parser = build_parser()
        args = parser.parse_args(["tasks", "claim", "task:demo", "--format", "json"])
        queue = MagicMock()
        queue_item = MagicMock()
        queue_item.to_dict.return_value = {
            "id": "task:demo",
            "title": "Refactor queue API",
            "metadata": {
                "allowed_paths": ["aragora/nomic/dev_coordination.py"],
                "acceptance_checks": ["pytest tests/nomic/test_dev_coordination.py -q"],
            },
        }
        queue.get.return_value = queue_item

        store = MagicMock()
        store.get_developer_task.return_value = None
        lease = MagicMock()
        lease.to_dict.return_value = _lease_payload()
        store.claim_lease.return_value = lease

        with (
            patch("aragora.cli.commands.tasks._load_queue", return_value=queue),
            patch("aragora.cli.commands.tasks._load_store", return_value=store),
            patch("aragora.cli.commands.tasks._repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.cli.commands.tasks._current_branch", return_value="codex/demo"),
        ):
            args.func(args)

        payload = json.loads(capsys.readouterr().out)
        assert payload["lease_id"] == "lease-1"
        store.claim_lease.assert_called_once()
        kwargs = store.claim_lease.call_args.kwargs
        assert kwargs["task_id"] == "task:demo"
        assert kwargs["title"] == "Refactor queue API"
        assert kwargs["allowed_globs"] == ["aragora/nomic/dev_coordination.py"]
        assert kwargs["expected_tests"] == ["pytest tests/nomic/test_dev_coordination.py -q"]

    def test_complete_uses_active_lease_defaults(self, capsys):
        parser = build_parser()
        args = parser.parse_args(["tasks", "complete", "lease-1", "--head-sha", "abc123"])
        active_lease = SimpleNamespace(
            lease_id="lease-1",
            owner_agent="codex",
            owner_session_id="session-1",
            branch="codex/demo",
            worktree_path="/tmp/wt",
        )
        receipt = MagicMock()
        receipt.to_dict.return_value = {
            "receipt_id": "receipt-1",
            "lease_id": "lease-1",
            "head_sha": "abc123",
        }
        store = MagicMock()
        store.list_active_leases.return_value = [active_lease]
        store.record_completion.return_value = receipt

        with (
            patch("aragora.cli.commands.tasks._load_store", return_value=store),
            patch("aragora.cli.commands.tasks._repo_root", return_value=Path("/tmp/repo")),
            patch("aragora.cli.commands.tasks._current_branch", return_value="codex/demo"),
        ):
            args.func(args)

        payload = json.loads(capsys.readouterr().out)
        assert payload["receipt_id"] == "receipt-1"
        kwargs = store.record_completion.call_args.kwargs
        assert kwargs["lease_id"] == "lease-1"
        assert kwargs["owner_agent"] == "codex"
        assert kwargs["branch"] == "codex/demo"
        assert kwargs["worktree_path"] == "/tmp/wt"
        assert kwargs["head_sha"] == "abc123"

    def test_sync_runs_both_projections(self, capsys):
        parser = build_parser()
        args = parser.parse_args(["tasks", "sync", "--format", "json"])
        queue = MagicMock()
        store = MagicMock()
        store.sync_developer_task_queue.return_value = {"created": 2}
        store.sync_pending_work_queue.return_value = {"updated": 1}

        with (
            patch("aragora.cli.commands.tasks._load_store", return_value=store),
            patch("aragora.cli.commands.tasks._load_queue", return_value=queue),
        ):
            args.func(args)

        payload = json.loads(capsys.readouterr().out)
        assert payload["developer_tasks"]["created"] == 2
        assert payload["pending"]["updated"] == 1


class TestResolve:
    def test_runs_coroutines_and_passes_plain_values_through(self):
        from aragora.cli.commands.tasks import _resolve

        async def produce() -> str:
            return "done"

        assert _resolve(produce()) == "done"
        assert _resolve({"id": 1}) == {"id": 1}
