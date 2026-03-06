"""Tests for the fleet integration worker."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aragora.coordination.reconciler import ConflictCategory, ConflictInfo
from aragora.nomic.branch_coordinator import MergeResult
from aragora.worktree.fleet import FleetCoordinationStore
from aragora.worktree.integration_target_workspace import FleetIntegrationTargetWorkspace
from aragora.worktree.integration_worker import FleetIntegrationWorker


def _checkout_error() -> str:
    return "Failed to checkout target branch main: 'main' is already checked out at /tmp/main"


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed command arguments in tests
        list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(cwd, "git", *args)


def _make_git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "checkout", "-b", "feature/test")
    (repo / "feature.py").write_text("VALUE = 1\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-m", "feature")
    _git(repo, "checkout", "main")
    return repo


@pytest.mark.asyncio
async def test_process_next_returns_idle_when_queue_empty(tmp_path: Path) -> None:
    worker = FleetIntegrationWorker(
        repo_path=tmp_path,
        fleet_store=FleetCoordinationStore(tmp_path),
        branch_coordinator=MagicMock(),
        reconciler=MagicMock(),
    )

    outcome = await worker.process_next(worker_session_id="integrator-1")

    assert outcome.action == "no_work"
    assert outcome.queue_status == "idle"


@pytest.mark.asyncio
async def test_process_next_blocks_on_reconciler_conflicts(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    queued = store.enqueue_merge(session_id="session-a", branch="codex/conflicted", priority=60)
    branch_coordinator = MagicMock()
    branch_coordinator.safe_merge = AsyncMock()
    reconciler = MagicMock()
    reconciler.get_changed_files.return_value = ["aragora/x.py"]
    reconciler.get_commits_ahead.return_value = 2
    reconciler.detect_conflicts.return_value = [
        ConflictInfo(
            file_path="aragora/x.py",
            category=ConflictCategory.UNKNOWN,
            auto_resolvable=False,
            description="CONFLICT (content): Merge conflict in aragora/x.py",
        )
    ]

    worker = FleetIntegrationWorker(
        repo_path=tmp_path,
        fleet_store=store,
        branch_coordinator=branch_coordinator,
        reconciler=reconciler,
    )

    outcome = await worker.process_next(worker_session_id="integrator-1")

    assert outcome.action == "blocked"
    assert outcome.queue_status == "blocked"
    assert outcome.queue_item_id == queued["item"]["id"]
    branch_coordinator.safe_merge.assert_not_called()
    assert store.list_merge_queue()[0]["status"] == "blocked"


@pytest.mark.asyncio
async def test_process_next_marks_checkout_constraint_needs_human(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.enqueue_merge(session_id="session-a", branch="codex/checkout-locked", priority=60)
    branch_coordinator = MagicMock()
    branch_coordinator.safe_merge = AsyncMock(
        return_value=MergeResult(
            source_branch="codex/checkout-locked",
            target_branch="main",
            success=False,
            error=_checkout_error(),
        )
    )
    reconciler = MagicMock()
    reconciler.get_changed_files.return_value = ["aragora/x.py"]
    reconciler.get_commits_ahead.return_value = 1
    reconciler.detect_conflicts.return_value = []

    worker = FleetIntegrationWorker(
        repo_path=tmp_path,
        fleet_store=store,
        branch_coordinator=branch_coordinator,
        reconciler=reconciler,
    )

    outcome = await worker.process_next(worker_session_id="integrator-1")

    assert outcome.action == "needs_human"
    assert outcome.queue_status == "needs_human"
    assert outcome.error == _checkout_error()
    assert store.list_merge_queue()[0]["status"] == "needs_human"


@pytest.mark.asyncio
async def test_process_next_validates_without_execute(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.enqueue_merge(session_id="session-a", branch="codex/ready", priority=60)
    branch_coordinator = MagicMock()
    branch_coordinator.safe_merge = AsyncMock(
        return_value=MergeResult(
            source_branch="codex/ready",
            target_branch="main",
            success=True,
        )
    )
    reconciler = MagicMock()
    reconciler.get_changed_files.return_value = ["aragora/x.py"]
    reconciler.get_commits_ahead.return_value = 3
    reconciler.detect_conflicts.return_value = []

    worker = FleetIntegrationWorker(
        repo_path=tmp_path,
        fleet_store=store,
        branch_coordinator=branch_coordinator,
        reconciler=reconciler,
    )

    outcome = await worker.process_next(worker_session_id="integrator-1")

    assert outcome.action == "validated"
    assert outcome.queue_status == "needs_human"
    assert outcome.dry_run_success is True
    assert store.list_merge_queue()[0]["metadata"]["validated_only"] is True


@pytest.mark.asyncio
async def test_process_next_executes_merge_successfully(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.enqueue_merge(session_id="session-a", branch="codex/ready", priority=60)
    branch_coordinator = MagicMock()
    branch_coordinator.safe_merge = AsyncMock(
        side_effect=[
            MergeResult(source_branch="codex/ready", target_branch="main", success=True),
            MergeResult(
                source_branch="codex/ready",
                target_branch="main",
                success=True,
                commit_sha="abc123",
            ),
        ]
    )
    reconciler = MagicMock()
    reconciler.get_changed_files.return_value = ["aragora/x.py"]
    reconciler.get_commits_ahead.return_value = 3
    reconciler.detect_conflicts.return_value = []

    worker = FleetIntegrationWorker(
        repo_path=tmp_path,
        fleet_store=store,
        branch_coordinator=branch_coordinator,
        reconciler=reconciler,
    )

    outcome = await worker.process_next(worker_session_id="integrator-1", execute=True)

    assert outcome.action == "merged"
    assert outcome.queue_status == "merged"
    assert outcome.merge_commit_sha == "abc123"
    assert store.list_merge_queue()[0]["metadata"]["merge_commit_sha"] == "abc123"


@pytest.mark.asyncio
async def test_process_next_marks_execution_conflicts_blocked(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.enqueue_merge(session_id="session-a", branch="codex/ready", priority=60)
    branch_coordinator = MagicMock()
    branch_coordinator.safe_merge = AsyncMock(
        side_effect=[
            MergeResult(source_branch="codex/ready", target_branch="main", success=True),
            MergeResult(
                source_branch="codex/ready",
                target_branch="main",
                success=False,
                error="Merge failed",
                conflicts=["aragora/x.py"],
            ),
        ]
    )
    reconciler = MagicMock()
    reconciler.get_changed_files.return_value = ["aragora/x.py"]
    reconciler.get_commits_ahead.return_value = 3
    reconciler.detect_conflicts.return_value = []

    worker = FleetIntegrationWorker(
        repo_path=tmp_path,
        fleet_store=store,
        branch_coordinator=branch_coordinator,
        reconciler=reconciler,
    )

    outcome = await worker.process_next(worker_session_id="integrator-1", execute=True)

    assert outcome.action == "failed"
    assert outcome.queue_status == "blocked"
    assert outcome.conflicts == ["aragora/x.py"]
    assert store.list_merge_queue()[0]["status"] == "blocked"


@pytest.mark.asyncio
async def test_process_next_uses_dedicated_integration_workspace(tmp_path: Path) -> None:
    repo = _make_git_repo(tmp_path)
    store = FleetCoordinationStore(repo)
    store.enqueue_merge(session_id="session-a", branch="feature/test", priority=60)

    worker = FleetIntegrationWorker(
        repo_path=repo,
        fleet_store=store,
        integration_workspace=FleetIntegrationTargetWorkspace(
            repo_root=repo,
            target_branch="main",
        ),
    )

    outcome = await worker.process_next(worker_session_id="integrator-1")

    assert outcome.action == "validated"
    assert outcome.queue_status == "needs_human"
    assert outcome.metadata["integration_workspace_path"] != str(repo)
